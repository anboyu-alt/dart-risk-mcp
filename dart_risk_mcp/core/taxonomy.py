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
        "name": "Disclosure Loophole Exploitation",
        "description": "Purposeful use of DART filing loopholes; material information omitted",
        "base_score": 2,
        "severity": "MEDIUM",
        "crisis_timeline_months": 9,
        "keywords": [
            "공시누락",
            "중요정보누락",
            "공시지연",
            "분할공시",
            "공시의무위반",
        ],
        "red_flags": [
            "Material event not disclosed within 4 hours",
            "Information split across multiple filings",
            "Negative information buried in attachments",
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
}


# ────────────────────────────────────────────────────────────────
# CROSS-SIGNAL PATTERN SEQUENCES
# ────────────────────────────────────────────────────────────────

CROSS_SIGNAL_PATTERNS = {
    "founder_fade": {
        "name": "The Founder Fade",
        "description": "Sequential founder ownership dilution → control loss → exit",
        "signal_sequence": ["3.2", "3.1", "4.1", "5.3", "8.1"],
        "timeline_months": 18,
        "severity": "CRITICAL",
        "field_evidence": [
            "헬릭스미스: 창업자 지분 10% 이하 → 경영권 상실 (20250902)",
            "SKAI: 강철순 지분·경영권 매각 (20250903)",
        ],
    },
    "debt_spiral": {
        "name": "The Debt Spiral",
        "description": "CB issuance → rollover cycle → refinancing crises → insolvency",
        "signal_sequence": ["1.4", "1.5", "1.3", "2.6", "8.2"],
        "timeline_months": 12,
        "severity": "CRITICAL",
        "field_evidence": [
            "위메이드: CB/EB 돌려막기 (20250903)",
            "SKAI: 연속 적자 기록 (20250903)",
        ],
    },
    "reverse_split_spiral": {
        "name": "The Reverse Split Spiral",
        "description": "Reverse split → capital reduction → distressed asset sales → delisting",
        "signal_sequence": ["2.1", "2.2", "6.1", "7.2", "8.3"],
        "timeline_months": 18,
        "severity": "CRITICAL",
        "field_evidence": [
            "셀레스트라: 15대1 감자 (20250806)",
            "셀리버리: 상장폐지 (20250918)",
        ],
    },
    "related_party_hollowing": {
        "name": "The Related-Party Hollowing",
        "description": "Related-party transactions → asset siphoning → insolvency → bankruptcy",
        "signal_sequence": ["4.2", "5.3", "3.2", "2.5", "8.4"],
        "timeline_months": 15,
        "severity": "CRITICAL",
        "field_evidence": [
            "파마리서차: RCPS 비대칭 구조 (20250708)",
            "동성제약: 경영권 방어용 회생신청 (20251014)",
        ],
    },
    "zombie_ma": {
        "name": "The Zombie M&A",
        "description": "무자본 M&A 세력이 차명·투자조합으로 경영권 인수 → 사모CB 대량발행·허위자금조달 → 허위 신사업 발표 → 주가부양 후 고가매도",
        "signal_sequence": ["3.1", "2.4", "1.2", "4.3", "7.1"],
        "timeline_months": 12,
        "severity": "CRITICAL",
        "field_evidence": [
            "2025-03-10 금감원: 사모CB·BW 허위자금조달 조직적 세력 적발 — 검찰 고발",
            "2026-01-08 금감원: 무자본 M&A 대량보유상황보고 허위기재 적발",
        ],
    },
    "audit_insider_dump": {
        "name": "The Audit Insider Dump",
        "description": "감사의견거절·비적정 미공개정보를 임원·최대주주가 직무상 취득 후 공시 전 주식 전량매도",
        "signal_sequence": ["4.4", "7.1", "3.1"],
        "timeline_months": 6,
        "severity": "CRITICAL",
        "field_evidence": [
            "2025-03-24 금감원: A사 대표이사가 감사의견거절 정보를 CB 보유자에게 전달 후 매도",
            "2026-02-27 금감원: 최근 3년 결산 불공정거래 24건 중 79%가 1~3월 발생, 84%가 내부자",
        ],
    },
    "delisting_evasion": {
        "name": "The Delisting Evasion",
        "description": "자본잠식·영업손실로 상장폐지 위기 → 연말 거액 유상증자(가장납입) + 재무제표 과대계상 → 요건 면탈 → 횡령",
        "signal_sequence": ["8.1", "2.4", "6.1", "4.3"],
        "timeline_months": 9,
        "severity": "CRITICAL",
        "field_evidence": [
            "2024-03-25 금감원: 좀비기업 15개사 부당이득 1,694억원 — 연말 유상증자 상폐요건 면탈 패턴",
            "2026-04-19 금감원: 상폐요건 강화 후 불법행위 급증, 허위 자기자본 확충 적발",
        ],
    },
    "fake_new_biz": {
        "name": "The Fake New Business Pump",
        "description": "주업과 무관한 테마사업(2차전지·AI·우주항공 등) 허위 발표 + 형식적 MOU·페이퍼컴퍼니 → 테마주 편승 주가급등 → 최대주주 주식 고가매도",
        "signal_sequence": ["5.4", "4.3", "7.2", "7.1"],
        "timeline_months": 6,
        "severity": "CRITICAL",
        "field_evidence": [
            "2024-01-18 금감원: 허위신사업 집중조사 — 20건 중 90%가 코스닥, 50%가 상폐·거래정지",
            "2025-05-21 금감원: B사 해외광물 허위발표 주가 24% 상승 후 수십억 부당이득",
            "2023-10-31 금감원: 신사업 추진실적 전무 129사 중 횡령·감사거절 22%",
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
    severity_data = SEVERITY_LEVELS.get(severity, SEVERITY_LEVELS["MEDIUM"])

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
