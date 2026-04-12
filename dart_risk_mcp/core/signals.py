"""주가조작 의심 신호 분류

8가지 신호 유형 정의 + 공시 제목 매칭 + 정정공시 판별.
dart-monitor/manipulation_monitor.py에서 추출.
"""

import re

# 정정공시 판별 패턴
# [기재정정], [첨부추가], [정정] 등의 접두사가 붙으면 기존 공시의 수정이며 새 공시가 아님
_AMENDMENT_RE = re.compile(r"^\[(?:기재정정|첨부추가|정정)[^\]]*\]\s*")

# manipulation_monitor → taxonomy 신호 ID 매핑
SIGNAL_KEY_TO_TAXONOMY: dict[str, list[str]] = {
    "CB_BW":       ["1.1", "1.5", "1.6"],
    "3PCA":        ["2.4"],
    "SHAREHOLDER": ["3.1", "3.2"],
    "EXEC":        ["3.3", "3.4"],
    "EMBEZZLE":    ["5.3", "8.1"],
    "AUDIT":       ["4.4", "8.4"],
    "INQUIRY":     ["4.3", "7.1"],
    "MGMT":        ["3.4", "5.4"],
}

SIGNAL_TYPES = [
    {
        "key":      "CB_BW",
        "label":    "CB/BW발행",
        "score":    3,
        "keywords": [
            "전환사채권발행결정",
            "신주인수권부사채권발행결정",
            "교환사채권발행결정",
            "전환사채",
            "신주인수권부사채",
            "전환가액의조정",
            "리픽싱",
        ],
    },
    {
        "key":      "3PCA",
        "label":    "제3자배정유상증자",
        "score":    4,
        "keywords": [
            "제3자배정",
            "유상증자결정",
        ],
    },
    {
        "key":      "SHAREHOLDER",
        "label":    "최대주주변경",
        "score":    3,
        "keywords": [
            "최대주주변경",
            "최대주주 변경",
            "대주주변경",
        ],
    },
    {
        "key":      "EXEC",
        "label":    "임원변경",
        "score":    2,
        "keywords": [
            "임원의변동",
            "대표이사변경",
            "대표이사 변경",
        ],
    },
    {
        "key":      "EMBEZZLE",
        "label":    "횡령배임",
        "score":    5,
        "keywords": [
            "횡령",
            "배임",
            "불공정거래",
            "주가조작",
            "시세조종",
        ],
    },
    {
        "key":      "AUDIT",
        "label":    "감사의견",
        "score":    4,
        "keywords": [
            "한정의견",
            "부적정의견",
            "의견거절",
            "계속기업불확실성",
            "감사범위제한",
        ],
    },
    {
        "key":      "INQUIRY",
        "label":    "조회공시",
        "score":    3,
        "keywords": [
            "조회공시",
            "풍문또는보도",
            "주가이상",
            "거래정지",
            "매매정지",
        ],
    },
    {
        "key":      "MGMT",
        "label":    "경영권변동",
        "score":    3,
        "keywords": [
            "경영권변동",
            "경영권 변동",
            "주식양수도",
            "공개매수",
            "합병결정",
            "분할결정",
        ],
    },
]


def match_signals(report_nm: str) -> list[dict]:
    """공시 제목에서 의심 신호 유형 매칭. 복수 유형 매칭 가능."""
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
