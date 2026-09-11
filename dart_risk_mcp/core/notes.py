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

import re

__all__ = [
    "NOTE_CATEGORIES",
    "classify_note_title",
    "summarize_note_sections",
    "build_note_summary",
    "outline_note_tables",
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

    ⚠ **현재 프로덕션 소비처 0** (2026-08-30 AST 전수 확인). 공개 API로 남겨
    두지만 새 코드가 이것에 기대기 전에 `tests/test_unused_exports.py`의
    근거를 먼저 읽을 것 — 지우지 않는 이유는 PyPI 배포 패키지라
    외부 import를 깰 수 있기 때문이지, 검증된 경로여서가 아니다.

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


# ── 주석 표 뼈대 (v1.25.0) ────────────────────────────────────────────
#
# 주석 목차에 「표 N개 · 각 표의 제목과 열 이름」을 덧붙여, 어느 주석을 열지
# 고르는 데 쓴다. **금액은 넣지 않는다** — 이미 받아 둔 원문을 다시 파싱하는
# 순수 함수라 추가 API 호출이 없다.
#
# ⚠ **2열 블록은 데이터 표가 아니다.** 실측(올품 주석 1·13·19)에서 마크다운
#   표로 잡히는 것의 절반 이상이 단위 표기(`| | (단위: 천원) |`)·소제목
#   (`| - 당기 | (단위: 천원) |`)·각주(`| (*1) | 설명… |`)다. 주석 19는 「표」가
#   14개 잡히지만 데이터 표는 6개뿐이다. 데이터 표는 **열 3개 이상**이다.
_NOTE_MIN_COLUMNS = 3
_NOTE_UNIT_RE = re.compile(r"\(\s*단위\s*[:：][^)]*\)")


def _note_is_separator(line: str) -> bool:
    """마크다운 표의 구분선(`|---|---|`)인가."""
    s = line.strip()
    if not (s.startswith("|") and s.endswith("|")):
        return False
    body = s[1:-1].replace("|", "").replace("-", "").replace(":", "").strip()
    return body == "" and "-" in s


def _note_cells(line: str) -> list[str] | None:
    s = line.strip()
    if len(s) < 2 or not (s.startswith("|") and s.endswith("|")):
        return None
    return [c.strip() for c in s[1:-1].split("|")]


def outline_note_tables(
    text: str,
    max_tables: int = 8,
    max_columns: int = 12,
) -> list[dict]:
    """주석별 표 뼈대 — 표 제목·열 이름·행 수·단위 표기. **금액은 없다.**

    Returns:
        `[{note_no, title, structured, reason, tables_total, tables_omitted,
           tables: [{caption, columns, columns_total, rows_n,
                     unit_as_reported}]}]`

    **행 이름은 담지 않는다** — 목차가 길어지면 목차의 의미가 없다. 표를
    구조화하지 못하면 `structured=False`와 이유를 담고 **추측해 만들지 않는다**.
    """
    from .audit_report import find_note_headings

    if not text:
        return []
    out: list[dict] = []
    for note in find_note_headings(text):
        body = text[note["offset"]:note["end"]]
        lines = body.split("\n")
        tables: list[dict] = []
        skipped_narrow = 0
        pending_unit, pending_caption = "", ""
        i = 0
        while i < len(lines):
            cells = _note_cells(lines[i])
            if cells is None:
                t = lines[i].strip()
                if t:
                    pending_caption = t
                i += 1
                continue
            # 표 머리 + 구분선이어야 데이터 표다
            if i + 1 < len(lines) and _note_is_separator(lines[i + 1]):
                j = i + 2
                rows = 0
                while j < len(lines) and _note_cells(lines[j]) is not None \
                        and not _note_is_separator(lines[j]):
                    rows += 1
                    j += 1
                if len(cells) >= _NOTE_MIN_COLUMNS:
                    tables.append({
                        "caption": pending_caption[:80],
                        "columns": cells[:max_columns],
                        "columns_total": len(cells),
                        "rows_n": rows,
                        "unit_as_reported": pending_unit,
                    })
                    pending_unit, pending_caption = "", ""
                else:
                    # ⚠ 좁은 블록을 그냥 버리면 **단위를 잃는다** — 실측에서
                    #   `| | (단위: 천원) |`이 구분선까지 갖춘 2열 표로 온다.
                    #   버리되 단위 표기는 건져 다음 표에 딸려 보낸다.
                    m = _NOTE_UNIT_RE.search(lines[i])
                    if m:
                        pending_unit = m.group(0)
                    skipped_narrow += 1
                i = j
                continue
            # 구분선 없는 한 줄짜리 블록 — 단위·각주 운반체
            m = _NOTE_UNIT_RE.search(lines[i])
            if m:
                pending_unit = m.group(0)
            i += 1

        total = len(tables)
        shown = tables[:max_tables]
        reason = ""
        structured = True
        if not tables:
            structured = False
            reason = (f"열 {_NOTE_MIN_COLUMNS}개 이상인 데이터 표를 찾지 못했습니다"
                      f"(2열 블록 {skipped_narrow}개는 단위·각주로 보고 제외)."
                      if skipped_narrow else "이 주석에 마크다운 표가 없습니다.")
        out.append({
            "note_no": note["no"],
            "title": note["title"],
            "structured": structured,
            "reason": reason,
            "tables_total": total,
            "tables_omitted": max(0, total - len(shown)),
            "tables": shown,
        })
    return out
