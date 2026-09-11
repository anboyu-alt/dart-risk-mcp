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


def search_notes(
    text: str,
    terms: list[str],
    mode: str = "all",
    context_chars: int = 600,
) -> dict:
    """보고서 **한 건** 안에서 주석을 낱말로 찾는다.

    ⚠ **전 회사를 가로지르는 검색이 아니다.** 그러려면 사전 색인 DB가 있어야
    한다. 이 함수는 넘겨받은 원문 하나만 훑는다.

    `terms`의 각 원소는 세로줄(`|`)로 OR을 넣을 수 있다 — 한국 공시는 같은
    말을 붙여도 쓰고 띄어도 써서(「영업권손상차손」 ↔ 「영업권 손상차손」)
    한 표기만 찾으면 놓친다.

    `mode="all"`이면 **모든 원소**가 들어 있는 주석만, `"any"`면 하나라도
    들어 있는 주석을 돌려준다(원소 안의 세로줄은 언제나 OR이다).

    Returns:
        {"notes": [{no, title, offset, end, hits: [{term, offset, excerpt}]}],
         "scanned_notes": int, "scope": str, "total_hits": int}

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
        matched, hits = 0, []
        for variants in groups:
            found_here = False
            for v in variants:
                start = body.find(v)
                while start != -1:
                    lo = max(0, start - context_chars)
                    hi = min(len(body), start + len(v) + context_chars)
                    hits.append({
                        "term": v,
                        "offset": sp["offset"] + start,
                        "excerpt": body[lo:hi].strip(),
                    })
                    found_here = True
                    start = body.find(v, start + len(v))
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
    """줄 전체가 절 제목이면 그 제목을 돌려준다.

    표 행(`| … |`)은 목차이므로 제외한다 — 「독립된 감사인의 감사보고서」는
    목차에도 나오고 본문에도 나온다(실측 offset 244 vs 841).
    """
    if line.lstrip().startswith("|"):
        return ""
    flat = _flat(line)
    return flat if flat in wanted else ""


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
    heads: list[tuple[int, str]] = []
    for i, ln in enumerate(lines):
        if not (start <= offs[i] < end):
            continue
        flat = _flat(ln)
        if ln.lstrip().startswith("|") or not flat or len(flat) > 24:
            continue
        if (flat in _OPINION_HEADS_F or flat in _GC_HEADS_F
                or flat in _EMPHASIS_HEADS_F or flat in _KAM_HEADS_F
                or flat in _OTHER_HEADS_F
                or (flat.endswith(_BASIS_SUFFIX)
                    and flat[:-len(_BASIS_SUFFIX)] in _OPINION_HEADS_F)):
            heads.append((offs[i], flat))
    bounds = [o for o, _ in heads] + [end]

    def _take(names, suffix: bool = False) -> dict:
        for off, flat in heads:
            hit = flat in names if not suffix else (
                flat.endswith(_BASIS_SUFFIX)
                and flat[:-len(_BASIS_SUFFIX)] in names)
            if hit:
                body = _section(text, off, bounds)
                return {"present": True, "heading": flat,
                        "text": body[len(flat):].strip() or body}
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
