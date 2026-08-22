"""1년 시장 공시 코퍼스 재수집 — 하루 청크 + 절단 자가진단 (2026-08-22).

2026-08-22 이전 수집기(`tmp/corpus365/collect.py`)는 **2일 청크 · max_pages=20(상한 2,000건)**으로 돌았는데,
183개 청크 중 **38개(20.8%)가 정확히 2,000건에 붙어** 절단됐다. 하필 2~3월
감사 시즌이 집중 절단돼, "그 표현이 안 쓰인다"와 "스캔 범위 밖이다"가
구분되지 않는 상태였다. `search_market_disclosures`가 v1.10.2에서 고친 것과
같은 뿌리의 문제다.

이 스크립트는 세 가지를 바꾼다.
  ① 하루 청크 — 2일치를 한 창에 넣지 않는다.
  ② max_pages를 넉넉히 — 하루 실측 최대가 2,000건을 넘는 날이 있다.
  ③ **절단 자가진단** — 상한에 닿은 날을 로그와 산출물 양쪽에 기록한다.
     조용히 잘린 코퍼스를 "전수"라고 부르지 않기 위해서다.

재개 가능: rows_daily.json이 있으면 이미 받은 날짜를 건너뛴다.
"""
import json
import os
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.abspath("."))
from dart_risk_mcp.core.dart_client import fetch_market_disclosures  # noqa: E402

KEY = os.environ["DART_API_KEY"]
OUT = os.environ.get("CORPUS_ROWS", "tmp/corpus365/rows_daily.json")
MAX_PAGES = 50          # 5,000건/일 — 실측 최대(약 2,400)의 두 배 여유
PAGE_SIZE = 100
FIELDS = ("rcept_no", "rcept_dt", "corp_code", "corp_name",
          "report_nm", "flr_nm", "corp_cls")

end = date(2026, 8, 21)         # 수집 시점의 마지막 완결일(오늘 접수분은 진행 중)
start = end - timedelta(days=364)

rows, seen, done, truncated = [], set(), set(), []
if os.path.exists(OUT):
    prev = json.load(open(OUT, encoding="utf-8"))
    rows = prev["rows"]
    truncated = prev.get("truncated_days", [])
    done = set(prev.get("days_done", []))
    seen = {r["rcept_no"] for r in rows}
    print(f"재개: {len(rows):,}건 · 완료 {len(done)}일", file=sys.stderr, flush=True)

d = start
while d <= end:
    key = d.strftime("%Y%m%d")
    if key in done:
        d += timedelta(days=1)
        continue
    try:
        chunk = fetch_market_disclosures(KEY, key, key, max_pages=MAX_PAGES)
    except Exception as e:                      # noqa: BLE001
        print(f"  !! {key}: {e}", file=sys.stderr, flush=True)
        d += timedelta(days=1)
        continue
    if len(chunk) >= MAX_PAGES * PAGE_SIZE:     # 상한에 닿았다 = 잘렸을 수 있다
        truncated.append(key)
        print(f"  ** {key}: 상한 도달 {len(chunk)}건", file=sys.stderr, flush=True)
    for r in chunk:
        rc = r.get("rcept_no")
        if rc and rc not in seen:
            seen.add(rc)
            rows.append({k: r.get(k, "") for k in FIELDS})
    done.add(key)
    if len(done) % 20 == 0:
        json.dump({"window": [str(start), str(end)], "rows": rows,
                   "days_done": sorted(done), "truncated_days": truncated},
                  open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
        print(f"  {key}: 누적 {len(rows):,} ({len(done)}/365일)",
              file=sys.stderr, flush=True)
    d += timedelta(days=1)
    time.sleep(0.1)

json.dump({"window": [str(start), str(end)], "rows": rows,
           "days_done": sorted(done), "truncated_days": truncated},
          open(OUT, "w", encoding="utf-8"), ensure_ascii=False)
print(f"수집 완료: {len(rows):,}건 · {len(done)}일 · 절단일 {len(truncated)}건")
if truncated:
    print("절단 의심일:", truncated)
