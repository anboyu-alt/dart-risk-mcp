"""임원 보수 출력의 **읽히지 않던 두 자리**를 잠근다.

도구 출력을 읽다 찾았다(2026-08-30, 두산).

## 1. 개행이 늘 줄바꿈인 것은 아니다

⑤ 주총 한도는 DART가 **구분·인원을 개행으로 묶어 한 행에** 준다.

    se   = '등기이사\\n사외이사\\n감사위원'
    nmpr = '3\\n0\\n4'

`_rows`가 개행을 공백으로 접으니(`ofcps` 대응, 2026-08-26) 화면이

    • 구분: 등기이사 사외이사 감사위원 | 인원수: 3 0 4

가 되어 **어느 숫자가 어느 구분인지 알 수 없었다**.

⚠ 그런데 개행이 **항상 구분자는 아니다.** 두산에너빌리티는

    se   = '등기이사\\n (사외이사, 감사위원회 위원 제외)'
    nmpr = '3'

으로 **한 이름이 줄바꿈된 것**이다. 그래서 `se`와 `nmpr`의 조각 수가 **같을
때만** 나눈다 — 다르면 옛 동작 그대로.

금액은 실측 3건 모두 **하나**뿐이었다(구분이 여럿이어도). 나눌 수 없으므로
「합계」로 적고 구분별로 아는 척하지 않는다.

## 2. 1인평균이 총액÷인원과 다르다

    인원수 34 | 연간급여 총액 36,810,000,000 | 1인평균 1,006,000,000

나누면 1,082,647,058이다(8% 차). DART가 주는 값이고, 평균의 분모가 다른 것으로
보인다(기중 인원 등). 12개사 실측 **4건**(1~8%), 골든 10개사에서는 22% 차도
나온다.

**다시 계산해 덮어쓰지 않는다** — 그건 DART가 말하지 않은 값을 만드는 것이다.
1% 넘게 어긋날 때만 사실로 밝힌다.
"""
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SRC = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")


def _fn(name: str) -> str:
    i = _SRC.index(f"    def {name}(")
    j = _SRC.index("\n\n    def ", i + 10)
    return _SRC[i:j]


# ── 1. 주총 한도 행 ────────────────────────────────────────────
def test_구분과_인원_조각_수가_같을_때만_나눈다():
    body = _fn("_agm_rows")
    assert "if len(se_parts) > 1 and len(se_parts) == len(np_parts):" in body, (
        "조각 수를 대조하지 않으면 줄바꿈된 이름을 두 구분으로 쪼갠다"
    )


def test_조각_수가_다르면_옛_동작이다():
    body = _fn("_agm_rows")
    assert "_rows([item], agm_cols)" in body, "폴백이 사라졌다"


def test_금액을_구분별로_나누지_않는다():
    """DART가 하나만 주므로 구분별 금액을 아는 척하면 안 된다."""
    body = _fn("_agm_rows")
    assert "주총승인 금액(합계, 원)" in body
    assert "gmtsck_confm_amount" in body
    assert "amt_parts" not in body, "금액을 쪼개려 하고 있다"


def test_금액_미기재를_0으로_읽지_않는다():
    body = _fn("_agm_rows")
    assert "주총승인 금액: 미기재" in body


def test_렌더가_전용_함수를_쓴다():
    assert '_agm_rows(data["agm_limit"])' in _SRC
    assert '_rows(data["agm_limit"], agm_cols)' not in _SRC, "옛 렌더가 남아 있다"


# ── 2. 1인평균 대조 ────────────────────────────────────────────
def test_평균을_다시_계산해_덮어쓰지_않는다():
    body = _fn("_avg_mismatch_note")
    assert "return (" in body and "DART가 준" in body
    # 원본 값을 바꾸는 대입이 없어야 한다
    assert "item[" not in body, "응답 값을 덮어쓰고 있다"


def test_1퍼센트_넘을_때만_말한다():
    body = _fn("_avg_mismatch_note")
    assert "abs(calc - avg) / avg > 0.01" in body


def test_값이_없으면_말하지_않는다():
    body = _fn("_avg_mismatch_note")
    assert "if not (tot and cnt and avg):" in body
    assert "continue" in body


def test_두_섹션_모두_대조한다():
    """① 이사·감사 전체와 ③ 미등기임원 — 같은 모양의 세 숫자다."""
    assert '_avg_mismatch_note(data["high_pay"], "mendng_totamt",' in _SRC
    assert '_avg_mismatch_note(data["unregistered"], "fyer_salary_totamt",' in _SRC


def test_빈_주석이_빈_줄을_만들지_않는다():
    """해당 없으면 빈 문자열이라 그대로 두면 줄이 하나 더 생긴다."""
    i = _SRC.index("_out: list[str] = []")
    body = _SRC[i:i + 300]
    assert "if not _l and _out and not _out[-1]:" in body


def test_숫자_파싱이_콤마와_빈값을_견딘다():
    body = _fn("_avg_mismatch_note")
    assert 'str(v).replace(",", "").strip()' in body
    assert "except (TypeError, ValueError):" in body


def test_응답_키가_픽스처에_기록돼_있다():
    """⑤ 엔드포인트는 픽스처에 아예 없었다 — 라이브로 떠서 기록했다."""
    import json
    fx = json.loads(
        (_ROOT / "tests" / "fixtures" / "api" / "response_keys.json")
        .read_text(encoding="utf-8"))
    keys = fx["endpoints"].get("drctrAdtAllMendngSttusGmtsckConfmAmount")
    assert keys, "엔드포인트가 픽스처에 없다"
    for k in ("se", "nmpr", "gmtsck_confm_amount"):
        assert k in keys, f"{k}가 기록돼 있지 않다"


def test_날짜_슬라이스가_상한으로_오인되지_않는다():
    """`test_no_silent_caps`의 허용 목록에 근거와 함께 있는지."""
    t = (_ROOT / "tests" / "test_no_silent_caps.py").read_text(encoding="utf-8")
    i = t.index('"_d8",')
    assert "목록 상한이 아니다" in t[i - 200:i]
    assert re.search(r'_d8\[:8\]', _SRC)
