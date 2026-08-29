"""상대방 자리에 **문장 조각**이 들어가는 것을 막는다 — 누락보다 나쁜 오탐.

공시 하단 주석에 이런 문장이 있다:

    - 상기 6.의 취득예정일자는 **거래상대방과의** 주식취득 완료일 기준으로
      작성되었습니다.

`_DISPOSAL_COUNTERPARTY_RES`의 「거래상대방 (.+?) …」 패턴이 표가 아니라 이
문장을 문다. 실측(2026-08-28, 시장 26건 표본): 상대방을 낸 5건 중 **1건(20%)**이

    '과의 주식취득 완료일 기준으로 작성되었습니다. - 상기 7.의 최근 사업연도말 …'

이었다. 화면은 이것을 **거래상대방이라고 자신 있게 말한다** — 값이 없는 것보다
나쁘다.

⚠ 이 위험은 v1.21.5에서 넓어졌다. 그전에는 DS005가 실패하면 「(미확인)」으로
끝났는데, 원문 폴백을 넣으면서 이 파서의 출력이 화면에 오르게 됐다.

프로젝트에는 이미 같은 태도의 `_RELATION_LOOKS_DIRTY_RE`(관계 값이 표를 삼키면
미기재로 버린다)가 있다. 상대방에도 같은 것을 둔다 — 회사·사람 이름에는
종결어미도 조사 시작도 없다.

⚠ 더러운 값을 만나면 **버리고 다음 패턴을 계속 본다**. 그 문서에도 진짜 표가
있을 수 있다 — 없는 사실을 적지 않되, 있는 사실은 찾는다.
"""
import pathlib

import pytest

from dart_risk_mcp.core.dart_client import (
    _COUNTERPARTY_LOOKS_DIRTY_RE,
    parse_asset_disposal_detail,
)

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")


@pytest.mark.parametrize("bad", [
    "과의 주식취득 완료일 기준으로 작성되었습니다. - 상기 7.의 최근 사업연도말",
    "와의 계약 체결일 기준으로 작성되었습니다",
    "은 아래와 같습니다",
    "취득예정일자는 별도로 정하였습니다",
    "자세한 내용은 원문을 참고 바랍니다",
])
def test_문장_조각을_더러움으로_본다(bad):
    assert _COUNTERPARTY_LOOKS_DIRTY_RE.search(bad), bad


@pytest.mark.parametrize("good", [
    "웹케시 주식회사",
    "㈜로아앤코홀딩스",
    "정은산업 주식회사",
    "주식회사 한국파일",
    "GH America Incorporation",
    "박*순 외 2인",
    "나카모토투자조합 외1인",
    "한국토지주택공사",
    "김영태, 배정호, 배충실, 송남연",
])
def test_진짜_이름은_통과한다(good):
    assert not _COUNTERPARTY_LOOKS_DIRTY_RE.search(good), good


_NOTE_ONLY = (
    "주요사항보고서(타법인주식및출자증권양수결정) 1. 발행회사 회사명 웹케시 "
    "- 상기 6.의 취득예정일자는 거래상대방과의 주식취득 완료일 기준으로 "
    "작성되었습니다. - 상기 7.의 최근 사업연도말 자산총액은 당사의 2025년말"
)

_NOTE_PLUS_TABLE = (
    "주요사항보고서(유형자산양수결정) "
    "6. 거래상대방 회사명(성명) 정은산업 주식회사 자본금(원) 300,000,000 "
    "회사와의 관계 - 7. 거래대금지급 "
    "- 상기 6.의 취득예정일자는 거래상대방과의 완료일 기준으로 작성되었습니다."
)


def test_주석만_있으면_상대방을_비운다():
    got = parse_asset_disposal_detail(_NOTE_ONLY)
    assert got["counterparty"] == "", got["counterparty"]


def test_주석이_있어도_진짜_표가_있으면_읽는다():
    """더러운 값을 만나 멈추면 있는 사실까지 잃는다."""
    got = parse_asset_disposal_detail(_NOTE_PLUS_TABLE)
    assert got["counterparty"] == "정은산업 주식회사", got["counterparty"]


def test_더러운_값에서_break하지_않는다():
    src = (_ROOT / "dart_risk_mcp" / "core" / "dart_client.py").read_text(encoding="utf-8")
    i = src.index("for rx in _DISPOSAL_COUNTERPARTY_RES:")
    body = src[i:i + 900]
    assert "continue" in body, "더러운 값에서 멈추면 뒤 패턴을 못 본다"
    assert "_COUNTERPARTY_LOOKS_DIRTY_RE.search(cand)" in body


def test_뷰어에도_같은_판정이_있다():
    assert "COUNTERPARTY_LOOKS_DIRTY_RE" in _HTML, "뷰어에 이식되지 않았다"
    i = _HTML.index("for (const rx of DISPOSAL_COUNTERPARTY_RES)")
    body = _HTML[i:i + 700]
    assert "COUNTERPARTY_LOOKS_DIRTY_RE.test(cand)) continue" in body
    assert "out.counterparty = cand.slice(0, 60)" in body
