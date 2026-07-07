"""재무제표 주석 카테고리 분류 — 섹션 제목 키워드 매칭.

공시 원문 섹션 제목에서 위험 판단에 자주 쓰이는 주석 카테고리
(계속기업·특수관계자·우발부채 등)를 태깅한다. 판정·점수 없이
"이 섹션이 이 주제의 주석으로 보인다"는 사실 라벨만 부여한다.

키워드 사전은 capitalparser/kreports-dart-mcp 의 note_parser.py NOTE_KEYWORDS 를
Apache License 2.0 조건에 따라 이식·수정. (https://github.com/capitalparser/kreports-dart-mcp)
수정 사항: 섹션 '제목' 태깅 용도에 맞춰 지나치게 범용적인 단독 키워드
("수익", "매출", "유동성", "손상", "담보" 등)는 제외하거나 복합어로 좁혔다 —
본문 전체가 아닌 제목에 대고 매칭하므로 넓은 키워드는 오탐이 커진다.
"""

__all__ = [
    "NOTE_CATEGORIES",
    "classify_note_title",
    "summarize_note_sections",
    "build_note_summary",
]

# key: (한글 라벨, 제목 매칭 키워드) — 키워드는 '포함' 매칭, 대소문자 무시(영문)
NOTE_CATEGORIES: dict[str, tuple[str, tuple[str, ...]]] = {
    "going_concern": (
        "계속기업",
        ("계속기업", "자본잠식", "중요한 불확실성", "중요한불확실성"),
    ),
    "related_parties": (
        "특수관계자",
        ("특수관계자", "관계자거래", "특수관계인"),
    ),
    "commitments_contingencies": (
        "우발부채·약정",
        ("우발부채", "우발자산", "약정사항", "지급보증", "소송사건", "소송 사건"),
    ),
    "subsidiaries_associates": (
        "종속·관계기업",
        ("종속기업", "관계기업", "공동기업", "연결대상"),
    ),
    "financial_instruments": (
        "금융상품",
        ("금융상품", "금융자산", "금융부채", "기대신용손실", "대손충당금",
         "신용위험", "유동성위험", "공정가치"),
    ),
    "revenue_recognition": (
        "수익인식",
        ("수익인식", "수익 인식", "고객과의 계약", "수행의무", "거래가격"),
    ),
    "lease": (
        "리스",
        ("리스", "사용권자산", "리스부채"),
    ),
    "provisions": (
        "충당부채",
        ("충당부채", "복구충당", "제품보증충당", "손실충당"),
    ),
    "impairment": (
        "자산손상",
        ("손상차손", "회수가능액", "현금창출단위"),
    ),
    "subsequent_events": (
        "보고기간후 사건",
        ("보고기간후", "보고기간 후", "후속사건", "후속 사건"),
    ),
}

# 위험 확인 우선순위가 높은 카테고리 — 요약 블록에서 먼저 표기
_PRIORITY_ORDER = (
    "going_concern",
    "related_parties",
    "commitments_contingencies",
    "subsidiaries_associates",
    "financial_instruments",
    "revenue_recognition",
    "impairment",
    "provisions",
    "lease",
    "subsequent_events",
)


def classify_note_title(title: str) -> list[str]:
    """섹션 제목 → 매칭되는 주석 카테고리 key 목록 (우선순위순, 최대 2개).

    제목이 비었거나 매칭이 없으면 [].
    """
    if not title:
        return []
    t = title.strip().lower()
    # 80자 초과는 제목이 아니라 본문 덩어리가 헤딩으로 잘못 잡힌 것 — 오탐 방지
    if len(t) > 80:
        return []
    hits = []
    for key in _PRIORITY_ORDER:
        _label, keywords = NOTE_CATEGORIES[key]
        if any(kw.lower() in t for kw in keywords):
            hits.append(key)
        if len(hits) >= 2:
            break
    return hits


def summarize_note_sections(file_list: list[dict]) -> list[tuple[str, list[str]]]:
    """파일별 섹션 목록에서 카테고리 → 섹션 id 목록 요약을 만든다.

    Args:
        file_list: list_document_sections 반환 구조
            [{"sections": [{"id": ..., "title": ...}, ...], ...}, ...]

    Returns:
        [(카테고리 한글 라벨, [섹션 id ...]), ...] — 우선순위순, 매칭 없으면 [].
    """
    by_key: dict[str, list[str]] = {}
    for f in file_list or []:
        for sec in f.get("sections", []):
            for key in classify_note_title(sec.get("title", "")):
                by_key.setdefault(key, []).append(sec.get("id", "?"))
    return [
        (NOTE_CATEGORIES[key][0], by_key[key])
        for key in _PRIORITY_ORDER
        if key in by_key
    ]


def build_note_summary(
    file_list: list[dict],
    title_hits: list[dict],
    max_per_category: int = 4,
) -> list[tuple[str, list[str]]]:
    """섹션 태그 + TITLE 스캔 결과를 합쳐 카테고리별 근거 목록을 만든다.

    Args:
        file_list: list_document_sections 반환 구조 (섹션 id 근거)
        title_hits: scan_note_titles 반환 구조 (파일 내 제목 근거)

    Returns:
        [(라벨, ["f0s2", "파일1 '32.우발부채와 약정사항' (약 62% 지점)", ...]), ...]
    """
    by_key: dict[str, list[str]] = {}
    for f in file_list or []:
        for sec in f.get("sections", []):
            for key in classify_note_title(sec.get("title", "")):
                by_key.setdefault(key, []).append(sec.get("id", "?"))
    for hit in title_hits or []:
        desc = (
            f"파일{hit.get('file_index', '?')} '{hit.get('title', '')}'"
            f" (약 {hit.get('position_pct', 0)}% 지점)"
        )
        for key in hit.get("categories", []):
            entries = by_key.setdefault(key, [])
            if desc not in entries:
                entries.append(desc)
    return [
        (NOTE_CATEGORIES[key][0], by_key[key][:max_per_category])
        for key in _PRIORITY_ORDER
        if key in by_key
    ]
