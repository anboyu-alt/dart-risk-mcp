"""known_actors 자동 갱신 — 시장 신규 CB/유상증자 공시에서 등재 인물의 인수 근거 수집.

GitHub Actions cron이 매일 실행. 등재 인물만 대상이며, 자동 매칭은 status=auto_matched
(동명이인 미확인)로 추가하고 verified로 승격하지 않는다.

사용: python scripts/refresh_known_actors.py
API 키: 환경변수 DART_API_KEY 또는 tmp/_apikey.txt.
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from dart_risk_mcp.core.dart_client import fetch_market_disclosures
from dart_risk_mcp.core.cb_extractor import extract_cb_investors
from dart_risk_mcp.core.investor_extractor import extract_rights_offering_investors
from dart_risk_mcp.core.signals import match_signals, is_amendment_disclosure

WINDOW_DAYS = 2
MAX_PAGES = 5
DATA_PATH = Path(__file__).resolve().parents[1] / "dart_risk_mcp" / "data" / "known_actors.json"


def _api_key() -> str:
    key = os.environ.get("DART_API_KEY")
    if key:
        return key.strip()
    p = Path(__file__).resolve().parents[1] / "tmp" / "_apikey.txt"
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def collect_auto_matches(api_key, known_names, window_days=WINDOW_DAYS, max_pages=MAX_PAGES):
    """최근 window_days CB/유상증자 공시에서 known_names와 매칭되는 인수자 근거 수집.

    반환: {인물명: [auto_matched record, ...]}
    """
    end = datetime.now()
    start = end - timedelta(days=max(1, window_days))
    discs = fetch_market_disclosures(
        api_key, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"),
        pblntf_ty="B", max_pages=max_pages) or []
    matches = {}
    for d in discs:
        rn = d.get("rcept_no", "")
        rnm = d.get("report_nm", "")
        corp = d.get("corp_name", "")
        cc = d.get("corp_code", "")
        if not rn or is_amendment_disclosure(rnm):
            continue
        keys = {s["key"] for s in (match_signals(rnm) or [])}
        invs = []
        if keys & {"CB_BW", "EB"}:
            invs += [("CB인수", i) for i in (extract_cb_investors(rn, api_key, cc) or [])]
        if keys & {"3PCA", "RIGHTS_UNDER"}:
            invs += [("유상증자", i) for i in (extract_rights_offering_investors(rn, api_key, cc) or [])]
        rdt = (d.get("rcept_dt", "") or "")
        date = f"{rdt[:4]}-{rdt[4:6]}" if len(rdt) >= 6 else ""
        for label, inv in invs:
            nm = (inv.get("name") or "").strip()
            if nm in known_names:
                matches.setdefault(nm, []).append({
                    "source": f"DART {label}(자동매칭)",
                    "status": "auto_matched",
                    "evidence": f"{corp} {label} 인수자로 등장",
                    "url": "https://dart.fss.or.kr",
                    "date": date,
                    "rcept_no": rn,
                    "tags": ["자동 매칭", "동명이인 미확인"],
                })
    return matches


def merge_auto_matches(data: dict, matches: dict) -> bool:
    """matches를 data에 병합. 등재 인물만, 동일 rcept_no 중복 스킵. 변경 여부 반환."""
    actors = data.setdefault("actors", {})
    changed = False
    for name, recs in matches.items():
        if name not in actors:
            continue  # 등재 인물만 근거 추가 (새 인물 등재 안 함)
        seen = {r.get("rcept_no") for r in actors[name] if r.get("rcept_no")}
        for rec in recs:
            if rec.get("rcept_no") and rec["rcept_no"] in seen:
                continue
            actors[name].append(rec)
            seen.add(rec.get("rcept_no"))
            changed = True
    return changed


def main():
    key = _api_key()
    if not key:
        raise SystemExit("DART_API_KEY 또는 tmp/_apikey.txt 필요")
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    known_names = set(data.get("actors", {}).keys())
    matches = collect_auto_matches(key, known_names)
    changed = merge_auto_matches(data, matches)
    if changed:
        DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"갱신: {sum(len(v) for v in matches.values())}건 근거 추가")
    else:
        print("변경 없음")


if __name__ == "__main__":
    main()
