"""주가조작 의심 신호 분류

37가지 신호 유형 정의 + 공시 제목 매칭 + 정정공시 판별.
taxonomy.py의 신호 분류 체계에 기반.
"""

import re

# 정정공시 판별 패턴
# [기재정정], [첨부추가], [정정] 등의 접두사가 붙으면 기존 공시의 수정이며 새 공시가 아님
_AMENDMENT_RE = re.compile(r"^\[(?:기재정정|첨부추가|정정)[^\]]*\]\s*")

# signal key → taxonomy 신호 ID 매핑
SIGNAL_KEY_TO_TAXONOMY: dict[str, list[str]] = {
    # Category 1: CB/채권 조작
    "CB_BW":       ["1.1", "1.5", "1.6"],
    "CB_REPAY":    ["1.2"],
    "EB":          ["1.3"],
    "RCPS":        ["1.4"],
    "CB_ROLLOVER": ["1.5"],
    "CB_BUYBACK":  ["1.6"],
    "TREASURY_EB": ["1.7"],
    # Category 2: 자본구조 조작
    "REVERSE_SPLIT": ["2.1"],
    "CAPITAL_RED":   ["2.2"],
    "GAMJA_MERGE":   ["2.3"],
    "3PCA":          ["2.4"],
    "RIGHTS_UNDER":  ["2.5"],
    "TREASURY":      ["2.6"],
    # Category 3: 경영권/지배구조
    "SHAREHOLDER":   ["3.1", "3.2"],
    "ACTIVIST":      ["3.3"],
    "EXEC":          ["3.3", "3.4"],
    "MGMT_DISPUTE":  ["3.4"],
    "CIRCULAR":      ["3.5"],
    # Category 4: 거버넌스/공시
    "MEETING_VIOL":  ["4.1"],
    "RELATED_PARTY": ["4.2"],
    "DISCLOSURE_VIOL": ["4.3"],
    "AUDIT":         ["4.4", "8.4"],
    # Category 5: 기업 활동 조작
    "EQUITY_SPLIT":  ["5.1"],
    "BUYBACK_NEG":   ["5.2"],
    "ASSET_TRANSFER": ["5.3"],
    "DISTRESS_MA":   ["5.4"],
    "DEMERGER":      ["5.5"],
    # Category 6: 회계/재무
    "REVENUE_IRREG": ["6.1"],
    "CONTINGENT":    ["6.2"],
    # Category 7: 시장 조작
    "INQUIRY":       ["4.3", "7.1"],
    "THEME_STOCK":   ["7.2"],
    # Category 8: 위기/부실
    "EMBEZZLE":      ["5.3", "8.1"],
    "INSOLVENCY":    ["8.1"],
    "DEBT_RESTR":    ["8.2"],
    "ASSET_SPIRAL":  ["8.3"],
    "GOING_CONCERN": ["8.4"],
    # v0.5.0: 자금흐름·주요결정
    "FUND_DIVERSION":         ["5.3", "8.1"],
    "FUND_UNREPORTED":        ["4.3"],
    "DECISION_RELATED_PARTY": ["4.2"],
    "DECISION_OVERSIZED":     ["5.3"],
    "DECISION_NO_EXTVAL":     ["4.3"],
    # 기존 호환 키
    "MGMT":          ["3.4", "5.4"],
}

SIGNAL_TYPES = [
    # ── Category 1: CB/채권 조작 ──────────────────────────────
    {
        "key":   "CB_BW",
        "label": "CB/BW발행",
        "score": 3,
        "keywords": [
            "전환사채권발행결정",
            "신주인수권부사채권발행결정",
            "전환사채",
            "신주인수권부사채",
            "전환가액의조정",
            "리픽싱",
            "전환가액조정",
            "전환가액인하",
            "콜옵션",
            "사모전환사채",
        ],
    },
    {
        "key":   "CB_REPAY",
        "label": "CB조기상환",
        "score": 4,
        "keywords": [
            "전환사채상환",
            "CB상환",
            "사채상환",
            "배당금상환",
            "자회사배당",
            "내부배당",
            "배당을통한상환",
        ],
    },
    {
        "key":   "EB",
        "label": "교환사채(EB)발행",
        "score": 4,
        "keywords": [
            "교환사채권발행결정",
            "교환사채",
            "교환채발행",
            "EB발행",
            "제3자배정교환채",
            "EB배임",
        ],
    },
    {
        "key":   "RCPS",
        "label": "상환전환우선주(RCPS)",
        "score": 4,
        "keywords": [
            "상환전환우선주",
            "RCPS",
            "전환우선주",
            "우선주발행",
        ],
    },
    {
        "key":   "CB_ROLLOVER",
        "label": "CB돌려막기",
        "score": 4,
        "keywords": [
            "돌려막기",
            "CB돌려막기",
            "EB돌려막기",
            "리파이낸싱",
            "차환",
            "연속CB발행",
            "연속차입",
        ],
    },
    {
        "key":   "CB_BUYBACK",
        "label": "자사채매입",
        "score": 3,
        "keywords": [
            "자사채매입",
            "사채매입",
            "저가상환",
            "조기상환",
        ],
    },
    {
        "key":   "TREASURY_EB",
        "label": "자사주EB",
        "score": 3,
        "keywords": [
            "자사주EB",
            "자사주연동",
            "자기주식EB",
            "자기주식연동",
        ],
    },
    # ── Category 2: 자본구조 조작 ─────────────────────────────
    {
        "key":   "REVERSE_SPLIT",
        "label": "무상감자/주식병합",
        "score": 3,
        "keywords": [
            "무상감자",
            "감자결정",
            "주식병합",
            "자본감소",
            "감자공시",
        ],
    },
    {
        "key":   "CAPITAL_RED",
        "label": "유상감자/손실보전감자",
        "score": 3,
        "keywords": [
            "유상감자",
            "손실보전감자",
            "이익배당으로서감자",
        ],
    },
    {
        "key":   "GAMJA_MERGE",
        "label": "감자병합",
        "score": 5,
        "keywords": [
            "감자병합",
            "감자및병합",
            "감자와병합",
        ],
    },
    {
        "key":   "3PCA",
        "label": "제3자배정유상증자",
        "score": 4,
        "keywords": [
            "제3자배정",
            "유상증자결정",
            "유상증자",
            "가장납입",
            "상폐요건면탈",
        ],
    },
    {
        "key":   "RIGHTS_UNDER",
        "label": "공모미달",
        "score": 2,
        "keywords": [
            "유상증자미달",
            "공모미달",
            "청약미달",
        ],
    },
    {
        "key":   "TREASURY",
        "label": "자사주매입/처분",
        "score": 3,
        "keywords": [
            "자기주식취득",
            "자기주식처분",
            "자사주매입",
            "자사주처분",
        ],
    },
    # ── Category 3: 경영권/지배구조 ───────────────────────────
    {
        "key":   "SHAREHOLDER",
        "label": "최대주주변경",
        "score": 3,
        "keywords": [
            "최대주주변경",
            "최대주주 변경",
            "대주주변경",
            "지분매각",
            "경영권이양",
            "무자본M&A",
            "대량보유상황보고",
        ],
    },
    {
        "key":   "EXEC",
        "label": "임원변경",
        "score": 2,
        "keywords": [
            "임원의변동",
            "대표이사변경",
            "대표이사 변경",
            "경영진교체",
            "이사진교체",
        ],
    },
    {
        "key":   "MGMT_DISPUTE",
        "label": "경영권분쟁",
        "score": 3,
        "keywords": [
            "경영권분쟁",
            "경영권 분쟁",
            "경영권다툼",
            "경영진분쟁",
        ],
    },
    {
        "key":   "CIRCULAR",
        "label": "순환출자",
        "score": 3,
        "keywords": [
            "순환출자",
            "순환구조",
            "지분연쇄",
        ],
    },
    {
        "key":   "ACTIVIST",
        "label": "주주행동주의",
        "score": 2,
        "keywords": [
            "활동주의펀드",
            "주주행동주의",
            "주주제안",
        ],
    },
    # ── Category 4: 거버넌스/공시 ─────────────────────────────
    {
        "key":   "MEETING_VIOL",
        "label": "주총절차위반",
        "score": 3,
        "keywords": [
            "주총위반",
            "소집절차위반",
            "의결정족수미달",
        ],
    },
    {
        "key":   "DISCLOSURE_VIOL",
        "label": "공시의무위반",
        "score": 3,
        "keywords": [
            "공시의무위반",
            "공시누락",
            "중요정보누락",
            "발행철회",
            "공시철회",
        ],
    },
    {
        "key":   "RELATED_PARTY",
        "label": "특수관계자거래",
        "score": 3,
        "keywords": [
            "특수관계자거래",
            "관련자거래",
            "관계회사거래",
            "비정상거래",
        ],
    },
    {
        "key":   "AUDIT",
        "label": "감사의견",
        "score": 4,
        "keywords": [
            "한정의견",
            "부적정의견",
            "의견거절",
            "계속기업불확실성",
            "감사범위제한",
            "감사인교체",
        ],
    },
    # ── Category 5: 기업 활동 조작 ────────────────────────────
    {
        "key":   "EQUITY_SPLIT",
        "label": "주식분할/액면분할",
        "score": 2,
        "keywords": [
            "주식분할결정",
            "액면분할결정",
            "주식배당결정",
        ],
    },
    {
        "key":   "BUYBACK_NEG",
        "label": "재무위기중자사주매입",
        "score": 2,
        "keywords": [
            "부도직전매입",
            "자금난속매입",
        ],
    },
    {
        "key":   "DISTRESS_MA",
        "label": "위기중인수합병",
        "score": 2,
        "keywords": [
            "위기속인수",
            "부실기업인수",
            "자금난속합병",
        ],
    },
    {
        "key":   "ASSET_TRANSFER",
        "label": "자산매각/유출",
        "score": 4,
        "keywords": [
            "자산매각",
            "사옥매각",
            "자회사매각",
            "사업양도",
            "저가매각",
        ],
    },
    {
        "key":   "DEMERGER",
        "label": "회사분할",
        "score": 4,
        "keywords": [
            "분할결정",
            "사업분할",
            "분할합병",
        ],
    },
    {
        "key":   "MGMT",
        "label": "경영권변동",
        "score": 3,
        "keywords": [
            "경영권변동",
            "경영권 변동",
            "주식양수도",
            "공개매수",
            "합병결정",
            "인수합병",
        ],
    },
    # ── Category 6: 회계/재무 ─────────────────────────────────
    {
        "key":   "REVENUE_IRREG",
        "label": "수익인식이상",
        "score": 3,
        "keywords": [
            "수익인식",
            "매출인식",
            "수익조정",
            "분식회계",
            "선수금",
            "미수금급증",
            "매출과대계상",
        ],
    },
    {
        "key":   "CONTINGENT",
        "label": "우발채무",
        "score": 3,
        "keywords": [
            "우발채무",
            "우발성채무",
            "보증채무",
        ],
    },
    # ── Category 7: 시장 조작 ─────────────────────────────────
    {
        "key":   "THEME_STOCK",
        "label": "테마주/작전주",
        "score": 2,
        "keywords": [
            "테마주",
            "작전주",
            "테마편승",
            "정치테마주",
            "핀플루언서",
        ],
    },
    {
        "key":   "INQUIRY",
        "label": "조회공시",
        "score": 3,
        "keywords": [
            "조회공시",
            "풍문또는보도",
            "주가이상",
            "거래정지",
            "매매정지",
            "이상거래",
            "조회공시요구",
            "거래량급증",
        ],
    },
    {
        "key":   "EMBEZZLE",
        "label": "횡령배임",
        "score": 5,
        "keywords": [
            "횡령",
            "배임",
            "불공정거래",
            "주가조작",
            "시세조종",
            "미공개정보이용",
            "미공개중요정보",
            "선행매매",
            "차명",
        ],
    },
    # ── Category 8: 위기/부실 ─────────────────────────────────
    {
        "key":   "INSOLVENCY",
        "label": "자본잠식/부도",
        "score": 5,
        "keywords": [
            "자본잠식",
            "부도",
            "어음부도",
            "의도적부도",
        ],
    },
    {
        "key":   "DEBT_RESTR",
        "label": "채무조정/구조조정",
        "score": 4,
        "keywords": [
            "구조조정",
            "채무조정",
            "채무면제",
            "워크아웃",
        ],
    },
    {
        "key":   "ASSET_SPIRAL",
        "label": "자산연쇄처분",
        "score": 3,
        "keywords": [
            "연쇄매각",
            "긴급자산처분",
        ],
    },
    {
        "key":   "GOING_CONCERN",
        "label": "계속기업불확실",
        "score": 5,
        "keywords": [
            "계속기업가정불확실",
            "계속기업불확실",
            "회생절차",
            "파산절차",
        ],
    },
    # ── v0.5.0: 자금흐름·주요결정 (프로그램적 부착) ─────────────
    {
        "key":   "FUND_DIVERSION",
        "label": "조달자금 목적외 사용",
        "score": 4,
        "keywords": [],
    },
    {
        "key":   "FUND_UNREPORTED",
        "label": "자금사용내역 미기재",
        "score": 3,
        "keywords": [],
    },
    {
        "key":   "DECISION_RELATED_PARTY",
        "label": "특수관계인 대상 결정",
        "score": 4,
        "keywords": [],
    },
    {
        "key":   "DECISION_OVERSIZED",
        "label": "자산대비 대형 결정",
        "score": 3,
        "keywords": [],
    },
    {
        "key":   "DECISION_NO_EXTVAL",
        "label": "외부평가 미실시 결정",
        "score": 3,
        "keywords": [],
    },
]


def match_signals(report_nm: str) -> list[dict]:
    """공시 제목에서 의심 신호 유형 매칭. 복수 유형 매칭 가능.

    정정공시([기재정정] 등)는 새 공시가 아니므로 빈 리스트를 반환한다.
    """
    if is_amendment_disclosure(report_nm):
        return []
    matched = []
    for sig in SIGNAL_TYPES:
        for kw in sig["keywords"]:
            if kw in report_nm:
                matched.append(sig)
                break
    return matched


def is_amendment_disclosure(report_nm: str) -> bool:
    """공시 제목이 정정공시(기존 공시의 수정·보완)인지 판별."""
    return bool(_AMENDMENT_RE.match(report_nm))
