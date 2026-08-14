# -*- coding: utf-8 -*-
"""신호 한정층 — 공시 제목 구조 파싱 + 신호 표시 계층 판정.

match_signals(signals.py)는 제목에 키워드가 들어있는지만 본다. 그래서
부정("해제"·"철회")·방향(발행/취득)·주체(회사/제3자)·수식어(제3자배정/일반공모)를
구분할 수단이 없고, 정상 공시가 위험 신호로 잡힌다.

이 모듈은 match_signals '이후'에 동작한다. 신호를 지우지 않고 tier만 붙인다:
- observed:   회사가 낸, 해당 사건 자체의 공시
- procedural: 제3자 제출 / 사후 보고 / 철회·해제 / 해명 / 정정

순수 함수만 둔다 — 네트워크 호출 없음.
"""
import re
from dataclasses import dataclass

from .dart_client import _fold_corp_name
from .signals import AMBIGUOUS_SIGNAL_KEYS

# 본체 어미 후보. 긴 것이 먼저 매칭돼야 하므로 _tail_of가 길이순으로 검사한다.
# 'ㆍ'(U+318D)는 DART 실제 표기라 그대로 둔다.
TAILS: tuple[str, ...] = (
    "해제ㆍ취소등", "결과보고서", "계약체결", "보고서", "결정", "해제",
    "취소", "철회", "해지", "중단", "해명", "신청", "확정", "변경",
    "발생", "요구", "취득", "매도",
)

_TAG_RE = re.compile(r"^\[([^\]]*)\]\s*")
_PAREN_RE = re.compile(r"\(([^()]*)\)")
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class ParsedName:
    """공시 제목을 구조 조각으로 나눈 결과.

    tags:      대괄호 접두 태그 — ("첨부정정",)
    body:      태그·괄호를 뺀 본체 (공백 제거)
    subtitles: 괄호 내용 (공백 제거)
    tail:      본체의 마지막 어미 토큰. 본체가 '~보고서' 껍데기이고 괄호가
               어미를 가지면 괄호 쪽 어미를 쓴다.
    compact:   태그를 뺀 전체 문자열 (공백 제거) — 부분 검사용
    """

    tags: tuple[str, ...]
    body: str
    subtitles: tuple[str, ...]
    tail: str
    compact: str


def _tail_of(text: str) -> str:
    """text가 TAILS 중 하나로 끝나면 그 어미를 반환. 긴 것 우선."""
    for cand in sorted(TAILS, key=len, reverse=True):
        if text.endswith(cand):
            return cand
    return ""


def parse_report_name(report_nm: str) -> ParsedName:
    """공시 제목을 {태그, 본체, 괄호부제, 어미}로 나눈다.

    공백은 전부 제거한다 — DART 표기가 '자회사의 주요경영사항'과
    '종속회사의주요경영사항'처럼 띄어쓰기가 섞여 오기 때문이다.
    """
    rest = (report_nm or "").strip()
    tags: list[str] = []
    while True:
        m = _TAG_RE.match(rest)
        if not m:
            break
        tags.append(m.group(1).strip())
        rest = rest[m.end():]

    compact = _WS_RE.sub("", rest)
    subtitles = tuple(s for s in _PAREN_RE.findall(compact) if s)
    body = _PAREN_RE.sub("", compact)

    tail = _tail_of(body)
    # '주요사항보고서(자기주식취득결정)'처럼 본체가 껍데기면 괄호 쪽을 본다.
    if tail == "보고서" and subtitles:
        inner = _tail_of(subtitles[-1])
        tail = inner or tail

    return ParsedName(
        tags=tuple(tags),
        body=body,
        subtitles=subtitles,
        tail=tail,
        compact=compact,
    )


TIER_OBSERVED = "observed"
TIER_PROCEDURAL = "procedural"

# R1b — 제3자가 회사에 대해 제출하는 보고서. 본체가 이것으로 시작하면
# 회사의 행위가 아니다(제출인은 국민연금·블랙록·개인 임원 등).
THIRD_PARTY_TITLES: tuple[str, ...] = (
    "주식등의대량보유상황보고서",
    "임원ㆍ주요주주특정증권등소유상황보고서",
    "최대주주등소유주식변동신고서",
)

# R2 — 이미 실행됐거나 되돌린 국면. 어미가 이것이면 새 사건이 아니다.
PHASE_TAILS: tuple[str, ...] = (
    "결과보고서", "해제ㆍ취소등", "해제", "취소", "철회", "해지", "중단",
)

# R3 — 공시 주체가 이 회사가 아닌 경우. 공백 제거 후 비교한다.
SUBSIDIARY_SUBTITLES: tuple[str, ...] = (
    "종속회사의주요경영사항",
    "자회사의주요경영사항",
    "관계회사의주요경영사항",
)
RELATED_PARTY_PREFIX = "특수관계인의"

# R5 — 기존 공시의 정정·후속. '[정정명령부과]'는 규제기관 조치라 여기 없다.
AMENDMENT_TAGS: tuple[str, ...] = (
    "기재정정", "첨부정정", "첨부추가", "정정", "발행조건확정", "연장결정",
)


def _is_amendment_tag(tag: str) -> bool:
    """R5 태그 판정 — 완전 일치 또는 '정정'으로 끝남.

    '정정명령부과'는 '정정'으로 시작할 뿐 끝나지 않으므로 걸리지 않는다.
    """
    t = (tag or "").strip()
    return t in AMENDMENT_TAGS or t.endswith("정정")


def is_false_amendment(parsed: ParsedName) -> bool:
    """_AMENDMENT_RE에는 걸리지만 실제 정정공시가 아닌 경우.

    match_signals는 '[정정명령부과]증권신고서'를 정정공시로 오판해 신호를
    통째로 삭제한다. 호출부는 이 함수가 True일 때만 접두를 벗겨 재매칭한다 —
    진짜 정정공시([기재정정] 등)의 기존 동작은 바뀌지 않는다.
    """
    if not parsed.tags:
        return False
    return not any(_is_amendment_tag(t) for t in parsed.tags)


@dataclass(frozen=True)
class Qualified:
    """한정된 신호 하나.

    key/label: 표시용. label은 보정될 수 있다(Task 4).
    tier:      TIER_OBSERVED | TIER_PROCEDURAL
    reason:    강등 사유 (사실 문장). observed면 "".
    note:      사실 주석 (방향 불일치 등). 없으면 "".
    """

    key: str
    label: str
    tier: str
    reason: str
    note: str


def _demotion_reason(parsed: ParsedName, filing: "dict | None") -> str:
    """강등 사유를 반환. 강등 대상이 아니면 빈 문자열.

    평가 순서 R1 → R1b → R5 → R2 → R3 → R4, 첫 매칭에서 멈춘다.
    R5를 앞에 두는 이유: 정정본은 내용과 무관하게 정정이다.
    """
    filing = filing or {}

    # R1 — 제출인이 회사가 아님
    filer = (filing.get("flr_nm") or "").strip()
    corp = (filing.get("corp_name") or "").strip()
    if filer and corp and _fold_corp_name(filer) != _fold_corp_name(corp):
        return f"회사가 낸 공시가 아닙니다 (제출인: {filer})"

    # R1b — 지분 보유·변동 신고서. filer 유무와 무관하게 평가한다.
    #
    # 라이브 실측(2026-08-14, 삼성전자 20260410~0425): '최대주주등소유주식변동
    # 신고서'는 flr_nm이 회사 자신("삼성전자")이라 R1으로는 걸리지 않는다.
    # 세 유형 모두 '회사가 한 일'이 아니라 지분 현황의 정례 보고이므로,
    # 누가 제출했든 사건 공시가 아니다. filer 가드를 두면 flr_nm이 존재하는
    # 실환경에서 이 규칙이 통째로 죽는다.
    for title in THIRD_PARTY_TITLES:
        if parsed.body.startswith(title):
            return "지분 보유·변동 신고서입니다 (회사의 사건 공시가 아님)"

    # R5 — 정정·후속 꼬리표
    for tag in parsed.tags:
        if _is_amendment_tag(tag):
            return f"기존 공시의 정정·후속 보고입니다 ({tag})"

    # R2 — 사후·해제 국면
    if parsed.tail in PHASE_TAILS:
        if parsed.tail == "결과보고서":
            return "이미 실행된 건의 결과 보고입니다"
        return f"체결이 아니라 {parsed.tail}입니다"

    # R3 — 자회사·특수관계인 사안
    if any(s in SUBSIDIARY_SUBTITLES for s in parsed.subtitles):
        return "이 회사가 아니라 자회사 사안입니다"
    if parsed.body.startswith(RELATED_PARTY_PREFIX):
        return "회사가 아니라 특수관계인의 행위입니다"

    # R4 — 해명·미확정
    if parsed.tail == "해명" or "미확정" in parsed.subtitles:
        return "회사가 미확정으로 답한 해명 공시입니다"

    return ""


# 라벨 보정 — 제목이 확정해주지 못하는 수식어는 라벨에서 뺀다.
# 3PCA 키워드에 '유상증자'가 통째로 있어 일반공모·소액공모까지 '제3자배정'으로
# 표기되던 것을 막는다(셀트리온 헤드라인 오탐의 직접 원인).
LABEL_OVERRIDES: dict = {
    "3PCA": {
        "missing_marker": "제3자배정",
        "label": "유상증자(배정방식 미상)",
    },
}

# 사실 주석 — tier는 바꾸지 않고 사실만 덧붙인다. 신호 재배정은 하지 않는다.
DIRECTION_NOTES: dict = {
    "CB_BW": {
        "markers": ("사채취득", "사채매도"),
        "note": "발행이 아니라 사채 취득·매도 건입니다",
    },
}


def _adjusted_label(sig: dict, parsed: ParsedName) -> str:
    """제목이 뒷받침하지 못하는 수식어를 뺀 표시 라벨."""
    label = sig.get("label", "")
    rule = LABEL_OVERRIDES.get(sig.get("key", ""))
    if rule and rule["missing_marker"] not in parsed.compact:
        return rule["label"]
    return label


def _direction_note(sig: dict, parsed: ParsedName) -> str:
    """방향이 신호 라벨과 어긋날 때의 사실 주석."""
    rule = DIRECTION_NOTES.get(sig.get("key", ""))
    if not rule:
        return ""
    if any(m in parsed.compact for m in rule["markers"]):
        return rule["note"]
    return ""


def qualify_signals(
    signals: list,
    parsed: ParsedName,
    filing: "dict | None" = None,
) -> "list[Qualified]":
    """match_signals 결과에 표시 계층(tier)과 사유를 붙인다.

    신호를 제거하지 않는다 — tier만 붙는다. 판단 불가하면 observed(기존
    동작)로 남긴다. 예외를 던지지 않는다.
    """
    reason = _demotion_reason(parsed, filing)
    tier = TIER_PROCEDURAL if reason else TIER_OBSERVED
    return [
        Qualified(
            key=sig.get("key", ""),
            label=_adjusted_label(sig, parsed),
            tier=tier,
            reason=reason,
            note=_direction_note(sig, parsed),
        )
        for sig in (signals or [])
    ]


def pick_headline(
    qualified: "list[Qualified]",
    order: "list[str] | None" = None,
) -> "Qualified | None":
    """헤드라인이 될 신호를 고른다. 없으면 None.

    후보 = observed 신호 중 AMBIGUOUS_SIGNAL_KEYS를 뺀 것.
    후보가 비면 None을 반환하고, 호출부는 중립 표기로 대체한다.

    ambiguous를 후보로 되돌리는 별도 조건은 두지 않는다 — non-ambiguous가
    하나라도 있으면 그것이 헤드라인이 되고, 없으면 중립 표기이므로
    ambiguous가 헤드라인이 되어야 할 경우가 존재하지 않는다.
    """
    candidates = [
        q for q in (qualified or [])
        if q.tier == TIER_OBSERVED and q.key not in AMBIGUOUS_SIGNAL_KEYS
    ]
    if not candidates:
        return None
    if not order:
        return candidates[0]
    rank = {k: i for i, k in enumerate(order)}
    return min(candidates, key=lambda q: rank.get(q.key, len(rank)))
