# -*- coding: utf-8 -*-
"""감사보고서 원문 분할 — 순수 함수만. 네트워크 호출 없음.

OpenDART 재무제표 API(`fnlttSinglAcnt` 계열)는 정기보고서 제출 법인 위주라
비상장 외부감사대상 법인은 「조회된 데이타가 없습니다」를 돌려준다. 그러나
**감사보고서 원문은 DART에 그대로 공시**되므로 원문 경로로 우회할 수 있다.
이 모듈은 그 원문(`_html_to_structured_text` 출력 마크다운)을 재무제표 /
주석 / 외부감사 실시내용으로 가른다.

## 왜 줄 단위 규칙인가

이 문서들에는 기댈 구조가 거의 없다(2026-09-11 실측).

  · `_html_to_structured_text`가 내는 `#` 헤딩 **0개**
  · `list_document_sections`는 6개만 내는데 그중 하나가 **623KB**라 못 자른다
  · `scan_note_titles`는 **0건** — 이 문서의 `<TITLE>` 9개가 전부
    「목 차」·「주석」·「외부감사 실시내용」처럼 `NOTE_CATEGORIES`에 안 걸린다

## 서식은 회계법인마다 다르다

비상장(E) 감사보고서 · 회계법인 10곳 표본에서 규칙별 적중률:

    주석 번호 헤딩(탐욕 증가)   10/10   ← 1순위 앵커
    「과목」 표 머리             9/10   ← 재무제표 앵커
    「주석」 참조 열             1/10   ← 삼일 서식 전용. 있으면 보존만
    재무제표 표제(단일 셀 행)     1/10   ← 삼일 서식 전용. 보조 앵커

`_FS_TITLES`로 표제를 찾는 경로를 남겨 두되 **그것만 믿지 않는다**.

## 판정하지 않는다

이 모듈은 자르기만 한다 — 숫자를 해석하거나 점수를 매기지 않는다(v0.8.5).
"""
from __future__ import annotations

import re

__all__ = [
    "find_note_headings",
    "split_audit_report",
    "search_notes",
    "split_audit_opinion",
    "build_fs_account_index",
    "lookup_fs_account",
]

# 재무제표 표제. 자간이 벌어진 형태(「연 결 재 무 상 태 표」)로 오므로
# 공백을 지운 뒤 비교한다.
_FS_TITLES = (
    "재무상태표", "포괄손익계산서", "손익계산서", "자본변동표",
    "현금흐름표", "대차대조표", "이익잉여금처분계산서", "결손금처리계산서",
)

# 재무제표 표의 첫 칸. 9/10 문서에 있다.
_ACCOUNT_HEADS = ("과목", "계정과목", "과 목")

# 주석 뒤에 오는 꼬리 절. 주석 구간의 끝이다.
_TAIL_TITLES = (
    "외부감사실시내용", "내부회계관리제도감사보고서", "내부회계관리제도검토의견",
    "내부회계관리제도감사또는검토의견",
)

# 줄 시작 번호 + 마침표 + 곧바로 제목. 제목이 본문과 붙어 오는 서식이 흔해
# (「1. 일반사항주식회사 올품(이하 …」) 줄 끝을 요구하지 않는다.
# ⚠ 마침표 뒤가 숫자면 안 된다 — 「2. 1 재무제표 작성기준」은 주석 2가 아니라
#   주석 2의 하위 항목이다. `[^\d\s|]`가 그것을 막는다.
_NOTE_HEAD_RE = re.compile(r"^[ \t]*(\d{1,2})\.[ \t]?([^\d\s|][^\n]{0,70})")

# 주석 번호가 한 번에 이만큼 넘게 뛰면 본문 안의 번호일 확률이 높다.
_MAX_NOTE_GAP = 5


def _line_offsets(text: str) -> tuple[list[str], list[int]]:
    lines = text.split("\n")
    offs, pos = [], 0
    for ln in lines:
        offs.append(pos)
        pos += len(ln) + 1
    return lines, offs


def _cells(line: str) -> list[str] | None:
    """마크다운 표 행이면 셀 목록, 아니면 None."""
    s = line.strip()
    if len(s) < 2 or not (s.startswith("|") and s.endswith("|")):
        return None
    return [c.strip() for c in s[1:-1].split("|")]


def _flat(s: str) -> str:
    return re.sub(r"\s+", "", s or "")


def find_note_headings(text: str) -> list[dict]:
    """주석 번호 헤딩을 찾는다. `[{no, title, offset, end}]`.

    번호가 1부터 시작해 **커지기만 하면** 받아들인다(탐욕적 증가). 정확히
    1씩 늘기를 요구하면 한 번 놓쳤을 때 뒤가 통째로 사라진다 — 실측 올품
    연결 2024에서 「14. 생물자산」이 줄 시작이 아니라 본문 안에 있어, 엄격
    방식은 13개에서 멈추고 탐욕 방식은 22개를 얻었다.

    후보가 여럿 있으면 **가장 긴 구간**을 택한다. 문서 끝의 「외부감사
    실시내용」도 1부터 번호를 다시 매기므로, 짧은 쪽을 버려야 한다.

    표 행(`| 1. 매출 | 100 |`)은 제외한다 — 표 내용이지 제목이 아니다.
    """
    if not text:
        return []
    lines, offs = _line_offsets(text)

    runs: list[list[dict]] = []
    cur: list[dict] = []
    last = 0
    for i, ln in enumerate(lines):
        if ln.lstrip().startswith("|"):
            continue
        m = _NOTE_HEAD_RE.match(ln)
        if not m:
            continue
        no = int(m.group(1))
        item = {"no": no, "title": m.group(2).strip()[:60], "offset": offs[i]}
        # 이어지면 잇고, 아니면 **여기서 새 런을 연다**. 「1부터」를 요구하면
        # 문서 중간을 잘라 온 발췌를 못 읽고, 주석이 1이 아닌 번호로 시작하는
        # 서식도 놓친다. 어느 런이 진짜인지는 아래에서 길이로 고른다.
        if last < no <= last + _MAX_NOTE_GAP:
            cur.append(item)
        else:
            if cur:
                runs.append(cur)
            cur = [item]
        last = no
    if cur:
        runs.append(cur)
    # 번호 하나짜리는 주석 목록이 아니다(본문에 흩어진 번호일 뿐).
    runs = [r for r in runs if len(r) >= 2]
    if not runs:
        return []

    best = max(runs, key=len)
    # 구간 끝은 다음 주석의 시작. 마지막은 호출부가 꼬리로 자른다.
    for a, b in zip(best, best[1:]):
        a["end"] = b["offset"]
    best[-1]["end"] = len(text)
    return best


def _find_tail(lines: list[str], offs: list[int]) -> int | None:
    """주석 뒤 꼬리 절의 시작. 마지막 등장을 쓴다(앞쪽은 목차다)."""
    found = None
    for i, ln in enumerate(lines):
        c = _cells(ln)
        flat = _flat(c[0] if (c and len(c) == 1) else ln)
        if flat in _TAIL_TITLES:
            found = offs[i]
    return found


def _find_account_table(lines: list[str], offs: list[int]) -> int | None:
    """첫 「과목」 표 머리의 위치 — 재무제표 표의 서명(signature)이다."""
    for i, ln in enumerate(lines):
        c = _cells(ln)
        if not c or len(c) < 3:
            continue
        head = _flat(c[0])
        if head in _ACCOUNT_HEADS or (head.endswith("과목") and len(head) <= 8):
            return offs[i]
    return None


def _find_fs_title_row(lines: list[str], offs: list[int]) -> int | None:
    """재무제표 표제가 **단일 셀 표 행**으로 오는 서식(삼일 등)의 보조 앵커.

    목차 행은 3셀에 점선(`| ㆍ 연 결 재 무 상 태 표 | .......... | 5~6 |`)이라
    셀 수로 갈린다.
    """
    for i, ln in enumerate(lines):
        c = _cells(ln)
        if not c or len(c) != 1:
            continue
        flat = _flat(c[0])
        if 4 <= len(flat) <= 20 and any(flat.endswith(t) for t in _FS_TITLES):
            return offs[i]
    return None


def split_audit_report(text: str) -> dict:
    """감사보고서 마크다운을 재무제표 / 주석 / 꼬리로 가른다.

    Returns:
        {
          "notes": [{no, title, offset, end}],   # 주석 헤딩
          "notes_start": int | None,
          "notes_end": int,
          "fs_start": int,       # 재무제표 구간 시작
          "fs_basis": str,       # 무엇을 앵커로 썼는지(사용자가 검증할 수 있게)
          "tail_start": int | None,
          "length": int,
        }

    `fs_basis`는 「과목표」·「재무제표표제」·「문서앞부터」 중 하나다. 무엇으로
    잘랐는지 말하지 않으면 사용자가 결과를 검증할 수 없다.
    """
    lines, offs = _line_offsets(text or "")
    notes = find_note_headings(text or "")
    tail = _find_tail(lines, offs)

    notes_start = notes[0]["offset"] if notes else None
    notes_end = len(text or "")
    if notes:
        if tail is not None and tail > notes[0]["offset"]:
            notes_end = tail
        notes[-1]["end"] = min(notes[-1]["end"], notes_end)

    acct = _find_account_table(lines, offs)
    title_row = _find_fs_title_row(lines, offs)
    limit = notes_start if notes_start is not None else notes_end

    fs_start, basis = 0, "문서앞부터"
    # 주석 시작보다 앞에 있는 앵커만 쓴다 — 뒤에 있는 것은 주석 본문의 표다.
    if title_row is not None and title_row < limit:
        fs_start, basis = title_row, "재무제표표제"
    elif acct is not None and acct < limit:
        fs_start, basis = acct, "과목표"

    return {
        "notes": notes,
        "notes_start": notes_start,
        "notes_end": notes_end,
        "fs_start": fs_start,
        "fs_basis": basis,
        "tail_start": tail,
        "length": len(text or ""),
    }


def _term_variants(term: str) -> list[str]:
    """`"가|나"` → `["가", "나"]`. 빈 조각은 버린다.

    ⚠ 세로줄은 **낱말 구분자이지 정규식이 아니다**. 사용자가 넣은 문자열을
    그대로 찾는다 — 정규식으로 해석하면 괄호·별표가 든 회계 용어
    (「(주1)」·「손상(*)」)에서 터진다.
    """
    return [p.strip() for p in (term or "").split("|") if p.strip()]


def _fold_spaces(text: str) -> tuple[str, list[int]]:
    """공백을 걷어낸 문자열과 **원문 오프셋 역매핑**을 함께 돌려준다.

    `("가 나", [0, 2])` — 접힌 문자열의 i번째 글자는 원문 `idx[i]`에 있다.
    이 역매핑이 있어야 적중 위치·발췌를 **원문 좌표로** 되돌릴 수 있다.
    """
    buf: list[str] = []
    idx: list[int] = []
    for i, ch in enumerate(text):
        if ch.isspace():
            continue
        buf.append(ch)
        idx.append(i)
    return "".join(buf), idx


def search_notes(
    text: str,
    terms: list[str],
    mode: str = "all",
    context_chars: int = 600,
) -> dict:
    """보고서 **한 건** 안에서 주석을 낱말로 찾는다.

    ⚠ **전 회사를 가로지르는 검색이 아니다.** 그러려면 사전 색인 DB가 있어야
    한다. 이 함수는 넘겨받은 원문 하나만 훑는다.

    **띄어쓰기는 무시하고 찾는다**(2026-09-13) — 한국 공시는 같은 말을 붙여도
    쓰고 띄어도 써서 한 표기만 찾으면 놓친다. 15개사 사업보고서 원문
    7,641,985자 실측:

        '매입채무및기타채무'  정확 일치 8곳 → 공백 무시 **15곳**
        '매출채권및기타채권'  정확 일치 8곳 → 공백 무시 **13곳**
        '판매비와 관리비'     정확 일치 10곳 → 공백 무시 **15곳**

    절반 가까이 놓치고 있었고, 이마트의 「매입채무 및 기타 채무」처럼
    **띄어쓰기가 두 군데** 다른 것도 있어 `|`로 손수 나열하기 어렵다.

    ⚠ **오탐 위험을 따로 쟀다.** 「대여금」이 원문 "대여 금액"에 걸리는 부류를
    겨냥해 위험 검색어 27개 × 15문서를 훑었더니 **공백을 건너뛰어야만 걸리는
    사례가 0건**이었다(정확 일치가 이미 있거나 357건, 아예 없거나 48건).
    오염을 만들 법한 표현은 3건 실재하지만(진원생명과학 「대여 금액/금융」 2 ·
    두산 「차입 금액/금리」 1) **그 문서에는 「대여금」·「차입금」이 이미 정확히
    있다** — 즉 공백 무시는 **매치가 없던 주석에 매치를 만들지 않는다**.
    이미 걸리는 주석에 발췌를 하나 더할 뿐이다.

    ⚠ 그래서 `hits[].matched`에 **원문에 실제로 적힌 표기**를 담는다 —
    사용자가 「매출채권및기타채권」으로 찾았는데 원문이 「매출채권 및
    기타채권」이면 그 사실이 보여야 한다.

    `terms`의 각 원소는 세로줄(`|`)로 OR을 넣을 수 있다. 띄어쓰기 변형은
    이제 자동이라 그것 때문에 나열할 필요는 없지만, **뜻이 다른 표기**를
    묶을 때는 여전히 쓴다(「판매후리스|세일앤리스백」).

    `mode="all"`이면 **모든 원소**가 들어 있는 주석만, `"any"`면 하나라도
    들어 있는 주석을 돌려준다(원소 안의 세로줄은 언제나 OR이다).

    Returns:
        {"notes": [{no, title, offset, end,
                    hits: [{term, matched, offset, excerpt}]}],
         "scanned_notes": int, "scope": str, "total_hits": int}

        `term`은 사용자가 넣은 낱말, `matched`는 원문 표기다. 한 자리를
        여러 변형이 동시에 맞혀도 **한 번만** 보고한다.

        주석 헤딩을 못 찾은 문서는 문서 전체를 한 덩어리로 훑고 `scope`에
        그 사실을 적는다 — 조용히 빈손을 돌려주면 「그런 말이 없다」로 읽힌다.
    """
    text = text or ""
    groups = [v for v in (_term_variants(t) for t in (terms or [])) if v]
    notes = find_note_headings(text)
    spans = [dict(n) for n in notes]
    scope = "주석"
    if not spans:
        scope = "문서 전체"
        spans = [{"no": 0, "title": "(주석 헤딩을 찾지 못함)",
                  "offset": 0, "end": len(text)}]

    if not groups:
        return {"notes": [], "scanned_notes": len(notes), "scope": scope,
                "total_hits": 0}

    want_all = mode != "any"
    out: list[dict] = []
    for sp in spans:
        body = text[sp["offset"]:sp["end"]]
        folded, fold_idx = _fold_spaces(body)
        matched, hits = 0, []
        seen: set[int] = set()
        for variants in groups:
            found_here = False
            for v in variants:
                nv = re.sub(r"\s+", "", v)
                if not nv:
                    continue
                start = folded.find(nv)
                while start != -1:
                    o_s = fold_idx[start]
                    o_e = fold_idx[start + len(nv) - 1] + 1
                    if o_s not in seen:     # 같은 자리를 변형끼리 중복 보고하지 않는다
                        seen.add(o_s)
                        lo = max(0, o_s - context_chars)
                        hi = min(len(body), o_e + context_chars)
                        hits.append({
                            "term": v,
                            # 원문에 실제로 적힌 표기 — 띄어쓰기가 다르면
                            # 사용자가 그 사실을 볼 수 있어야 한다.
                            "matched": body[o_s:o_e],
                            "offset": sp["offset"] + o_s,
                            "excerpt": body[lo:hi].strip(),
                        })
                    found_here = True
                    start = folded.find(nv, start + len(nv))
            if found_here:
                matched += 1
        if not hits:
            continue
        if want_all and matched < len(groups):
            continue
        hits.sort(key=lambda h: h["offset"])
        item = dict(sp)
        item["hits"] = hits
        out.append(item)

    return {
        "notes": out,
        "scanned_notes": len(notes),
        "scope": scope,
        "total_hits": sum(len(n["hits"]) for n in out),
    }


# ── 감사의견 절 (v1.25.0) ─────────────────────────────────────────────
#
# ⚠ **「계속기업」은 상용문구에 항상 나온다.** 감사보고서의 「재무제표에 대한
#   경영진과 지배기구의 책임」·「감사인의 책임」 단락이 계속기업 존속능력
#   평가를 정형 문구로 언급한다. 낱말로 세면 모든 회사가 걸린다 — 실측
#   CSA 코스믹은 문서 전체 7건인데 **의견 블록 안에는 0건**이고, 올품은 6건
#   중 0건이다. 그래서 **경영진 책임 단락 앞**을 의견 블록으로 자른다.
#
# ⚠ **의견 제목이 「감사의견」이 아닐 수 있다.** 제이스코홀딩스 2025는
#   「의견거절」·「의견거절근거」이고, 계속기업 불확실성이 **그 근거 단락
#   안**에 있다(별도 절 제목 없음). 제목만 찾으면 이 회사를 놓친다.
_OPINION_HEADS = ("감사의견", "한정의견", "부적정의견", "의견거절", "검토의견")
_BASIS_SUFFIX = "근거"
# 의견 블록의 끝 — 여기서부터는 정형 문구다.
_OPINION_BLOCK_END = (
    "재무제표에 대한 경영진과 지배기구의 책임",
    "연결재무제표에 대한 경영진과 지배기구의 책임",
    "재무제표에 대한 경영진과 지배기구의책임",
    "재무제표감사에 대한 감사인의 책임",
    "연결재무제표감사에 대한 감사인의 책임",
)
_OPINION_START = "독립된 감사인의 감사보고서"
_GC_HEADS = ("계속기업 관련 중요한 불확실성", "계속기업관련 중요한 불확실성",
             "계속기업 가정의 불확실성")
_EMPHASIS_HEADS = ("강조사항",)
_KAM_HEADS = ("핵심감사사항",)
_OTHER_HEADS = ("기타사항", "그 밖의 사항")


def _folded(words: tuple) -> frozenset:
    """제목 상수를 **공백 접은 형태**로 바꾼다.

    ⚠ 원문 제목은 「연결재무제표에 대한 경영진과 지배기구의 책임」처럼 띄어
    쓰는데 비교는 `_flat`(공백 제거)로 한다. 상수를 그대로 두면 한 건도 안
    맞는다(실제로 처음에 그랬다 — 의견 블록이 문서 전체가 됐다).
    """
    return frozenset(_flat(w) for w in words)


_OPINION_HEADS_F = _folded(_OPINION_HEADS)
_OPINION_BLOCK_END_F = _folded(_OPINION_BLOCK_END)
_OPINION_START_F = _folded((_OPINION_START,))
_GC_HEADS_F = _folded(_GC_HEADS)
_EMPHASIS_HEADS_F = _folded(_EMPHASIS_HEADS)
_KAM_HEADS_F = _folded(_KAM_HEADS)
_OTHER_HEADS_F = _folded(_OTHER_HEADS)


def _is_heading(line: str, wanted) -> str:
    """줄이 절 제목으로 **시작**하면 그 제목을 돌려준다.

    ⚠ 줄 **전체**가 제목일 것을 요구하면 안 된다 — 제목이 본문과 붙어 오는
    서식이 있다(실측 아틀라스링크·한농화성):

        재무제표에 대한 경영진과 지배기구의 책임경영진은 한국채택국제회계기준에 …
        감사의견우리는 주식회사 …의 재무제표를 감사하였습니다.

    그러면 의견 블록의 **끝을 못 찾아** 상용문구가 블록 안에 들어오고
    계속기업이 오탐된다(주석 제목에서 이미 겪은 것과 같은 현상).

    ⚠ **긴 제목을 먼저 본다** — 「감사의견근거」가 「감사의견」으로 시작한다.

    표 행(`| … |`)은 목차이므로 제외한다 — 「독립된 감사인의 감사보고서」는
    목차에도 나오고 본문에도 나온다(실측 offset 244 vs 841).
    """
    if line.lstrip().startswith("|"):
        return ""
    flat = _flat(line)
    if not flat:
        return ""
    for w in sorted(wanted, key=len, reverse=True):
        if flat.startswith(w):
            return w
    return ""


def _section(text: str, start: int, ends: list[int]) -> str:
    later = [e for e in ends if e > start]
    return text[start:min(later)].strip() if later else text[start:].strip()


def split_audit_opinion(text: str) -> dict:
    """감사보고서 원문에서 감사의견 관련 절을 잘라 낸다 (순수 함수).

    Returns:
        {
          "opinion_block_start": int, "opinion_block_end": int,
          "opinion":       {present, heading, text},   # 감사의견 / 의견거절 …
          "basis":         {present, heading, text},   # …근거
          "going_concern": {present, own_section, found_in, text},
          "emphasis":      {present, heading, text},   # 강조사항
          "kam":           {present, heading, text},   # 핵심감사사항
          "other_matters": {present, heading, text},   # 기타사항
        }

    문장은 **원문 그대로** 담는다 — 요약하거나 바꿔 쓰지 않는다. 기사에 옮길 때
    감사인이 실제로 쓴 문장이 필요하다. 판정·점수·등급은 붙이지 않는다.
    """
    empty = {"present": False, "heading": "", "text": ""}
    out = {
        "opinion_block_start": 0, "opinion_block_end": 0,
        "opinion": dict(empty), "basis": dict(empty),
        "going_concern": {"present": False, "own_section": False,
                          "found_in": "", "text": ""},
        "emphasis": dict(empty), "kam": dict(empty), "other_matters": dict(empty),
    }
    if not text:
        return out
    lines, offs = _line_offsets(text)

    # ① 의견 블록의 시작 — 본문의 「독립된 감사인의 감사보고서」(목차 아님)
    start = 0
    for i, ln in enumerate(lines):
        if _is_heading(ln, _OPINION_START_F):
            start = offs[i]
            break
    # ② 끝 — 정형 문구 단락의 첫 등장
    end = len(text)
    for i, ln in enumerate(lines):
        if offs[i] <= start:
            continue
        if _is_heading(ln, _OPINION_BLOCK_END_F):
            end = offs[i]
            break
    if end <= start:
        end = len(text)
    out["opinion_block_start"], out["opinion_block_end"] = start, end

    # ③ 블록 안의 절 제목을 모은다
    # 절 제목 후보. ⚠ 제목이 본문과 붙어 오므로 **접두 일치**로 찾고,
    #   「감사의견근거」가 「감사의견」으로 시작하니 **긴 것을 먼저** 본다.
    _basis_f = frozenset(o + _BASIS_SUFFIX for o in _OPINION_HEADS_F)
    _all_heads = (_basis_f | _OPINION_HEADS_F | _GC_HEADS_F
                  | _EMPHASIS_HEADS_F | _KAM_HEADS_F | _OTHER_HEADS_F)
    heads: list[tuple[int, str]] = []
    for i, ln in enumerate(lines):
        if not (start <= offs[i] < end):
            continue
        hit = _is_heading(ln, _all_heads)
        if not hit:
            continue
        # ⚠ 같은 제목이 **연달아** 오는 서식이 있다(실측 CSA 코스믹:
        #   「핵심감사사항」 다음 줄이 「핵심감사사항은 우리의 전문가적 …」).
        #   접두 일치라 둘 다 걸리는데, 그대로 두면 첫 절이 **6자로 잘린다**.
        #   연속 중복은 앞의 것만 남긴다.
        if heads and heads[-1][1] == hit:
            continue
        heads.append((offs[i], hit))
    bounds = [o for o, _ in heads] + [end]

    def _take(names, suffix: bool = False) -> dict:
        for off, flat in heads:
            hit = flat in names if not suffix else (
                flat.endswith(_BASIS_SUFFIX)
                and flat[:-len(_BASIS_SUFFIX)] in names)
            if hit:
                body = _section(text, off, bounds)
                # 제목이 본문과 붙어 있으면(`감사의견우리는 …`) 제목 글자만
                # 떼어 낸다. 공백이 섞인 표기도 있어 글자 수로 자르지 않고
                # 접두를 한 번 더 확인한다.
                stripped = body.lstrip()
                cut = len(body) - len(stripped)
                head_len = 0
                probe = _flat(stripped[:len(flat) + 12])
                if probe.startswith(flat):
                    seen = 0
                    for idx, ch in enumerate(stripped):
                        if not ch.isspace():
                            seen += 1
                        if seen == len(flat):
                            head_len = idx + 1
                            break
                out_text = stripped[head_len:].strip() if head_len else stripped
                return {"present": True, "heading": flat,
                        "text": out_text or body.strip()}
        return dict(empty)

    out["basis"] = _take(_OPINION_HEADS_F, suffix=True)
    out["opinion"] = _take(_OPINION_HEADS_F)
    out["emphasis"] = _take(_EMPHASIS_HEADS_F)
    out["kam"] = _take(_KAM_HEADS_F)
    out["other_matters"] = _take(_OTHER_HEADS_F)

    # ④ 계속기업 — 절 제목이 있으면 그 절, 없으면 **의견 블록 안**에서 찾는다.
    #    블록 밖(경영진·감사인 책임)에만 있으면 상용문구이므로 세지 않는다.
    gc = _take(_GC_HEADS_F)
    if gc["present"]:
        out["going_concern"] = {"present": True, "own_section": True,
                                "found_in": gc["heading"], "text": gc["text"]}
    else:
        block = text[start:end]
        pos = block.find("계속기업")
        if pos >= 0:
            where = ""
            for off, flat in heads:
                if off - start <= pos:
                    where = flat
            para = _paragraph_around(block, pos)
            out["going_concern"] = {"present": True, "own_section": False,
                                    "found_in": where, "text": para}
    return out


def _paragraph_around(text: str, pos: int) -> str:
    """`pos`가 든 문단을 원문 그대로 돌려준다(빈 줄 경계)."""
    lo = text.rfind("\n\n", 0, pos)
    lo = 0 if lo < 0 else lo + 2
    hi = text.find("\n\n", pos)
    hi = len(text) if hi < 0 else hi
    return text[lo:hi].strip()


# ── 원문 계정명 대조 (v1.26.0) ─────────────────────────────────────────
#
# `fnlttSinglAcntAll`은 회사가 제출한 XBRL의 **표준 태그**에 맞춘 계정명을 준다.
# 회사가 어느 태그에 실었느냐에 따라 원문과 어긋난다 — 실측 CSA 코스믹 2025에서
# API의 「파생상품평가손익 -8,969,358」은 원문 연결포괄손익계산서의
# 「지분법자본변동 (8,969,358)」이고(블루원(주) 관계기업투자에서 나온 값),
# 「파생상품평가손익」은 **문서 전체에 0건**이다.
#
# 규모(2026-09-12 · 8개사 · API 행 1,444개): 대조 성공 76.9%(같음 50.6% ·
# **다름 26.4%**) · 모호 9.1% · 못찾음 14.0%. 네 개 중 하나가 다르다.
#
# ⚠ 숫자는 손대지 않는다. 여기서 바꾸는 것은 **이름뿐**이다.

# 표 위의 단위 표기. 긴 것부터 봐야 「백만원」이 「원」에 먼저 걸리지 않는다.
_FS_UNITS = (("십억원", 1_000_000_000), ("억원", 100_000_000),
             ("백만원", 1_000_000), ("천원", 1_000), ("원", 1))
_FS_UNIT_RE = re.compile(r"단위\s*[:：]\s*([가-힣]+)")

# 재무제표 표제 → sj_div. 「손익계산서」는 포괄손익계산서의 접미이기도 해
# 순서대로 본다(긴 것 먼저).
_FS_DIV_KEYS = (
    ("CIS", ("포괄손익계산서",)),
    ("SCE", ("자본변동표",)),
    ("CF", ("현금흐름표",)),
    ("BS", ("재무상태표", "대차대조표")),
    ("IS", ("손익계산서",)),
)
# 손익계산서를 따로 내지 않는 회사가 많다 — 서로 폴백한다.
_FS_DIV_FALLBACK = {"IS": "CIS", "CIS": "IS"}

# 번호 접두. ⚠ 로마숫자를 **라틴 대문자**로 적는 회사가 많다(「I. 유동자산」 —
# U+2160이 아니라 ASCII I). 그걸 빼면 실측 「다름」이 부풀려진다.
_FS_BULLET_RE = re.compile(r"^[\-–—▶▷►○●■□*]+")
_FS_ORD_RE = re.compile(
    r"^\s*(?:[ⅠⅡⅢⅣⅤⅥⅦⅧⅨⅩ]+|[IVX]{1,4}|\d{1,2}|[가나다라마바사아자차]|[①-⑳])\s*[.)]\s*")
# 날짜처럼 생긴 것은 계정명이 아니다 — 실측 삼성전자 자본총계 402조가
# 자본변동표의 「2025.12.31(당기말)」 행에 물렸다.
# ⚠ 구분자 뒤에 **공백이 오는 표기**를 함께 본다 — 실측 두산 자본변동표는
#   「2025. 1. 1.(당기초)」라 붙여 쓴 꼴만 보던 옛 가드를 통과했고, API 「기초」가
#   그 날짜 행에 물려 계정명이 시점 표시로 바뀌었다.
#   한글 표기도 실재한다 — 실측 STX 자본변동표 「2025년 1월 1일(당기초)」 32건
#   (8개사 인덱스 2,659행 기준).
_FS_DATEISH_RE = re.compile(
    r"\d{4}\s*[.\-/]\s*\d{1,2}\s*[.\-/]\s*\d{1,2}"
    r"|\d{4}\s*년\s*\d{1,2}\s*월")
_FS_HANGUL_RE = re.compile(r"[가-힣A-Za-z]")


def _fs_norm(name: str) -> str:
    """계정명 비교용 정규화 — 공백·번호 접두·불릿·괄호·가운뎃점을 접는다.

    ⚠ 접는 것은 **비교할 때뿐**이고 화면에는 원문 표기를 그대로 낸다.
    """
    t = re.sub(r"\s+", "", name or "")
    prev = None
    while prev != t:
        prev = t
        t = _FS_ORD_RE.sub("", t)
        # 들여쓰기 불릿은 계정명의 일부가 아니다 — 실측 두산 자본변동표가
        # 하위 항목을 「- 당기순이익」으로 적어 「다름」이 부풀었다.
        t = _FS_BULLET_RE.sub("", t)
    for ch in "()（）·ㆍ,":
        t = t.replace(ch, "")
    return t


def _fs_amounts(cells: list[str]) -> list[int]:
    """셀에서 금액을 읽는다. **괄호는 음수**다."""
    out = []
    for c in cells:
        t = (c or "").strip()
        neg = t.startswith("(") and t.endswith(")")
        if neg:
            t = t[1:-1]
        t = t.replace(",", "").replace("원", "").strip()
        if re.fullmatch(r"-?\d+", t) and len(t.lstrip("-")) >= 2:
            v = int(t)
            out.append(-v if neg else v)
    return out


def _fs_is_account_name(name: str) -> bool:
    """계정명으로 볼 만한가 — 날짜·숫자 덩어리는 뺀다."""
    t = (name or "").strip()
    if not t or len(t) > 60:
        return False
    if _FS_DATEISH_RE.search(t):
        return False
    return bool(_FS_HANGUL_RE.search(t))


def build_fs_account_index(fs_text: str) -> dict:
    """감사보고서 **재무제표 구간**에서 {재무제표: {금액: 계정명들}}을 만든다.

    Returns:
        `{"unit": (표기, 배수), "by_div": {sj_div: {amount: [name, ...]}}}`

    ⚠ **재무제표별로** 나눈다. 전역으로 모으면 엉뚱한 표의 행에 붙고 모호가
    늘어난다(실측 CSA 코스믹 모호 16 → 41).
    """
    text = fs_text or ""
    unit_name, unit_mul = "원", 1
    m = _FS_UNIT_RE.search(text[:5000])
    if m:
        for nm, mul in _FS_UNITS:
            if m.group(1).endswith(nm):
                unit_name, unit_mul = nm, mul
                break

    lines = text.split("\n")
    # 표제 행(단일 셀)로 구간을 가른다
    marks: list[tuple[int, str]] = []
    for i, ln in enumerate(lines):
        c = _cells(ln)
        if not c or len(c) != 1:
            continue
        flat = _flat(c[0])
        if len(flat) > 24:
            continue
        for div, keys in _FS_DIV_KEYS:
            if any(flat.endswith(k) for k in keys):
                marks.append((i, div))
                break

    by_div: dict[str, dict[int, list[str]]] = {}
    for idx, (start_i, div) in enumerate(marks):
        end_i = marks[idx + 1][0] if idx + 1 < len(marks) else len(lines)
        bucket = by_div.setdefault(div, {})
        for ln in lines[start_i:end_i]:
            c = _cells(ln)
            if not c or len(c) < 2:
                continue
            name = " ".join((c[0] or "").split())
            if not _fs_is_account_name(name):
                continue
            for v in _fs_amounts(c[1:]):
                names = bucket.setdefault(v * unit_mul, [])
                if name not in names:
                    names.append(name)
    return {"unit": (unit_name, unit_mul), "by_div": by_div}


def lookup_fs_account(index: dict, sj_div: str, amount: int,
                      api_name: str) -> dict:
    """금액으로 원문 계정명을 찾는다.

    Returns:
        `{"name": 원문 계정명 or "", "status": same|diff|ambiguous|missing,
          "candidates": [후보들]}`

    ⚠ **금액 0은 찾지 않는다** — 표에 흔해 아무 데나 물린다.
    ⚠ 같은 금액에 **정규화 후에도 다른 이름이 둘 이상**이면 붙이지 않고
      후보만 돌려준다. 틀린 이름을 조용히 붙이는 것이 그냥 두는 것보다 나쁘다.
    """
    miss = {"name": "", "status": "missing", "candidates": []}
    if not amount:
        return miss
    by_div = (index or {}).get("by_div") or {}
    # ⚠ 폴백은 **금액 단위**로 한다. 맵 단위로 하면 CIS 맵이 비어 있지 않은
    #   순간 IS 표를 아예 안 본다 — 실측 CSA 코스믹은 매출원가·판매비와관리비가
    #   손익계산서 쪽에 있어 「대조 실패」가 10/26까지 올라갔다.
    # ⚠ 부호 규약이 서로 다르다. 원문 손익계산서는 비용을 **괄호(차감 표시)**로
    #   적고 API는 매출원가·판관비·금융비용을 **양수**로 준다 — 같은 사실인데
    #   부호를 그대로 대조하면 원문에 버젓이 있는 줄을 「대조 실패」라 적는다
    #   (실측 CSA 코스믹 26행 중 확인 10행 → 세 줄이 이 이유로 샜다).
    #   **정확 일치가 먼저**이고, 그 부호로 못 찾을 때만 뒤집어 본다 — 같은
    #   절댓값의 +행과 -행이 서로 다른 계정일 수 있다.
    found: list[str] = []
    for want in (amount, -amount):
        for div in (sj_div, _FS_DIV_FALLBACK.get(sj_div)):
            if not div:
                continue
            got = (by_div.get(div) or {}).get(want)
            if got:
                found = got
                break
        if found:
            break
    if not found:
        return miss
    if len({_fs_norm(n) for n in found}) > 1:
        return {"name": "", "status": "ambiguous", "candidates": list(found)}
    # 정규화가 같은 것들 중 **가장 짧은 표기**를 대표로 — 번호 접두가 붙은
    # 것과 안 붙은 것이 함께 있으면 짧은 쪽이 읽기 쉽다.
    best = sorted(found, key=len)[0]
    same = _fs_norm(best) == _fs_norm(api_name)
    return {"name": best, "status": "same" if same else "diff",
            "candidates": list(found)}
