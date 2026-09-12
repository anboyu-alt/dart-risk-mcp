"""감사·비감사 용역 블록(`loadAuditServices`)의 불변식.

core가 2026-08-23에 **「비감사용역 비중 30% 초과」 경고를 뺀** 이유를 뷰어가
되살리지 않게 잠근다 — 보수 금액의 단위가 회사마다 달라 비율이 1,000배로
부푼다(12개사 중 4개사 오탐이었다).

실측(2026-09-13):

    감사보수(adt_cntrct_dtls_mendng)   삼성전자 8,100 · 코아스 125 · 제이스코 280  (단위 없음)
    비감사보수(servc_mendng)           코아스 "10,000,000원" · 삼성전자 "43"        (혼용)

같은 화면에 「43」과 「10,000,000원」이 나란히 오므로 우리가 단위를 붙이거나
나눗셈을 하면 안 된다 — **원문 표기 그대로만** 옮긴다.
"""
import pathlib
import re

_HTML = pathlib.Path(__file__).parent.parent / "docs" / "tool" / "index.html"
_SRC = _HTML.read_text(encoding="utf-8")


def _fn(name: str) -> str:
    i = _SRC.find(f"async function {name}(")
    assert i >= 0, f"{name}을 찾지 못했다"
    depth = 0
    for j in range(i, len(_SRC)):
        if _SRC[j] == "{":
            depth += 1
        elif _SRC[j] == "}":
            depth -= 1
            if depth == 0:
                return _SRC[i:j + 1]
    raise AssertionError(f"{name}의 중괄호가 닫히지 않았다")


class TestAuditServices:
    def test_보수로_비중을_계산하지_않는다(self):
        """단위가 회사마다 달라 나누면 1,000배로 부푼다(core가 뺀 이유)."""
        body = _fn("loadAuditServices")
        for bad in ("servc_mendng /", "/ adt_cntrct_dtls_mendng",
                    "adt_cntrct_dtls_mendng /", "* 100"):
            assert bad not in body, f"보수로 비율을 만들고 있다: {bad!r}"
        assert "비중" not in body or "내지 않습니다" in body, (
            "「비중」을 말하려면 왜 내지 않는지 함께 적어야 한다"
        )

    def test_금액에_단위를_붙이지_않는다(self):
        """「43」이 백만원인지 원인지 우리는 모른다 — 원문 표기만 옮긴다."""
        body = _fn("loadAuditServices")
        assert "fmtKRW(" not in body, (
            "fmtKRW는 값을 원 단위로 가정한다 — 여기 오는 값은 단위가 불명확하다"
        )
        assert "원문 표기" in body, "표 머리에 원문 표기임을 밝혀야 한다"

    def test_빈_행을_뺀_사실을_밝힌다(self):
        """DART가 모든 칸이 `-`인 자리 행을 보낸다(실측 삼성전자 1건)."""
        body = _fn("loadAuditServices")
        assert "목록에서 뺐습니다" in body, "조용히 빼면 안 된다"

    def test_상한에_걸린_건수를_밝힌다(self):
        body = _fn("loadAuditServices")
        assert re.search(r"slice\(0,\s*10\)", body), "표시 상한이 있어야 한다"
        assert "건 생략" in body, "몇 건을 뺐는지 적지 않으면 조용한 절단이다"

    def test_판정_어휘를_쓰지_않는다(self):
        """같은 감사인이 비감사용역도 받는 것은 사실이지 우리의 판정이 아니다."""
        body = _fn("loadAuditServices")
        for bad in ("독립성", "부적절", "의심", "위반"):
            assert bad not in body, f"판정 어휘가 섞였다: {bad!r}"

    def test_실패와_부재를_가른다(self):
        body = _fn("loadAuditServices")
        assert "fetchFailHTML(" in body, "조회 실패를 「없음」으로 말하면 안 된다"
        assert '=== "013"' in body, "013(자료 없음)은 정상 응답이다"
