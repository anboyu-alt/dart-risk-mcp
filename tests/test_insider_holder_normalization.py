"""보고자 이름의 공백·개행 차이로 **같은 사람이 갈리지** 않는지 잠근다.

`track_insider_trading` 출력을 끝까지 읽어 찾았다(진원생명과학, 2026-08-25).

    ▶ 동반성장투자조합제1호
        2026  11.39%  [최대주주]

    ▶ 동반성장투자조합 제1호            ← 공백 하나 차이
        20260213   5.71%  [최대주주 변동]
        20260304  11.40% (Δ+5.69%)  [최대주주 변동]

DART가 보고자명에 **개행과 이중 공백**을 섞어 보내는데 `strip()`만 하고
있었다. 이 도구의 존재 이유가 **한 주체의 Δ 시계열**인데, 이름이 갈리면
그 시계열이 끊긴다 — 클러스터 탐지도 함께 놓친다.

실측(20개사) — **9건**:

    카카오      '최용석 (주1)' · '최용석  (주1)' · 개행 변형     ← 한 사람이 3명
    삼성전자     '삼성생명보험㈜(특별계정)' 개행 유/무
    SK하이닉스   'SK스퀘어㈜' 개행 유/무
    이오플로우    'Citadel Multi-Asset Master Fund Ltd.' · 공백 없는 변형
    코아스       '백운조합' · '백운 조합'

## 고른 방식

묶는 키는 **공백을 전부 지운다** — 영문명은 한쪽에만 공백이 있어 한 칸으로
줄이는 것만으로는 안 묶인다(`Citadel Multi-Asset…` vs `CitadelMulti-Asset…`).
화면 이름은 개행만 공백으로 펴고, 변형 중 **가장 긴 것**을 고른다(공백이
살아 있는 쪽이라 읽기 좋다).

수정 후 카카오·진원생명과학 모두 중복 **0건**이고, 진원생명과학에서는
「동반성장투자조합 제1호」가 하나로 묶이며 **매수 클러스터가 새로 탐지**된다.
"""
import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SRC = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")


from dart_risk_mcp.server import _holder_display, _holder_key


@pytest.mark.parametrize("a,b", [
    ("동반성장투자조합제1호", "동반성장투자조합 제1호"),
    ("최용석 (주1)", "최용석  \n(주1)"),
    ("삼성생명보험㈜\n(특별계정)", "삼성생명보험㈜(특별계정)"),
    ("SK스퀘어㈜", "SK스퀘어\n㈜"),
    ("Citadel Multi-Asset Master Fund Ltd.", "CitadelMulti-AssetMasterFundLtd."),
    ("백운조합", "백운 조합"),
    ("KIM JESSE JAEJIN", "KIMJESSEJAEJIN"),
])
def test_같은_주체는_같은_키다(a, b):
    key = _holder_key
    assert key(a) == key(b)


@pytest.mark.parametrize("a,b", [
    ("박영근", "박희곤"),
    ("최용석 (주1)", "최용석 (주2)"),
])
def test_다른_주체는_갈린다(a, b):
    """공백만 지우므로 실제로 다른 이름은 그대로 다르다."""
    key = _holder_key
    assert key(a) != key(b)


def test_표시_이름은_읽을_수_있다():
    disp = _holder_display
    assert disp("SK스퀘어\n㈜") == "SK스퀘어 ㈜"
    assert disp("  최용석  \n(주1) ") == "최용석 (주1)"


def test_화면에_묶음_키를_쓰지_않는다():
    """키는 공백이 지워진 형태라 그대로 출력하면 읽기 나쁘다."""
    assert "holder = holder_names.get(_hk, _hk)" in _SRC
    assert "timeline[_hk].append(" in _SRC
    assert "timeline[holder].append(" not in _SRC


def test_가장_긴_변형을_표시로_고른다():
    assert 'len(_disp) > len(holder_names.get(_hk, ""))' in _SRC


def test_strip만_하던_옛_코드가_없다():
    i = _SRC.index("def _extract_row")
    j = _SRC.index("_SOURCE_LABEL = {", i)
    block = _SRC[i:j]
    # 원본 필드 추출에는 strip()이 남아 있어도 되지만, 묶기 전에 정규화가 있어야 한다
    assert "_holder_key" in _SRC[j:j + 3000] or "_holder_key" in block
