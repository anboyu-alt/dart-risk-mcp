# 자금 조달 후 목적 외 사용(fund misuse) 탐지 능력 검증 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 뷰어(docs/tool)와 MCP(`track_fund_usage` 등)가 "자금 조달 뒤 목적대로 사용하지 않는 경우"를 실제 시장 데이터에서 잡아내는지 실측으로 검증하고, 결과를 검증 매트릭스·골드에 정직하게 기록한다.

**Architecture:** 탐지 계층은 3개다 — ① MCP `track_fund_usage`의 레코드 플래그(`FUND_DIVERSION` 키워드 14종 / `FUND_UNREPORTED` 미집행), ② 복합 패턴 `fund_diversion_chain`(CB 조달→타법인 출자, ⚠ 라이브 미검증), ③ 뷰어 fundChain 패널(무판정 — "집행 차이 사유 보고 있음" 사실 표기 + 90일 근접 공시 힌트). 검증은 "실제 차이사유 문구 코퍼스를 시장에서 수집 → 키워드 리콜/미집행 정밀도 실측 → 발화 사례로 MCP 종단 + 뷰어 렌더 확인" 순서로 진행한다.

**Tech Stack:** Python 3.11 (레포 core 함수 직접 호출), DART OpenAPI(`DART_API_KEY` 환경변수 설정 확인됨), 뷰어는 `scripts/dev_relay.py` 로컬 릴레이 + 프로덕션(Vercel) 양쪽.

## 사전 실측 사실 (이 계획의 근거)

- `_detect_fund_anomaly`(dart_client.py:653): `FUND_UNREPORTED` = 계획금액>0 && (실집행액==0 || 실집행 내용 공란). `FUND_DIVERSION` = 차이발생사유(`dffrnc_occrrnc_resn`)에 키워드 14종("목적 변경", "사업취소", "일반운영자금", "변경사용", "유보" 등, dart_client.py:571-576) 포함.
- **기존 골드 7사(`tests/fixtures/sample_outputs/*_fund_usage.txt`) 전부 플래그 발화 0건** — 두 플래그 모두 라이브 검증 이력이 없고, CLAUDE.md 검증 매트릭스에 항목 자체가 없다.
- `fund_diversion_chain` 패턴은 매트릭스에 ⚠(2026-08-04 재점검에도 미발굴).
- 뷰어(docs/tool/index.html:1744-2060): `fundChain`이 납입일 기준 조달건으로 묶고 `hasDiff`면 "· 집행 차이 사유 보고 있음" 1줄 + `fundChainDisclosureHints`(90일 근접 신호 공시) 표기. **키워드 판정은 뷰어에 없다**(무판정 원칙에 따른 의도된 설계) — 따라서 뷰어 검증 목표는 "판정하는가"가 아니라 "차이 사유가 있는 회사에서 사실 표기·근접 힌트가 실제로 렌더되는가"다.

## Global Constraints

- 점수·등급 없음 원칙(v0.8.5): 검증 과정에서 어떤 판정 문구도 사용자 출력에 추가하지 않는다. 이 계획은 **기존 출력의 발화 여부 확인**이며 렌더 문구 변경은 범위 밖.
- 인물 데이터·미검증 의심 기업 실명은 public 레포에 커밋하지 않는다. 수집 코퍼스는 `tmp/fund_misuse_probe/`(gitignore 영역)에만 둔다.
- 키워드 보강·임계 변경 등 **코드 수정은 이 계획의 범위 밖** — 갭은 REPORT.md에 기록만 하고 후속 PR 후보로 남긴다(단, Task 4에서 발화 사례가 나오면 골드 추가·매트릭스 갱신 커밋은 수행).
- DART 호출 예산: 표본 40사 기준 약 300~500 호출 — 일 한도 내이지만 `time.sleep(0.15)` 유지.
- API 키는 환경변수 `DART_API_KEY`(설정 확인됨) 또는 `tmp/_apikey.txt`.

---

### Task 1: 차이사유 코퍼스 수집 스크립트

**Files:**
- Create: `tmp/fund_misuse_probe/collect.py`
- Output: `tmp/fund_misuse_probe/corpus.json`

**Interfaces:**
- Consumes: `dart_risk_mcp.core.dart_client`의 `fetch_market_disclosures`, `fetch_fund_usage`
- Produces: `corpus.json` — `[{corp_name, corp_code, corp_cls, records: [정규화 레코드(+flags)]}]`. Task 2~4가 이 파일을 읽는다.

- [ ] **Step 1: 수집 스크립트 작성**

```python
# tmp/fund_misuse_probe/collect.py
"""최근 사모 CB·유상증자 발행 소형사 표본에서 자금사용 내역을 수집.

표본 논리: 목적 외 사용은 사모 CB 다발 발행 소형사에서 관찰될 확률이
높다(금감원 2019-12 무자본 M&A 합동점검 — 조달자금 유용 최대 경로가
비상장주식 취득 55%). corp_code 역검색이 불가하므로 시장 스캔으로
CB 발행사를 추린 뒤 각사 fund_usage를 당긴다.
"""
import json, os, sys, time
from datetime import date, timedelta

ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
from dart_risk_mcp.core.dart_client import fetch_market_disclosures, fetch_fund_usage

API_KEY = os.environ.get("DART_API_KEY") or open(
    os.path.join(ROOT, "tmp", "_apikey.txt"), encoding="utf-8").read().strip()

CB_TITLES = ("전환사채권발행결정", "신주인수권부사채권발행결정", "유상증자결정")
end = date.today()
bgn = end - timedelta(days=365)

items = fetch_market_disclosures(
    API_KEY, bgn.strftime("%Y%m%d"), end.strftime("%Y%m%d"), max_pages=10)
issuers = {}
for it in items:
    nm = it.get("report_nm", "")
    if any(t in nm for t in CB_TITLES) and "기재정정" not in nm:
        code = it.get("corp_code")
        if code and code not in issuers:
            issuers[code] = {"corp_name": it.get("corp_name", ""),
                             "corp_cls": it.get("corp_cls", "K")}

print(f"CB/유상증자 발행사 {len(issuers)}곳 발견, 상위 40곳 조사")
out = []
for i, (code, meta) in enumerate(list(issuers.items())[:40]):
    recs = fetch_fund_usage(code, API_KEY, meta["corp_cls"], lookback_years=3)
    if recs:
        out.append({"corp_code": code, **meta, "records": recs})
    time.sleep(0.15)
    if (i + 1) % 10 == 0:
        print(f"  {i+1}/40 처리, 자금사용 보고 보유 {len(out)}곳")

with open(os.path.join(os.path.dirname(__file__), "corpus.json"),
          "w", encoding="utf-8") as f:
    json.dump(out, f, ensure_ascii=False, indent=1)
n_diff = sum(1 for c in out for r in c["records"] if r.get("dffrnc_resn"))
n_flag = sum(1 for c in out for r in c["records"] if r.get("flags"))
print(f"완료: {len(out)}곳 / 차이사유 보고 레코드 {n_diff}건 / 플래그 발화 {n_flag}건")
```

> 주의: `fetch_fund_usage`의 반환 레코드 필드명(`dffrnc_resn`·`flags`)은 실행 전
> `dart_client.py:1984` 부근에서 실제 반환 스키마를 확인해 맞춘다(`_normalize_fund_usage`는
> `dffrnc_resn`, 플래그 부착 키는 docstring상 `flags`).

- [ ] **Step 2: 실행**

```bash
python tmp/fund_misuse_probe/collect.py
```

Expected: `완료: N곳 / 차이사유 보고 레코드 M건 / 플래그 발화 K건` 출력. N=0이면 `fetch_market_disclosures` 페이지 수를 20으로 늘려 재실행.

- [ ] **Step 3: 표본이 빈약하면(차이사유 레코드 <5건) 윈도우 확대**

`bgn`을 730일로 늘리고 `[:40]`을 `[:80]`으로 확대해 1회 재실행. 그래도 <5건이면 그 사실 자체가 발견이다(사모 CB 발행사의 차이사유 보고가 희소) — Task 6 보고서에 기록하고 진행.

- [ ] **Step 4: 커밋 없음 확인**

`tmp/`는 산출물 영역 — `git status`로 추적 파일에 corpus가 없는지 확인만 한다.

---

### Task 2: FUND_DIVERSION 키워드 리콜 실측

**Files:**
- Create: `tmp/fund_misuse_probe/analyze_keywords.py`
- Output: `tmp/fund_misuse_probe/keyword_report.txt`

**Interfaces:**
- Consumes: `corpus.json`(Task 1), `dart_risk_mcp.core.dart_client._FUND_DIVERSION_KEYWORDS`
- Produces: `keyword_report.txt` — 히트/미스 문구 전량 목록. Task 6이 인용한다.

- [ ] **Step 1: 분석 스크립트 작성**

```python
# tmp/fund_misuse_probe/analyze_keywords.py
import json, os, sys
ROOT = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))
sys.path.insert(0, ROOT)
from dart_risk_mcp.core.dart_client import _FUND_DIVERSION_KEYWORDS

base = os.path.dirname(__file__)
corpus = json.load(open(os.path.join(base, "corpus.json"), encoding="utf-8"))

hits, misses = [], []
for c in corpus:
    for r in c["records"]:
        resn = (r.get("dffrnc_resn") or "").strip()
        if not resn:
            continue
        row = (c["corp_name"], resn[:120])
        if any(kw in resn for kw in _FUND_DIVERSION_KEYWORDS):
            hits.append(row)
        else:
            misses.append(row)

lines = [f"차이사유 보고 레코드: {len(hits)+len(misses)}건",
         f"키워드 히트(FUND_DIVERSION 발화): {len(hits)}건",
         f"키워드 미스(문구는 있으나 미발화): {len(misses)}건", "", "== 히트 =="]
lines += [f"  [{n}] {t}" for n, t in hits]
lines += ["", "== 미스 (키워드 보강 후보) =="]
lines += [f"  [{n}] {t}" for n, t in misses]
open(os.path.join(base, "keyword_report.txt"), "w", encoding="utf-8").write("\n".join(lines))
print("\n".join(lines[:4]))
```

- [ ] **Step 2: 실행 및 판독**

```bash
python tmp/fund_misuse_probe/analyze_keywords.py
```

판독 기준: 미스 문구 중 **의미상 목적 외 사용**(예: "자금운용 계획 변경", "사용계획 변경", "미집행", "타 용도 사용" 등 변형)이 있으면 = 리콜 갭 확정 → Task 6 보고서의 "키워드 보강 후보" 절에 문구 원문 그대로 기록. 미스가 전부 정상 사유(집행 지연·환율 등)면 키워드는 현행 유지가 맞다고 기록.

---

### Task 3: FUND_UNREPORTED 정밀도(오탐) 점검

**Files:**
- Create: `tmp/fund_misuse_probe/analyze_unreported.py`
- Output: `tmp/fund_misuse_probe/unreported_report.txt`

**Interfaces:**
- Consumes: `corpus.json`(Task 1)
- Produces: `unreported_report.txt` — 납입 경과일 구간별 FUND_UNREPORTED 분포. Task 6이 인용한다.

- [ ] **Step 1: 분석 스크립트 작성**

핵심 가설: "납입 직후(예: 6개월 미만)의 미집행은 정상일 수 있다 → FUND_UNREPORTED가 recency와 무관하게 발화한다면 오탐 소지". 이를 분포로 실측한다.

```python
# tmp/fund_misuse_probe/analyze_unreported.py
import json, os
from datetime import date, datetime

base = os.path.dirname(__file__)
corpus = json.load(open(os.path.join(base, "corpus.json"), encoding="utf-8"))
today = date.today()
buckets = {"~6개월": [], "6~18개월": [], "18개월~": [], "납입일불명": []}

for c in corpus:
    for r in c["records"]:
        if "FUND_UNREPORTED" not in (r.get("flags") or []):
            continue
        pay = (r.get("pay_de") or "").replace(".", "").replace("-", "")[:8]
        try:
            days = (today - datetime.strptime(pay, "%Y%m%d").date()).days
        except ValueError:
            buckets["납입일불명"].append(c["corp_name"]); continue
        key = "~6개월" if days < 183 else ("6~18개월" if days < 548 else "18개월~")
        buckets[key].append(c["corp_name"])

lines = ["FUND_UNREPORTED 발화 레코드의 납입 경과일 분포:"]
for k, v in buckets.items():
    lines.append(f"  {k}: {len(v)}건" + (f" — {', '.join(sorted(set(v))[:5])}" if v else ""))
lines.append("")
lines.append("판독: '~6개월' 비중이 크면 정상 미집행 포함 오탐 소지(후속 보강 후보 — "
             "납입 recency 유예 등). '18개월~'는 실질 미집행·미보고로 의미 있는 신호.")
open(os.path.join(base, "unreported_report.txt"), "w", encoding="utf-8").write("\n".join(lines))
print("\n".join(lines))
```

- [ ] **Step 2: 실행**

```bash
python tmp/fund_misuse_probe/analyze_unreported.py
```

Expected: 구간별 건수 출력. 발화 0건이면 그것도 결과 — "표본 내 FUND_UNREPORTED 무발화"로 기록.

---

### Task 4: MCP 종단 검증 + 골드·매트릭스 갱신

**Files:**
- Modify: `scripts/regen_goldens.py`(발화 회사 확보 시 COMPANIES 추가) 또는 `tests/fixtures/sample_outputs/<회사명>_fund_usage.txt` 직접 추가
- Modify: `CLAUDE.md` 라이브 검증 매트릭스(`FUND_DIVERSION`/`FUND_UNREPORTED` 행 신설)

**Interfaces:**
- Consumes: Task 1~3 결과 중 플래그 발화 회사명
- Produces: 골드 파일 + 매트릭스 행. 기존 회귀 게이트(`test_golden_output_hygiene.py`)가 이후 이 골드를 지킨다.

- [ ] **Step 1: 발화 회사로 MCP 도구 종단 실행**

corpus에서 플래그 발화 회사 1~2곳(FUND_DIVERSION 우선, 없으면 FUND_UNREPORTED 중 "18개월~" 구간)을 골라 도구 레벨로 실행:

```bash
python -c "
import asyncio
from dart_risk_mcp.server import track_fund_usage
print(asyncio.run(track_fund_usage('회사명', lookback_years=3)))
"
```

> `track_fund_usage`가 동기 함수면 `asyncio.run` 없이 직접 호출로 바꾼다(실행 전 `server.py`에서 async 여부 확인).

Expected: 출력에 플래그 라인(`FUND_DIVERSION` 또는 `FUND_UNREPORTED`)과 차이사유 원문이 보인다. **점수·등급 문구가 없어야 한다.**

- [ ] **Step 2: 골드 추가**

```bash
python scripts/regen_goldens.py --companies <회사명> --tools fund_usage
python -m pytest tests/test_golden_output_hygiene.py -v
```

Expected: hygiene PASS. 실패 시 출력에 금지 표기가 섞였다는 뜻 — 원인 확인 후 골드가 아니라 계획 밖 코드 이슈로 기록.

- [ ] **Step 3: 검증 매트릭스 갱신**

CLAUDE.md 매트릭스에 행 추가 — 발화 확보 시 ✅(회사·rcept 근거 명기), 미발굴 시 ⚠로 정직 기록(기존 관례: "코드 정상, 사례 미발굴" 형식으로 표본 규모·날짜 명기).

- [ ] **Step 4: 커밋**

```bash
git add CLAUDE.md tests/fixtures/sample_outputs/ scripts/regen_goldens.py
git commit -m "test: FUND_DIVERSION/FUND_UNREPORTED 라이브 검증 — 코퍼스 실측 결과 반영"
```

---

### Task 5: `fund_diversion_chain` 패턴(⚠) 발화 시도

**Files:**
- Output: `tmp/fund_misuse_probe/chain_candidates.txt`
- Modify(발화 시): `CLAUDE.md` 매트릭스 ⚠→✅, 골드 추가

**Interfaces:**
- Consumes: Task 1의 issuers 목록(CB 발행사), `analyze_company_risk`
- Produces: 후보별 패턴 발화 여부 기록

- [ ] **Step 1: 교차 후보 추출**

Task 1 스캔 결과에서 **CB 발행 + "타법인주식및출자증권양수결정" 둘 다** 최근 1년 내 공시한 회사를 추린다(시장 items를 corp_code로 groupby — collect.py 실행 시 `items`를 `market_items.json`으로 함께 덤프해 두면 재호출 불필요. Task 1 Step 1 스크립트에 `json.dump(items, ...)` 1줄 추가).

- [ ] **Step 2: 후보별 analyze_company_risk 실행**

```bash
python -c "
from dart_risk_mcp.server import analyze_company_risk
print(analyze_company_risk('후보회사명', lookback_years=1))
"
```

(async 여부는 Task 4 Step 1과 동일하게 확인.) Expected: 복합 패턴 섹션에 `fund_diversion_chain`("조달-유용 체인") 표시 여부 확인. 후보 최대 5곳.

- [ ] **Step 3: 결과 기록**

발화 시: 골드 추가(`<회사명>_analyze.txt`) + 매트릭스 ⚠ 제거. 미발화 시: 후보 회사 수·사유(예: CB_BW 신호와 stock_acq 신호가 같은 조회 창에 안 잡힘)를 매트릭스 ⚠ 행에 갱신 기록.

---

### Task 6: 뷰어(기본형) 렌더 검증 — 로컬 + 배포 실물

**Files:**
- Output: 스크린샷(스크래치패드), `tmp/fund_misuse_probe/REPORT.md`(최종 종합)

**Interfaces:**
- Consumes: Task 1~5에서 확보한 "차이사유 보고 있는 회사" 1곳 + 발화 회사 1곳
- Produces: REPORT.md — 3계층(MCP 플래그/패턴/뷰어) 검증 결과 종합

- [ ] **Step 1: 로컬 릴레이 기동 + 뷰어 열기**

`.claude/launch.json`에 dev_relay 항목이 없으면 추가한 뒤 preview로 기동(`scripts/dev_relay.py`, 포트는 스크립트 상단 확인). 뷰어 `docs/tool/index.html`을 브라우저 pane으로 연다.

- [ ] **Step 2: 대상 회사 조회 → fundCore 패널 확인**

확인 항목(모두 **무판정 원칙 준수** 여부 포함):
1. "자금사용 내역" 패널에 조달건이 납입일 기준으로 묶여 표시되는가(`fundChain`)
2. 차이사유 보고가 있는 회사에서 "· 집행 차이 사유 보고 있음" 줄이 실제로 렌더되는가
3. "근접 조달 신호 공시" 힌트(90일 창)가 뜨는가
4. 판정성 문구(전용·유용·위험 등급 등)가 **없는가** — 있으면 회귀

- [ ] **Step 3: 배포 실물 확인**

프로덕션 뷰어(Vercel 배포 URL — 레포 README/vercel 설정에서 확인)에서 같은 회사로 반복. 근거: 파일이 맞다는 것과 배포가 동작한다는 것은 다르다(과거 실측 교훈). API 키 입력이 필요한 화면이면 사용자 키 입력이 필요하므로, 로컬 릴레이 결과와 네트워크 요청(pssrpCptalUseDtls/prvsrpCptalUseDtls 200 응답)까지만 확인하고 그 사실을 REPORT에 명기.

- [ ] **Step 4: 종합 보고서 작성**

`tmp/fund_misuse_probe/REPORT.md`에 기록:
- 표본 규모·기간, 차이사유 보고 밀도(희소성 자체가 발견일 수 있음)
- FUND_DIVERSION 리콜 실측(히트/미스, 보강 후보 키워드 문구 원문)
- FUND_UNREPORTED recency 분포와 오탐 소지 평가
- fund_diversion_chain 발화 여부
- 뷰어 렌더 4항목 결과(로컬/배포 각각)
- 후속 과제 후보(키워드 보강, FUND_UNREPORTED recency 유예 등 — 코드 수정은 별도 PR)

- [ ] **Step 5: 커밋 (매트릭스·골드 변경분만)**

```bash
git add CLAUDE.md tests/fixtures/sample_outputs/
git commit -m "docs: fund misuse 탐지 검증 라운드 결과 — 매트릭스 갱신"
```

`tmp/` 산출물은 커밋하지 않는다(미검증 의심 기업 실명 포함 가능).

---

## 성공 기준

| 질문 | 판정 방법 |
|---|---|
| MCP가 목적 외 사용을 잡는가 | FUND_DIVERSION 라이브 발화 ≥1건 확보 → 골드+매트릭스 ✅. 미발굴이면 표본 규모와 함께 ⚠ 정직 기록 |
| 키워드 14종이 충분한가 | 코퍼스 미스 문구 중 의미상 유용 사례 존재 여부(존재=리콜 갭 확정, 문구 원문 기록) |
| FUND_UNREPORTED가 신호인가 소음인가 | 납입 경과일 분포 — ~6개월 발화 비중으로 오탐 소지 평가 |
| 패턴 계층(fund_diversion_chain)이 작동하는가 | CB+타법인양수 교차 후보 ≤5곳에서 analyze_company_risk 발화 여부 |
| 뷰어가 같은 사실을 보여주는가 | 차이사유 보유 회사에서 "집행 차이 사유 보고 있음"+근접 힌트 렌더(로컬+배포), 무판정 유지 |

## Self-Review 결과

- 스펙 커버리지: 사용자 질문은 "뷰어(기본형)과 MCP 양쪽" — MCP 플래그(Task 1~4)·패턴(Task 5)·뷰어(Task 6) 모두 태스크 존재. ✅
- 플레이스홀더: 실행 코드 전량 포함. 단 `fetch_fund_usage` 반환 필드명·server 도구의 async 여부 2건은 실행 시점 확인 지시로 명기(스키마 추정 커밋 방지 — "재지 않은 값" 교훈). ✅
- 타입 일관성: corpus.json 스키마(Task 1 산출)를 Task 2·3이 동일 키로 소비. ✅

---

## 부록 A: FUND_DIVERSION 리콜 갭 6건 원문 표

`.superpowers/sdd/2026-08-02-fund-misuse-detection-verification/task-2-report.md`(2차 개정, 리뷰 반영 재작성)의 확정 결과를 그대로 옮긴다. 코퍼스: 15개 회사·문장형 차이사유(`dffrnc_resn`) 429건 전수 표본.

**판정 로직(재작성판)**: `plan_useprps`(계획 용도)/`real_dtls_cn`(실집행 용도)/`dffrnc_resn`(차이사유) 3필드 각각에서 6개 표준 카테고리(채무상환/타법인증권취득/자산취득·지분취득/시설자금/신규사업투자/운영자금·운전자금) 키워드를 전부 스캔해 집합으로 뽑고, `plan_set`과 `real_set`이 완전히 disjoint일 때만(또는 구조화 필드가 겹쳐도 `dffrnc_resn` 자체가 disjoint 카테고리를 언급할 때) "카테고리 불일치"로 판정한다. 같은 회사의 같은 카테고리 전환은 `(회사, plan_set, real_set, resn_set)` 단위로 묶어 대표 문구 1건 + 반복 횟수로 집계한다(문구 바이트 차이로 인한 중복 카운트 방지).

**재실행 출력(실측)**:

```
차이사유 보고 레코드(실질 문장형, '-' 마커 제외): 429건
키워드 히트(FUND_DIVERSION 발화): 0건
키워드 미스: 429건
  - 카테고리 불일치(리콜 갭 후보, 회사×카테고리 전환 단위): 6건
  - 카테고리 동일(상환 메커니즘 상세 등, 고유 문구): 48건
    (그중 미사용/미집행류 — FUND_UNREPORTED 후보, 고유 문구): 1건
```

**진짜 리콜 갭 6건 (회사×카테고리 전환 단위, 원문 인용)**:

| # | 회사 | plan_useprps → real_dtls_cn (카테고리) | 대표 dffrnc_resn 원문 | 반복 |
|---|------|------------------------------------------|------------------------|------|
| 1 | 본느 | 운전자금 → 운전자금(원재료 매입 외) *[구조화는 동일 카테고리, 사유 문구가 disjoint]* | "사내보유, 타사지분취득" | 8건 |
| 2 | 링크드 | 운영자금 → 타법인증권취득자금 | "2023년 12월 11일 (주)액션스퀘어 제3자배정 유상증자 약32억원 납입" | 8건 |
| 3 | 링크드 | 운영자금 → 채무상환 자금 | "2024년 2월 19일 (주)와이제이엠게임즈 제4회차 전환사채 15억원 조기상환" | 8건 |
| 4 | 링크드 | 운영자금 → 시설자금 | "2025년 4월 30일 토지,건물 등 유형자산 37억원 취득" | 2건 |
| 5 | 형지엘리트 | 신규사업 투자 및 운영 자금 → 전환사채 상환(주1) | "이자비용 등" | 5건 |
| 6 | 비에스제이홀딩스 | 채무상환 → 자산취득 | "(주)엘에스엘씨엔씨 회사채 인수대금으로 사용" | 11건 |

**판독**:
- **본느**: 계획·실집행 모두 "운전자금" 카테고리로 구조화 보고됐지만, 차이사유 문구가 그 운전자금 잔액 일부를 "타사지분취득"에 썼다고 명시한다 — 구조화 필드로는 포착 안 되는 목적 외 사용이며, 금감원 2019-12 무자본 M&A 합동점검이 지목한 "조달자금 유용의 최대 경로(비상장주식 취득 55%)"와 정확히 일치.
- **링크드**: 계획은 "운영자금"인데 실집행이 타법인증권취득자금(제3자배정 유상증자 납입)·채무상환자금(타사 CB 조기상환)·시설자금(부동산 취득)으로 각각 갈렸다 — 구조화 필드 자체가 계획과 다른 카테고리를 보고한 명백한 불일치. 상대방 상호가 보고 시점마다 액션스퀘어→넥써쓰, 와이제이엠게임즈→링크드(자기 자신)로 바뀌는 점은 상호변경 이력이 있는 회사군 사이를 자금이 순환한 정황이나, 이는 이 태스크의 판정 범위(카테고리 불일치) 밖이라 별도 기록만 남긴다.
- **형지엘리트**: 계획은 신규사업투자+운영자금인데 실집행이 전환사채 상환(채무상환) — 구조화 필드 자체가 disjoint.
- **비에스제이홀딩스**: 계획은 채무상환인데 실집행이 자산취득(타법인 회사채 인수) — 구조화 필드 자체가 disjoint. 같은 회사의 나머지 9종 문구(미지급배당금 출자전환·차입금 출자전환·CB 차환 4종·종속회사 지분취득·상계발행)는 계획=실집행 카테고리가 동일해 리콜 갭에서 제외했다.

**결론**: 이 6건은 전부 현재 14종 키워드(목적변경/사업취소/운영자금 전용/유보 등 정형화된 법정 문구)에 걸리지 않는다 — 키워드가 "계획-실집행 카테고리 자체의 이탈"이 아니라 "정형 문구 재진술"만 잡고 있다는 구조적 한계가 실측으로 확인된다. 발화 0건이라 재현 가능한 라이브 골드는 만들 수 없어 골드는 미추가 — 키워드 보강 후보로 남긴다.

---

## 부록 B: FUND_UNREPORTED 31/17 산정 방법

`.superpowers/sdd/2026-08-02-fund-misuse-detection-verification/task-3-report.md`(2차 개정, 재리뷰 반영)의 최종 방법 정의와 수치를 그대로 옮긴다.

**방법**: 조달건(corp_code+tm+pay_de+kind) 단위로 corpus 전체(플래그 여부 무관)에서 그 조달건의 모든 레코드를 모아 가장 최근 `year`(사업연도) 레코드들만 남기고, 그 안의 각 라인아이템에 core `_detect_fund_anomaly`(`dart_risk_mcp/core/dart_client.py:653`)와 동일한 조건 — `plan_amount>0 and (real_dtls_amount==0 or not real_dtls_cn)` — 을 적용한다. 하나라도 만족하면 "미해소(도구가 최신 데이터에서도 여전히 플래그)", 전부 불만족이면 "해소(옛 스냅샷 잔재)". 재구현이 corpus에 이미 기록된 core 실제 `flags`와 100% 일치하는지 코드 내 `assert`로 자체 검증(불일치 0건 확인 후 실행 성공).

**① 레코드 단위 원 분포(48건, 도구가 실제 뱉는 값 — 브리프 PART 1)**:

```
~6개월    :  2건 — 링크드
6~18개월  : 13건 — 링크드, 오르비텍, 피아이이
18개월~   : 33건 — HLB, 유티아이, 코이즈, 피아이이
납입일불명 :  0건
```

회사별 분포(48건): 유티아이 25 · 오르비텍 8 · 피아이이 6 · HLB 5 · 링크드 3 · 코이즈 1. 조달건(회사+tm+pay_de+kind) 단위로는 15건. 공모/사모 교차 중복 0건.

**② 최신연도 기준 실질 미집행 재산출(주 기준, 도구 실제 판정)**:

```
전체 조달건: 15건
해소(옛 스냅샷 잔재 — 도구가 더 이상 플래그하지 않음): 레코드 31건 (64.6%) / 조달건 8건
미해소(도구가 최신 데이터에서도 여전히 플래그): 레코드 17건 (35.4%) / 조달건 7건
```

해소된 8개 조달건 중 6개(링크드·코이즈·유티아이 4건)는 100% 완전소진, HLB(tm=-/2022.12.09)·피아이이(tm=1/2025.01.23, public) 2개는 부분집행(각 15.0%·25.5%)이지만 `real_dtls_amount>0`·`real_dtls_cn` 기재로 도구가 더 이상 플래그하지 않는다. 미해소 7개 조달건(17건)은 링크드 잔여 1건(tm=4)·HLB 1건(tm=-/2022.12.10)·오르비텍 4건(tm=8~11회차)·피아이이 1건.

**[참고 지표] 100% 완전소진 기준(1차 수정 정의)**: `sum(plan_amount) == sum(real_dtls_amount) > 0`으로 다시 집계하면 해소 27건/6조달건(56.2%), 미해소 21건/9조달건(43.8%)이 된다 — 도구 실제 판정과는 HLB(2022.12.09)·피아이이(2025.01.23, public) 2개 조달건·4레코드만큼 괴리가 있어 참고 지표로만 병기한다.

**확정 결론(주 기준)**:

1. FUND_UNREPORTED의 주된 오탐 모드는 recency(~6개월 유예 부족)가 아니라 "다년 보고 스냅샷 미정산"이다 — 48건 중 31건(64.6%)은 플래그가 발화한 시점의 스냅샷일 뿐, 같은 조달건의 더 나중 연도 보고서에서 도구의 실제 판정 기준으로 이미 갱신돼 더 이상 플래그되지 않는다.
2. 유티아이 25건(48건 중 최다)은 4개 조달건 전부 100% 완전소진으로 해소됐다 — 최다 기여 회사가 사실은 가장 확실하게 "해소된" 사례였다.
3. recency(~6개월) 오탐은 이번 표본에서 미미하다 — 미해소로 남는 ~6개월 구간은 2건(1개 조달건, 링크드)뿐이다.
4. 최신 데이터 기준으로도 도구가 여전히 플래그하는 실질 미해소는 17건(7개 조달건, 4개 회사: 링크드 잔여 1건·HLB 1건·오르비텍 4건·피아이이 1건)이다. HLB(3.65년째 14% 집행, 단 최신 데이터 자체가 2023년산)와 오르비텍(4개 조달건 전부 최신 2026년 보고서에서도 real=0)이 가장 뚜렷한 신호다.
5. **도구 개선 후보로 명기**: FUND_UNREPORTED 판정 시 같은 조달건의 더 최신 연도 보고서가 존재하면 그 보고서 기준으로 재정산해야 한다("최신 보고 기준 정산" 로직 부재가 구조적 오탐 원인). 현재는 연도별 스냅샷을 독립적으로 순회해 플래그를 매기므로 이미 해소된 조달건도 과거 스냅샷 그대로 48건 중 31건(64.6%)이 "오탐" 상태로 남는다.

---

## 부록 C: fund_diversion_chain 교차 후보 산정

`tmp/fund_misuse_probe/find_chain_candidates.py`(Task 5 Step 1, market_items.json 365일 시장 전체 스캔 기반) 스크립트 전문과 `tmp/fund_misuse_probe/chain_candidates.txt` 실행 결과를 보존한다.

**스크립트 전문**:

```python
"""
Task 5 Step 1: CB/BW 발행 + 타법인주식및출자증권양수결정(또는 영업양수결정) 둘 다
최근 1년 내 공시한 회사를 찾는다. market_items.json (365일 시장 전체 스캔)을 사용.
기재정정 공시는 제외.
"""
import json
import re

with open("tmp/fund_misuse_probe/market_items.json", encoding="utf-8") as f:
    items = json.load(f)

def is_amendment(report_nm):
    return bool(re.match(r"^\s*\[기재정정\]", report_nm)) or "정정신고서" in report_nm

CB_BW_PAT = re.compile(r"(전환사채권발행결정|신주인수권부사채권발행결정)")
ACQ_PAT = re.compile(r"(타법인주식및출자증권양수결정|영업양수결정)")

by_corp = {}
for it in items:
    rn = it.get("report_nm", "")
    if is_amendment(rn):
        continue
    corp = it.get("corp_code")
    if corp not in by_corp:
        by_corp[corp] = {"corp_name": it.get("corp_name"), "stock_code": it.get("stock_code"), "cb": [], "acq": []}
    if CB_BW_PAT.search(rn):
        by_corp[corp]["cb"].append((it.get("rcept_dt"), rn, it.get("rcept_no")))
    if ACQ_PAT.search(rn):
        by_corp[corp]["acq"].append((it.get("rcept_dt"), rn, it.get("rcept_no")))

candidates = {c: v for c, v in by_corp.items() if v["cb"] and v["acq"]}
cb_only = {c: v for c, v in by_corp.items() if v["cb"]}
acq_only = {c: v for c, v in by_corp.items() if v["acq"]}
cb_disclosure_count = sum(len(v["cb"]) for v in by_corp.values())
acq_disclosure_count = sum(len(v["acq"]) for v in by_corp.values())

print(f"Total corps in market_items: {len(by_corp)}")
print(f"CB_BW (전환사채권발행결정/신주인수권부사채권발행결정, 기재정정 제외): "
      f"{cb_disclosure_count} disclosures / {len(cb_only)} corps")
print(f"ACQ_REVIEW (타법인주식및출자증권양수결정/영업양수결정, 기재정정 제외): "
      f"{acq_disclosure_count} disclosures / {len(acq_only)} corps")
print(f"Candidates (CB/BW + ACQ both present, non-amendment): {len(candidates)}")
print()

print("=== CB_BW corps (full list) ===")
for corp, v in sorted(cb_only.items(), key=lambda x: x[1]["corp_name"] or ""):
    print(f"  {v['corp_name']} (corp_code={corp}, stock={v['stock_code']}): {len(v['cb'])} disclosures")
    for d in sorted(v["cb"]):
        print(f"    {d[0]} | {d[1]} | {d[2]}")
print()

print("=== ACQ_REVIEW corps (full list) ===")
for corp, v in sorted(acq_only.items(), key=lambda x: x[1]["corp_name"] or ""):
    print(f"  {v['corp_name']} (corp_code={corp}, stock={v['stock_code']}): {len(v['acq'])} disclosures")
    for d in sorted(v["acq"]):
        print(f"    {d[0]} | {d[1]} | {d[2]}")
print()

print("=== Candidates (intersection, full detail) ===")
for corp, v in candidates.items():
    print(f"=== {v['corp_name']} (corp_code={corp}, stock={v['stock_code']}) ===")
    print("  CB/BW disclosures:")
    for d in sorted(v["cb"]):
        print(f"    {d[0]} | {d[1]} | {d[2]}")
    print("  ACQ disclosures:")
    for d in sorted(v["acq"]):
        print(f"    {d[0]} | {d[1]} | {d[2]}")
    print()
```

**실행 결과(`chain_candidates.txt`)**:

```
Total corps in market_items: 1058
CB_BW (전환사채권발행결정/신주인수권부사채권발행결정, 기재정정 제외): 6 disclosures / 5 corps
ACQ_REVIEW (타법인주식및출자증권양수결정/영업양수결정, 기재정정 제외): 1 disclosures / 1 corps
Candidates (CB/BW + ACQ both present, non-amendment): 0

=== CB_BW corps (full list) ===
  HLB (corp_code=00199252, stock=028300): 1 disclosures
    20251103 | 주요사항보고서(신주인수권부사채권발행결정) | 20251103000268
  본느 (corp_code=01098792, stock=226340): 2 disclosures
    20260803 | 주요사항보고서(전환사채권발행결정) | 20260731000813
    20260803 | 주요사항보고서(전환사채권발행결정) | 20260731000816
  유티아이 (corp_code=00961774, stock=179900): 1 disclosures
    20251031 | 주요사항보고서(전환사채권발행결정) | 20251031000418
  피아이이 (corp_code=01429220, stock=452450): 1 disclosures
    20250804 | 주요사항보고서(전환사채권발행결정) | 20250804000209
  효성화학 (corp_code=01316236, stock=298000): 1 disclosures
    20251031 | 주요사항보고서(전환사채권발행결정) | 20251031000547

=== ACQ_REVIEW corps (full list) ===
  두산 (corp_code=00117212, stock=000150): 1 disclosures
    20260731 | 주요사항보고서(타법인주식및출자증권양수결정) | 20260731000787

=== Candidates (intersection, full detail) ===
```

교집합 0 — CB_BW 6건/5개 법인, ACQ_REVIEW 1건/1개 법인, 겹치는 법인 없음. 후보 0건이라 `analyze_company_risk` 종단 실행은 생략했다.
