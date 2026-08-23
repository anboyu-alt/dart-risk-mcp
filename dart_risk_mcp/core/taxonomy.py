"""
Signal Taxonomy Mapping for dart-monitor
────────────────────────────────────────────────────────────────
Maps the 27-signal corporate manipulation taxonomy (derived from 166
field news articles June 2025-March 2026) to the dart-monitor detection
pipeline. Extends the current 8-signal system with enhanced keyword
patterns, severity grades, and cross-signal correlation logic.

CATEGORIES:
  1. Convertible Bond & Debt Manipulation (7 signals)
  2. Capital Structure Manipulation (6 signals)
  3. Ownership & Control (5 signals)
  4. Governance & Disclosure (4 signals)
  5. Corporate Action Manipulation (5 signals)
  6. Accounting & Financial Reporting (3 signals)
  7. Market Manipulation & Trading (3 signals)
  8. Crisis & Distress Signals (4 signals)

SEVERITY GRADES:
  - CRITICAL: 24-month median crisis timeline, 8+ months to peak impact
  - HIGH: 12-18 month median crisis timeline, 4-8 months to impact
  - MEDIUM: 6-12 month median crisis timeline, 2-4 months to impact
  - LOW: 3-6 month latency, delayed impact signal

Usage:
  import signal_taxonomy_mapping as stm

  # Get signal config
  signal = stm.TAXONOMY["1.1"]
  keywords = signal["keywords"]

  # Cross-reference signals
  patterns = stm.CROSS_SIGNAL_PATTERNS["founder_fade"]

  # Score aggregation with severity weighting
  risk_score = stm.calculate_risk_score(signals_detected, weights=stm.SEVERITY_WEIGHTS)
"""

import os
from datetime import datetime, timedelta
from typing import Dict, List, Tuple, Optional

# ────────────────────────────────────────────────────────────────
# SIGNAL TAXONOMY: 27 Distinct Manipulation Signals
# ────────────────────────────────────────────────────────────────

TAXONOMY = {
    # CATEGORY 1: Convertible Bond & Debt Manipulation (7 signals)
    "1.1": {
        "id": "1.1",
        "category": "Convertible Bond & Debt Manipulation",
        "name": "Refixing (리픽싱)",
        "description": "Downward adjustment of conversion price without DART disclosure",
        "base_score": 3,
        "severity": "HIGH",
        "crisis_timeline_months": 12,
        "keywords": [
            "리픽싱",
            "전환가액조정",
            "전환가액인하",
            "전환가격인하",
            "전환가격 인하",
            "전환가액 인하",
            "조정된 전환가액",
        ],
        "red_flags": [
            "Magnitude >10% downward",
            "Multiple refixings <6 months",
            "Timing: refixing without prior guidance",
            "Market price <conversion price",
        ],
        "field_evidence": ["위메이드 800억원 CB조기상환", "리픽싱모니터"],
        "investor_implication": "Existing shareholders diluted; CB holders protected at shareholders' expense",
    },
    "1.2": {
        "id": "1.2",
        "category": "Convertible Bond & Debt Manipulation",
        "name": "CB Early Repayment with Internal Dividends",
        "description": "CB redemption funded by subsidiary payouts (non-operating)",
        "base_score": 4,
        "severity": "HIGH",
        "crisis_timeline_months": 18,
        "keywords": [
            "전환사채상환",
            "CB상환",
            "사채상환",
            "자회사배당",
            "내부배당",
            "배당금상환",
            "배당을통한상환",
        ],
        "red_flags": [
            "CB redemption >50% funded by subsidiary dividends",
            "Subsidiary dividend >operating profit",
            "Timing: CB redemption weeks after dividend",
            "Negative operating CF + positive net CF",
        ],
        "field_evidence": [
            "위메이드: 전기아이피 400억, 위메이드맥스 100억, 비상장사 700억 배당 → CB상환",
            "반복불가능한 자금조달",
            "2025-03-24 금감원: 사모CB 악용 4유형 적발 (미공개정보·허위사업·가액부풀리기·허위자금조달)",
        ],
        "investor_implication": "Asset base hollowing; unsustainable liquidity management",
    },
    "1.3": {
        "id": "1.3",
        "category": "Convertible Bond & Debt Manipulation",
        "name": "Exchange Bond (EB) Issuance to Related Parties",
        "description": "EB issued to related parties at favorable conversion terms",
        "base_score": 4,
        "severity": "CRITICAL",
        "crisis_timeline_months": 9,
        "keywords": [
            "교환사채",
            "교환채발행",
            "EB발행",
            "EB배임",
            "제3자배정교환채",
            "자사주연동EB",
            "관련자EB",
        ],
        "red_flags": [
            "Related-party issuance >50%",
            "Conversion discount >15% vs market",
            "Automatic conversion upon stock decline",
            "EB to founders/insiders at preferential terms",
        ],
        "field_evidence": [
            "하림지주 EB (20250919)",
            "중앙첨단소재 CB (20250924)",
            "인피니트 EB배임 (20251020)",
        ],
        "investor_implication": "Minority shareholder dilution; governance failure",
    },
    "1.4": {
        "id": "1.4",
        "category": "Convertible Bond & Debt Manipulation",
        "name": "RCPS (Redeemable Convertible Preferred Stock) Hidden Dilution",
        "description": "RCPS with guaranteed returns + automatic conversion triggers",
        "base_score": 4,
        "severity": "HIGH",
        "crisis_timeline_months": 15,
        "keywords": [
            "RCPS",
            "상환전환우선주",
            "우선주발행",
            "전환우선주",
            "보장수익",
            "4%연복리",
            "우선주배임",
        ],
        "red_flags": [
            "Guaranteed return ≥3% annually",
            "Automatic conversion on stock split/dividend",
            "Most-favored-creditor clauses",
            "RCPS terms more favorable than equity",
        ],
        "field_evidence": [
            "파마리서치 RCPS: CVC캐피탈 4% 연복리 + 전환조항 (20250708)",
            "대신증권 RCPS발행 (20251121)",
        ],
        "investor_implication": "Compound dilution; RCPS holders protected vs equity holders",
    },
    "1.5": {
        "id": "1.5",
        "category": "Convertible Bond & Debt Manipulation",
        "name": "CB Issue-and-Refinance Cycle (EB Rollover)",
        "description": "Continuous CB issuance to cover maturing CB; net cash worsens",
        "base_score": 4,
        "severity": "CRITICAL",
        "crisis_timeline_months": 6,
        "keywords": [
            "돌려막기",
            "CB돌려막기",
            "EB돌려막기",
            "리파이낸싱",
            "차환",
            "연속CB발행",
            "연속차입",
        ],
        "red_flags": [
            "CB/EB issuance ≤30 days before CB maturity",
            "New issuance principal <110% maturing CB",
            "Repeat ≥3 times annually",
            "Negative FCF despite debt rollover",
        ],
        "field_evidence": [
            "SKAI (비트나인): CB/EB 돌려막기 (20250903)",
            "셀리버리: 연속 유증·CB (20250918)",
        ],
        "investor_implication": "Debt spiral; imminent default risk",
    },
    "1.6": {
        "id": "1.6",
        "category": "Convertible Bond & Debt Manipulation",
        "name": "Below-Market CB Redemption",
        "description": "Company repurchases own CB at 10-20% below market price",
        "base_score": 3,
        "severity": "HIGH",
        "crisis_timeline_months": 12,
        "keywords": [
            "자사채매입",
            "사채매입",
            "차입금감소",
            "저가상환",
            "조기상환",
            "우대상환",
        ],
        "red_flags": [
            "CB repurchase discount 10-20%",
            "Timing: before earnings announcement",
            "Accounting treatment as debt reduction vs. OCI",
        ],
        "field_evidence": [
            "동성제약: 경영권 방어용 회생 신청 (회생신청전 부도조장) (20251014)",
        ],
        "investor_implication": "Artificial distress signaling; governance violation",
    },
    "1.7": {
        "id": "1.7",
        "category": "Convertible Bond & Debt Manipulation",
        "name": "Self-Held Equity Securities (EB on Treasury Stock)",
        "description": "EB/CB linked to company's own treasury stock, not new issuance",
        "base_score": 3,
        "severity": "MEDIUM",
        "crisis_timeline_months": 12,
        "keywords": [
            "자사주EB",
            "자사주연동",
            "자사주기반",
            "자사채",
            "자기주식EB",
            "자기주식연동",
        ],
        "red_flags": [
            "EB conversion: treasury stock vs new shares",
            "Treasury repurchase → EB issuance pattern",
            "Circular: repurchase → hold → issue → dilution",
        ],
        "field_evidence": ["자사주EB급증 (20251010)"],
        "investor_implication": "Hidden share dilution; share count manipulation",
    },

    # CATEGORY 2: Capital Structure Manipulation (6 signals)
    "2.1": {
        "id": "2.1",
        "category": "Capital Structure Manipulation",
        "name": "Reverse Split (Stock Consolidation)",
        "description": "Dramatic reverse split (>5:1) to mask poor financial health",
        "base_score": 3,
        "severity": "HIGH",
        "crisis_timeline_months": 18,
        "keywords": [
            "감자",
            "역감자",
            "주식병합",
            "주식통합",
            "15대1감자",
            "50대1감자",
            "액면분할",
        ],
        "red_flags": [
            "Reverse split ratio >5:1",
            "Share count reduction >80%",
            "Timing: before delisting threshold",
            "Market float suppression",
        ],
        "field_evidence": [
            "셀레스트라: 15대1 감자 (3800만주→250만주) (20250806)",
            "NPX상장폐지위기 (20251103)",
        ],
        "investor_implication": "Forced liquidation at depressed valuation; delisting risk",
    },
    "2.2": {
        "id": "2.2",
        "category": "Capital Structure Manipulation",
        "name": "Capital Reduction (Equity Dilution via Reverse Split)",
        "description": "Reverse split announced as 'capital reduction'; ratio >10:1",
        "base_score": 3,
        "severity": "HIGH",
        "crisis_timeline_months": 15,
        "keywords": [
            "자본감소",
            "감자결정",
            "감자공시",
            "이익배당으로서감자",
            "손실보전감자",
            "주식병합으로감자",
        ],
        "red_flags": [
            "Capital reduction >50% of prior share capital",
            "Timing: before earnings release or debt maturity",
            "Announced as 'shareholder-friendly' measure",
            "Shares consolidated >10:1",
        ],
        "field_evidence": ["감자·병합 모니터링 (20250915)"],
        "investor_implication": "Share consolidation triggers forced liquidation at depressed valuation",
    },
    "2.3": {
        "id": "2.3",
        "category": "Capital Structure Manipulation",
        "name": "Gamja-Hapbyeong (Simultaneous Reverse Split + Merger)",
        "description": "Reverse split + merger announcement within 30 days",
        "base_score": 5,
        "severity": "CRITICAL",
        "crisis_timeline_months": 8,
        "keywords": [
            "감자병합",
            "감자및병합",
            "감자병합동시신고",
            "감자와병합",
            "통합감자",
        ],
        "red_flags": [
            "Both gamja + hapbyeong filings ≤30 days apart",
            "Stock price <1,000 KRW + debt restructuring",
            "Timing: before insolvency announcement",
        ],
        "field_evidence": ["gamja_hapbyeong_monitor.py detects ≥2 signals within window"],
        "investor_implication": "Prelude to delisting or forced restructuring; near-insolvency signal",
    },
    "2.4": {
        "id": "2.4",
        "category": "Capital Structure Manipulation",
        "name": "3rd Party Placement (제3자배정 유상증자)",
        "description": "3rd party equity placement at preferential terms",
        "base_score": 4,
        "severity": "HIGH",
        "crisis_timeline_months": 12,
        "keywords": [
            "제3자배정",
            "유상증자",
            "제3자배정유상증자",
            "특정인배정",
            "지정배정",
        ],
        "red_flags": [
            "Price ≥15% discount to VWAP",
            "Buyer: PE fund / private equity",
            "Lock-up period <1 year",
            "Multiple 3PA within 12 months",
        ],
        "field_evidence": [
            "2026-04-19 금감원: 상폐회피 목적 허위 자기자본 확충 — 횡령자금 유상증자 적발",
            "2025-03-10 금감원: 투자조합·페이퍼컴퍼니 CB·BW 인수대상으로 내세운 가장납입 구조",
        ],
        "investor_implication": "Existing shareholders diluted; governance control transferred",
    },
    "2.5": {
        "id": "2.5",
        "category": "Capital Structure Manipulation",
        "name": "Rights Undersubscription (공모 미달)",
        "description": "Rights offering undersubscribed; shortfall filled by related parties",
        "base_score": 2,
        "severity": "MEDIUM",
        "crisis_timeline_months": 9,
        "keywords": [
            "유상증자미달",
            "공모미달",
            "청약미달",
            "미청약",
            "인수회피",
        ],
        "red_flags": [
            "Subscription rate <70%",
            "Shortfall filled by founders/PE",
            "Offer price >VWAP",
        ],
        "field_evidence": ["공모 미달로 인한 시장 신뢰도 하락"],
        "investor_implication": "Market rejection of capital raise; weaker shareholders diluted",
    },
    "2.6": {
        "id": "2.6",
        "category": "Capital Structure Manipulation",
        "name": "Treasury Stock Buyback + Reissue Pattern",
        "description": "Buyback for capital reduction + immediate reissue as EB/CB",
        "base_score": 3,
        "severity": "MEDIUM",
        "crisis_timeline_months": 12,
        "keywords": [
            "자기주식",
            "자사주매입",
            "자사주처분",
            "자사주EB",
            "자기주식매입",
        ],
        "red_flags": [
            "Buyback announcement → reissue ≤6 months",
            "Buyback volume >total FCF",
            "Reissue as EB/CB to related parties",
        ],
        "field_evidence": ["자사주EB급증 (20251010)"],
        "investor_implication": "Share count manipulation; hidden dilution",
    },
    "2.7": {
        "id": "2.7",
        "category": "Capital Structure Manipulation",
        "name": "자본 이벤트 과다 반복",
        "description": "12개월 내 증자·감자·자사주·CB/BW/EB 등 자본 이벤트가 비정상적으로 집중",
        "base_score": 4,
        "severity": "HIGH",
        "crisis_timeline_months": 12,
        "keywords": [],  # 복합 판정이라 키워드 없음
        "red_flags": [
            "12개월 내 증자·감자·자사주 등 자본 이벤트 3건 이상",
            "CB·BW·EB 연속 발행",
            "자본구조 리듬의 비정상성",
        ],
        "field_evidence": [
            "금감원 2024·2025 주가조작 적발 사례(동성제약·헬릭스미스·셀리버리 등) "
            "공통 특징: 12개월 내 3~6건의 자본 이벤트 집중",
        ],
        "investor_implication": "잦은 자본 이벤트로 기존 주주 지분 희석·자본구조 불투명성 확대; 무자본 M&A·허위 신사업·상폐 회피 세력의 공통 지표",
    },
    "2.8": {
        "id": "2.8",
        "category": "Capital Structure Manipulation",
        "name": "Treasury Stock Trust Indirect Acquisition",
        "description": "신탁회사를 통한 자기주식 우회 매입·해지. 직접 매입 신고 없이 신탁계약으로 자사주 매입 효과를 거두는 경로. 자사주 직접 결정과 같은 시계열에 표기해 자본 리듬을 본다.",
        "base_score": 0,
        "severity": "OBSERVATION",
        "crisis_timeline_months": 12,
        "keywords": [
            "자기주식취득 신탁계약",
            "자기주식취득 신탁",
            "자기주식 신탁",
        ],
        "red_flags": [
            "신탁계약 체결 후 단기간(<6개월) 해지",
            "직접 매입과 신탁 매입의 동시 발생",
            "신탁 만기 직후 처분",
        ],
        "field_evidence": [],
        "investor_implication": "Indirect treasury acquisition path; combined with direct treasury cycle indicates capital rhythm management",
    },

    # CATEGORY 3: Ownership & Control (5 signals)
    "3.1": {
        "id": "3.1",
        "category": "Ownership & Control",
        "name": "Major Shareholder Change via Debt Conversion",
        "description": "Ownership transfer through CB/EB conversion; founder ownership diluted",
        "base_score": 3,
        "severity": "CRITICAL",
        "crisis_timeline_months": 9,
        "keywords": [
            "최대주주변경",
            "대주주변경",
            "채권자주주화",
            "채무자주주화",
            "순위변경",
        ],
        "red_flags": [
            "Major shareholder changes ≥2 times <1 year",
            "Founder ownership drops <10%",
            "External investor takes control via CB conversion",
        ],
        "field_evidence": [
            "헬릭스미스: 카나리아바이오엠→바이오솔루션 경영권 교체 (20250902)",
            "동성제약: 1억 어음부도→경영권 박탈 (20251014)",
        ],
        "investor_implication": "Founder exit imminent; governance instability",
    },
    "3.2": {
        "id": "3.2",
        "category": "Ownership & Control",
        "name": "Controlling Shareholder Below-Market Exit",
        "description": "Founder sells stake at significant discount to market value",
        "base_score": 3,
        "severity": "HIGH",
        "crisis_timeline_months": 12,
        "keywords": [
            "지분매각",
            "저가매각",
            "주식매각",
            "경영권이양",
            "지분양수도",
        ],
        "red_flags": [
            "Sale price ≥15% discount to market",
            "Timing: before earnings announcement",
            "Founder retains <10% post-sale",
            "Buyer: PE fund / activist investor",
        ],
        "field_evidence": [
            "SKAI: 강철순 전 대표 지분·경영권 매각 (94억원, 주당2851원) (20250903)",
        ],
        "investor_implication": "Founder abandonment; governance deterioration",
    },
    "3.3": {
        "id": "3.3",
        "category": "Ownership & Control",
        "name": "Activist Investor Board Takeover",
        "description": "External investor forces board replacement; management purge",
        "base_score": 4,
        "severity": "HIGH",
        "crisis_timeline_months": 9,
        "keywords": [
            "경영진교체",
            "이사진교체",
            "사외이사진출",
            "활동주의펀드",
            "제2의창업",
        ],
        "red_flags": [
            "Board replacement >50%",
            "Timing: during operational crisis",
            "Activist investor stake >10%",
        ],
        "field_evidence": ["경영권 분쟁 4년 이상 지속 사례"],
        "investor_implication": "Governance warfare; operational disruption",
    },
    "3.4": {
        "id": "3.4",
        "category": "Ownership & Control",
        "name": "Management Succession Disputes",
        "description": "Founder vs external investor clash over CEO succession",
        "base_score": 3,
        "severity": "MEDIUM",
        "crisis_timeline_months": 12,
        "keywords": [
            "경영권분쟁",
            "대표이사분쟁",
            "경영진분쟁",
            "경영권다툼",
            "내홍",
        ],
        "red_flags": [
            "Multiple CEO announcements <12 months",
            "Founder vs board conflict public statements",
            "Shareholder lawsuits filed",
        ],
        "field_evidence": [
            "헬릭스미스: 창업자 김선영 지분 10% 이하 추락 (20250902)",
        ],
        "investor_implication": "Governance paralysis; strategic uncertainty",
    },
    "3.5": {
        "id": "3.5",
        "category": "Ownership & Control",
        "name": "Related-Party Circular Transfers",
        "description": "Share transfers through related party chain; ultimate owner hidden",
        "base_score": 3,
        "severity": "MEDIUM",
        "crisis_timeline_months": 15,
        "keywords": [
            "순환출자",
            "계열회사",
            "순환구조",
            "지분연쇄",
            "관련자거래",
        ],
        "red_flags": [
            "Ownership chain >3 levels deep",
            "Related party: family members / shell companies",
            "Transfer price <market value",
        ],
        "field_evidence": ["동성제약: SK플래닛 지분 정리 (150억원) (20250903)"],
        "investor_implication": "Hidden ownership; opaque control structure",
    },
    "3.6": {
        "id": "3.6",
        "category": "Ownership & Control",
        "name": "Insider Selling Before Adverse Disclosure",
        "description": "임원·대주주가 매도한 직후 30일 내에 감사의견 비적정·부도·횡령·조회공시 등 부정적 공시가 게시되는 패턴. 정보 우위 매도 가능성 검토 대상.",
        "base_score": 0,
        "severity": "OBSERVATION",
        "crisis_timeline_months": 3,
        "keywords": [],
        "red_flags": [
            "임원 매도 후 30일 내 감사의견 비적정",
            "임원 매도 후 30일 내 부도/횡령/조회공시",
            "분기 보고서 시점 보유 비율 급락 + 인접 부정 공시",
        ],
        "field_evidence": [],
        "investor_implication": "Possible information advantage trading; pre-disclosure selling pattern",
    },
    "3.7": {
        "id": "3.7",
        "category": "Ownership & Control",
        "name": "Controlling Shareholder Stock Pledge Agreement",
        "description": (
            "최대주주가 보유 주식을 담보로 제공하는 계약(체결·해제·취소)입니다. "
            "금감원 무자본 M&A 합동점검에서는 인수 단계①에서 인수주식을 담보로 "
            "잡힌 대출이 5% 대량보유보고에 미기재된 채 적발된 사례가 있습니다. "
            "다만 오너의 정상적인 주식담보대출(주담대)도 시장에서 흔한 자금 조달 "
            "방식이라 이 신호 하나만으로는 판단 근거가 되지 않아 참고 강도"
            "으로 다룹니다."
        ),
        "base_score": 2,
        "severity": "MEDIUM",
        "crisis_timeline_months": 12,
        "keywords": [
            "주식담보제공계약",
        ],
        "red_flags": [
            "인수 직후(단기간 내) 인수주식 자체를 담보로 제공",
            "담보설정비율이 보유 지분 대비 과도하게 높음",
            "5% 대량보유보고·임원 소유보고에 담보 사실 미기재",
            "담보권 실행(반대매매) 시 최대주주 지분 급락",
        ],
        "field_evidence": [
            "2019-12-19 금감원 무자본 M&A 합동점검: 인수 단계에서 인수주식을 "
            "담보로 잡힌 대출을 5% 대량보유보고에 기재하지 않은 사례 적발",
        ],
        "investor_implication": (
            "Not itself a determination — owner stock-secured loans are common; "
            "watch for post-acquisition timing and disclosure omissions"
        ),
    },

    # CATEGORY 4: Governance & Disclosure (4 signals)
    "4.1": {
        "id": "4.1",
        "category": "Governance & Disclosure",
        "name": "Shareholder Meeting Procedural Violations",
        "description": "Irregularities in shareholder voting; agenda manipulation",
        "base_score": 2,
        "severity": "MEDIUM",
        "crisis_timeline_months": 12,
        "keywords": [
            "주총위반",
            "의결권행사",
            "소집절차위반",
            "의결정족수미달",
            "주총부실",
        ],
        "red_flags": [
            "Quorum barely met",
            "Voting irregularities (split ballots, late tabuluation)",
            "Board proposal rejection rate >10%",
        ],
        "field_evidence": ["주주총회 소집절차 문제"],
        "investor_implication": "Governance failure; minority shareholder rights violated",
    },
    "4.2": {
        "id": "4.2",
        "category": "Governance & Disclosure",
        "name": "Related-Party Transactions at Non-Arm's-Length Prices",
        "description": "Related-party transactions with significant price distortion",
        "base_score": 3,
        "severity": "HIGH",
        "crisis_timeline_months": 12,
        "keywords": [
            "관련자거래",
            "특수관계자거래",
            "관계회사거래",
            "거래처집중",
            "비정상거래",
        ],
        "red_flags": [
            "Related-party transactions >20% revenue",
            "Price deviation >15% from market",
            "Buyer/seller: related party",
        ],
        "field_evidence": [
            "파마리서치 RCPS: 4% 연복리 (시장 수익률보다 높음) (20250708)",
        ],
        "investor_implication": "Asset siphoning; minority shareholder value transfer",
    },
    "4.3": {
        "id": "4.3",
        "category": "Governance & Disclosure",
        "name": "Disclosure and Reporting Obligation Violation",
        # 옛 값은 "Purposeful use of DART filing loopholes"였다. 2026-08-17 실측에서
        # 이 유형으로 실제 잡히는 공시가 전부 「불성실공시법인지정(예고)」 계열이고
        # 의도("purposeful")는 도구가 관측할 수 없는 값이라 사실 서술로 바꿨다.
        "description": "Exchange sanction for non-compliant disclosure; periodic/audit reports missing or filed late",
        "base_score": 2,
        "severity": "MEDIUM",
        "crisis_timeline_months": 9,
        "keywords": [
            "공시누락",
            "중요정보누락",
            "공시지연",
            "분할공시",
            "공시의무위반",
            # 2026-08-16/17 시장 전체 실측(60일, 30,765건) — DISCLOSURE_VIOL
            # 실제 매칭 51건/16종 전부가 「불성실공시법인지정(예고)」 계열이고,
            # 정정 제외 24,350건에서 아래 4개가 기존 키워드가 놓치던 실제
            # 제목(사업보고서미제출·감사보고서제출지연·공시위반제재금미납 등)을
            # 오탐 0건으로 추가 포착했다. 근거:
            # docs/catalog/gap-triage-2026-08-17.md.
            "불성실공시법인",
            "보고서미제출",
            "제출지연",
            "공시위반",
        ],
        # 옛 값("4시간 이내 미공시", "첨부파일 깊숙이 묻힘")은 이 도구가 잴 수 없는
        # 항목이었다. labels_ko.json의 한글 red_flags가 표시 단일 출처지만,
        # scripts/catalog/labels.py의 폴백이 이 값을 쓸 수 있어 함께 맞춘다.
        "red_flags": [
            "Designated (or pre-announced) as a non-compliant discloser by the exchange",
            "Annual/periodic report not filed",
            "Audit or half-year report filed late",
            "Disclosure-violation penalty left unpaid",
        ],
        "field_evidence": [
            "2025-02-27 금감원: IPO 허위 매출·자기자본 과대계상으로 상장 후 급락 사례",
            "2025-03-10 금감원: 공시서류 중요사항 허위기재 + 발행철회 반복 패턴 적발",
        ],
        "investor_implication": "Investor information asymmetry; market inefficiency",
    },
    "4.4": {
        "id": "4.4",
        "category": "Governance & Disclosure",
        "name": "Auditor Opinion Qualifications",
        "description": "Auditor opinion: qualified / adverse / disclaimed",
        "base_score": 4,
        "severity": "CRITICAL",
        "crisis_timeline_months": 12,
        "keywords": [
            "한정의견",
            "부적정의견",
            "의견거절",
            "감사범위제한",
            "감사인교체",
            "계속기업불확실",
        ],
        "red_flags": [
            "Auditor opinion: qualified / adverse / disclaimed",
            "Going-concern doubt disclosed",
            "Auditor change within 12 months",
            "Multiple accountants in 3 years",
        ],
        "field_evidence": [
            "네오이뮨텍: 계속기업가정 불확실 (20250902)",
            "2026-02-27 금감원: 최근 3년 결산 불공정거래 24건 중 79%가 1~3월 발생, 84%가 내부자 연루",
        ],
        "investor_implication": "Insolvency risk; default imminent",
    },

    # CATEGORY 5: Corporate Action Manipulation (5 signals)
    "5.1": {
        "id": "5.1",
        "category": "Corporate Action Manipulation",
        "name": "Equity Split + Dividend Combination",
        "description": "Stock split + dividend announcement to inflate shareholder count",
        "base_score": 2,
        "severity": "MEDIUM",
        "crisis_timeline_months": 6,
        "keywords": [
            "주식분할",
            "배당금",
            "분할배당",
            "주식배당",
            "액면분할",
        ],
        "red_flags": [
            "Stock split + dividend ≤30 days apart",
            "Pre-split dividend record date unclear",
        ],
        "field_evidence": ["기업행동 조작 패턴"],
        "investor_implication": "Artificial shareholder count inflation; trading liquidity illusion",
    },
    "5.2": {
        "id": "5.2",
        "category": "Corporate Action Manipulation",
        "name": "Buyback + Negative Cash Flow",
        "description": "Share buyback announcement despite negative operating cash flow",
        "base_score": 3,
        "severity": "HIGH",
        "crisis_timeline_months": 9,
        "keywords": [
            "자사주매입",
            "주식소각",
            "부도직전매입",
            "자금난속매입",
        ],
        "red_flags": [
            "FCF <0, buyback >10M USD announced",
            "Buyback funded by debt issuance",
            "Share price <book value",
        ],
        "field_evidence": ["부채상황에서의 자사주 매입 신호"],
        "investor_implication": "Shareholder value destruction; imminent debt distress",
    },
    "5.3": {
        "id": "5.3",
        "category": "Corporate Action Manipulation",
        "name": "Off-Market Asset Transfers",
        "description": "Asset transfer to related party at below fair value",
        "base_score": 4,
        "severity": "HIGH",
        "crisis_timeline_months": 12,
        "keywords": [
            "자산매각",
            "저가매각",
            "관련자자산매각",
            "사옥매각",
            "자산유출",
        ],
        "red_flags": [
            "Asset sale price <fair value (>15% discount)",
            "Buyer: related party / founder's shell company",
            "Timing: during cash crisis",
        ],
        "field_evidence": [
            "헬릭스미스: 마곡 사옥 매각 (20250902)",
        ],
        "investor_implication": "Asset base hollowing; founder wealth extraction",
    },
    "5.4": {
        "id": "5.4",
        "category": "Corporate Action Manipulation",
        "name": "Acquisitions During Distress",
        "description": "M&A announcement during financial distress; unrelated diversification",
        "base_score": 3,
        "severity": "MEDIUM",
        "crisis_timeline_months": 9,
        "keywords": [
            "인수",
            "합병",
            "인수합병",
            "위기속인수",
            "화장품인수",
        ],
        "red_flags": [
            "M&A deal size >50% of market cap",
            "Timing: during earnings miss / debt maturity",
            "Target: unrelated industry",
            "Deal financing: new debt + CB",
        ],
        "field_evidence": [
            "셀리버리: 700억원 화장품 회사 인수 (20250918)",
        ],
        "investor_implication": "Strategic misalignment; value destruction M&A",
    },
    "5.5": {
        "id": "5.5",
        "category": "Corporate Action Manipulation",
        "name": "Demerger with Asymmetric Value Distribution",
        "description": "Demerger with unequal value transfer to related party",
        "base_score": 4,
        "severity": "HIGH",
        "crisis_timeline_months": 12,
        "keywords": [
            "분할",
            "사업분할",
            "분할결정",
            "분할공시",
            "비대칭분할",
        ],
        "red_flags": [
            "Spun-off entity valuation opaque",
            "Founder/related party preferential stake in spinco",
            "Spinco burn rate >50% within 12 months post-spin",
        ],
        "field_evidence": [
            "파마리서치 RCPS 분할: 비대칭 가치배분 (20250708)",
        ],
        "investor_implication": "Value transfer to insiders; minority shareholder dilution",
    },
    "5.6": {
        "id": "5.6",
        "category": "Corporate Action Manipulation",
        "name": "Dividend Outflow While Loss-Making",
        "description": "당기순이익 적자임에도 현금배당이 결정되는 패턴. 특수관계자 보유 비중이 높을 때 자금 우회 경로로 작용할 수 있어 사실 표기 대상.",
        "base_score": 0,
        "severity": "OBSERVATION",
        "crisis_timeline_months": 12,
        "keywords": [
            "현금배당",
            "현금ㆍ현물배당결정",
            "주당 현금배당금",
        ],
        "red_flags": [
            "당기순이익 적자 + 현금배당 양수",
            "특수관계자 보유 ≥30% + 고배당",
            "감자 직후 단기간(<12개월) 배당 결정",
        ],
        "field_evidence": [],
        "investor_implication": "Cash outflow path to related parties despite operating losses",
    },
    "5.7": {
        "id": "5.7",
        "category": "Corporate Action Manipulation",
        "name": "Cash Outflow to Acquirer Side (Loans, Guarantees, Asset Purchases)",
        "description": (
            "금전대여·채무보증·담보제공·유형자산양수처럼 회사 자금·신용이 밖으로 "
            "나가는 거래. 대기업의 일상적 계열 지원과 단독으로는 구분되지 않아 "
            "참고 수준으로 다룬다. 다만 경영권 변경(최대주주변경) 직후 발생하면, "
            "인수 측이 인수자금을 회수하거나 인수 주체를 지원하는 구조로 쓰인 "
            "사례가 있어 시점을 함께 살펴볼 관찰 포인트가 된다. 2019-12-19 "
            "금감원 무자본 M&A 합동점검에서도 관계회사 등 대여·선급금이 조달자금 "
            "유용 경로의 29%를 차지한 것으로 집계됐다."
        ),
        "base_score": 2,
        "severity": "MEDIUM",
        "crisis_timeline_months": 12,
        "keywords": [
            "금전대여",
            "자금대여",
            "채무보증",
            "담보제공",
            "유형자산양수",
        ],
        "red_flags": [
            "최대주주변경 이후 12개월 내 발생",
            "거래 상대방이 특수관계자·계열회사",
            "동일 상대방 대상 반복 거래",
            "재무제표상 대여금·선급금이 전기 대비 큰 폭으로 증가",
        ],
        "field_evidence": [
            "아틀라스링크(구 알로이스): 최대주주변경 주식양수도(20260608) 후 "
            "계열회사 유형자산 현금 양수 60억(20260722)·타인에대한채무보증(20260729) 연쇄",
        ],
        "investor_implication": "Observation point on fund direction after a control change; not itself a determination",
    },
    "5.8": {
        "id": "5.8",
        "category": "Corporate Action Manipulation",
        "name": "Acquisition Requiring Counterparty Review",
        "description": (
            "영업양수·타법인주식및출자증권 양수(취득) 결정. 정상적인 사업 확장 M&A가 "
            "대다수이므로 그 자체는 판단 근거가 아니며, 거래 상대방·가액·외부평가 "
            "여부를 원문에서 직접 확인해야 성격을 알 수 있는 사실 안내 신호다."
        ),
        "base_score": 0,
        "severity": "OBSERVATION",
        "crisis_timeline_months": 12,
        # 2026-08-22: DART 실제 표기가 두 가지다 — DS005 법정 「…양수결정」과
        # 자율공시 「…취득결정」(후자가 4배 흔하다). 90일 실측 220건 중 189건이
        # 무신호였던 재현율 갭 수정. signals.py의 ACQ_REVIEW와 짝을 맞춘다.
        "keywords": [
            "영업양수",
            "타법인주식및출자증권양수",
            "타법인주식및출자증권취득",
        ],
        "red_flags": [
            "거래 상대방이 특수관계자",
            "외부평가 미실시",
            "자산총액 대비 거래규모 과대",
        ],
        "field_evidence": [],
        "investor_implication": "Counterparty and valuation confirmation needed; not itself a determination",
    },

    # CATEGORY 6: Accounting & Financial Reporting (3 signals)
    "6.1": {
        "id": "6.1",
        "category": "Accounting & Financial Reporting",
        "name": "Revenue Recognition Irregularities",
        "description": "Revenue recognition policy changes or aggressive timing",
        "base_score": 3,
        "severity": "HIGH",
        "crisis_timeline_months": 12,
        "keywords": [
            "수익인식",
            "매출인식",
            "수익조정",
            "선수금",
            "미수금급증",
        ],
        "red_flags": [
            "Revenue recognition policy change >K-IFRS guidelines",
            "Accounts receivable / revenue ratio spike",
            "Revenue recognition before cash receipt >90 days",
        ],
        "field_evidence": [
            "2026-04-19 금감원: 특수관계자 실물거래 없는 매출 과대계상·허위 재고자산으로 매출원가 축소 적발",
        ],
        "investor_implication": "Earnings quality deterioration; restatement risk",
    },
    "6.2": {
        "id": "6.2",
        "category": "Accounting & Financial Reporting",
        "name": "Contingent Liability Omission",
        "description": "Material contingent liabilities omitted from disclosures",
        "base_score": 3,
        "severity": "HIGH",
        "crisis_timeline_months": 15,
        "keywords": [
            "우발채무",
            "우발성채무",
            "미공개채무",
            "소송중인사건",
            "보증채무",
        ],
        "red_flags": [
            "Contingent liabilities >50% shareholders' equity",
            "Material lawsuit / regulatory fine not disclosed",
            "Guarantee obligations to related parties",
        ],
        "field_evidence": ["회계투명성 위반"],
        "investor_implication": "Hidden liabilities; balance sheet misrepresentation",
    },
    "6.3": {
        "id": "6.3",
        "category": "Accounting & Financial Reporting",
        "name": "RCPS Accounting Restructuring",
        "description": "RCPS reclassified as equity/debt to manipulate ratios",
        "base_score": 2,
        "severity": "MEDIUM",
        "crisis_timeline_months": 12,
        "keywords": [
            "RCPS회계",
            "우선주회계",
            "지분/부채분류",
            "회계변경",
        ],
        "red_flags": [
            "RCPS classification changes >K-IFRS guidance",
            "Debt/equity ratio manipulation via RCPS classification",
        ],
        "field_evidence": ["RCPS 회계 처리 신호"],
        "investor_implication": "Financial ratio manipulation; leverage misrepresentation",
    },

    # CATEGORY 7: Market Manipulation & Trading (3 signals)
    "7.1": {
        "id": "7.1",
        "category": "Market Manipulation & Trading",
        "name": "Pre-Disclosure Abnormal Trading",
        "description": "Unusual trading volume/price spike preceding public disclosure",
        "base_score": 4,
        "severity": "CRITICAL",
        "crisis_timeline_months": 3,
        "keywords": [
            "이상거래",
            "선반영",
            "미공개정보",
            "부당이득",
            "거래량급증",
        ],
        "red_flags": [
            "Trading volume >5x 20-day avg 1-5 days before disclosure",
            "Price spike >10% without news",
            "Timing: coincides with insider trading allegations",
        ],
        "field_evidence": [
            "2026-03-25 금감원: 상장사 IR 담당 임원이 미공개중요정보(자회사 치료제 승인) 이용 차명계좌 매수 — 5.5억 부당이득",
            "2026-01-21 금감원: 지배주주 연루 미공개정보 이용 거래 적발",
        ],
        "investor_implication": "Insider trading; market integrity violation",
    },
    "7.2": {
        "id": "7.2",
        "category": "Market Manipulation & Trading",
        "name": "Theme Stock Manipulation",
        "description": "Stock price inflation via speculative theme / meme stock pattern",
        "base_score": 3,
        "severity": "MEDIUM",
        "crisis_timeline_months": 6,
        "keywords": [
            "테마주",
            "작전주",
            "급등",
            "급락",
            "테마편승",
        ],
        "red_flags": [
            "Price volatility >100% YTD without fundamental changes",
            "Retail investor participation spike",
            "Media mentions spike without business updates",
        ],
        "field_evidence": [
            "SKAI: AI 테마주 (20250903)",
            "셀리버리: 파킨슨병 치료제 테마 (20250918)",
        ],
        "investor_implication": "Retail investor losses; speculative bubble",
    },
    "7.3": {
        "id": "7.3",
        "category": "Market Manipulation & Trading",
        "name": "Derivative Abuse (EB/CB Speculation)",
        "description": "EB/CB used for leveraged speculation rather than financing",
        "base_score": 3,
        "severity": "HIGH",
        "crisis_timeline_months": 9,
        "keywords": [
            "레버리지거래",
            "파생상품거래",
            "CB투기",
            "EB투기",
        ],
        "red_flags": [
            "EB/CB trading volume >>company equity volume",
            "Retail investor EB/CB position concentration",
        ],
        "field_evidence": ["파생상품 남용 신호"],
        "investor_implication": "Leverage-induced losses; retail investor harm",
    },

    # CATEGORY 8: Crisis & Distress Signals (4 signals)
    "8.1": {
        "id": "8.1",
        "category": "Crisis & Distress Signals",
        "name": "Engineered Insolvency",
        "description": "Deliberate asset depletion / liability inflation to trigger insolvency",
        "base_score": 5,
        "severity": "CRITICAL",
        "crisis_timeline_months": 6,
        "keywords": [
            "자본잠식",
            "부도",
            "회생",
            "어음부도",
            "의도적부도",
        ],
        "red_flags": [
            "Capital erosion >50% shareholders' equity within 12 months",
            "Debt restructuring while paying founder dividends",
            "Bill of exchange (어음) default without explanation",
        ],
        "field_evidence": [
            "동성제약: 1억 어음 부도 (20251014)",
            "셀리버리: 재무상태 악화 (20250918)",
            "2024-03-25 금감원: 좀비기업 15개사 부당이득 1,694억원 — 연말 유상증자 상폐요건 면탈 패턴 적발",
        ],
        "investor_implication": "Likely default / receivership; total shareholder loss",
    },
    "8.2": {
        "id": "8.2",
        "category": "Crisis & Distress Signals",
        "name": "Debt Restructuring as Equity Grab",
        "description": "Debt-to-equity conversion; founder exits while equity holders absorb loss",
        "base_score": 4,
        "severity": "CRITICAL",
        "crisis_timeline_months": 9,
        "keywords": [
            "구조조정",
            "채무조정",
            "채무면제",
            "DIP파이낸싱",
            "환권",
        ],
        "red_flags": [
            "Debt-to-equity conversion at <50% of par",
            "Founder exit before / during restructuring",
            "New investor (PE) enters post-restructuring",
        ],
        "field_evidence": [
            "헬릭스미스: 바이오솔루션 경영권 이양 (20250902)",
        ],
        "investor_implication": "Equity wiped out; shareholder control diluted to <1%",
    },
    "8.3": {
        "id": "8.3",
        "category": "Crisis & Distress Signals",
        "name": "Asset Liquidation Spiral",
        "description": "Sequential asset sales (real estate, subsidiaries) at distressed prices",
        "base_score": 4,
        "severity": "CRITICAL",
        "crisis_timeline_months": 12,
        "keywords": [
            "자산매각",
            "사옥매각",
            "자회사매각",
            "사업양도",
            "연쇄매각",
        ],
        "red_flags": [
            "Multi-asset sale pattern within 12 months",
            "Sale prices consistently <fair value",
            "Timing: during operational losses",
        ],
        "field_evidence": [
            "헬릭스미스: 사옥 매각 (20250902)",
            "셀리버리: 화장품 인수→손실 (20250918)",
        ],
        "investor_implication": "Cash burn from asset fire sales; liquidation path",
    },
    "8.4": {
        "id": "8.4",
        "category": "Crisis & Distress Signals",
        "name": "Going-Concern Doubt Escalation",
        "description": "Auditor doubt disclosure; management fails to remediate",
        "base_score": 5,
        "severity": "CRITICAL",
        "crisis_timeline_months": 6,
        "keywords": [
            "계속기업가정불확실",
            "계속기업불확실성",
            "회생절차",
            "파산절차",
            "감사인교체",
        ],
        "red_flags": [
            "Going-concern doubt disclosed ≥2 consecutive reporting periods",
            "Management response insufficient (restructuring plan delayed)",
            "Auditor change post-doubt disclosure",
        ],
        "field_evidence": [
            "네오이뮨텍: 계속기업가정 불확실 (20250902)",
        ],
        "investor_implication": "Default / receivership imminent; equity worthless",
    },
    "8.5": {
        "id": "8.5",
        "category": "Crisis & Distress Signals",
        "name": "Distress Stage Entry",
        "description": "부도발생·영업정지·회생절차 개시신청·해산사유 발생 — 부실 단계 진입을 직접 알리는 주요사항보고서. GOING_CONCERN 이후 후속 단계로 발생.",
        "base_score": 0,
        "severity": "OBSERVATION",
        "crisis_timeline_months": 0,
        "keywords": [],
        "red_flags": [
            "당좌거래정지(부도) 발생",
            "관리종목 사유 영업정지",
            "회생절차 개시신청",
            "주총 해산결의·해산사유 발생",
        ],
        "field_evidence": [],
        "investor_implication": "Receivership / liquidation path activated; equity claim subordinated",
    },
}


# ────────────────────────────────────────────────────────────────
# CROSS-SIGNAL PATTERN SEQUENCES
# ────────────────────────────────────────────────────────────────
#
# ⚠ `signal_sequence`는 이름과 달리 **순서로 쓰이지 않는다.** 매칭은
# `find_pattern_match`(부분집합)와 `find_pattern_overlaps`(교집합 크기)
# 둘 다 순서를 보지 않는다.
#
# `timeline_months`는 **2026-08-21부터 `find_pattern_overlaps`의 관찰 윈도우
# 게이트에 쓰인다**(`taxonomy_dates`를 넘긴 호출부에 한해). 아래 순서 축
# 실측 직후 같은 날 재측정으로 바뀐 부분이라 순서를 밝혀 둔다 —
# `find_pattern_match`는 여전히 날짜를 보지 않는다.
#
# 이는 미구현이 아니라 실측에 근거한 결정이다(2026-08-21, 12개사×3년,
# 관측 37건):
#   · 순서 일치율 48/75 = 64% (무작위 50%) — 셋 중 하나는 순서를 어긴다.
#     제약으로 넣으면 진짜 사례를 그만큼 떨어뜨린다.
#   · timeline_months 안에 들어온 관측 18/37 = 49% — 동전 던지기.
#     실제 기간은 중앙값 9개월·최대 35개월(예: 제이스코홀딩스 founder_fade
#     32개월 vs 설정 18개월, STX delisting_evasion 27개월 vs 설정 9개월).
#
# **간격 축은 그 뒤 재측정으로 도입했다**(2026-08-21 후속, 250개사×5년·관측
# 363건 — 위 측정이 스스로 지목한 "표본이 작다, 수백 개 회사가 필요하다"를
# 메운 표본). 위 49%가 옳았다는 것이 더 큰 표본에서도 확인됐다: 옛 설정값으로
# 게이트를 걸면 관측의 31.4%가 영향을 받았다(20.9% 패턴 자체 탈락 + 10.5%
# 축소). 결론은 "간격을 쓰지 말자"가 아니라 **"설정값이 틀렸다"**였다 —
# 패턴별 필요 개월의 p90으로 재보정(zombie_ma 12→30, fake_new_biz 6→30,
# audit_insider_dump 6→33, delisting_evasion 9→27, debt_spiral 12→21,
# fund_diversion_chain 12→21, related_party_hollowing 15→18)하니 영향이
# 31.4% → 8.0%로 떨어졌다. capital_backflow(12)는 "최대주주변경 후 12개월 내"가
# 패턴의 정의 자체이고 v1.6.1 내용 확인 게이트를 따로 갖고 있어 유지했다.
# founder_fade(18)·reverse_split_spiral(18)은 이미 p90보다 넉넉해 그대로 뒀다.
#
# ⚠ 재보정값은 **in-sample calibration이지 validation이 아니다** — p90은 정의상
# 그 표본의 90%를 담는다. 다른 기간·다른 회사군에서 같은 8%가 나온다는 보장은
# 없다. 값을 좁히는 방향으로 바꾸려면 out-of-sample로 다시 재야 한다.
# 근거: docs/superpowers/specs/2026-08-21-pattern-window-recalibration.md
# 원인(판단): 이 도구가 보는 것은 사건 발생 순서가 아니라 **공시 접수일**이라,
# 정기보고서·감사의견·거래소 제재처럼 공시 유형별 시차가 순서를 흐트러뜨린다.
#
# 따라서 `signal_sequence`의 **순서**는 여전히 서사 설명·표시용 메타다(64%로는
# 근거 부족 — 순서 축은 도입하지 않았다). 순서를 매칭 조건으로 승격하려면
# 먼저 더 큰 표본으로 다시 재야 한다.
# 근거: docs/superpowers/specs/2026-08-21-pattern-sequence-measurement.md

CROSS_SIGNAL_PATTERNS = {
    "founder_fade": {
        "name": "창업주 퇴장",
        "description": "창업주·기존 대주주의 지분이 CB·제3자배정으로 희석되고 경영진이 물러나며 외부 세력이 지배권을 확보하는 흐름",
        "signal_sequence": ["3.2", "3.1", "4.1", "5.3", "8.1"],
        "timeline_months": 18,
        "severity": "CRITICAL",
        "field_evidence": [
            "헬릭스미스: 창업자 지분 10% 이하 → 경영권 상실 (20250902)",
            "SKAI: 강철순 지분·경영권 매각 (20250903)",
        ],
    },
    "debt_spiral": {
        "name": "부채 악순환",
        "description": "전환사채를 새 전환사채로 갚는 차환이 반복되며 부채 부담과 재조달 압박이 커지는 흐름",
        "signal_sequence": ["1.4", "1.5", "1.3", "2.6", "8.2"],
        "timeline_months": 21,
        "severity": "CRITICAL",
        "field_evidence": [
            "위메이드: CB/EB 돌려막기 (20250903)",
            "SKAI: 연속 적자 기록 (20250903)",
        ],
    },
    "reverse_split_spiral": {
        "name": "감자 나선",
        "description": "주식병합·감자로 주가와 재무 요건을 맞춘 직후 희석성 발행이 반복되는 흐름",
        "signal_sequence": ["2.1", "2.2", "6.1", "7.2", "8.3"],
        "timeline_months": 18,
        "severity": "CRITICAL",
        "field_evidence": [
            "셀레스트라: 15대1 감자 (20250806)",
            "셀리버리: 상장폐지 (20250918)",
        ],
    },
    "related_party_hollowing": {
        "name": "특수관계 자산 공동화",
        "description": "특수관계자와의 거래로 자산·영업이 회사 밖으로 이전되며 회사 실체가 비어가는 흐름",
        "signal_sequence": ["4.2", "5.3", "3.2", "2.5", "8.4"],
        "timeline_months": 18,
        "severity": "CRITICAL",
        "field_evidence": [
            "파마리서차: RCPS 비대칭 구조 (20250708)",
            "동성제약: 경영권 방어용 회생신청 (20251014)",
        ],
    },
    "zombie_ma": {
        "name": "무자본 M&A",
        "description": "무자본 M&A 세력이 차명·투자조합으로 경영권 인수 → 사모CB 대량발행·허위자금조달 → 허위 신사업 발표 → 주가부양 후 고가매도",
        "signal_sequence": ["3.1", "2.4", "1.2", "4.3", "7.1", "2.7"],
        "timeline_months": 30,
        "severity": "CRITICAL",
        "field_evidence": [
            "2025-03-10 금감원: 사모CB·BW 허위자금조달 조직적 세력 적발 — 검찰 고발",
            "2026-01-08 금감원: 무자본 M&A 대량보유상황보고 허위기재 적발",
        ],
    },
    "audit_insider_dump": {
        "name": "감사의견 내부자 덤프",
        "description": "감사의견거절·비적정 미공개정보를 임원·최대주주가 직무상 취득 후 공시 전 주식 전량매도",
        "signal_sequence": ["4.4", "7.1", "3.1"],
        "timeline_months": 33,
        "severity": "CRITICAL",
        "field_evidence": [
            "2025-03-24 금감원: A사 대표이사가 감사의견거절 정보를 CB 보유자에게 전달 후 매도",
            "2026-02-27 금감원: 최근 3년 결산 불공정거래 24건 중 79%가 1~3월 발생, 84%가 내부자",
        ],
    },
    "delisting_evasion": {
        "name": "상폐 회피",
        "description": "자본잠식·영업손실로 상장폐지 위기 → 연말 거액 유상증자(가장납입) + 재무제표 과대계상 → 요건 면탈 → 횡령",
        "signal_sequence": ["8.1", "2.4", "6.1", "4.3", "2.7", "8.2"],
        "timeline_months": 27,
        "severity": "CRITICAL",
        "field_evidence": [
            "2024-03-25 금감원: 좀비기업 15개사 부당이득 1,694억원 — 연말 유상증자 상폐요건 면탈 패턴",
            "2026-04-19 금감원: 상폐요건 강화 후 불법행위 급증, 허위 자기자본 확충 적발",
        ],
    },
    "fake_new_biz": {
        "name": "허위 신사업 주가부양",
        "description": "주업과 무관한 테마사업(2차전지·AI·우주항공 등) 허위 발표 + 형식적 MOU·페이퍼컴퍼니 → 테마주 편승 주가급등 → 최대주주 주식 고가매도",
        "signal_sequence": ["5.4", "4.3", "7.2", "7.1"],
        "timeline_months": 30,
        "severity": "CRITICAL",
        "field_evidence": [
            "2024-01-18 금감원: 허위신사업 집중조사 — 20건 중 90%가 코스닥, 50%가 상폐·거래정지",
            "2025-05-21 금감원: B사 해외광물 허위발표 주가 24% 상승 후 수십억 부당이득",
            "2023-10-31 금감원: 신사업 추진실적 전무 129사 중 횡령·감사거절 22%",
        ],
    },
    "capital_churn_anomaly": {
        "name": "자본 이벤트 과다 반복",
        "description": "잦은 자본 변동과 공시 지연·위반이 겹치면 자본 투명성 훼손 우려",
        "signal_sequence": ["2.7", "4.3"],
        "timeline_months": 12,
        "severity": "HIGH",
        "field_evidence": [
            "금감원 2024·2025 주가조작 적발 — 자본 이벤트 반복 + 공시의무 위반 동시 발생 공통",
        ],
    },
    "capital_backflow": {
        "name": "자금 역류",
        "description": (
            "경영권 변경(최대주주변경) 후 12개월 내 피인수회사가 금전대여·"
            "채무보증·담보제공·자산 양수로 인수자 측(계열·특수관계)에 자원을 "
            "이전하는 흐름 — 무자본 M&A에서 인수자금 회수 수단으로 쓰인 사례가 "
            "있는 조합"
        ),
        "signal_sequence": ["3.1", "5.7"],
        "timeline_months": 12,
        "severity": "CRITICAL",
        "field_evidence": [
            "2019-12-19 금감원 무자본 M&A 합동점검: 24사 위법행위 적발 — 조달자금 "
            "중 관계회사 등 대여·선급금 유용 3,799억(29%)",
            "동 점검 사례: 페이퍼컴퍼니에 대여 후 인출 유용, 투자조합 경유 이체로 "
            "회수 가장(투자자산 허위계상)",
        ],
    },
    "fund_diversion_chain": {
        "name": "조달-유용 체인",
        "description": (
            "사모 방식(CB 등)으로 자금을 조달한 뒤 비상장주식 취득·타법인 "
            "출자로 자금이 이동하는 흐름 — 금감원 합동점검에서 조달자금 유용의 "
            "최대 경로(비상장주식 취득 55%)로 집계된 조합. 제3자배정 유상증자 "
            "경로도 자금 이동 구조는 같은 맥락이나 시퀀스에는 포함하지 않았다"
        ),
        "signal_sequence": ["1.1", "5.8"],
        "timeline_months": 21,
        "severity": "HIGH",
        "field_evidence": [
            "2019-12-19 금감원 무자본 M&A 합동점검: 조달자금 74%를 비영업용자산에 "
            "사용 — 비상장주식 취득 7,030억(55%)",
            "동 점검 사례: 비상장주식 고가취득 시 외부평가 과대평가, 타법인주식 "
            "취득 자금조달 공시의 대상회사 정보 미기재·사용목적 부실기재",
        ],
    },
}


# ────────────────────────────────────────────────────────────────
# SEVERITY WEIGHTS FOR RISK SCORING
# ────────────────────────────────────────────────────────────────

SEVERITY_WEIGHTS = {
    "CRITICAL": 1.5,
    "HIGH": 1.0,
    "MEDIUM": 0.7,
    "LOW": 0.4,
}

SEVERITY_LEVELS = {
    "CRITICAL": {"max_months": 9, "equity_loss_pct": 90},
    "HIGH": {"max_months": 15, "equity_loss_pct": 70},
    "MEDIUM": {"max_months": 12, "equity_loss_pct": 40},
    "LOW": {"max_months": 6, "equity_loss_pct": 20},
}


# ────────────────────────────────────────────────────────────────
# HELPER FUNCTIONS
# ────────────────────────────────────────────────────────────────


def get_signal(signal_id: str) -> Optional[Dict]:
    """Retrieve signal configuration by ID."""
    return TAXONOMY.get(signal_id)


def get_category_signals(category: str) -> List[Dict]:
    """Get all signals in a category."""
    return [s for s in TAXONOMY.values() if s["category"] == category]


def calculate_risk_score(
    detected_signals: List[str],
    weights: Optional[Dict[str, float]] = None,
) -> float:
    """
    Calculate composite risk score from detected signals.

    Args:
        detected_signals: List of signal IDs (e.g., ["1.1", "2.1", "8.4"])
        weights: Custom severity weight mapping (default: SEVERITY_WEIGHTS)

    Returns:
        Composite risk score (0-100)
    """
    if not weights:
        weights = SEVERITY_WEIGHTS

    total_score = 0.0
    for signal_id in detected_signals:
        signal = get_signal(signal_id)
        if signal:
            base_score = signal["base_score"]
            severity = signal["severity"]
            weight = weights.get(severity, 1.0)
            total_score += base_score * weight

    # Normalize to 0-100 scale
    # Max theoretical score: 27 signals × 5 base points × 1.5 weight = 202.5
    return min(100.0, (total_score / 202.5) * 100)


def find_pattern_match(
    detected_signals: List[str],
) -> Optional[Dict]:
    """
    Check if detected signals match a known cross-signal pattern.

    Args:
        detected_signals: List of signal IDs

    Returns:
        Matching pattern (if any), else None
    """
    detected_set = set(detected_signals)

    for pattern_key, pattern in CROSS_SIGNAL_PATTERNS.items():
        pattern_set = set(pattern["signal_sequence"])
        # Match if detected signals are a superset or exact match
        if pattern_set.issubset(detected_set):
            return {**pattern, "pattern_id": pattern_key}

    return None


def _tid_sort_key(tid: str) -> tuple:
    """taxonomy ID("5.1" 등)를 숫자 오름차순으로 정렬하는 키.

    `find_pattern_overlaps`는 입력을 set 경유로 받을 수 있어(호출부가
    `list({...})`로 만들어 넘기는 관례), matched/missing을 정렬하지 않으면
    출력 순서가 PYTHONHASHSEED에 따라 실행마다 달라진다(core/catalog.py의
    `_taxonomy_sort_key`와 같은 근거). 숫자가 아닌 값은 뒤로 보낸다.
    """
    parts = tid.split(".")
    try:
        return (0, [int(p) for p in parts])
    except ValueError:
        return (1, [tid])


def _window_end(start: str, months: int) -> str:
    """YYYYMMDD 시작일에 months를 더한 창 종료일(YYYYMMDD, 경계 포함).

    달력 연산만 하며 예외를 던지지 않는다 — 말일 오버플로(1/31 + 1개월)는
    그 달의 마지막 날로 자른다(datetime 없이 순수 정수 연산).
    """
    y, m, d = int(start[:4]), int(start[4:6]), int(start[6:8])
    m += months
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    if m == 2:
        last = 29 if (y % 4 == 0 and (y % 100 != 0 or y % 400 == 0)) else 28
    elif m in (4, 6, 9, 11):
        last = 30
    else:
        last = 31
    return f"{y:04d}{m:02d}{min(d, last):02d}"


def _best_window(
    seq_set: "set[str]",
    taxonomy_dates: "dict[str, list[str]]",
    months: int,
) -> "tuple[set[str], str, str]":
    """패턴 구성 신호 중 `months` 길이의 한 창 안에 함께 관찰된 최대 집합.

    각 관찰 날짜를 창 시작 후보로 삼아 [d, d+months] 안에 들어오는 taxonomy를
    세고, 가장 많이 담기는 창을 고른다. 담기는 개수가 같으면 **늦은 창**을
    택한다 — 이 도구는 관측용이라 같은 겹침이면 최근 것이 사용자에게 더
    유용하고, 후보를 오름차순으로 훑으며 마지막 최대값을 남기므로 결과는
    입력 순서와 무관하게 결정적이다. 날짜가 하나도 없으면 빈 집합을 반환한다.

    Returns:
        (관찰된 taxonomy 집합, 창 시작 YYYYMMDD, 창 종료 YYYYMMDD)
    """
    cands = sorted({
        dt for tid in seq_set for dt in taxonomy_dates.get(tid, []) if dt
    })
    best: "set[str]" = set()
    best_win = ("", "")
    for start in cands:
        end = _window_end(start, months)
        seen: "list[str]" = []
        inside: "set[str]" = set()
        for tid in seq_set:
            hits = [dt for dt in taxonomy_dates.get(tid, []) if dt and start <= dt <= end]
            if hits:
                inside.add(tid)
                seen.extend(hits)
        if len(inside) >= len(best):
            # 표시용 구간은 창의 이론적 경계(start ~ start+months)가 아니라
            # **실제로 관찰된 날짜의 범위**로 돌려준다. 경계를 그대로 쓰면
            # 관찰이 2026.03~08인데 "창 2026.03.17~2028.12.17"처럼 아직 오지도
            # 않은 날짜가 사용자에게 표시된다(2026-08-22 실측 — 진원생명과학
            # audit_insider_dump). 게이트 판정 자체는 경계로 하고, 표기만
            # 사실로 좁힌다.
            best, best_win = inside, (min(seen), max(seen)) if seen else (start, end)
    return best, best_win[0], best_win[1]


def find_pattern_overlaps(
    detected_taxonomies: List[str],
    min_overlap: int = 2,
    taxonomy_dates: "dict[str, list[str]] | None" = None,
) -> List[Dict]:
    """등록된 복합 패턴과 관찰된 taxonomy 집합의 부분 겹침을 조회한다.

    `find_pattern_match`(패턴의 signal_sequence를 **전부** 충족해야 발화)와
    달리, 이 함수는 "구성 신호 중 얼마나 관찰됐는지"를 사실로 반환한다.
    실측(10개사·365일 창)으로는 전부 일치가 회사당 0.2개에 그치는 반면
    부분 일치(≥2)는 회사당 1.3개이면서 대조군(정상 대기업 3사)에서는
    0개였다 — 임계를 낮춰도 아무 데나 붙지 않는다는 근거.

    이 함수 자체는 "이 회사가 이 패턴이다"라고 판정하지 않는다(v0.8.5
    무판정 원칙). 반환값은 관찰/미관찰 사실의 목록이며, 렌더러가 이를
    판정 어휘 없이 사실 문장으로만 표시해야 한다.

    Args:
        detected_taxonomies: 관찰된 taxonomy ID 목록(중복·set 경유 허용)
        min_overlap: 겹침으로 인정할 최소 구성 신호 개수(미만이면 결과 제외)
        taxonomy_dates: {taxonomy id: [관찰 날짜 YYYYMMDD, ...]}. 주면 패턴의
            `timeline_months` 길이 창 안에 함께 관찰된 신호만 matched로 인정한다
            (창 밖 신호는 missing으로 간다). 미전달(None)이면 창 게이트를 적용하지
            않아 기존 호출부와 동작이 동일하다.

    Returns:
        각 항목: pattern_id, name, description, signal_sequence, checkpoints
        (`core.explain.pattern_checkpoints` — 없으면 빈 리스트), matched
        (창 안에서 관찰된 id, 오름차순), missing(matched가 아닌 id, 오름차순),
        outside_window(missing 중 **관찰은 됐지만 창 밖**인 id — 표기를 가르기
        위한 부분집합), n_matched,
        n_total. 정렬은 충족률(n_matched/n_total) 내림차순 → n_matched
        내림차순 → pattern_id 오름차순으로 고정해 입력이 set에서 와도
        출력이 결정적이다. 존재하지 않는 taxonomy ID가 섞여 있어도 그냥
        무시된다(예외 없음).
    """
    # 지연 import — core/taxonomy.py는 CROSS_SIGNAL_PATTERNS 같은 순수
    # 데이터를 다루는 모듈이라 core/explain.py(사용자 표시용 산문 사전)에
    # 대한 모듈 레벨 의존을 최소화한다. explain.py는 taxonomy.py를
    # import하지 않아 순환은 없지만, 함수 내부 import로 두 모듈의 역할
    # 경계(데이터 vs 산문)를 계속 분리해 둔다.
    from .explain import pattern_checkpoints as _pattern_checkpoints

    detected_set = set(detected_taxonomies)
    results: List[Dict] = []

    for pattern_id, pattern in CROSS_SIGNAL_PATTERNS.items():
        seq = pattern["signal_sequence"]
        seq_set = set(seq)
        matched_set = seq_set & detected_set
        if len(matched_set) < min_overlap:
            continue

        # 관찰 윈도우 게이트 — 날짜를 받았을 때만 적용한다(미전달 시 기존
        # 동작 그대로). 패턴의 timeline_months는 원래 카드 문구로만 쓰이고
        # 매칭에는 관여하지 않아, 5년 스캔에서 2~3년 떨어진 신호가 한 패턴으로
        # 묶이면서 "관찰 윈도우 12개월"이라는 거짓 표기가 나왔다.
        window_start = window_end = ""
        if taxonomy_dates is not None:
            months = pattern.get("timeline_months") or 0
            if months > 0:
                matched_set, window_start, window_end = _best_window(
                    matched_set, taxonomy_dates, months
                )
                if len(matched_set) < min_overlap:
                    continue

        missing_set = seq_set - matched_set
        # 창 게이트가 밀어낸 것과 아예 관찰되지 않은 것은 **다른 사실**이다.
        # 둘을 한 덩어리로 「안 보임」이라 적으면, 리포트 위쪽 「관찰된 신호」에
        # 실려 있는 바로 그 신호를 아래 카드가 "안 보인다"고 말하게 된다
        # (2026-08-24 실측: 7개사×5년에서 KR모터스 fake_new_biz의 4.3 — 2022-03-22
        # 관찰인데 창 밖이라 밀렸다). 드물지만 한 화면이 서로 반대되는 말을 한다.
        outside_set = missing_set & detected_set
        results.append({
            "pattern_id": pattern_id,
            "name": pattern["name"],
            "description": pattern["description"],
            "signal_sequence": list(seq),
            "checkpoints": _pattern_checkpoints(pattern_id),
            "matched": sorted(matched_set, key=_tid_sort_key),
            "missing": sorted(missing_set, key=_tid_sort_key),
            # `missing`의 부분집합 — 하위 호환을 위해 missing은 그대로 두고
            # 표기에서만 가른다(옛 소비자는 이 키를 몰라도 동작이 변하지 않는다).
            "outside_window": sorted(outside_set, key=_tid_sort_key),
            "n_matched": len(matched_set),
            "n_total": len(seq_set),
            "timeline_months": pattern.get("timeline_months"),
            "window_start": window_start,
            "window_end": window_end,
        })

    results.sort(
        key=lambda r: (
            -(r["n_matched"] / r["n_total"]),
            -r["n_matched"],
            r["pattern_id"],
        )
    )
    return results


def estimate_crisis_timeline(signal_id: str) -> Dict[str, int]:
    """
    Estimate time to crisis based on signal severity.

    Returns:
        {"months_to_impact": int, "equity_loss_pct": int}
    """
    signal = get_signal(signal_id)
    if not signal:
        return {"months_to_impact": 999, "equity_loss_pct": 0}

    severity = signal["severity"]
    # OBSERVATION 등 SEVERITY_LEVELS 밖 severity는 위기 통계가 정의되지
    # 않은 참고 강도 — MEDIUM으로 폴백하면 근거 없는 "위기 도달 N개월"
    # 문장이 렌더되므로 미상 센티널을 반환한다(렌더 게이트 months<999).
    severity_data = SEVERITY_LEVELS.get(severity)
    if severity_data is None:
        return {"months_to_impact": 999, "equity_loss_pct": 0}

    return {
        "months_to_impact": severity_data["max_months"],
        "equity_loss_pct": severity_data["equity_loss_pct"],
    }


# ────────────────────────────────────────────────────────────────
# INTEGRATION WITH DART-MONITOR
# ────────────────────────────────────────────────────────────────
# This module extends manipulation_monitor.py by:
# 1. Providing keyword patterns for all 27 signals (vs. current 8)
# 2. Enabling cross-signal pattern detection (e.g., "Founder Fade")
# 3. Calculating severity-weighted risk scores
# 4. Estimating crisis timelines
#
# Usage in enhanced manipulation_monitor.py:
#   from signal_taxonomy_mapping import TAXONOMY, calculate_risk_score, find_pattern_match
#
#   # Match signal by keywords
#   for signal_id, signal_cfg in TAXONOMY.items():
#       for keyword in signal_cfg["keywords"]:
#           if keyword in report_nm:
#               matched_signals.append(signal_id)
#
#   # Detect cross-signal patterns
#   pattern = find_pattern_match(matched_signals)
#   if pattern and pattern["severity"] == "CRITICAL":
#       alert_urgent(company, pattern)
