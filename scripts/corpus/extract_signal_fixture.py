"""수집한 1년 rows에서 회귀 픽스처를 뽑는다 (2026-08-22).

픽스처에는 **신호가 붙는 고유 제목**만 빈도와 함께 담는다. 원본 rows는
50MB급이라 커밋하지 않는다(제목만 남기면 100KB 내외).

기존 90일 픽스처를 1년으로 바꾸는 이유: 90일 창은 계절 표현을 못 본다.
「감사보고서 제출」·「사업보고서」·감사의견 계열은 3월에 몰려 있어, 90일
코퍼스에서 0건인 것이 "안 쓰이는 표현"인지 "창 밖"인지 구분되지 않았다.
"""
import json
import os
import sys
from collections import Counter

sys.path.insert(0, os.path.abspath("."))
from dart_risk_mcp.core.signals import match_signals  # noqa: E402

SRC = os.environ.get("CORPUS_ROWS", "tmp/corpus365/rows_daily.json")
DST = "tests/fixtures/corpus/signal_titles_365d.json"

src = json.load(open(SRC, encoding="utf-8"))
rows = src["rows"]
truncated = src.get("truncated_days", [])

counter: Counter = Counter()
for r in rows:
    nm = (r.get("report_nm") or "").strip()
    if nm and match_signals(nm):
        counter[nm] += 1

titles = [{"nm": nm, "n": n} for nm, n in counter.most_common()]
out = {
    "window": src["window"],
    "source": "시장 전체 공시(list.json) 하루 청크 수집 — 신호가 붙는 고유 제목",
    "n_disclosures_scanned": len(rows),
    "n_titles_with_signal": len(titles),
    # 정직 표기: 상한에 닿아 잘렸을 수 있는 날. 비어 있어야 전수라 부를 수 있다.
    "truncated_days": truncated,
    "titles": titles,
}
os.makedirs(os.path.dirname(DST), exist_ok=True)
json.dump(out, open(DST, "w", encoding="utf-8"), ensure_ascii=False, indent=1)

size = os.path.getsize(DST)
print(f"공시 {len(rows):,}건 → 신호 제목 {len(titles):,}종 · {size/1024:.0f}KB")
print(f"절단 의심일: {len(truncated)}건 {truncated if truncated else ''}")
tot = sum(counter.values())
print(f"신호가 붙은 공시 {tot:,}건 ({tot/len(rows)*100:.1f}%)")
