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

from dart_risk_mcp.core.dart_client import fetch_bulk_holdings
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
    print(f"[DIAG] 진입 회사 {len(cidx)}곳 · elestock 보고자 대조 시작")

    n_have = 0                 # elestock 레코드 있는 회사
    n_reporters = 0            # elestock 보고자(레코드) 총계
    exact_pairs = []           # (회사, 행위자, 보유비율들)
    near_pairs = []            # (회사, 행위자, elestock보고자)
    shown = 0
    dumped = 0                 # 원시 레코드 덤프한 회사 수

    for i, (cc, meta) in enumerate(sorted(cidx.items()), 1):
        entrants = set(meta["entrants"].keys())      # 정규화된 진입자
        recs = fetch_bulk_holdings(cc, key)
        time.sleep(PACE_SEC)
        if not recs:
            continue
        n_have += 1
        n_reporters += len(recs)
        # elestock 보고자 정규화 집합 + 비율
        reporters = {}
        for r in recs:
            nm = (r.get("repror") or "").strip()
            if not nm:
                continue
            reporters.setdefault(normalize_name(nm), []).append(
                (r.get("rcept_dt", ""), _ratio(r.get("stkqy_rt"))))
        exact = entrants & set(reporters.keys())
        for e in exact:
            exact_pairs.append((meta["corp"], e, sorted(reporters[e])))
        # 매칭된 회사 첫 2곳은 원시 elestock 레코드를 통째로 덤프 →
        # 어떤 필드가 '보유비율'인지 확정(현 stkqy_rt가 None인 원인 규명).
        if exact and dumped < 2:
            dumped += 1
            print(f"[RAW] {meta['corp']} — 매칭 보고자 {sorted(exact)} 원시 레코드:")
            for r in recs:
                if normalize_name((r.get('repror') or '').strip()) in exact:
                    kv = {k: v for k, v in r.items() if v not in (None, "", "-")}
                    print(f"[RAW]   {json.dumps(kv, ensure_ascii=False)}")
            if dumped >= 2:
                print("[RAW] 원시 덤프 2건 확보 — 조기 종료(필드명 확정용).")
                break
        # 근접(이름 갭 후보)
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
            print(f"[DIAG] …{i}/{len(cidx)} (elestock有 {n_have})")

    print("\n[SUMMARY] 진단 결과")
    print(f"  · 진입 회사            : {len(cidx)}")
    print(f"  · elestock 보고 있는 회사: {n_have}  (없음 {len(cidx) - n_have})")
    print(f"  · elestock 보고자 레코드 : {n_reporters}")
    print(f"  · 우리 행위자 ↔ 보고자 정확 매칭: {len(exact_pairs)}쌍")
    print(f"  · 근접(이름 갭 후보)     : {len(near_pairs)}쌍")
    if exact_pairs:
        print("  · 정확 매칭 예시(회사·행위자·[(날짜,비율)…]):")
        for corp, e, series in exact_pairs[:10]:
            print(f"      {corp} · {e} · {series}")
    if near_pairs:
        print("  · 근접 매칭 예시(회사·진입자 ↔ 보고자):")
        for corp, e, rp in near_pairs[:15]:
            print(f"      {corp} · '{e}' ↔ '{rp}'")
    print("\n[해석] 정확 매칭≈0 & 근접≈0 → (A) 5% 미만이라 정상(다른 소스 필요). "
          "근접 다수 → (B) 이름 매칭 갭(정규화 개선 필요).")
    print("[DONE]")


if __name__ == "__main__":
    main()
