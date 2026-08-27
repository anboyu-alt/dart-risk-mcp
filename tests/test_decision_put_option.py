"""DS005의 **풋옵션 등 계약**을 사실로 표기하는지 잠근다 (2026-08-27).

## 어떻게 찾았나

`currency`(#343)를 찾은 각도를 뒤집었다 — **응답에 있는데 소스 어디에도
이름조차 없는 필드**를 전수로 뽑았다(254종). 대부분은 도구가 일부러 안 내는
DS005 세부지만, 두 가지가 이 도구의 존재 이유와 정면으로 맞닿았다.

    popt_ctr_atn / popt_ctr_cn   풋옵션 등 계약 체결 여부·내용  (6개 엔드포인트)
    bdlst_atn / *_bdlst_sf_atn   우회상장 해당 여부            (4개 엔드포인트)

이면계약과 우회상장은 무자본 M&A 점검의 단골 수법이다.

## 실측이 하나만 고르게 했다 (40개사 DS005 40행, 2024-01~2026-08)

    popt_ctr_atn   「예」 **1건**(2.5%) — 내용이 실질적이다
    bdlst_atn      「예」 **0건** (해당사항없음 19 · 아니오 13)

풋옵션만 넣는다. 늘 「아니오」인 줄은 넣지 않는다 — CLAUDE.md 「새 신호 유형
추가」 0단계와 같은 판단이다.

라이브: **링크드** 20260212001692(타법인 주식 양도) —
「풋옵션 등 계약: 체결 — 각 교환사채의 사채권자는 사채의 발행일로부터
18개월이 되는 날 …조기상환…」. #321에서 자금 용도 이탈로 이미 걸린 회사다.
"""
import pytest

from dart_risk_mcp.core.dart_client import _normalize_decision


def _norm(raw):
    """`_normalize_decision(raw, dtype, url)` — 테스트에서는 유형·URL이
    결과에 영향을 주지 않는 값을 넣는다."""
    return _normalize_decision(raw, "stock_div", "")


def _raw(**over):
    base = {"dlptn_cmpnm": "상대회사", "inhdtl_inhprc": "1,000",
            "inhdtl_tast_vs": "1.0", "exevl_atn": "예"}
    base.update(over)
    return base


class TestNormalize:
    @pytest.mark.parametrize("v,want", [
        ("예", True), ("Y", True), ("아니오", False), ("-", False),
        ("", False), (None, False),
    ])
    def test_체결_여부(self, v, want):
        assert _norm(_raw(popt_ctr_atn=v))["put_option"] is want

    def test_내용의_개행을_접는다(self):
        d = _norm(_raw(popt_ctr_atn="예",
                                     popt_ctr_cn="가\n나  다"))
        assert d["put_option_text"] == "가 나 다"

    def test_필드가_없으면_거짓(self):
        d = _norm(_raw())
        assert d["put_option"] is False and d["put_option_text"] == ""

    def test_기존_필드를_건드리지_않는다(self):
        d = _norm(_raw(popt_ctr_atn="예"))
        assert d["counterparty"] == "상대회사"
        assert d["external_eval"] is True


class TestRender:
    def _render(self, raw):
        import dart_risk_mcp.server as srv

        norm = _norm(raw)
        with pytest.MonkeyPatch.context() as mp:
            mp.setattr(srv, "_DART_API_KEY", "k")
            mp.setattr(srv, "resolve_decision_type", lambda *a, **kw: "stock_div")
            mp.setattr(srv, "fetch_major_decision",
                       lambda *a, **kw: dict(norm, flags=[]))
            return srv.get_major_decision("20260212001692", "stock_div", "00000001")

    def test_체결이면_적는다(self):
        out = self._render(_raw(popt_ctr_atn="예", popt_ctr_cn="조기상환 조건"))
        assert "풋옵션 등 계약: 체결" in out
        assert "조기상환 조건" in out

    def test_아니면_줄을_만들지_않는다(self):
        assert "풋옵션" not in self._render(_raw(popt_ctr_atn="아니오"))

    def test_내용이_없어도_체결_사실은_적는다(self):
        out = self._render(_raw(popt_ctr_atn="예", popt_ctr_cn="-"))
        assert "풋옵션 등 계약: 체결" in out
        assert "체결 —" not in out


def test_우회상장은_넣지_않았다():
    """0건인 줄을 넣으면 늘 「아니오」가 한 줄 는다 — 근거를 남긴다."""
    import pathlib

    import dart_risk_mcp.server as srv

    src = pathlib.Path(srv.__file__).read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "bdlst_atn" not in code
