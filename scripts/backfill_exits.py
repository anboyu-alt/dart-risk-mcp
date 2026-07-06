"""행위자 이탈(exit) 스윕 — 진입한 회사에서의 지분 처분·전환청구를 sightings에 기록.

우리가 이미 그래프에 그리는 (행위자→회사) 진입 연결에 대해, 그 회사에서의
이탈 흔적을 DART에서 찾아 'out' 이벤트로 누적한다. 이탈해도 삭제하지 않고
닫힌 관계로 보존한다(merge_sightings가 닫힌 관계는 window와 무관하게 유지).

이탈 소스
  - 5% 대량보유 감소 (elestock) — 보고자=진입 행위자, 보유비율 감소 → 개별 귀속.
  - 전환청구권행사 — 회사 단위 이벤트(company_events)로 별도 기록(개별 귀속 안 함).

진입만 있는 회사(대부분)는 elestock가 비어 no-op. 회사당 2콜(elestock + 공시목록),
0.3s 페이싱. 멱등 — 같은 접수·회사·이벤트는 중복 스킵.

사용: SIGHTINGS_PATH=_sightings/sightings.json python scripts/backfill_exits.py
환경: DART_API_KEY(또는 tmp/_apikey.txt), SIGHTINGS_PATH.
"""
import json
import os
import time
from pathlib import Path

from dart_risk_mcp.core.dart_client import fetch_bulk_holdings, fetch_company_disclosures
from dart_risk_mcp.core.exit_extractor import extract_holding_exits, scan_conversion_events
from dart_risk_mcp.core.known_actors import classify_actor
from dart_risk_mcp.core.signals import is_amendment_disclosure
from scripts.discover_actors import merge_sightings, _TRACKED_KINDS
from scripts.refresh_known_actors import _api_key

_DEFAULT = Path(__file__).resolve().parents[1] / "tmp" / "sightings.json"
PACE_SEC = 0.3
CONV_LOOKBACK_DAYS = 400


def build_company_index(sdata: dict) -> dict:
    """corp_code -> {"entrants": {norm: {"name","corp","corp_cls","kind"}}}.

    진입('in') 기록이 있는 회사·행위자만. 이탈 기록 부착에 필요한 메타를 보관.
    """
    idx: dict = {}
    for norm, recs in sdata.get("sightings", {}).items():
        if classify_actor(norm) not in _TRACKED_KINDS:
            continue
        for r in recs:
            if r.get("event") == "out":
                continue
            cc = r.get("corp_code")
            if not cc:
                continue
            ent = idx.setdefault(cc, {"corp": r.get("corp") or cc, "entrants": {}})
            ent["corp"] = r.get("corp") or ent["corp"]
            ent["entrants"].setdefault(norm, {
                "corp_cls": r.get("corp_cls", ""),
                "kind": r.get("kind", ""),
            })
    return idx


def main():
    key = _api_key()
    if not key:
        raise SystemExit("DART_API_KEY 또는 tmp/_apikey.txt 필요")
    path = Path(os.environ.get("SIGHTINGS_PATH") or _DEFAULT)
    sdata = json.loads(path.read_text(encoding="utf-8"))

    cidx = build_company_index(sdata)
    print(f"[START] 진입 회사 {len(cidx)}곳 이탈 스윕")

    exit_recs = []          # merge_sightings로 병합할 'out' 기록
    company_events = sdata.setdefault("company_events", {})
    n_hold, n_conv = 0, 0

    for i, (cc, meta) in enumerate(sorted(cidx.items()), 1):
        entrants = meta["entrants"]
        tracked_norm = set(entrants.keys())

        # 1) 5% 대량보유 감소 → 개별 이탈
        for ev in extract_holding_exits(fetch_bulk_holdings(cc, key), tracked_norm):
            info = entrants.get(ev["norm"], {})
            exit_recs.append({
                "name": ev["name"], "corp": meta["corp"], "corp_code": cc,
                "corp_cls": info.get("corp_cls", ""), "kind": info.get("kind", ""),
                "date": ev["date"], "rcept_no": ev["rcept_no"],
                "event": "out", "event_type": "지분감소", "pct": ev["pct"],
            })
            n_hold += 1
        time.sleep(PACE_SEC)

        # 2) 전환청구권행사 → 회사 단위 이벤트 (개별 귀속 안 함)
        discs = [d for d in (fetch_company_disclosures(cc, key, CONV_LOOKBACK_DAYS) or [])
                 if not is_amendment_disclosure(d.get("report_nm", ""))]
        seen = {e.get("rcept_no") for e in company_events.get(cc, [])}
        for cev in scan_conversion_events(discs, {cc}):
            if cev["rcept_no"] in seen:
                continue
            company_events.setdefault(cc, []).append({
                "date": cev["date"], "rcept_no": cev["rcept_no"],
                "event_type": cev["event_type"],
            })
            seen.add(cev["rcept_no"])
            n_conv += 1
        time.sleep(PACE_SEC)

        if i % 25 == 0 or i == len(cidx):
            print(f"[DART] {i}/{len(cidx)} · 누적 지분감소 {n_hold} · 전환청구 {n_conv}")

    # 이탈 기록 병합 (닫힌 관계 보존은 merge_sightings가 처리)
    changed = merge_sightings(sdata, exit_recs) if exit_recs else False
    if changed or n_conv:
        path.write_text(json.dumps(sdata, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"[SUMMARY] 지분감소 {n_hold}건 · 전환청구(회사) {n_conv}건 · "
          f"sightings {'갱신' if (changed or n_conv) else '무변경'}")
    print("[DONE]")


if __name__ == "__main__":
    main()
