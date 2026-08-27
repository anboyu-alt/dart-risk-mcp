"""DS005가 **상대방의 재무 실체**를 적는지 잠근다 (2026-08-27).

## 답이 같은 응답 안에 있었다

`fund_diversion_chain`의 「확인해볼 것」은 사용자에게 이렇게 안내한다 —

    - 상대 법인의 실체 — 타법인출자현황의 최초취득일·피출자사 손익

그 답의 일부가 **같은 DS005 응답 안에** 있는데 한 번도 읽지 않고 있었다.

    dlptn_cpt / dlptn_mbsn                    거래상대방 자본금·주요사업
    rbsnfdtl_tast / _tdbt / _teqt / _cpt      상대회사 자산·부채·자본·자본금

실측(40개사 DS005 40행): `dlptn_*`는 20행 중 13행, `rbsnfdtl_*`는 **20행
전부** 채워져 있다. 껍데기 법인은 여기서 바로 드러난다 — 실측 예로
자산 11.9억 · 부채 0.1억 · 자본 11.8억인데 **자본금이 12.1억**인 곳이
있었다(결손).

라이브: **다산디엠씨** — 「상대방 재무: 주요사업 네트워크 서비스 솔루션의
개발 및 공급 · 자본금 209억원」(특수관계 거래와 함께 표시된다).

⚠ **사실만 적는다** — 「껍데기」라고 부르지 않는다(v0.8.5 불변).
"""
import pytest

from dart_risk_mcp.core.dart_client import _normalize_decision
from dart_risk_mcp.server import _counterparty_substance


def _norm(raw):
    base = {"dlptn_cmpnm": "상대회사", "inhdtl_inhprc": "1,000",
            "inhdtl_tast_vs": "1.0"}
    base.update(raw)
    return _normalize_decision(base, "stock_acq", "")


class TestNormalize:
    def test_거래상대방_묶음(self):
        d = _norm({"dlptn_cpt": "20,981,453,000", "dlptn_mbsn": "IT 서비스"})
        assert d["cp_capital"] == 20_981_453_000
        assert d["cp_business"] == "IT 서비스"

    def test_상대회사_묶음(self):
        d = _norm({"rbsnfdtl_tast": "1,192,168,003",
                   "rbsnfdtl_tdbt": "11,106,778",
                   "rbsnfdtl_teqt": "1,181,061,225",
                   "rbsnfdtl_cpt": "1,205,880,000"})
        assert (d["cp_assets"], d["cp_debt"], d["cp_equity"]) == (
            1_192_168_003, 11_106_778, 1_181_061_225)
        assert d["cp_capital"] == 1_205_880_000

    def test_없으면_0이거나_빈_문자열(self):
        d = _norm({})
        assert d["cp_capital"] == 0 and d["cp_business"] == ""

    def test_개행을_접는다(self):
        assert _norm({"dlptn_mbsn": "가\n나"})["cp_business"] == "가 나"


class TestLine:
    def test_값이_있으면_적는다(self):
        s = _counterparty_substance({"cp_business": "IT 서비스",
                                     "cp_capital": 20_981_453_000})
        assert "주요사업 IT 서비스" in s and "자본금" in s

    def test_대시는_값이_아니다(self):
        """DART는 값이 없을 때 「-」를 넣는다 — 「주요사업 -」이 나왔었다."""
        assert _counterparty_substance({"cp_business": "-"}) == ""

    def test_아무것도_없으면_빈_문자열(self):
        assert _counterparty_substance({}) == ""
        assert _counterparty_substance({"cp_capital": 0}) == ""

    def test_재무_네_항목이_순서대로(self):
        s = _counterparty_substance({"cp_assets": 100, "cp_debt": 20,
                                     "cp_equity": 80, "cp_capital": 90})
        assert s.index("자산") < s.index("부채") < s.index("자본 ") < s.index("자본금")

    def test_판정_어휘를_쓰지_않는다(self):
        s = _counterparty_substance({"cp_assets": 1, "cp_equity": -5,
                                     "cp_capital": 100})
        for w in ("껍데기", "페이퍼", "위험", "의심", "부실"):
            assert w not in s


def test_렌더에_배선돼_있다():
    import pathlib

    import dart_risk_mcp.server as srv

    src = pathlib.Path(srv.__file__).read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert code.count("_counterparty_substance(") >= 3, "두 도구 모두에 붙어야 한다"
