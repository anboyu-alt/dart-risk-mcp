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
)

__all__ = [
    "parse_decision_parties",
    "extract_board_section",
    "parse_board_resolutions",
    "find_resolution_rows",
    "match_director_overlap",
    "summarize_board_conflict",
]

# ── 공통 유틸 ──────────────────────────────────────────────────────────────

_WS_RE = re.compile(r"\s+")
_FOOTNOTE_RE = re.compile(r"\(\s*\d+\s*\)")  # 임원현황 이름 뒤 각주 표지: 이재철(1)
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

    for rel in (out["counterparty"]["relation"], out["target"]["relation"]):
        if any(k in rel for k in _MARKERS) and classify_outflow_relation(rel) != "external":
            out["related_party"] = True
    return out


# ── extract_board_section ──────────────────────────────────────────────────

# 제목은 회사마다 다르다 — 「(2) 이사회의 주요 의결사항 등」(SKAI) · 「다. 중요의결사항 등」(셀트리온).
_BOARD_TITLE_RE = re.compile(r"(?:이사회의\s*)?(?:주요|중요)\s*의결\s*사항")
_NEXT_HEADING_RE = re.compile(r"^\s*(?:\(\d+\)|[가-하]\.|\d+\.|[IVX]+\.)|^#{1,4} ")


def _section_from(lines: list[str], start: int) -> str:
    end = len(lines)
    for j in range(start + 1, len(lines)):
        if _NEXT_HEADING_RE.match(lines[j]):
            end = j
            break
    return "\n".join(lines[start:end]).rstrip()


def extract_board_section(markdown: str) -> str:
    """「이사회의 주요 의결사항」·「중요의결사항」 제목 줄부터 다음 소제목 줄 앞까지. 없으면 ""."""
    lines = _norm(markdown).split("\n")
    starts = [i for i, ln in enumerate(lines) if _BOARD_TITLE_RE.search(ln)]
    if not starts:
        return ""
    # 우선순위: ① 이사 그룹 머리(사내이사 등의 성명) 표가 든 절 — 제목 변형을 넓힌 뒤에는
    # 「다. 중요 의결 사항 등 (1) 이사회 운영 규정」처럼 같은 낱말을 쓰는 다른 절이 앞에
    # 올 수 있다(SKAI 사업보고서 실측: 정관 발췌 표가 먼저 잡혀 의결표를 가렸다)
    # ② 표(`|`)가 딸린 절(목차 줄의 언급이 아니라 실제 절) ③ 첫 절.
    fallback = ""
    with_table = ""
    for s in starts:
        sec = _section_from(lines, s)
        if not fallback:
            fallback = sec
        if _GROUP_HDR_RE.search(sec) and "|" in sec:
            return sec
        if "|" in sec and not with_table:
            with_table = sec
    return with_table or fallback


# ── parse_board_resolutions ────────────────────────────────────────────────

_SEP_CELL_RE = re.compile(r":?-{3,}:?")
_ATTEND_RE = re.compile(r"^(.*?)\s*\(\s*출석률\s*[:：]\s*([\d.]+\s*%)\s*\)\s*$", re.S)
# 이사 그룹 머리 — SKAI는 「사내이사 등의 성명」·「사외이사 등의 성명」 두 칸, 삼성전자·두산은
# 「이사의 성명」 한 칸(사내/사외를 가르지 않는다 — group은 ""로 둔다).
_GROUP_HDR_RE = re.compile(
    r"사내\s*이사\s*등의\s*성명|사외\s*이사\s*등의\s*성명|(?<![가-힣])이사의\s*성명")
# 그룹 머리 칸이 따로 없는 서식(셀트리온)의 머리 줄: 「개최일자」와 「의안」 칸이 함께 있다.
_HDR_DATE_RE = re.compile(r"개최\s*일자")
_HDR_AGENDA_RE = re.compile(r"의\s*안")
_PLAIN_GROUP_RE = re.compile(r"(?:사내|사외)\s*이사")
# 출석률 표기가 없는 이름 줄의 셀: 한글 2~5자 또는 쉼표·공백이 든 로마자(숫자 없음)
_PERSON_CELL_RE = re.compile(r"[가-힣]{2,5}|[A-Za-z][A-Za-z ,.'-]*[A-Za-z]")
_ATTEND_ROW_RE = re.compile(r"출석\s*[률율]")
_RESULT_LABEL_RE = re.compile(r"가결\s*여부")


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


def parse_board_resolutions(section_md: str) -> dict:
    """이사회 의결표(2단 헤더 파이프 표)를 읽는다.

    상단 헤더(회차·개최 일자·의안 내용·가결 여부·사내이사 등·사외이사 등) 아래
    이사 이름 줄(`이름(출석률: N%)`)이 따로 오고, 데이터 행은 4칸 + 이사 수만큼이다.
    `group`: 이름 줄에 사내/사외 표지가 없고 상단 헤더의 두 그룹 셀 폭이 마크다운에
    드러나지 않아 위치로 추정할 수 없다 — 추측하지 않고 전부 ""로 둔다.
    """
    empty = {"directors": [], "rows": [], "unparsed": 0}
    lines = _norm(section_md).split("\n")

    h = None
    hcells = None
    for i, ln in enumerate(lines):
        c = _cells(ln)
        if c and any(_GROUP_HDR_RE.search(x) for x in c):
            h, hcells = i, c
            break
    if h is None:  # 그룹 머리 칸이 없는 서식 — 「개최일자」·「의안」 칸이 함께 있는 줄
        for i, ln in enumerate(lines):
            c = _cells(ln)
            if (c and any(_HDR_DATE_RE.search(x) for x in c)
                    and any(_HDR_AGENDA_RE.search(x) for x in c)):
                h, hcells = i, c
                break
    if h is None:
        return empty
    fixed = next((k for k, x in enumerate(hcells)
                  if _GROUP_HDR_RE.search(x) or _PLAIN_GROUP_RE.fullmatch(x)), 4)
    if fixed < 4:
        return empty

    i = h + 1
    while i < len(lines) and (_cells(lines[i]) is None and not lines[i].strip()):
        i += 1
    while i < len(lines):
        c = _cells(lines[i])
        if c is None or not _is_sep(c):
            break
        i += 1
    if i >= len(lines):
        return empty
    name_cells = _cells(lines[i])
    if not name_cells:
        return empty
    with_attend = any(_ATTEND_RE.match(x) for x in name_cells)
    if not with_attend and not (
            len(name_cells) >= 2 and all(_PERSON_CELL_RE.fullmatch(x) for x in name_cells)):
        return empty

    directors = []
    for x in name_cells:
        m = _ATTEND_RE.match(x)
        name, att = (m.group(1), _WS_RE.sub("", m.group(2))) if m else (x, "")
        directors.append({"name": _clean_name(name), "group": "", "attendance": att})
    names = [d["name"] for d in directors]
    expected = fixed + len(names)

    rows: list[dict] = []
    unparsed = 0
    i += 1
    while i < len(lines):
        c = _cells(lines[i])
        if c is None:
            break
        i += 1
        if _is_sep(c) or len(c) == 1:  # 구분선·「찬 반 여 부」 같은 1칸 줄
            continue
        if _RESULT_LABEL_RE.fullmatch(c[0]) and len(c) == 2:  # 「가결여부 | 찬 반 여 부」
            continue
        if _ATTEND_ROW_RE.fullmatch(c[0]) and len(c) == len(names) + 1:  # 출석율 줄
            for d, a in zip(directors, c[1:]):
                d["attendance"] = _WS_RE.sub("", a)
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
        return empty  # 이름 줄 같아 보였지만 열 수가 맞는 데이터 행이 없다 — 이사를 주장하지 않는다
    return {"directors": directors, "rows": rows, "unparsed": unparsed}


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


def _career_quote(career: str, company_fold: str) -> str:
    """주요경력에서 (공백 무시·대문자) 회사명이 나오면 그 줄 안 앞뒤 20자까지 인용."""
    idx = [i for i, ch in enumerate(career) if not ch.isspace()]
    flat = "".join(career[i].upper() for i in idx)
    pos = flat.find(company_fold)
    if pos < 0:
        return ""
    start, end = idx[pos], idx[pos + len(company_fold) - 1] + 1
    line_start = career.rfind("\n", 0, start) + 1
    line_end = career.find("\n", end)
    line_end = len(career) if line_end < 0 else line_end
    a, b = max(line_start, start - 20), min(line_end, end + 20)
    return _WS_RE.sub(" ", career[a:b]).strip()


def _birth_match(birth: str, others: list[dict]):
    flags = []
    for o in others:
        ob = (o.get("birth_ym") or "").strip()
        if birth and ob:
            flags.append(birth == ob)
    if not flags:
        return None
    return any(flags)


def match_director_overlap(
    roster_rows: list[dict],
    parties: dict,
    other_roster_rows: "list[dict] | None" = None,
) -> list[dict]:
    """공시 회사 임원현황과 거래상대방·대상회사를 사실로 대조한다.

    근거 ① 임원 이름 = 공시에 적힌 상대방/대상회사 대표자 ② 주요경력에 상대방/대상회사
    이름이 적힘 ③ `other_roster_rows`(거래상대방의 임원현황)에 같은 이름. ③이 있을 때만
    `birth_match`(생년월 일치 여부)를 채운다. 사람이 상대방·대상 양쪽에 걸리면 행 둘.
    """
    parties = parties or {}
    others = [r for r in (other_roster_rows or []) if isinstance(r, dict)]
    other_by_key: dict[str, list[dict]] = {}
    for o in others:
        other_by_key.setdefault(_name_key(o.get("nm")), []).append(o)

    sides = []
    for side in ("counterparty", "target"):
        p = parties.get(side) or {}
        sides.append((side, p.get("name") or "", p.get("rep") or ""))

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
            fold = _fold_corp_name(other_name)
            if len(fold) >= 2:
                quote = _career_quote(career, fold)
                if quote:
                    evidence.append(f"임원현황 주요경력: 「{quote}」")
                    role_other = role_other or quote
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
                "side": side,
                "other_name": other_name,
                "role_at_other": role_other,
                "evidence": evidence,
                "birth_match": birth,
                "mxmm_shrholdr_relate": (r.get("mxmm_shrholdr_relate") or "").strip(),
            })
    return out


# ── summarize_board_conflict ───────────────────────────────────────────────

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


def summarize_board_conflict(directors: list[dict], overlaps: "list[dict] | None", row: "dict | None") -> str:
    """한 줄 사실 요약 — 판정·평가 어휘 없음.

    `overlaps=None`은 「대조하지 못했다」(임원 명부를 못 받았거나 비었다)이고 빈 리스트
    `[]`는 「대조했고 일치가 없다」다 — 둘을 섞으면 못 본 것이 「겸직 0인」으로 읽힌다.
    """
    n = len(directors or [])
    if overlaps is None:
        head = ((f"이사 {n}인 · " if n else "이사 수 확인 불가 · ")
                + "상대방·대상회사 임원 겸직 대조 불가(임원 명부 확인 불가)")
        if not row:
            return head + " · 의결표 없음"
        votes = row.get("votes") or {}
        if not votes:
            return head + " · 결의 표기 없음"
        return head + f" · 전체 이사 결의 표기: {_tally(list(votes.values()))}"
    persons = {}
    for o in overlaps or []:
        persons.setdefault(_name_key(o.get("name")), o.get("name") or "")
    k = len(persons)
    head = (f"이사 {n}인 중 {k}인이 상대방·대상회사 임원 겸직" if n
            else f"이사 수 확인 불가 · 상대방·대상회사 임원 겸직 {k}인")
    if not row:
        return head + " · 의결표 없음"
    votes = row.get("votes") or {}
    if not votes:
        return head + " · 결의 표기 없음"
    by_key = {_name_key(name): v for name, v in votes.items()}
    parts = [head]
    if k:
        mine = [by_key[key] for key in persons if key in by_key]
        missing = sum(1 for key in persons if key not in by_key)
        t = _tally(mine) if mine else ""
        if missing:
            t = (t + " · " if t else "") + f"표에 없음 {missing}"
        parts.append(f"겸직 이사 결의 표기: {t}")
    parts.append(f"전체 이사 결의 표기: {_tally(list(votes.values()))}")
    return " · ".join(parts)
