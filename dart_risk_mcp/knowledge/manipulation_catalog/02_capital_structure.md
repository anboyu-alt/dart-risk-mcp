# 자본구조 조작
> 카테고리: Capital Structure Manipulation  
> 생성일: 2026-04-20  
> 포함 유형: 2.1, 2.2, 2.3, 2.4, 2.5, 2.6

---

## 2.1: Reverse Split (Stock Consolidation)

- **Severity**: HIGH
- **Base Score**: 3
- **Crisis Timeline**: 18개월

### 정의
Dramatic reverse split (>5:1) to mask poor financial health

### 탐지 키워드
감자, 역감자, 주식병합, 주식통합, 15대1감자, 50대1감자, 액면분할

### Red Flags
- Reverse split ratio >5:1
- Share count reduction >80%
- Timing: before delisting threshold
- Market float suppression

### 금감원·금융위 적발 사례

> 현재 수집 기간 내 해당 유형의 보도자료 사례가 확인되지 않았습니다.

### 적발 기법 종합

> 집계된 항목이 없습니다.


### 인용 법조

> 집계된 항목이 없습니다.


### 기존 현장 기사 인용

- 셀레스트라: 15대1 감자 (3800만주→250만주) (20250806)
- NPX상장폐지위기 (20251103)

---

## 2.2: Capital Reduction (Equity Dilution via Reverse Split)

- **Severity**: HIGH
- **Base Score**: 3
- **Crisis Timeline**: 15개월

### 정의
Reverse split announced as 'capital reduction'; ratio >10:1

### 탐지 키워드
자본감소, 감자결정, 감자공시, 이익배당으로서감자, 손실보전감자, 주식병합으로감자

### Red Flags
- Capital reduction >50% of prior share capital
- Timing: before earnings release or debt maturity
- Announced as 'shareholder-friendly' measure
- Shares consolidated >10:1

### 금감원·금융위 적발 사례

> 현재 수집 기간 내 해당 유형의 보도자료 사례가 확인되지 않았습니다.

### 적발 기법 종합

> 집계된 항목이 없습니다.


### 인용 법조

> 집계된 항목이 없습니다.


### 기존 현장 기사 인용

- 감자·병합 모니터링 (20250915)

---

## 2.3: Gamja-Hapbyeong (Simultaneous Reverse Split + Merger)

- **Severity**: CRITICAL
- **Base Score**: 5
- **Crisis Timeline**: 8개월

### 정의
Reverse split + merger announcement within 30 days

### 탐지 키워드
감자병합, 감자및병합, 감자병합동시신고, 감자와병합, 통합감자

### Red Flags
- Both gamja + hapbyeong filings ≤30 days apart
- Stock price <1,000 KRW + debt restructuring
- Timing: before insolvency announcement

### 금감원·금융위 적발 사례

> 현재 수집 기간 내 해당 유형의 보도자료 사례가 확인되지 않았습니다.

### 적발 기법 종합

> 집계된 항목이 없습니다.


### 인용 법조

> 집계된 항목이 없습니다.


### 기존 현장 기사 인용

- gamja_hapbyeong_monitor.py detects ≥2 signals within window

---

## 2.4: 3rd Party Placement (제3자배정 유상증자)

- **Severity**: HIGH
- **Base Score**: 4
- **Crisis Timeline**: 12개월

### 정의
3rd party equity placement at preferential terms

### 탐지 키워드
제3자배정, 유상증자, 제3자배정유상증자, 특정인배정, 지정배정

### Red Flags
- Price ≥15% discount to VWAP
- Buyer: PE fund / private equity
- Lock-up period <1 year
- Multiple 3PA within 12 months

### 금감원·금융위 적발 사례

- **2026-04-19 12:00:50 / 금융감독원** — [상장폐지 회피 등을 위한 불법행위 끝까지 추적하여 엄단하겠습니다](https://www.fss.or.kr/fss/bbs/B0000188/view.do?nttId=217322&menuNo=200218)  
  - 적발 기법: 유상증자 공시심사 강화, 특수관계자 거래 패턴 분석, 매출액 및 자기자본 과대계상 적발, 시세조종 주문 패턴 분석, 회계처리기준 위반 감시, 미공개정보 이용 거래 탐지, 거래량 미달 회피 행위 적발  
  - 제재: 조사·공시·회계 부서 합동 대응체계 구축, 집중감시 및 엄정 조치, 회계감리 대상 30% 이상 확대, 필요시 정정명령 및 검찰 고발  
  - 인용 법조: 자본시장법, 상장폐지 기준, 회계처리기준, 공시 의무 규정  
  - 요약: 상장폐지 요건 강화(2026년 1월)에 따라 상장폐지 위험 기업들의 불법행위가 급증. 금감원이 적발한 주요 사례: (1) 횡령 자금으로 유상증자하여 허위 자기자본 확충, (2) 특수관계자와의 실물거래 없는 매출 과대계상, (3) 허위 재고자산으로 매출원가 축소, (4) 회계처리기준 위반 공시 전 내부자 주식 매도, (5) 본인 및 가족계좌를 이용한 시세조종으로 거래량 미달 요건 회피

- **2025-03-10 11:29:32 / 금융감독원** — [사모 CB,BW를 통한 허위 자금조달 및 허위 사업계획으로 주가 부양 후 부당이득을 취한 조직적 불공정거래 세력 적발,조치](https://www.fss.or.kr/fss/bbs/B0000188/view.do?nttId=191815&menuNo=200218)  
  - 적발 기법: 대량보유상황 보고서 허위 기재 적발, 공시서류의 중요사항 허위 기재 분석, 사모CB·BW 발행 계획 대비 실제 조달 현황 추적, 신규사업 발표와 자금조달 공시의 시간적 연관성 분석, 관계자 거래를 통한 순환구조 추적, 주가 급등 후 고가 매도 패턴 분석  
  - 제재: 검찰 고발 및 과징금 부과 조치 의결 (구체 규모는 비공개)  
  - 인용 법조: 자본시장법 제178조 (부정거래 행위 금지), 자본시장법 제161조 (신고·공시의무), 코스닥시장 상장규정 제51조 (의무보유 규정)  
  - 요약: 불공정거래 세력이 다수의 투자조합을 통해 코스닥 상장사들의 경영권을 인수하면서, 실제 인수주체를 은폐하고 특별관계자 주식보유를 숨겨 의무보유 기간 회피. 전기차·우주항공 등 주력사업과 무관한 허위 신규사업을 발표하고, 실체 불분명한 투자조합과 페이퍼컴퍼니를 CB·BW 인수대상자로 내세워 대규모 자금조달이 성공한 것처럼 홍보. 실제로는 발행이 장기간 지연되거나 철회되었으며, 일부 조달된 자금도 담보 구매 등 사용 불가능한 조건부 자금. 주가를 인위적으로 부양 후 고가 매도하여 수백억원의 부당이득 취득.

- **2024-03-25 12:00:49 / 금융감독원** — [불공정거래로 연명하는 좀비기업을 집중조사하여 주식시장에서 퇴출시키겠습니다](https://www.fss.or.kr/fss/bbs/B0000188/view.do?nttId=134936&menuNo=200218)  
  - 적발 기법: 연말 거액 유상증자를 통한 상폐요건 면탈 패턴 분석, 가장납입성 유상증자 혐의 적발, 차명주식 고가 매도를 통한 부당이득 추적, 재무제표 자산 과대계상 적발, CB·BW 발행을 통한 자금조달 후 부실 심화 분석, 미공개정보 이용 주가 조종 적발, 감사의견 거절 전 주식 매도 거래 분석, 호재성 정보 유포 및 고가 매도 패턴  
  - 제재: 조치완료된 15개사 중 부당이득규모 총 1,694억원, 부정거래 7건·시세조종 1건·미공개·보고의무위반 7건, 증선위 결정·검찰 이첩 등  
  - 인용 법조: 자본시장법 제174조 (부정거래), 자본시장법 제175조 (시세조종), 자본시장법 제188조 (미공개정보 이용), 자본시장법 제167조 (보고의무위반)  
  - 요약: 상장폐지 회피 목적으로 불공정거래를 적발한 사례들: ① A사: 실질사주가 시세조종 전문가에게 지시하여 12명 명의 계좌로 주가 인위조종 후 CB·BW 73억원 조달, 10개월 내 상장폐지. ② B사: 최대주주가 백신 위탁생산 호재 유포로 주가 상승 후 고가 매도(52억원 부당이득), 감사의견 거절 전 추가 매도(105억원 부당이득). ③ C사: 무자본 M&A 세력이 연말 거액 유상증자로 상폐요건 면탈 후 증자대금 횡령, 차명주식 고가 매도. ④ D사: 자산 과대계상으로 상폐요건 탈피 후 최대주주 주식 매도, 수년간 수백억원대 자금조달.

### 적발 기법 종합

- 연말 거액 유상증자를 통한 상폐요건 면탈 패턴 분석 (1건)
- 가장납입성 유상증자 혐의 적발 (1건)
- 차명주식 고가 매도를 통한 부당이득 추적 (1건)
- 재무제표 자산 과대계상 적발 (1건)
- CB·BW 발행을 통한 자금조달 후 부실 심화 분석 (1건)
- 미공개정보 이용 주가 조종 적발 (1건)
- 감사의견 거절 전 주식 매도 거래 분석 (1건)
- 호재성 정보 유포 및 고가 매도 패턴 (1건)
- 대량보유상황 보고서 허위 기재 적발 (1건)
- 공시서류의 중요사항 허위 기재 분석 (1건)

### 인용 법조

- 자본시장법 제174조 (부정거래) (1건)
- 자본시장법 제175조 (시세조종) (1건)
- 자본시장법 제188조 (미공개정보 이용) (1건)
- 자본시장법 제167조 (보고의무위반) (1건)
- 자본시장법 제178조 (부정거래 행위 금지) (1건)
- 자본시장법 제161조 (신고·공시의무) (1건)
- 코스닥시장 상장규정 제51조 (의무보유 규정) (1건)
- 자본시장법 (1건)
- 상장폐지 기준 (1건)
- 회계처리기준 (1건)

### 기존 현장 기사 인용

- manipulation_monitor.py signal type: 3PCA

---

## 2.5: Rights Undersubscription (공모 미달)

- **Severity**: MEDIUM
- **Base Score**: 2
- **Crisis Timeline**: 9개월

### 정의
Rights offering undersubscribed; shortfall filled by related parties

### 탐지 키워드
유상증자미달, 공모미달, 청약미달, 미청약, 인수회피

### Red Flags
- Subscription rate <70%
- Shortfall filled by founders/PE
- Offer price >VWAP

### 금감원·금융위 적발 사례

> 현재 수집 기간 내 해당 유형의 보도자료 사례가 확인되지 않았습니다.

### 적발 기법 종합

> 집계된 항목이 없습니다.


### 인용 법조

> 집계된 항목이 없습니다.


### 기존 현장 기사 인용

- 공모 미달로 인한 시장 신뢰도 하락

---

## 2.6: Treasury Stock Buyback + Reissue Pattern

- **Severity**: MEDIUM
- **Base Score**: 3
- **Crisis Timeline**: 12개월

### 정의
Buyback for capital reduction + immediate reissue as EB/CB

### 탐지 키워드
자기주식, 자사주매입, 자사주처분, 자사주EB, 자기주식매입

### Red Flags
- Buyback announcement → reissue ≤6 months
- Buyback volume >total FCF
- Reissue as EB/CB to related parties

### 금감원·금융위 적발 사례

> 현재 수집 기간 내 해당 유형의 보도자료 사례가 확인되지 않았습니다.

### 적발 기법 종합

> 집계된 항목이 없습니다.


### 인용 법조

> 집계된 항목이 없습니다.


### 기존 현장 기사 인용

- 자사주EB급증 (20251010)

---
