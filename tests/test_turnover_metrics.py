"""compute_turnover_metrics 경계값 테스트 (순수 함수 — 네트워크 호출 없음).

Phase 1(회전율·CCC 지표 신설)의 산술·사실 표기 계약을 잠근다:
- 매출원가 미노출 시 매출로 폴백하고 그 사실을 `basis`에 남긴다.
- 분모가 없거나 0이면 value=None + 한국어 사실 문장(reason).
- 운전자본이 0 이하이면 회전율을 내지 않고 금액을 담은 사실 문장을 낸다.
- CCC는 세 회전율이 전부 있어야 계산되고, 없으면 어느 것이 없는지 적는다.
- prior를 주면 yoy_pct를 함께 낸다(전기 0/None이면 None).
- v0.8.5 원칙: 판정 어휘("위험"·"양호"·"우수"·"나쁨"·점수)를 출력에 섞지 않는다.
"""
import pytest

from dart_risk_mcp.core.dart_client import compute_turnover_metrics


def _period(**overrides):
    base = {
        "매출액": 1000,
        "매출원가": 600,
        "매출채권": 100,
        "재고자산": 150,
        "매입채무": 120,
        "유동자산": 500,
        "유동부채": 200,
        "자산총계": 2000,
    }
    base.update(overrides)
    return base


def test_정상_계산():
    result = compute_turnover_metrics(_period())
    m = result["metrics"]

    assert m["receivable"]["value"] == pytest.approx(10.0)
    assert m["receivable"]["numerator"] == 1000
    assert m["receivable"]["denominator"] == 100

    assert m["inventory"]["value"] == pytest.approx(4.0)
    assert m["inventory"]["basis"] == "매출원가"

    assert m["payable"]["value"] == pytest.approx(5.0)
    assert m["payable"]["basis"] == "매출원가"

    assert result["working_capital"] == 300
    assert m["working_capital"]["value"] == pytest.approx(1000 / 300)

    assert m["asset"]["value"] == pytest.approx(0.5)

    ccc = result["ccc"]
    assert ccc["dso"] == pytest.approx(36.5)
    assert ccc["dio"] == pytest.approx(91.25)
    assert ccc["dpo"] == pytest.approx(73.0)
    assert ccc["value"] == pytest.approx(36.5 + 91.25 - 73.0)
    assert ccc["reason"] == ""


def test_매출원가_미노출시_매출로_폴백():
    period = _period()
    del period["매출원가"]
    result = compute_turnover_metrics(period)
    m = result["metrics"]

    # 매출원가가 없으니 매출액(1000)으로 재고자산·매입채무 회전율을 낸다.
    assert m["inventory"]["basis"] == "매출액"
    assert m["inventory"]["numerator"] == 1000
    assert m["inventory"]["value"] == pytest.approx(1000 / 150)

    assert m["payable"]["basis"] == "매출액"
    assert m["payable"]["numerator"] == 1000


def test_매출원가와_매출_모두_없으면_사유를_남긴다():
    period = _period()
    del period["매출원가"]
    del period["매출액"]
    result = compute_turnover_metrics(period)
    m = result["metrics"]

    assert m["inventory"]["value"] is None
    assert m["inventory"]["basis"] == ""
    assert "매출원가" in m["inventory"]["reason"]
    assert "매출액" in m["inventory"]["reason"]


def test_분모가_0이면_계산하지_않는다():
    result = compute_turnover_metrics(_period(매출채권=0))
    m = result["metrics"]["receivable"]

    assert m["value"] is None
    assert m["numerator"] == 1000
    assert m["denominator"] == 0
    assert m["reason"] == "분모가 0입니다"


def test_운전자본이_음수면_회전율을_내지_않는다():
    result = compute_turnover_metrics(_period(유동자산=100, 유동부채=2_000_100))
    m = result["metrics"]["working_capital"]

    assert m["value"] is None
    assert result["working_capital"] == 100 - 2_000_100
    # 사실 문장에 실제 음수 금액이 콤마와 함께 실린다.
    assert f"{100 - 2_000_100:,}" in m["reason"]
    assert "원" in m["reason"]


def test_운전자본이_0이면_회전율을_내지_않는다():
    result = compute_turnover_metrics(_period(유동자산=200, 유동부채=200))
    m = result["metrics"]["working_capital"]

    assert result["working_capital"] == 0
    assert m["value"] is None
    assert m["reason"] != ""


def test_계정_자체가_없는_금융업형_dict():
    """계정 자체가 재무제표에 노출되지 않는 업종(예: 금융업)을 흉내낸다."""
    result = compute_turnover_metrics({})
    m = result["metrics"]

    for key in ("receivable", "inventory", "payable", "working_capital", "asset"):
        assert m[key]["value"] is None
        assert m[key]["reason"] != ""

    assert result["working_capital"] is None
    assert result["ccc"]["value"] is None
    assert result["ccc"]["reason"] != ""


def test_CCC_결측_사유_부분_누락():
    """재고자산만 없어도 CCC 전체가 계산 불가 상태가 되고, 사유에 그 이름이 남는다."""
    period = _period()
    del period["재고자산"]
    result = compute_turnover_metrics(period)
    ccc = result["ccc"]

    assert ccc["value"] is None
    assert ccc["dio"] is None
    assert ccc["dso"] is not None
    assert ccc["dpo"] is not None
    assert "재고자산회전율" in ccc["reason"]
    assert "매출채권회전율" not in ccc["reason"]


def test_prior_전달시_yoy_pct_계산():
    prior = _period(매출액=800, 매출채권=80, 매출원가=480, 재고자산=120, 매입채무=96,
                     유동자산=400, 유동부채=160, 자산총계=1600)
    result = compute_turnover_metrics(_period(), prior=prior)
    m = result["metrics"]["receivable"]

    assert m["prior_value"] == pytest.approx(800 / 80)
    assert m["value"] == pytest.approx(10.0)
    # 전기·당기 회전율이 둘 다 10.0으로 동일 → 변동률 0%
    assert m["yoy_pct"] == pytest.approx(0.0)
    assert m["numerator_yoy_pct"] == pytest.approx((1000 - 800) / 800 * 100)
    assert m["denominator_yoy_pct"] == pytest.approx((100 - 80) / 80 * 100)


def test_prior_0이면_yoy_pct는_None():
    prior = _period(매출채권=0)
    result = compute_turnover_metrics(_period(), prior=prior)
    m = result["metrics"]["receivable"]

    # 전기 회전율 자체가 계산 불가(분모 0)이므로 prior_value가 None이고
    # yoy_pct도 None이어야 한다.
    assert m["prior_value"] is None
    assert m["yoy_pct"] is None
    # 분모(매출채권) 자체의 전기값은 0이라 yoy 계산이 정의되지 않는다.
    assert m["denominator_yoy_pct"] is None


def test_prior_없으면_yoy_필드가_없다():
    result = compute_turnover_metrics(_period())
    m = result["metrics"]["receivable"]
    assert "prior_value" not in m
    assert "yoy_pct" not in m


_JUDGMENT_WORDS = ("위험", "양호", "우수", "나쁨", "점수", "등급")


def test_판정_어휘가_섞이지_않는다():
    """v0.8.5 원칙 — 점수·등급 부여 금지. 모든 경계 상태를 한 번에 훑는다."""
    cases = [
        _period(),
        {},
        _period(매출채권=0),
        _period(유동자산=100, 유동부채=999_999_999),
    ]
    for period in cases:
        result = compute_turnover_metrics(period, prior=_period(매출채권=0))
        text = str(result)
        for word in _JUDGMENT_WORDS:
            assert word not in text, f"판정 어휘 '{word}'가 출력에 섞였습니다: {text}"


# ── 라이브 실측에서 나온 실제 서식들 (2026-08-28, 38개사) ──────────────────


def test_비용을_음수로_보고한_회사도_계산한다():
    """손익계산서를 가산 형식으로 적어 매출원가를 음수로 내는 회사가 있다.

    실측: STX 2024 매출원가 -7,990억 · 2023 -8,866억. 그대로 나누면 재고·
    매입채무 회전율이 **음수**로 나와 뜻이 뒤집힌다(수정 전 -10.31·-11.33).
    절댓값으로 계산하되 그 사실을 basis에 남긴다.
    """
    r = compute_turnover_metrics(_period(매출원가=-600))
    inv = r["metrics"]["inventory"]
    assert inv["value"] == pytest.approx(4.0)
    assert "음수 보고" in inv["basis"], inv["basis"]
    assert r["metrics"]["payable"]["value"] == pytest.approx(5.0)


def test_자산_계정이_음수면_계산하지_않는다():
    """비용과 달리 자산의 음수는 절댓값으로 읽을 근거가 없다."""
    r = compute_turnover_metrics(_period(재고자산=-150))
    inv = r["metrics"]["inventory"]
    assert inv["value"] is None
    assert "음수" in inv["reason"]
    assert r["ccc"]["value"] is None


def test_번호_접두가_붙은_계정도_찾는다():
    """실측: 고려아연이 「Ⅱ.매출원가」·「Ⅰ.유동자산」처럼 로마숫자를 단다.

    `_pick_account`는 정확 일치라 이 회사에서는 매출액·매출원가·유동자산·
    유동부채가 통째로 안 잡혀 회전율이 빈다. 접두는 표시용 번호이지 계정명이
    아니므로 정확 일치 실패 시에만 떼고 다시 본다.
    """
    period = {
        "Ⅰ.매출액": 1000, "Ⅱ.매출원가": 600, "매출채권": 100,
        "재고자산": 150, "매입채무": 120,
        "Ⅰ.유동자산": 500, "Ⅰ.유동부채": 200, "자산총계": 2000,
    }
    r = compute_turnover_metrics(period)
    assert r["metrics"]["asset"]["value"] == pytest.approx(0.5)
    assert r["metrics"]["inventory"]["value"] == pytest.approx(4.0)
    assert r["metrics"]["working_capital"]["value"] == pytest.approx(1000 / 300)


def test_정확_일치가_접두보다_우선한다():
    """접두 폴백이 기존 회사의 값을 가로채면 안 된다."""
    period = _period()
    period["Ⅱ.매출원가"] = 999_999
    assert compute_turnover_metrics(period)["metrics"]["inventory"]["numerator"] == 600


@pytest.mark.parametrize("label,expected_key", [
    ("유동재고자산", "inventory"),          # CJ제일제당·오리온·STX·KR모터스·코아스
    ("매출채권 및 기타수취채권", "receivable"),  # 이마트
    ("매출채권 및 기타채권", "receivable"),      # KR모터스
])
def test_실측된_표기로도_계정을_찾는다(label, expected_key):
    """별칭 하나가 빠지면 그 회사에서 지표가 **조용히** 사라진다.

    재고자산은 별칭이 「재고자산」 하나뿐이라 38개사 중 6개사(16%)에서
    `INVENTORY_SURGE`까지 함께 죽어 있었다.
    """
    period = _period()
    drop = "재고자산" if expected_key == "inventory" else "매출채권"
    del period[drop]
    period[label] = 150 if expected_key == "inventory" else 100
    assert compute_turnover_metrics(period)["metrics"][expected_key]["value"] is not None
