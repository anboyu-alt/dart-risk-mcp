"""이사회 이해상충 점검용 순수 파서 — 네트워크 호출 없음.

타법인 주식 양수 등 결정 공시(원문 평문)에서 거래 당사자를, 사업보고서(마크다운)에서
이사회 의결표를, 임원현황(`exctvSttus`)에서 겸직 단서를 읽어 사실만 대조한다.
판정·점수·등급은 없다 — 일치한 근거를 문자열로 남길 뿐이다(v0.8.5 원칙).
"""
import re
from collections import Counter

from .dart_client import (
    _COUNTERPARTY_LOOKS_DIRTY_RE,
    _fold_corp_name,
    _is_amended_document,
    classify_outflow_relation,
    strip_holder_suffix,
)

__all__ = [
    "parse_decision_parties",
    "is_related_relation",
    "extract_board_section",
    "extract_board_section_with_title",
    "parse_board_resolutions",
    "find_resolution_rows",
    "match_director_overlap",
    "career_mentions",
    "board_scope",
    "summarize_board_conflict",
]

# ── 공통 유틸 ──────────────────────────────────────────────────────────────

_WS_RE = re.compile(r"\s+")
# 임원현황 이름 뒤 각주 표지: 이재철(1) · 김승현* · 조대민** · 김진철***(라이브 나이스정보통신
# 2026/11012) · †·‡·※. 사람 이름에 이 기호가 들어가는 일은 없어 위치와 무관하게 뗀다.
_FOOTNOTE_RE = re.compile(r"\(\s*\d+\s*\)|[*＊†‡※]+")
_DATE_RE = re.compile(r"(\d{4})\s*[년.\-/]\s*(\d{1,2})\s*[월.\-/]\s*(\d{1,2})")
_SKIP_NAMES = {"", "계", "합계"}


def _norm(text) -> str:
    """CRLF → LF. None·비문자열은 빈 문자열."""
    if not isinstance(text, str):
        return ""
    return text.replace("\r\n", "\n").replace("\r", "\n")


def _date8(s: str) -> str:
    m = _DATE_RE.search(s or "")
    if not m:
        return ""
    y, mo, d = m.groups()
    return f"{int(y):04d}{int(mo):02d}{int(d):02d}"


def _clean_name(name) -> str:
    """각주 표지·줄바꿈·앞뒤 공백을 걷어낸 표시용 이름."""
    s = _FOOTNOTE_RE.sub("", name or "")
    return _WS_RE.sub(" ", s).strip()


def _name_key(name) -> str:
    """이름 비교 키 — 각주·공백(개행 포함)·쉼표 제거 + 대문자.

    `known_actors.normalize_name`은 역할 괄호 제거가 목적이라 각주 표지 `(1)`와
    `MAO,\\nXUCHAO`↔`MAO, XUCHAO` 같은 줄바꿈·쉼표 차이를 흡수하지 못해 쓰지 않았다.
    """
    return re.sub(r"[\s,]+", "", _clean_name(name)).upper()


def _squash(s) -> str:
    return _WS_RE.sub("", s or "")


# ── parse_decision_parties ─────────────────────────────────────────────────

_EMPTY_PARTY = {"name": "", "rep": "", "relation": ""}

_STOP_LABELS = (
    r"회사명|국적|대표자|자본금|주요사업|본점소재지|주소|회사와의?\s*관계|"
    r"발행주식총수|이사회결의일|거래대금"
)
_HEADING_RE = re.compile(r"\s\d{1,2}\.\s+[가-힣]")
_REP_OK_RE = re.compile(r"[가-힣A-Za-z][가-힣A-Za-z,. ]{1,29}")
_REL_LABEL = r"회사와의?\s*관계"  # 「회사와 관계」(발행회사)·「회사와의 관계」(상대방) 둘 다
_REP_IN_SECTION_RE = re.compile(
    r"대표(?:이사|집행임원)\s+([가-힣A-Za-z][가-힣A-Za-z,. ]{0,28}?)\s+[\d,]+(?:\s|$)"
)
_MARKERS = ("최대주주", "특수관계", "계열")


def _block(text: str, start_re: str, span: int = 700) -> str:
    """start_re가 처음 나오는 곳부터 다음 번호 소제목('2. 양수내역' 등) 앞까지."""
    m = re.search(start_re, text)
    if not m:
        return ""
    blk = text[m.start():m.start() + span]
    h = _HEADING_RE.search(blk, 3)
    return blk[:h.start()] if h else blk


def _field(block: str, label_re: str) -> str:
    """라벨 뒤 값을 다음 라벨 앞(또는 블록 끝)까지 읽어 strip."""
    m = re.search(label_re + r"\s+(.*?)(?=\s+(?:" + _STOP_LABELS + r")|\s*$)", block, re.S)
    return m.group(1).strip() if m else ""


def _clean_rep(v: str) -> str:
    v = (v or "").strip()
    if not _REP_OK_RE.fullmatch(v) or _COUNTERPARTY_LOOKS_DIRTY_RE.search(v):
        return ""
    # 한글 이름은 공백이 없다 — 한글 조각에 공백이 끼면 조사·문장이 붙은 것이므로 버린다
    # (라틴 이름 「MAO XUCHAO」·쉼표로 이은 공동대표는 통과)
    for part in v.split(","):
        if re.search(r"[가-힣]", part) and re.search(r"\s", part.strip()):
            return ""
    return v


def _clean_name_value(v: str) -> str:
    v = (v or "").strip()
    if v in ("", "-") or len(v) > 80 or _COUNTERPARTY_LOOKS_DIRTY_RE.search(v):
        return ""
    return v


def _counterparty_rep_from_section(text: str) -> str:
    """6. 블록에 「대표자」 라벨이 없을 때 【거래상대방에 관한 사항】 표의 「대표이사 <이름>」."""
    pos = [m.start() for m in re.finditer(r"【\s*거래상대방에 관한 사항\s*】", text)]
    for p in reversed(pos):  # 첫 등장은 각주 참조라 마지막 등장부터 본다
        m = _REP_IN_SECTION_RE.search(text[p:p + 1500])
        if m:
            rep = _clean_rep(m.group(1))
            if rep:
                return rep
    return ""


def parse_decision_parties(text: str) -> dict:
    """결정 공시 원문 평문에서 거래상대방·대상회사(발행회사)·이사회결의일을 읽는다.

    정정 원문이면 모두 빈 값(어느 값이 현재인지 파서가 판단할 수 없다).
    """
    out = {
        "counterparty": dict(_EMPTY_PARTY),
        "target": dict(_EMPTY_PARTY),
        "resolution_date8": "",
        "outside_directors_present": "",
        "related_party": False,
    }
    t = _norm(text).strip()
    if not t or _is_amended_document(t):
        return out

    tb = _block(t, r"(?:\d+\.\s*)?발행회사\s+회사명")
    if tb:
        out["target"] = {
            "name": _clean_name_value(_field(tb, r"회사명")),
            "rep": _clean_rep(_field(tb, r"대표자")),
            "relation": _field(tb, _REL_LABEL),
        }

    cb = _block(t, r"(?:\d+\.\s*)?거래상대방\s+회사명(?:\(성명\))?")
    if cb:
        rep = _clean_rep(_field(cb, r"대표자"))
        out["counterparty"] = {
            "name": _clean_name_value(_field(cb, r"회사명(?:\(성명\))?")),
            "rep": rep or _counterparty_rep_from_section(t),
            "relation": _field(cb, _REL_LABEL),
        }

    m = re.search(r"이사회\s*결의일\s*(?:\(\s*결정일\s*\))?\s*(\d{4}\s*[년.\-/]\s*\d{1,2}\s*[월.\-/]\s*\d{1,2})", t)
    if m:
        out["resolution_date8"] = _date8(m.group(1))
        tail = t[m.end():m.end() + 200]
        n = re.search(r"참석\s*\(명\)\s*(\d+)", tail)
        if n:
            out["outside_directors_present"] = n.group(1)

    out["related_party"] = any(is_related_relation(rel) for rel in (
        out["counterparty"]["relation"], out["target"]["relation"]))
    return out


def is_related_relation(rel) -> bool:
    """관계 표기가 최대주주·특수관계인·계열을 말하는가(부정 표기로 external이면 아니다)."""
    rel = rel or ""
    return any(k in rel for k in _MARKERS) and classify_outflow_relation(rel) != "external"


# ── extract_board_section ──────────────────────────────────────────────────

# 제목은 회사마다 다르다 — 「(2) 이사회의 주요 의결사항 등」(SKAI) · 「다. 중요의결사항 등」(셀트리온).
_BOARD_TITLE_RE = re.compile(r"(?:이사회의\s*)?(?:주요|중요)\s*의결\s*사항")
_NEXT_HEADING_RE = re.compile(r"^\s*(?:\(\d+\)|[가-하]\.|\d+\.|[IVX]+\.)|^#{1,4} ")
_SEP_CELL_RE = re.compile(r":?-{3,}:?")
_ATTEND_RE = re.compile(r"^(.*?)\s*\(\s*출석률\s*[:：]\s*([\d.]+\s*%)\s*\)\s*$", re.S)
# 의결표 머리 줄의 칸들 — 「개최일자」는 모든 서식에 있고, 「가결여부」나 「회차」가 같은 줄에 있다.
_HDR_DATE_CELL_RE = re.compile(r"개최\s*일자")
_HDR_RESULT_OR_NO_RE = re.compile(r"가결\s*여부|회차")
# 이사 그룹 머리 — SKAI는 「사내이사 등의 성명」·「사외이사 등의 성명」 두 칸, 삼성전자·두산은
# 「이사의 성명」 한 칸(사내/사외를 가르지 않는다 — group은 ""로 둔다). ⚠ 이 넓은 형태는
# **머리 줄 판정에만** 쓴다 — 절 선택에 쓰면 같은 낱말을 쓰는 다른 표가 의결표 절을 가린다.
_NAME_HDR_RE = re.compile(
    r"사내\s*이사\s*등의\s*성명|사외\s*이사\s*등의\s*성명|(?<![가-힣])이사의\s*성명")
# 그룹 머리 칸이 따로 없는 서식(셀트리온)의 머리 줄: 「개최일자」 칸과 칸 전체가 「의안(내용)」인 칸.
_HDR_AGENDA_CELL_RE = re.compile(r"의\s*안(?:\s*내\s*용)?")
_PLAIN_GROUP_RE = re.compile(r"(?:사내|사외)\s*이사")
# 출석률 표기가 없는 이름 줄의 셀: 한글 2~5자 또는 쉼표·공백이 든 로마자(숫자 없음)
_PERSON_CELL_RE = re.compile(r"[가-힣]{2,5}|[A-Za-z][A-Za-z ,.'-]*[A-Za-z]")
# 이름처럼 생겼지만 이름이 아닌 칸 — 머리·합계 줄이 이사 줄로 읽히는 것을 막는다.
_NON_NAME_TOKENS = frozenset({
    "이사", "사내이사", "사외이사", "기타비상무이사", "비상무이사", "감사", "감사위원", "성명",
    "구분", "계", "합계", "소계", "비고", "회차", "개최일자", "의안내용", "가결여부",
    "찬반여부", "출석률", "출석율", "참석여부",
})
_ATTEND_ROW_RE = re.compile(r"출석\s*[률율]")
_RESULT_LABEL_RE = re.compile(r"가결\s*여부")


def _section_from(lines: list[str], start: int) -> str:
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if _NEXT_HEADING_RE.match(lines[j]):
            end = j
            break
    return "\n".join(lines[start:end]).rstrip()


_TITLE_MAX = 60


def _title_of(sec: str) -> str:
    """절의 첫 줄(앞뒤 공백 제거). 60자를 넘으면 말줄임표로 끊긴 것을 밝힌다."""
    first = sec.split("\n", 1)[0].strip()
    return first if len(first) <= _TITLE_MAX else first[:_TITLE_MAX] + "…"


def _has_resolution_table(sec: str) -> bool:
    """절에 의결표 머리 줄이 있는가 — 「개최일자」 칸과 「가결여부」·「회차」 칸이 한 줄에."""
    for ln in sec.split("\n"):
        c = _cells(ln)
        if (c and any(_HDR_DATE_CELL_RE.search(x) for x in c)
                and any(_HDR_RESULT_OR_NO_RE.search(x) for x in c)):
            return True
    return False


def extract_board_section_with_title(markdown: str) -> "tuple[str, str]":
    """`(제목 줄, 절)` — 제목 줄은 절의 첫 줄(원문 표기 그대로, 앞뒤 공백만 제거). 없으면 `("", "")`.

    우선순위: ① **의결표 머리 줄**(「개최일자」+「가결여부」/「회차」 칸)이 든 절 — 제목 변형을
    넓힌 뒤에는 「다. 중요 의결 사항 등 (1) 이사회 운영 규정」(정관 발췌 표)처럼 같은 낱말을
    쓰는 다른 절이 앞에 올 수 있다(SKAI 사업보고서 실측) ② 표(`|`)가 딸린 절(목차 줄의
    언급이 아니라 실제 절) ③ 첫 절.
    """
    lines = _norm(markdown).split("\n")
    starts = [i for i, ln in enumerate(lines) if _BOARD_TITLE_RE.search(ln)]
    if not starts:
        return "", ""
    fallback = ""
    with_table = ""
    for s in starts:
        sec = _section_from(lines, s)
        if not fallback:
            fallback = sec
        if "|" in sec and _has_resolution_table(sec):
            return _title_of(sec), sec
        if "|" in sec and not with_table:
            with_table = sec
    sec = with_table or fallback
    return _title_of(sec), sec


def extract_board_section(markdown: str) -> str:
    """「이사회의 주요 의결사항」·「중요의결사항」 제목 줄부터 다음 소제목 줄 앞까지. 없으면 ""."""
    return extract_board_section_with_title(markdown)[1]


# ── parse_board_resolutions ────────────────────────────────────────────────

def _cells(line: str):
    s = line.strip()
    if not s.startswith("|"):
        return None
    s = s[1:]
    if s.endswith("|"):
        s = s[:-1]
    return [c.strip() for c in s.split("|")]


def _is_sep(cells) -> bool:
    return bool(cells) and all(_SEP_CELL_RE.fullmatch(c) for c in cells)


def _is_header_cells(c) -> bool:
    return bool(c) and any(_HDR_DATE_CELL_RE.search(x) for x in c) and (
        any(_NAME_HDR_RE.search(x) for x in c)
        or any(_HDR_AGENDA_CELL_RE.fullmatch(x) for x in c))


def _plausible_names(cells) -> bool:
    return (len(cells) >= 2
            and all(_PERSON_CELL_RE.fullmatch(x) and _WS_RE.sub("", x) not in _NON_NAME_TOKENS
                    for x in cells))


def _is_table_header(lines: list[str], i: int) -> bool:
    """i번째 줄이 새 의결표의 머리 줄인가 — 머리 칸 + 바로 다음 줄이 구분선."""
    c = _cells(lines[i]) if i < len(lines) else None
    return bool(c) and _is_header_cells(c) and i + 1 < len(lines) and _is_sep(_cells(lines[i + 1]))


def _next_pipe_line(lines: list[str], i: int) -> "int | None":
    """i부터 빈 줄을 건너뛴 첫 줄의 위치 — 그 줄이 파이프 행이 아니면(본문 문장) None."""
    while i < len(lines) and not lines[i].strip():
        i += 1
    if i < len(lines) and _cells(lines[i]) is not None:
        return i
    return None


def _parse_one_table(lines: list[str], h: int, hcells: list[str]):
    """머리 줄 h부터 표 하나를 읽는다 → `(표 dict 또는 None, unparsed, 표가 끝난 위치)`.

    표 dict는 `{"directors", "rows"}`. None은 「표는 찾았으나 이 서식을 읽지 못했다」.
    끝난 위치는 다음 표의 머리 줄(있으면) 또는 표 바깥 첫 줄이다.
    """
    fixed = next((k for k, x in enumerate(hcells)
                  if _NAME_HDR_RE.search(x) or _PLAIN_GROUP_RE.fullmatch(x)), 4)
    if fixed < 4:
        return None, 0, h + 1

    i = h + 1
    while i < len(lines) and (_cells(lines[i]) is None and not lines[i].strip()):
        i += 1
    while i < len(lines):
        c = _cells(lines[i])
        if c is None or not _is_sep(c):
            break
        i += 1
    if i >= len(lines):
        return None, 0, i
    name_cells = _cells(lines[i])
    if not name_cells:
        return None, 0, i
    name_i = i
    with_attend = any(_ATTEND_RE.match(x) for x in name_cells)
    if not with_attend and not _plausible_names(name_cells):
        return None, 0, i + 1
    if not with_attend:
        # 출석률 표기가 없는 이름 줄은 열 수가 맞는 첫 데이터 행이 있어야 이사 줄이다
        first_data = None
        for j in range(i + 1, len(lines)):
            d = _cells(lines[j])
            if d is None:
                break
            if (_is_sep(d) or len(d) == 1
                    or (_RESULT_LABEL_RE.fullmatch(d[0]) and len(d) == 2)
                    or (_ATTEND_ROW_RE.fullmatch(d[0]) and len(d) == len(name_cells) + 1)):
                continue
            first_data = d
            break
        if first_data is None or len(first_data) != fixed + len(name_cells):
            return None, 0, i + 1

    directors = []
    for x in name_cells:
        m = _ATTEND_RE.match(x)
        name, att = (m.group(1), _WS_RE.sub("", m.group(2))) if m else (x, "")
        directors.append({"name": _clean_name(name), "group": "", "attendance": att})
    names = [d["name"] for d in directors]
    expected = fixed + len(names)

    rows: list[dict] = []
    unparsed = 0
    attend_done = False
    i = name_i + 1
    while i < len(lines):
        if not lines[i].strip():
            # 표 안의 빈 줄 — 뒤에 파이프 행이 이어지면 같은 표다(조용히 버리지 않는다).
            # 새 머리 줄이면 그 자리에서 이 표가 끝나고, 본문 문장이면 표 바깥이다.
            nxt = _next_pipe_line(lines, i)
            if nxt is None or _is_table_header(lines, nxt):
                return {"directors": directors, "rows": rows}, unparsed, (nxt if nxt is not None else i)
            i = nxt
            continue
        c = _cells(lines[i])
        if c is None:
            break
        if _is_table_header(lines, i):
            return {"directors": directors, "rows": rows}, unparsed, i  # 새 표의 머리 줄
        pos = i
        i += 1
        if _is_sep(c) or len(c) == 1:  # 구분선·「찬 반 여 부」 같은 1칸 줄
            continue
        if _RESULT_LABEL_RE.fullmatch(c[0]) and len(c) == 2:  # 「가결여부 | 찬 반 여 부」
            continue
        if (not attend_done and pos <= name_i + 2 and _ATTEND_ROW_RE.fullmatch(c[0])
                and len(c) == len(names) + 1):  # 이름 줄 바로 다음의 출석율 줄 — 한 번만
            for d, a in zip(directors, c[1:]):
                d["attendance"] = _WS_RE.sub("", a)
            attend_done = True
            continue
        if len(c) != expected or not (c[0] or c[1] or c[2]):
            unparsed += 1
            continue
        rows.append({
            "no": c[0],
            "date8": _date8(c[1]),
            "agenda": _WS_RE.sub(" ", c[2]).strip(),
            "result": c[3],
            "votes": dict(zip(names, c[fixed:])),
        })
    if not with_attend and not rows:
        return None, unparsed, i  # 이름 줄 같아 보였지만 열 수가 맞는 데이터 행이 없다
    return {"directors": directors, "rows": rows}, unparsed, i


def parse_board_resolutions(section_md: str) -> dict:
    """이사회 의결표(2단 헤더 파이프 표)를 읽는다.

    상단 헤더(회차·개최 일자·의안 내용·가결 여부·사내이사 등·사외이사 등) 아래
    이사 이름 줄(`이름(출석률: N%)`)이 따로 오고, 데이터 행은 4칸 + 이사 수만큼이다.
    `group`: 이름 줄에 사내/사외 표지가 없고 상단 헤더의 두 그룹 셀 폭이 마크다운에
    드러나지 않아 위치로 추정할 수 없다 — 추측하지 않고 전부 ""로 둔다.

    `table_found`: **의결표 머리 줄을 찾았는가**. False는 「표가 없다」, True인데
    `directors`·`rows`가 비면 「표는 있으나 이 서식을 읽지 못했다」다 — 두 경우를 섞으면
    못 읽은 표가 「의결표 없음」으로 나온다.

    이름 줄은 **양성 근거**가 있을 때만 이사 줄로 읽는다: 칸 하나 이상이 `이름(출석률: N%)`이거나,
    (출석률 표기가 없으면) 모든 칸이 사람 이름이고 비이름 단어(사내이사·구분·합계…)가 없으며
    그 다음 데이터 행의 열 수가 이름 수와 맞아야 한다. 「출석율」 줄은 이름 줄 바로 다음
    (사이에 구분선만 허용) 한 번만 적용한다.

    **반복 의결표**(두산 — 이사 구성이 바뀔 때마다 같은 머리의 표가 다시 온다): 새 머리 줄이
    나오면 거기서 새 표를 읽는다. `tables`는 표마다 `{"directors", "rows"}`(행 dict는
    `rows`와 **같은 객체**라 `r is row`로 어느 표의 행인지 찾는다). `directors`는 첫 표의 이사다
    (하위 호환) — 행의 이사는 그 행이 든 표에서 읽어야 한다. 첫 표 뒤의 표를 못 읽으면 거기서
    멈추고 `unparsed`에 1을 더한다. 표 안의 빈 줄 뒤에 파이프 행이 이어지면 같은 표로 읽는다.
    """
    empty = {"directors": [], "rows": [], "unparsed": 0, "table_found": False, "tables": []}
    lines = _norm(section_md).split("\n")

    h = None
    hcells = None
    for i, ln in enumerate(lines):  # ① 그룹 머리 칸(…등의 성명 / 이사의 성명)이 있는 머리 줄
        c = _cells(ln)
        if (c and any(_HDR_DATE_CELL_RE.search(x) for x in c)
                and any(_NAME_HDR_RE.search(x) for x in c)):
            h, hcells = i, c
            break
    if h is None:  # ② 그룹 머리 칸이 없는 서식 — 「개최일자」와 「의안(내용)」 칸
        for i, ln in enumerate(lines):
            c = _cells(ln)
            if (c and any(_HDR_DATE_CELL_RE.search(x) for x in c)
                    and any(_HDR_AGENDA_CELL_RE.fullmatch(x) for x in c)):
                h, hcells = i, c
                break
    if h is None:
        return empty
    found = dict(empty, table_found=True)  # 이후의 빈 반환은 「표는 찾았으나 못 읽음」

    table, unparsed, end = _parse_one_table(lines, h, hcells)
    if table is None:
        return found
    tables = [table]
    while end < len(lines) and _is_table_header(lines, end):
        nxt, n_unparsed, nxt_end = _parse_one_table(lines, end, _cells(lines[end]))
        if nxt is None:
            unparsed += 1  # 이어진 표를 읽지 못했다 — 조용히 버리지 않고 센다
            break
        unparsed += n_unparsed
        tables.append(nxt)
        if nxt_end <= end:
            break
        end = nxt_end
    rows = [r for t in tables for r in t["rows"]]
    return {"directors": tables[0]["directors"], "rows": rows, "unparsed": unparsed,
            "table_found": True, "tables": tables}


# ── find_resolution_rows ───────────────────────────────────────────────────

def find_resolution_rows(parsed: dict, date8: str, agenda_hint: str = "") -> list[dict]:
    """결의일이 일치하는 행 전부. 안건 힌트가 든 행을 앞에(안정 정렬)."""
    rows = [r for r in ((parsed or {}).get("rows") or []) if r.get("date8") == date8 and date8]
    if len(rows) < 2 or not (agenda_hint or "").strip():
        return rows
    words = [_squash(agenda_hint)] + [_squash(w) for w in agenda_hint.split() if len(_squash(w)) >= 2]
    hit = [r for r in rows if any(w and w in _squash(r.get("agenda")) for w in words)]
    return hit + [r for r in rows if r not in hit]


# ── match_director_overlap ─────────────────────────────────────────────────

def _role(ofcps, rgist) -> str:
    o = _WS_RE.sub(" ", ofcps or "").strip()
    g = _WS_RE.sub(" ", rgist or "").strip()
    return "/".join(dict.fromkeys(x for x in (o, g) if x))  # 직위=구분이면 한 번만


# 주요경력 조각의 시제 — 겸직 근거 ②는 **현재** 조각만 쓴다(최종 리뷰 I4).
# ⚠ 「현」·「전」 한 글자는 단어 안에 흔하다(현대·삼성전자) — 괄호 표기 「(현)」·「전)」나
#   조각 맨 앞의 「현 」·「전 」일 때만 표지로 본다.
_DATE_TOKEN = r"\d{2,4}(?:[.\-/]\d{1,2}){0,2}"
_PRESENT_RE = re.compile(r"現|현재|재직\s*중|\(\s*현\s*\)|(?<![가-힣])현\s*\)|^\s*현(?=\s)")
_PAST_RE = re.compile(r"前|\(\s*전\s*\)|(?<![가-힣])전\s*\)|^\s*전(?=\s)")
_OPEN_PERIOD_RE = re.compile(_DATE_TOKEN + r"\s*~(?!\s*[\d~])")        # 21.04~ · 21.04~ 現
_CLOSED_PERIOD_RE = re.compile(_DATE_TOKEN + r"\s*~\s*\d{2,4}|^\s*~\s*\d")  # 18.07~21.04 · ~08.02
_LETTER_RE = re.compile(r"[가-힣A-Za-z]")
# 조각 경계: 기간 시작(날짜 + ~) 앞 · 「 / 」·「|」·「;」·「·」 구분자
_SEG_SPLIT_RE = re.compile(r"(?<![\d.\-/])(?=" + _DATE_TOKEN + r"\s*~)|\s+/\s+|\s*[|;·]\s*")
_MARKER_POS_RE = re.compile(r"前|現|\(\s*[전현]\s*\)|(?<![가-힣])[전현](?=\s)")
# 접사를 뗀 회사명이 이보다 짧으면 경력 대조를 하지 않는다 — 「LG」·「SK」는 다른 계열사
# 이름(LG전자·SK하이닉스) 안에 들어 있어 같은 회사라고 볼 근거가 없다.
_CAREER_MIN_FOLD = 3
_GENERIC_FOLDS = frozenset({
    "주식회사", "회사", "홀딩스", "그룹", "코리아", "HOLDINGS", "GROUP", "KOREA",
})


def _split_markers(seg: str) -> list[str]:
    """「前 A사 상무 現 B사 고문」처럼 한 조각에 표지가 둘이면 표지 앞에서 가른다.
    「21.04~ 現 …」처럼 기간 바로 뒤의 표지는 같은 조각이다(가르면 기간이 떨어진다)."""
    out: list[str] = []
    start = 0
    for m in _MARKER_POS_RE.finditer(seg):
        p = m.start()
        prev = seg[start:p].rstrip()
        if p == start or not prev or prev.endswith("~"):
            continue
        out.append(seg[start:p])
        start = p
    out.append(seg[start:])
    return out


def _career_segments(career: str) -> list[str]:
    """주요경력을 경력 조각으로 나눈다 — 줄·기간 시작·구분자·표지 기준.
    날짜만 있는 줄(「2013~2016 」 + 다음 줄 「Bestfit Consulting CEO」)은 다음 줄과 잇는다."""
    lines: list[str] = []
    for ln in _norm(career).split("\n"):
        if not ln.strip():
            continue
        if lines and not _LETTER_RE.search(lines[-1]):
            lines[-1] = lines[-1] + " " + ln
        else:
            lines.append(ln)
    segs: list[str] = []
    for ln in lines:
        for part in _SEG_SPLIT_RE.split(ln):
            for sub in _split_markers(part or ""):
                if sub.strip():
                    segs.append(sub.strip())
    return segs


def _segment_tense(seg: str) -> str:
    """`current`(現·현재·재직 중·열린 기간) · `past`(前·닫힌 기간) · `unknown`(표기 없음)."""
    if _PRESENT_RE.search(seg) or _OPEN_PERIOD_RE.search(seg):
        return "current"
    if _PAST_RE.search(seg) or _CLOSED_PERIOD_RE.search(seg):
        return "past"
    return "unknown"


def _career_fold(company_name: str) -> str:
    """경력 대조에 쓸 회사명 폴딩 — 너무 짧거나 일반 낱말이면 ""(대조하지 않는다)."""
    fold = _fold_corp_name(company_name)
    if len(fold) < _CAREER_MIN_FOLD or fold in _GENERIC_FOLDS:
        return ""
    return fold


def _quote_in(seg: str, company_fold: str) -> str:
    """조각에서 (공백 무시·대문자) 회사명이 나오면 앞뒤 20자까지 인용. 없으면 ""."""
    idx = [i for i, ch in enumerate(seg) if not ch.isspace()]
    flat = "".join(seg[i].upper() for i in idx)
    pos = flat.find(company_fold)
    if pos < 0:
        return ""
    start, end = idx[pos], idx[pos + len(company_fold) - 1] + 1
    a, b = max(0, start - 20), min(len(seg), end + 20)
    return _WS_RE.sub(" ", seg[a:b]).strip()


def _career_hits(career: str, company_fold: str) -> list[tuple[str, str]]:
    """회사명이 나오는 경력 조각마다 `(시제, 인용)`."""
    if not company_fold:
        return []
    out = []
    for seg in _career_segments(career):
        q = _quote_in(seg, company_fold)
        if q:
            out.append((_segment_tense(seg), q))
    return out


_PERSON_NAME_RE = re.compile(r"[가-힣]{2,4}")


def _individual_name(name: str) -> str:
    """거래상대방 표기가 개인 이름(「김상곤 외 2인」)이면 대표 성명. 아니면 ""."""
    base = strip_holder_suffix(name or "").strip()
    if _PERSON_NAME_RE.fullmatch(base) and _fold_corp_name(base) == base:
        return base
    return ""


def _birth_match(birth: str, others: list[dict]):
    flags = []
    for o in others:
        ob = (o.get("birth_ym") or "").strip()
        if birth and ob:
            flags.append(birth == ob)
    if not flags:
        return None
    return any(flags)


def _sides(parties: dict):
    out = []
    for side in ("counterparty", "target"):
        p = (parties or {}).get(side) or {}
        out.append((side, p.get("name") or "", p.get("rep") or ""))
    return out


def match_director_overlap(
    roster_rows: list[dict],
    parties: dict,
    other_roster_rows: "list[dict] | None" = None,
) -> list[dict]:
    """공시 회사 임원현황과 거래상대방·대상회사를 사실로 대조한다.

    근거 ① 임원 이름 = 공시에 적힌 상대방/대상회사 대표자 (①′ 거래상대방이 개인이면 그 성명)
    ② 주요경력의 **현재** 경력 조각(現·현재·재직 중·열린 기간 `21.04~`)에 상대방/대상회사
    이름이 적힘 — 前·닫힌 기간(`18.07~21.04`)·시기 표기 없는 조각은 겸직 근거가 아니다
    (`career_mentions`가 사실로만 돌려준다). 접사를 뗀 회사명이 3자 미만이거나 일반 낱말이면
    ②를 하지 않는다 ③ `other_roster_rows`(거래상대방의 임원현황)에 같은 이름. ③이 있을 때만
    `birth_match`(생년월 일치 여부)를 채운다. 사람이 상대방·대상 양쪽에 걸리면 행 둘.
    """
    parties = parties or {}
    others = [r for r in (other_roster_rows or []) if isinstance(r, dict)]
    other_by_key: dict[str, list[dict]] = {}
    for o in others:
        other_by_key.setdefault(_name_key(o.get("nm")), []).append(o)

    sides = _sides(parties)
    cp_person = _individual_name(sides[0][1])

    out: list[dict] = []
    seen: set = set()
    for r in roster_rows or []:
        if not isinstance(r, dict):
            continue
        name = _clean_name(r.get("nm"))
        key = _name_key(name)
        if key in _SKIP_NAMES or name in _SKIP_NAMES:
            continue
        career = r.get("main_career") or ""
        for side, other_name, rep in sides:
            if (key, side) in seen:
                continue
            evidence: list[str] = []
            role_other = ""
            if rep and key == _name_key(rep):
                evidence.append("공시 거래상대방 대표자 일치" if side == "counterparty"
                                else "공시 발행회사 대표자 일치")
                role_other = "대표자(공시 기재)"
            if side == "counterparty" and cp_person and key == _name_key(cp_person):
                evidence.append("공시 거래상대방 본인(성명 일치)")
                role_other = role_other or "거래상대방 본인"
            current = [q for t, q in _career_hits(career, _career_fold(other_name)) if t == "current"]
            if current:
                evidence.append(f"임원현황 주요경력: 「{current[0]}」")
                role_other = role_other or current[0]
            birth = None
            if side == "counterparty" and key in other_by_key:
                evidence.append("상대방 임원현황 이름 일치")
                o = other_by_key[key][0]
                role_other = role_other or _role(o.get("ofcps"), o.get("rgist_exctv_at"))
                birth = _birth_match((r.get("birth_ym") or "").strip(), other_by_key[key])
            if not evidence:
                continue
            seen.add((key, side))
            out.append({
                "name": name,
                "role_at_issuer": _role(r.get("ofcps"), r.get("rgist_exctv_at")),
                "rgist": _WS_RE.sub(" ", r.get("rgist_exctv_at") or "").strip(),
                "side": side,
                "other_name": other_name,
                "role_at_other": role_other,
                "evidence": evidence,
                "birth_match": birth,
                "mxmm_shrholdr_relate": (r.get("mxmm_shrholdr_relate") or "").strip(),
            })
    return out


def career_mentions(roster_rows: list[dict], parties: dict) -> list[dict]:
    """주요경력에 상대방·대상회사 이름이 나오지만 **현재 경력이 아닌** 경우 — 사실로만 남긴다.

    `tense`: `past`(前·닫힌 기간) · `unknown`(재직 시기 표기 없음). 같은 사람·같은 쪽에
    현재 경력 일치가 있으면(겸직 근거 ②) 돌려주지 않는다. 겸직으로 세지 않고 게이트도 열지 않는다.
    """
    out: list[dict] = []
    for r in roster_rows or []:
        if not isinstance(r, dict):
            continue
        name = _clean_name(r.get("nm"))
        key = _name_key(name)
        if key in _SKIP_NAMES or name in _SKIP_NAMES:
            continue
        career = r.get("main_career") or ""
        for side, other_name, _rep in _sides(parties):
            hits = _career_hits(career, _career_fold(other_name))
            if not hits or any(t == "current" for t, _q in hits):
                continue
            tense, quote = hits[0]
            out.append({"name": name, "side": side, "other_name": other_name,
                        "quote": quote, "tense": tense})
    return out


# ── summarize_board_conflict ───────────────────────────────────────────────

# 「독립이사」: 2026 반기보고서부터 사외이사가 이 표기로 온다(라이브 두산·나이스정보통신 2026/11012).
_REGISTERED = frozenset({"사내이사", "사외이사", "독립이사", "기타비상무이사"})
_TABLE_SUFFIX = {
    "none": " · 의결표 없음",
    "unread": " · 의결표 못 읽음",
    "no_row": " · 결의일 행 없음",
    "periodic_failed": " · 의결표 확인 불가",
}


def _vote_label(v: str) -> str:
    v = (v or "").strip()
    if v == "":
        return "「공란」"
    return f"「{v}」" if v == "-" else v


def _tally(values: list[str]) -> str:
    """원문 표기별 개수 — 많은 순, 같으면 먼저 나온 순."""
    c = Counter(values)
    first = {}
    for k, v in enumerate(values):
        first.setdefault(v, k)
    order = sorted(c, key=lambda v: (-c[v], first[v]))
    return " · ".join(f"{_vote_label(v)} {c[v]}" for v in order)


def board_scope(directors: list[dict], roster: "list[dict] | None"):
    """요약의 「이사 N인」 범위 → `(라벨, 이름 키 집합 또는 None, 범위 밖 라벨)`.

    의결표 이사가 있으면 그 이름들, 없으면 명부(`exctvSttus`)의 사내이사·사외이사(독립이사)·기타비상무이사
    (「등기이사 N인(명부 기준)」), 둘 다 없으면 `("", None, "")` — 이사 수 확인 불가.
    """
    if directors:
        keys = {_name_key(d.get("name")) for d in directors}
        return f"이사 {len(directors)}인", keys, "의결표 밖 임원 겸직"
    reg = [r for r in (roster or []) if isinstance(r, dict)
           and _WS_RE.sub("", r.get("rgist_exctv_at") or "") in _REGISTERED]
    if reg:
        keys = {_name_key(r.get("nm")) for r in reg}
        return f"등기이사 {len(keys)}인(명부 기준)", keys, "등기이사 밖 임원 겸직"
    return "", None, ""


def summarize_board_conflict(directors: list[dict], overlaps: "list[dict] | None", row: "dict | None",
                             *, table_unread: bool = False, table_state: str = "",
                             roster: "list[dict] | None" = None,
                             unmatched_reason: str = "") -> str:
    """한 줄 사실 요약 — 판정·평가 어휘 없음.

    `overlaps=None`은 「대조하지 못했다」(임원 명부를 못 받았거나 비었다, 거래 당사자를 원문에서
    못 읽었다 — 사유는 `unmatched_reason`)이고 빈 리스트 `[]`는 「대조했고 일치가 없다」다 —
    둘을 섞으면 못 본 것이 「겸직 0인」으로 읽힌다.

    「이사 N인 중 K인」: N은 의결표 이사 수(없으면 명부의 등기이사 수), K는 **그 안의** 겸직자다.
    범위 밖 겸직자(미등기 임원 등)는 「의결표 밖 임원 겸직 M인」으로 따로 적고 K에 넣지 않는다.

    `table_state`: `none`(의결표 없음) · `unread`(의결표는 있으나 이 서식을 못 읽음) · `no_row`
    (의결표는 읽었으나 결의일 행 없음) · `periodic_failed`(정기보고서 원문을 못 받음).
    `table_unread=True`는 `table_state="unread"`와 같다(하위 호환).
    """
    state = table_state or ("unread" if table_unread else "none")
    no_table = _TABLE_SUFFIX.get(state, _TABLE_SUFFIX["none"])
    label, scope, outside_label = board_scope(directors, roster)
    if overlaps is None:
        reason = unmatched_reason or "임원 명부 확인 불가"
        head = ((f"{label} · " if label else "이사 수 확인 불가 · ")
                + f"상대방·대상회사 임원 겸직 대조 불가({reason})")
        if not row:
            return head + no_table
        votes = row.get("votes") or {}
        if not votes:
            return head + " · 결의 표기 없음"
        return head + f" · 전체 이사 결의 표기: {_tally(list(votes.values()))}"
    persons: dict = {}
    for o in overlaps or []:
        persons.setdefault(_name_key(o.get("name")), o.get("name") or "")
    inside = [k for k in persons if scope is None or k in scope]
    outside = [k for k in persons if scope is not None and k not in scope]
    k = len(inside)
    head = (f"{label} 중 {k}인이 상대방·대상회사 임원 겸직" if label
            else f"이사 수 확인 불가 · 상대방·대상회사 임원 겸직 {k}인")
    if outside:
        head += f" · {outside_label} {len(outside)}인"
    if not row:
        return head + no_table
    votes = row.get("votes") or {}
    if not votes:
        return head + " · 결의 표기 없음"
    by_key = {_name_key(name): v for name, v in votes.items()}
    parts = [head]
    if k:
        mine = [by_key[key] for key in inside if key in by_key]
        missing = sum(1 for key in inside if key not in by_key)
        t = _tally(mine) if mine else ""
        if missing:
            t = (t + " · " if t else "") + f"표에 없음 {missing}"
        parts.append(f"겸직 이사 결의 표기: {t}")
    parts.append(f"전체 이사 결의 표기: {_tally(list(votes.values()))}")
    return " · ".join(parts)
