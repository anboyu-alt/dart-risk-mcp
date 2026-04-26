# 활용 예시 — DART Risk MCP v1.0.0 데모 보고서 4종

같은 시기(2026-04-25), 같은 한국 상장사 3개(셀트리온·제이스코홀딩스·헬릭스미스)를 대상으로 **MCP 사용 여부와 보고서 형태를 달리해 만든 보고서 4편**입니다. Claude(또는 Claude Code)가 동일 입력에서 어떤 결과를 만들어내는지 직접 비교할 수 있습니다.

대상 회사 3개는 정상/위험/부실 스펙트럼으로 선정됐습니다 — `tests/fixtures/sample_outputs/` 골드 매트릭스에서 검증된 회사들의 부분집합.

---

## 4편 비교

| # | 파일 | 입력 | 작성 도구 | 분량 | 용도 |
|---|------|------|---------|:---:|------|
| 1 | [`dart_risk_v1_0_demo.md`](dart_risk_v1_0_demo.md) | "MCP 18개 도구 39회 호출 후 데모 보고서" | **DART Risk MCP만** | 1,574줄 | **MCP 단독 출력** — 도구별 한국어 prose 원문이 그대로 보존된 점검·데모 보고서 |
| 2 | [`dart_baseline_no_mcp.md`](dart_baseline_no_mcp.md) | "같은 3개 회사 비교" | **MCP 없이 web_search만** | 279줄 | **대조군** — 일반 검색·언론 기사로만 작성한 baseline |
| 3 | [`dart_integrated_report.md`](dart_integrated_report.md) | "정량 분석(MCP) + 맥락(검색) 결합" | **MCP + web_search** | 389줄 | **종합 보고서** — 분석가가 두 자료원을 결합해 작성한 실무형 |
| 4 | [`dart_risk_v1_0_investor.md`](dart_risk_v1_0_investor.md) | "일반 투자자도 읽을 수 있게 풀어 써줘" | **MCP + 자연어 가이드** | 1,865줄 | **일반 투자자용** — 5분 용어 가이드 + 위험 신호 해석 + 학습 포인트 |

전체 원본(.html, .pdf 포함)은 `OneDrive/필드뉴스/202604/files/`에 보관.

---

## 결합 효과 — #2와 #3·#4를 비교하면 보이는 것

같은 회사를 같은 시점에 봤지만, **MCP가 있고 없고가 결정적으로 갈리는 사실 3가지**가 종합 보고서(#3)에서 등장합니다.

### 1. 제이스코홀딩스 — "매출 +45% 성장" vs "손실 더 깊어짐"

- **#2 일반 검색 baseline**: "중국 바오리에너지에 7,600억원 규모 니켈 공급 계약" 외형 호재 중심
- **#3 종합 (MCP 결합)**:
  - 매출 283억 → 410억 (**+45%**)
  - 당기순손실 -267억 → **-320억 (악화)**
  - 누적 결손금 +330억 더 쌓임 → 자본총계/자본금 150% → **124% (잠식 직전)**
  - MCP `track_capital_structure`가 **`capital_churn_anomaly`(자본 주무르기) 패턴 감지** + **자기전환사채매도결정 9건 연속**
  - MCP `check_disclosure_anomaly`가 **정정공시 비율 56%** (정상 경고선 20%의 3배)

### 2. 헬릭스미스 — "거의 흑자 전환" 보도의 진실

- **#2 일반 검색**: "당기순손실 -4.6억으로 거의 흑자 전환"
- **#3 종합 (MCP 결합)**:
  - 매출 49.7억 → **26억 (-48%)**
  - 영업이익 **-99억 (여전히 적자)**
  - 당기순이익이 0에 가까워진 결정적 이유: **당기손익-공정가치측정금융자산 평가이익 +468억**(영업외수익)
  - MCP `track_fund_usage`가 **사모 38·39·40회차 운영자금 사용내역 미보고 15건 누적** 자동 검출

### 3. 셀트리온 — "비정상 빈도" 신호의 의도 입증

- **#1 MCP 단독**: 365일 중 자사주 거래 32건 — 표면상 비정상 빈도
- **#3 종합 (MCP 결합)**: 서정진 회장 공개 발언 ("현금배당 세금 50% vs 자사주 소각 세금 0") + 정부 밸류업 가이드라인 호응 + 일관된 매입-소각 시간 간격 → **위험이 아닌 의도적 설계**로 해석

→ **같은 신호도 MCP만으로는 위험으로 분류되고, 검색 맥락을 더하면 의도적 설계로 정확히 해석됩니다.** 양쪽이 보완 관계라는 결론이 #3·#4에서 명시적으로 도출됩니다.

---

## 사용된 MCP 도구 (보고서 1·3·4 공통)

회사별 9개 (× 3 회사 = 27회):
- `analyze_company_risk`, `build_event_timeline`, `track_capital_structure`, `track_insider_trading`, `get_audit_opinion_history`, `scan_financial_anomaly`, `track_fund_usage`, `track_debt_balance`, `check_disclosure_anomaly`

회사 정보 보조 (× 3 = 9회):
- `get_company_info`, `get_shareholder_info`, `get_executive_compensation`

회사 무관 (× 1 = 4회):
- `compare_financials`, `find_actor_overlap`, `find_risk_precedents`, `search_market_disclosures`

총 **18종 도구·39회 호출** (도구 카탈로그 23개 중 78% 커버리지).

---

## 재현 방법

본 4편 보고서를 직접 재현하려면:

1. DART Risk MCP를 설치한 Claude Code 인스턴스를 준비합니다 ([설치 방법](../README.md#5-설치-방법) 참고).
2. 보고서 1(데모)을 만들고 싶다면 `~/.claude/plans/v1-0-ga-plan-spicy-sunbeam.md`의 "최종 프롬프트" 블록을 그대로 붙여넣기.
3. 보고서 4(일반 투자자용)는 같은 도구 호출에 "일반 투자자도 읽을 수 있게 5분 용어 가이드와 위험 신호 해석 + 학습 포인트를 추가해줘" 한 줄을 더하면 됩니다.
4. 보고서 2(MCP 없는 baseline)는 "MCP 도구를 사용하지 말고 web_search만으로 같은 3개 회사를 비교해줘"로 가능합니다.

각 보고서는 약 5 ~ 10분 (보고서 1·3) 또는 10 ~ 15분 (보고서 4) 소요됩니다.

---

본 예시 4편은 모두 v1.0.0 GA 시점(2026-04-25~26)에 생성. v1.0의 stable output contract([CHANGELOG.md](../CHANGELOG.md) 참고)가 적용된 한국어 prose 출력의 실제 모습을 보여줍니다.
