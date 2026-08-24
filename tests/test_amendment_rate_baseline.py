"""정정공시 비율의 기준선이 **실측**인지 잠근다.

core와 뷰어가 같은 말을 하고 있었다.

    "정상 기업은 보통 5% 안쪽이고, 20%를 넘으면 최초 공시 품질이 떨어지거나
     정보를 조금씩 흘려보내는 의도가 있을 수 있습니다."

근거가 없었고 실측과 어긋난다. 시장 전체 44일(2026-07-10~08-22 · 고유 공시
27,780건 · 법인 6,371곳)을 재니:

| 표본(공시 10건 이상) | 법인 | 중앙값 | p75 | p90 | 5% 초과 | 20% 초과 |
|---|---:|---:|---:|---:|---:|---:|
| **상장사(Y·K)** | 488 | **10.0%** | 23.1% | 38.5% | **70.1%** | 27.7% |
| 그 외(E·N) | 80 | 33.3% | 51.2% | 57.0% | 82.5% | 58.8% |

'5% 이내가 정상'은 상장사의 **70%가 위반**한다. 20%도 28%가 넘으니 기준선이
아니다(p75가 23%다).

⚠ **표본을 가르지 않으면 반대로 틀린다** — 자산운용사는 펀드 상품 공시 정정이
일상이라 중앙값이 33~47%다(삼성자산운용 58.9% · KB자산운용 56.3%). 섞어 재면
"정상이 50%"라는 반대 방향의 거짓이 나온다.

뷰어 표기 문턱도 10 → 25로 올렸다. 10은 실측 **중앙값**이라 상장사 절반에
붙었다 — 절반에 붙는 것은 주석이 아니라 기본값이다(#259와 같은 계산).
"""
import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SRV = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")
# ⚠ 파일 전문을 parametrize 인자로 넘기면 테스트 ID가 수만 자가 되어
#   pytest가 환경변수 한도(32,767자)로 죽는다 — 라벨만 넘긴다.


def _rendered(src: str) -> str:
    """사용자에게 **보이는** 문자열만 남긴다.

    두 가지를 걷어내야 검사가 성립한다.
      · `#` 주석 — 왜 고쳤는지 옛 문구를 인용해 두므로 금칙어가 그대로 남는다.
      · 문자열 연결 이음매 — 소스에서는 `"…실측(2026-07-10"` 다음 줄에
        `"~08-22, …"` 로 끊겨 있어, 렌더되면 이어지는 문구가 부분 문자열로는
        안 잡힌다.
    """
    lines = [ln for ln in src.splitlines() if not ln.lstrip().startswith("#")]
    return re.sub(r'"\s*"', "", "".join(ln.strip() for ln in lines))


_LAYERS = {"core": _rendered(_SRV), "viewer": _rendered(_HTML)}

# 2026-08-24 실측값 — 문서와 코드가 같은 수를 말하는지 대조하는 기준
MEASURED = {
    "median": 10,
    "p75": 23,
    "p90": 39,
    "n_listed": 488,
    "n_disclosures": "27,780",
    "window": "2026-07-10~08-22",
}


@pytest.mark.parametrize("layer", ["core", "viewer"])
def test_근거_없는_기준선_문구가_사라졌다(layer):
    text = _LAYERS[layer]
    for phrase in ("정상 기업은 보통 5%", "정상 기업은 대체로 5% 이내",
                   "20%를 넘으면 최초 공시 품질", "기준선으로 통용"):
        assert phrase not in text, f"{layer}: '{phrase}'가 남아 있다"


@pytest.mark.parametrize("layer", ["core", "viewer"])
def test_실측_출처와_수치를_함께_적는다(layer):
    text = _LAYERS[layer]
    """숫자만 바꾸면 다음 사람이 또 근거 없이 고친다 — 창과 표본을 함께 남긴다."""
    assert MEASURED["window"] in text, f"{layer}: 측정 창이 없다"
    assert MEASURED["n_disclosures"] in text, f"{layer}: 표본 크기가 없다"
    assert str(MEASURED["n_listed"]) in text, f"{layer}: 상장사 표본 수가 없다"
    assert "중앙값" in text


@pytest.mark.parametrize("layer", ["core", "viewer"])
def test_두_레이어가_같은_수를_말한다(layer):
    text = _LAYERS[layer]
    """core를 고치고 뷰어를 안 고치면 같은 회사가 두 화면에서 다르게 보인다."""
    for key in ("median", "p75", "p90"):
        assert f"{MEASURED[key]}%" in text, f"{layer}: {key}={MEASURED[key]}% 누락"


def test_뷰어_문턱이_중앙값보다_높다():
    """중앙값에 문턱을 두면 절반에 붙는다 — 그건 주석이 아니라 기본값이다."""
    m = re.search(r"const AMEND_NOTE_FLOOR = (\d+);", _HTML)
    assert m, "AMEND_NOTE_FLOOR 상수가 없다"
    floor = int(m.group(1))
    assert floor > MEASURED["median"], "중앙값 이하 문턱은 변별력이 없다"
    assert floor >= MEASURED["p75"] - 3, f"p75({MEASURED['p75']}%) 언저리여야 한다"


def test_자산운용사_왜곡을_기록해_뒀다():
    """표본을 가르지 않으면 반대로 틀린다는 사실을 코드에 남긴다."""
    assert "자산운용" in _SRV, "core 주석에 표본 왜곡 근거가 없다"  # 원본(주석 포함)


def test_비율만으로_판정하지_않는다고_말한다():
    """v0.8.5 — 수치를 주더라도 그것으로 이상 여부를 단정하지 않는다."""
    for layer, text in _LAYERS.items():
        assert re.search(r"비율(만으로|\s*자체로)", text), f"{layer}: 한정 문구 없음"
