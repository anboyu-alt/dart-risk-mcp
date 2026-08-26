r"""임원 보수 5섹션이 실제 응답 필드와 맞는지 잠근다 (2026-08-26).

골드를 보다 ④의 값이 ②와 **똑같이** 보이는 것이 이상해서 열었다.
네 섹션이 전부 어긋나 있었다 — 응답 키를 실제로 떠서 확인했다.

| 섹션 | 무엇이 틀렸나 |
|---|---|
| ① | `hmvAuditAllSttus`는 이사·감사 **전체 총계**다. `nm`·`ofcps`가 없어 「성명: - \| 직위: -」로 나왔고 라벨도 「5억 이상 고액수령자」(명단)였다 |
| ② | `indvdlByPay`에 `stk_optn_exrcs_mny`가 없다 → 스톡옵션행사액이 늘 「-」 |
| ③ | 총액 필드는 `fyer_salary_totamt`인데 `mendng_totamt`를 읽었다 → 삼성전자 **7,054억**이 「-」 |
| ④ | 「주총 승인 보수한도」가 실은 `hmvAuditIndvdlBySttus`(이사·감사 **개인별 보수**)였다 |

진짜 한도는 `drctrAdtAllMendngSttusGmtsckConfmAmount`이고, 붙이고 나서야
삼성전자 「계 360억」이 처음 나왔다.

⚠ `ofcps`에는 개행이 섞여 온다("부회장\n(대표이사)") — 접지 않으면 표가
깨진다. `report_resn`(#328)과 같은 함정이다.
"""
import json
import pathlib

import pytest

import dart_risk_mcp.server as srv

_KEYS = json.loads((pathlib.Path(__file__).resolve().parents[1] / "tests"
                    / "fixtures" / "api" / "response_keys.json")
                   .read_text(encoding="utf-8"))["endpoints"]

_DATA = {
    "high_pay": [{"nmpr": "9", "mendng_totamt": "28,052,000,000",
                  "jan_avrg_mendng_am": "3,006,000,000"}],
    "individual": [{"nm": "한종희", "ofcps": "부회장\n(대표이사)",
                    "mendng_totamt": "13,407,000,000"}],
    "unregistered": [{"se": "미등기임원", "nmpr": "989",
                      "fyer_salary_totamt": "705,452,000,000",
                      "jan_salary_am": "744,000,000"}],
    "audit_indv": [{"nm": "이재용", "ofcps": "회장",
                    "mendng_totamt": "1,843,000,000"}],
    "agm_limit": [{"se": "계", "nmpr": "10",
                   "gmtsck_confm_amount": "36,000,000,000"}],
}


def _render(data=None):
    with pytest.MonkeyPatch.context() as mp:
        mp.setattr(srv, "_DART_API_KEY", "k")
        mp.setattr(srv, "resolve_corp",
                   lambda q, k: ("삼성전자", {"corp_code": "00126380"}))
        mp.setattr(srv, "fetch_executive_compensation",
                   lambda *a, **kw: data if data is not None else _DATA)
        return srv.get_executive_compensation("삼성전자")


class TestFieldsExist:
    """읽는 필드가 그 엔드포인트 응답에 실제로 있는가."""

    @pytest.mark.parametrize("ep,fields", [
        ("hmvAuditAllSttus", ["nmpr", "mendng_totamt", "jan_avrg_mendng_am"]),
        ("indvdlByPay", ["nm", "ofcps", "mendng_totamt"]),
        ("unrstExctvMendngSttus", ["se", "nmpr", "fyer_salary_totamt",
                                   "jan_salary_am"]),
        ("hmvAuditIndvdlBySttus", ["nm", "ofcps", "mendng_totamt"]),
    ])
    def test_필드가_응답에_있다(self, ep, fields):
        have = set(_KEYS[ep])
        assert have, f"{ep} 응답 키가 픽스처에 없다"
        for f in fields:
            assert f in have, f"{ep}에 {f}가 없다"

    def test_없던_필드를_다시_읽지_않는다(self):
        src = pathlib.Path(srv.__file__).read_text(encoding="utf-8")
        code = "\n".join(ln for ln in src.splitlines()
                         if not ln.lstrip().startswith("#"))
        assert "stk_optn_exrcs_mny" not in code


class TestSections:
    def test_다섯_섹션이_나온다(self):
        out = _render()
        for h in ["① 이사·감사 전체 보수", "② 개인별 보수", "③ 미등기임원 보수",
                  "④ 이사·감사 개인별 보수", "⑤ 주총 승인 보수한도"]:
            assert h in out, h

    def test_미등기임원_총액이_나온다(self):
        assert "705,452,000,000" in _render()

    def test_주총_한도가_나온다(self):
        assert "36,000,000,000" in _render()

    def test_전체_총계에_이름을_묻지_않는다(self):
        """①은 총계라 이름이 없다 — 성명 칸을 만들면 늘 「-」다."""
        body = [l for l in _render().splitlines() if "인원수: 9" in l][0]
        assert "성명" not in body

    def test_직위의_개행을_접는다(self):
        body = [l for l in _render().splitlines() if "한종희" in l][0]
        assert "부회장 (대표이사)" in body
        assert body.count("|") == 2, "행이 찢어졌다"

    def test_자료가_없으면_공시_없음(self):
        empty = {k: [] for k in _DATA}
        assert _render(empty).count("(공시 없음)") == 5
