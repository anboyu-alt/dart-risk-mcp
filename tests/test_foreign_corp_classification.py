"""외국 법인이 **개인**으로 분류되던 문제.

`classify_actor`의 값은 비공개 Notion 레지스트리의 「구분」 select로 들어간다.
법인을 개인으로 적으면 **실명 명부가 틀린 사실을 담는다**.

`_ORG_PAT`에는 `co|ltd|llc|inc|corp`만 있고 유럽·아시아식 접미사가 없었다.
docstring은 corp에 "외국 법인"을 포함한다고 적어 뒀으니 의도가 아니라
구현의 공백이다.

라이브 실측(2026-08-23, 시장 120건에서 상대방 이름 82종 추출):

| | 전 | 후 |
|---|---|---|
| person | 4종 (그중 **2종이 외국 법인**) | **2종**(둘 다 진짜 인명) |
| corp | 73종 | 75종 |

걸렸던 이름: `CS Wind Offshore A/S` · `CS Wind Portugal S.A.`

⚠ 라틴 문자만 쓰므로 한글 인명은 걸리지 않고, **접미사가 없는 외국인
인명**(예: 'LIU HUAN' — CLAUDE.md가 레지스트리 키 사례로 드는 표기)도
person으로 남아야 한다. 그쪽이 뒤집히면 개인이 법인으로 적힌다.
"""
import pytest

from dart_risk_mcp.core.known_actors import KIND_LABELS, classify_actor

FOREIGN_CORPS = [
    "CS Wind Offshore A/S",        # 라이브 실측
    "CS Wind Portugal S.A.",       # 라이브 실측
    "Philips B.V.",
    "Heineken N.V.",
    "Ferrari S.p.A.",
    "Tesco PLC",
    "Volvo AB",
    "Siemens AG",
    "Air Liquide S.A.S.",
    "Genting Sdn Bhd",
    "Flextronics Pte Ltd",
]

PERSONS = [
    "손제호", "서경선", "홍길동", "김철수",     # 한글 인명
    "LIU HUAN", "DING SHAO YING", "John Smith",  # 접미사 없는 외국인 인명
]

UNCHANGED = [
    ("주식회사 로아앤코홀딩스", "corp"),
    ("정은산업 주식회사", "corp"),
    ("㈜한국파일", "corp"),
    ("다래개인투자조합2호", "fund"),
    ("아이비케이-스톤브릿지 라이징제2호 투자조합", "fund"),
    ("국민은행", "institution"),
    ("미래에셋증권 주식회사", "institution"),
]


@pytest.mark.parametrize("name", FOREIGN_CORPS)
def test_외국_법인은_corp이다(name):
    assert classify_actor(name) == "corp", name


@pytest.mark.parametrize("name", PERSONS)
def test_인명은_person으로_남는다(name):
    """접미사 없는 외국인 인명이 법인으로 뒤집히면 개인이 법인으로 적힌다."""
    assert classify_actor(name) == "person", name


@pytest.mark.parametrize("name,kind", UNCHANGED)
def test_기존_분류가_바뀌지_않는다(name, kind):
    assert classify_actor(name) == kind, name


def test_레지스트리_표기가_한글이다():
    """「구분」 select에 들어가는 값 — 사용자(제작자)가 읽는 라벨."""
    assert KIND_LABELS["corp"] == "법인"
    assert KIND_LABELS["person"] == "개인"


def test_접미사만으로도_잡는다():
    """회사명 본체를 몰라도 접미사로 법인임을 안다."""
    for suffix in ("A/S", "GmbH", "S.A.", "B.V.", "PLC", "Pte", "Sdn Bhd"):
        assert classify_actor(f"Acme {suffix}") == "corp", suffix
