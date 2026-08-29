"""운전자본회전율에 **분모를 병기**하는지 잠근다.

운전자본은 이 도구에서 **유일하게 차감으로 만들어진 분모**다
(유동자산 − 유동부채). 다른 분모(매출채권·재고자산·매입채무·자산총계)는
잔액 그 자체라 0에 가까워질 일이 드물지만, 이건 두 큰 수의 차라 0 근처로
쉽게 간다. 그러면 회전율이 발산해 **「효율이 좋다」가 아니라 「분모가 0에
가깝다」**는 뜻이 된다.

실측(2026-08-30, 두산 000150):

    2023년  운전자본 74억원 · 매출 19조원  →  운전자본회전율 **2,559.01회**
            같은 해 다른 회전율은 매출채권 11.48 · 재고 5.43 · 매입채무 5.90

표만 보면 이 회사가 운전자본을 극도로 효율적으로 쓴다고 읽힌다.

⚠ **임계를 만들지 않는다**(v1.21.0에서 정한 원칙 — 「적정범위 평가는 하지
않는다」). 「N회 넘으면 경고」 같은 선을 그으면 그것이 판정이 된다. 대신
**모든 연도에 조건 없이** 분모를 병기해 발산의 원인이 그 자리에서 보이게 한다.
"""
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SERVER = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")


def test_추세표가_운전자본_분모를_병기한다():
    i = _SERVER.index('lines.append("**연도별 회전율 (기말잔액 기준)**")')
    body = _SERVER[i:i + 2200]
    assert 'if tkey == "working_capital":' in body, "운전자본만 특별 취급하지 않는다"
    assert '(운전자본 {_amt(_den)})' in body


def test_스냅숏도_병기한다():
    i = _SERVER.index('lines.append("**회전율 (기말잔액 기준)**")')
    body = _SERVER[i:i + 1800]
    assert '_tkey == "working_capital"' in body
    assert "운전자본 {" in body


def test_다른_지표에는_병기하지_않는다():
    """잔액 그 자체인 분모는 0에 가까워질 일이 드물다 — 표가 넓어질 뿐이다."""
    i = _SERVER.index('lines.append("**연도별 회전율 (기말잔액 기준)**")')
    body = _SERVER[i:i + 2200]
    for other in ("receivable", "inventory", "payable", "asset"):
        assert f'tkey == "{other}"' not in body, f"{other}에도 병기가 붙었다"


def test_임계를_만들지_않는다():
    """「N회 넘으면」 같은 선을 그으면 그것이 판정이 된다."""
    i = _SERVER.index('lines.append("**연도별 회전율 (기말잔액 기준)**")')
    body = _SERVER[i:i + 2200]
    assert not re.search(r"value.{0,12}[><]=?\s*\d{2,}", body), (
        "회전율 크기로 분기하는 임계가 들어갔다"
    )
    assert "_den is not None" in body, "값 유무로만 갈라야 한다"


def test_값이_없으면_병기하지_않는다():
    i = _SERVER.index('lines.append("**연도별 회전율 (기말잔액 기준)**")')
    body = _SERVER[i:i + 2200]
    assert 'cell != "—"' in body, "미계산 셀에 분모만 붙으면 이상하다"


def test_뷰어에도_같은_병기가_있다():
    i = _HTML.index("const parts = ascYears.map((y, i) => {")
    body = _HTML[i:i + 700]
    assert 'key === "workingCapital"' in body, "뷰어 키는 camelCase다"
    assert "운전자본 ${fmtKRW(ms[i].denominator)}" in body
    assert "ms[i].denominator !== null" in body, "분모가 없을 때를 가르지 않는다"


def test_뷰어도_임계를_쓰지_않는다():
    i = _HTML.index("const parts = ascYears.map((y, i) => {")
    body = _HTML[i:i + 700]
    assert not re.search(r"value\s*[><]=?\s*\d{2,}", body)
