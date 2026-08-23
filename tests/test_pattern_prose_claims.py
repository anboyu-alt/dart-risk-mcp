"""패턴 해설의 **사실 주장**이 근거를 갖는지 잠근다.

`PATTERN_PROSE`는 사용자 화면에 그대로 나가면서 날짜·기관·법조문을 특정해
규제기관 조치를 인용한다. 2026-08-24 대조에서 셋이 틀렸다.

| 패턴 | 무엇이 틀렸나 |
|---|---|
| `audit_insider_dump` | 「2026년 2월 금감원 적발」 — 그날 자료는 ㈜국보 **회계처리 위반** 조치로 감사의견 직전 내부자 매도와 무관. 게다가 「30일 이전 매도 클러스터가 핵심 증거로 제시」는 **우리 taxonomy의 관찰 창**을 규제기관 주장으로 둔갑시킨 것 |
| `delisting_evasion` | 「집중 **감리** 대상으로 지정」 — 실제 표현은 「집중**조사**」. 회계감리와 불공정거래 조사는 다른 절차 |
| `founder_fade` | 「6개월 내 주가가 절반 이하로 떨어지는 경우가 많았습니다」 — 근거 없음(카탈로그 191KB에 '절반'·'6개월 내'·'반토막' 0건). 이 도구는 주가 데이터를 다루지 않는다 |

여기서 거는 것은 문장이 아니라 **성질**이다 — 없는 근거를 만들지 않는가,
우리 파라미터를 규제기관 것으로 적지 않는가, 가격 결과를 말하지 않는가.
"""
import pathlib
import re

import pytest

from dart_risk_mcp.core.explain import PATTERN_PROSE
from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS

_CATALOG = pathlib.Path(__file__).resolve().parents[1] / "dart_risk_mcp" / "knowledge" / "manipulation_catalog"


@pytest.fixture(scope="module")
def catalog_text():
    files = sorted(_CATALOG.glob("*.md"))
    assert files, "카탈로그 MD가 없다"
    return "\n".join(f.read_text(encoding="utf-8") for f in files)


@pytest.fixture(scope="module")
def catalog_dates(catalog_text):
    """카탈로그에 실재하는 보도자료 연-월 집합."""
    return {f"{y}-{m}" for y, m in
            re.findall(r"\*\*(\d{4})-(\d{2})-\d{2} / ", catalog_text)}


@pytest.mark.parametrize("pid", sorted(PATTERN_PROSE))
def test_인용한_연월이_카탈로그에_실재한다(pid, catalog_dates):
    """해설이 'YYYY년 M월 금감원…'이라 적으면 그 달 자료가 있어야 한다."""
    prose = PATTERN_PROSE[pid]
    for y, m in re.findall(r"(\d{4})년\s*(\d{1,2})월", prose):
        ym = f"{y}-{int(m):02d}"
        assert ym in catalog_dates, (
            f"{pid}: {ym} 자료가 카탈로그에 없다. 인용을 확인하세요."
        )


def test_가격_결과를_말하지_않는다():
    """이 도구는 주가 데이터를 다루지 않는다(CLAUDE.md 비범위: 가격 예측)."""
    banned = ("절반 이하", "반토막", "주가가 절반", "% 하락", "배 상승", "급등할")
    for pid, prose in PATTERN_PROSE.items():
        for w in banned:
            assert w not in prose, f"{pid}: 근거 없는 가격 주장 '{w}'"


def test_우리_파라미터를_규제기관_주장으로_적지_않는다():
    """`detect_insider_pre_disclosure`의 30일은 우리 관찰 창이다."""
    prose = PATTERN_PROSE["audit_insider_dump"]
    assert "30일" in prose, "창 자체는 사실로 표기해도 된다"
    assert "핵심 증거로 제시" not in prose
    assert "도구의 관찰 창" in prose or "규제기관이 제시한 기준은 아닙니다" in prose


def test_규제_용어를_바꿔_적지_않는다(catalog_text):
    """회계감리와 불공정거래 조사는 다른 절차다."""
    prose = PATTERN_PROSE["delisting_evasion"]
    assert "집중 감리 대상으로 지정" not in prose
    assert "집중조사" in prose
    assert "좀비기업을 집중조사" in catalog_text, "원 자료 표현이 바뀌었다"


def test_감사의견_덤프_인용이_실제_유형과_맞다(catalog_text):
    """인용한 자료가 이 패턴의 사건을 실제로 다뤄야 한다."""
    prose = PATTERN_PROSE["audit_insider_dump"]
    assert "2024년 2월" in prose
    i = catalog_text.find("결산시기 악재성 미공개 정보 이용행위 집중점검")
    assert i > 0, "인용 자료가 카탈로그에서 사라졌다"
    body = catalog_text[i:i + 700]
    assert "감사의견" in body and "매도" in body


@pytest.mark.parametrize("pid", sorted(CROSS_SIGNAL_PATTERNS))
def test_모든_패턴에_해설이_있다(pid):
    assert PATTERN_PROSE.get(pid, "").strip(), f"{pid}: 해설 없음"


def test_해설에_점수_등급_어휘가_없다():
    banned = ("매우위험", "고위험", "위험도 점수", "등급", "CRITICAL", "HIGH", "MEDIUM")
    for pid, prose in PATTERN_PROSE.items():
        for w in banned:
            assert w not in prose, f"{pid}: 금칙어 '{w}'"
