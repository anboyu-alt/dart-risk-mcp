"""이탈 백필의 '지분감소 0건'이 진짜인지 진단.

두 가설을 가른다:
  (A) 5% 미만 정상 — 우리 세력이 대량보유(≥5%) 공시선 아래라 elestock에
      애초에 안 잡힘. → 대량보유는 이 모집단에 부적합, 다른 이탈 소스 필요.
  (B) 이름 매칭 갭 — elestock에 우리 행위자가 등장하는데 표기 차이로 매칭 실패.
      → 정규화 규칙을 손봐야 함.

elestock만 조회(회사당 1콜, 공시목록 없음)라 빠르다. 진입 회사별로
우리 진입자 vs elestock 보고자를 나란히 출력하고, 매칭·근접매칭을 집계한다.

사용: SIGHTINGS_PATH=_sightings/sightings.json python scripts/diagnose_exits.py
환경: DART_API_KEY(또는 tmp/_apikey.txt), SIGHTINGS_PATH,
     DIAG_SHOW(상세 출력 회사 수, 기본 20).
"""
import json
import os
import time
from pathlib import Path

from dart_risk_mcp.core.dart_client import fetch_bulk_holdings, fetch_major_holdings
from dart_risk_mcp.core.exit_extractor import extract_holding_exits, _ratio
from dart_risk_mcp.core.known_actors import normalize_name
from scripts.backfill_exits import build_company_index
from scripts.refresh_known_actors import _api_key

_DEFAULT = Path(__file__).resolve().parents[1] / "tmp" / "sightings.json"
PACE_SEC = 0.3


def _near(a: str, b: str) -> bool:
    """정규화 근접 매칭 — 부분포함 또는 앞 4자 공유(이름 갭 후보)."""
    if not a or not b or a == b:
        return False
    if a in b or b in a:
        return True
    return len(a) >= 4 and len(b) >= 4 and a[:4] == b[:4]


def main():
    key = _api_key()
    if not key:
        raise SystemExit("DART_API_KEY 또는 tmp/_apikey.txt 필요")
    path = Path(os.environ.get("SIGHTINGS_PATH") or _DEFAULT)
    show = int(os.environ.get("DIAG_SHOW", "20"))
    sdata = json.loads(path.read_text(encoding="utf-8"))
    cidx = build_company_index(sdata)
    print(f"[DIAG] 진입 회사 {len(cidx)}곳 · majorstock(대량보유 5%) 대조 시작")

    n_have = 0                 # 대량보유 보고 있는 회사
    n_reporters = 0            # 보고자 레코드 총계
    exact_pairs = []           # (회사, 행위자, [(date, stkrt, irds)…])
    near_pairs = []            # (회사, 진입자, 보고자)
    decreases = []             # (회사, 행위자, date, stkrt, irds<0) = 실제 이탈
    shown = 0
    dumped = 0

    for i, (cc, meta) in enumerate(sorted(cidx.items()), 1):
        entrants = set(meta["entrants"].keys())      # 정규화된 진입자
        recs = fetch_major_holdings(cc, key)
        time.sleep(PACE_SEC)
        if not recs:
            continue
        n_have += 1
        n_reporters += len(recs)
        # 보고자 정규화 → (날짜, 보유비율 stkrt, 증감 stkrt_irds)
        reporters = {}
        for r in recs:
            nm = (r.get("repror") or "").strip()
            if not nm:
                continue
            reporters.setdefault(normalize_name(nm), []).append(
                (r.get("rcept_dt", ""), _ratio(r.get("stkrt")), _ratio(r.get("stkrt_irds"))))
        exact = entrants & set(reporters.keys())
        for e in exact:
            series = sorted(reporters[e])
            exact_pairs.append((meta["corp"], e, series))
            for dt, rt, ird in series:
                if ird is not None and ird < 0:      # 보유비율 감소 = 이탈
                    decreases.append((meta["corp"], e, dt, rt, ird))
        # 매칭 회사 첫 2곳 원시 레코드 덤프(필드 확정)
        if exact and dumped < 2:
            dumped += 1
            print(f"[RAW] {meta['corp']} — 매칭 보고자 {sorted(exact)} majorstock 원시:")
            for r in recs:
                if normalize_name((r.get('repror') or '').strip()) in exact:
                    kv = {k: v for k, v in r.items() if v not in (None, "", "-")}
                    print(f"[RAW]   {json.dumps(kv, ensure_ascii=False)}")
            if dumped >= 2:
                print("[RAW] 원시 2건 확보 — 조기 종료.")
                break
        near_here = False
        for e in entrants:
            for rp in reporters:
                if rp not in exact and _near(e, rp):
                    near_pairs.append((meta["corp"], e, rp))
                    near_here = True
        if shown < show:
            shown += 1
            tag = "★매칭" if exact else ("~근접" if near_here else "")
            print(f"[DIAG] {meta['corp']} {tag}\n"
                  f"        진입자 : {', '.join(sorted(entrants))[:120]}\n"
                  f"        보고자 : {', '.join(sorted(reporters.keys()))[:160]}")
        if i % 100 == 0:
            print(f"[DIAG] …{i}/{len(cidx)} (대량보유有 {n_have})")

    print("\n[SUMMARY] majorstock(대량보유) 진단")
    print(f"  · 진입 회사               : {len(cidx)}")
    print(f"  · 대량보유 보고 있는 회사 : {n_have}  (없음 {len(cidx) - n_have})")
    print(f"  · 보고자 레코드           : {n_reporters}")
    print(f"  · 우리 행위자 정확 매칭    : {len(exact_pairs)}쌍")
    print(f"  · 그 중 감소(이탈) 이벤트  : {len(decreases)}건  ← 핵심")
    print(f"  · 근접(이름 갭 후보)      : {len(near_pairs)}쌍")
    for corp, e, series in exact_pairs[:10]:
        print(f"      매칭: {corp} · {e} · {series}")
    for corp, e, dt, rt, ird in decreases[:15]:
        print(f"      감소: {corp} · {e} · {dt} · {rt}% (Δ{ird})")
    for corp, e, rp in near_pairs[:15]:
        print(f"      근접: {corp} · '{e}' ↔ '{rp}'")
    print("\n[해석] 감소 이벤트>0 → majorstock가 옳은 소스(extractor를 majorstock+stkrt_irds로 교체). "
          "매칭 0 → 대량보유에도 없음(다른 소스 검토).")
    print("[DONE]")


if __name__ == "__main__":
    main()
