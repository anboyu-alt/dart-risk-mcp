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
