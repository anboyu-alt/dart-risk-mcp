"""연속 적자 연수가 **조회 창에 막힌 값인지** 밝히는지 잠근다.

연속 연수가 조회 창을 다 채우면 그 값은 **창 상한이지 사실이 아니다.**
옛 문구는 거기에 연도 범위까지 붙여 「5년 연속(2021~2025)」이라 적었고,
이는 **2021년에 시작했다**는 뜻으로 읽힌다.

실측(2026-08-28, 창을 9년으로 넓혀 재측정):

    STX 순손실          창 5년 표기 「5년 연속(2021~2025)」 → 실제 **7년**
    헬릭스미스 영업손실  창 5년 표기 「5년 연속(2021~2025)」 → 실제 **9년+**
    헬릭스미스 순손실    창 5년 표기 「5년 연속(2021~2025)」 → 실제 **9년+**

절단된 값에 **시작 연도를 단정해 붙이는 것**은 「조용한 절단」의 가장 나쁜
형태다. 창 안에서 끝난 연속(STX 영업손실 4년)은 그대로 연도 범위를 쓴다 —
그건 실제로 2022년에 시작했다.

## 뷰어는 같은 화면이 두 숫자를 말했다

    finCore    「**2개 연도** 연속 영업적자입니다」   ← 하드코딩된 임계 문구
    auditCore  「영업손실 **3년** 연속」              ← 같은 데이터로 센 값

`op[0] < 0 && op[1] < 0`이면 무조건 「2개 연도」라 적었다. 실제 개수를 쓰고,
본 기간을 다 채웠으면 그 사실을 함께 밝힌다.
"""
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SERVER = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")


def _core_block() -> str:
    i = _SERVER.index('lines.append("**연속 적자 (참고)**")')
    return _SERVER[i:i + 1800]


def test_core가_창을_다_채우면_연도_범위를_단정하지_않는다():
    body = _core_block()
    assert "def _streak_part(" in body, "창 상한 분기가 없다"
    assert "n >= _n_years" in body, "창을 다 채웠는지 보지 않는다"
    assert "실제 연속 연수는" in body, "더 길 수 있다는 사실을 말하지 않는다"


def test_core가_창_안에서_끝난_연속은_연도_범위를_쓴다():
    """4년 연속이 5년 창 안에서 끝났다면 시작 연도를 아는 것이다."""
    body = _core_block()
    assert "{_latest - n + 1}~{_latest}" in body, (
        "창 안에서 끝난 연속까지 범위를 지우면 정보가 준다"
    )


def test_옛_단정_문구가_되살아나지_않는다():
    body = _core_block()
    assert '{_op_n}년 연속({_latest - _op_n + 1}' not in body
    assert '{_ni_n}년 연속({_latest - _ni_n + 1}' not in body


def test_뷰어가_하드코딩된_2개_연도를_쓰지_않는다():
    """같은 화면의 다른 블록은 같은 데이터로 3년이라 적었다."""
    i = _HTML.index("function lossStreakTail(")
    region = _HTML[i:i + 3000]
    assert '"2개 연도 연속 영업적자입니다."' not in _HTML, "옛 하드코딩이 남아 있다"
    assert "${_opStreak}개 연도 연속 영업적자입니다" in _HTML
    assert "${_niStreak}개 연도 연속 순손실입니다" in _HTML


def test_뷰어_꼬리_문구가_본_기간을_기준으로_판단한다():
    i = _HTML.index("function lossStreakTail(")
    body = _HTML[i:_HTML.index("\n}", i)]
    assert "series.filter((v) => v !== null).length" in body, (
        "null을 세면 창 크기를 잘못 잡는다"
    )
    assert "n >= seen" in body
    assert "조회 범위 밖" in body


def test_뷰어_AUDIT_블록도_창_상한을_밝힌다():
    assert "lossStreakCapped" in _HTML, "창 상한 여부를 넘기지 않는다"
    i = _HTML.index("const _capNote = finData.lossStreakCapped")
    body = _HTML[i:i + 700]
    assert "실제 연속 연수는 더 길 수 있습니다" in body
    assert "esc(_capNote)" in body, "이스케이프를 거치지 않는다"


def test_lossStreakCapped가_두_계정을_모두_본다():
    i = _HTML.index("lossStreakCapped:")
    body = _HTML[i:i + 200]
    assert "_seenOp" in body and "_seenNi" in body
    assert re.search(r"_seenOp > 0 && _op >= _seenOp", body), "영업 판정이 없다"
    assert re.search(r"_seenNi > 0 && _ni >= _seenNi", body), "순손익 판정이 없다"
