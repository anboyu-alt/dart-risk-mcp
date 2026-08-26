r"""규제기관 조치 태그를 정정공시로 오판하지 않는지 잠근다 (2026-08-26).

## 무엇이 잘못돼 있었나

`_AMENDMENT_RE`가 「`정정`으로 **시작**하는 태그」를 전부 정정공시로 읽었다.

    ^\[(?:기재정정|첨부추가|정정)[^\]]*\]

`[^\]]*` 꼬리 때문에 `[정정명령부과]`·`[정정제출요구]`가 걸린다. 이 둘은
회사가 스스로 낸 수정이 아니라 **금융당국이 그 공시가 미흡하다고 판단한
사실**이다. `match_signals`는 정정공시에 대해 빈 리스트를 돌려주므로,
제재를 받은 공시가 화면에서 **통째로 사라졌다**.

## 이미 알고 있었지만 우회로 막고 있었다

`qualifiers.is_false_amendment`의 docstring이 이 버그를 그대로 적고
있었다 — *"match_signals는 '[정정명령부과]증권신고서'를 정정공시로 오판해
신호를 통째로 삭제한다. 호출부는 이 함수가 True일 때만 접두를 벗겨
재매칭한다"*. 그런데 **소비처 일곱 중 둘만** 그렇게 하고 있었다
(`analyze_company_risk`·`build_event_timeline`). #307과 같은 미적용이다.

뿌리에서 고치면 모든 소비처가 자동으로 옳아지고 우회는 사라진다.

## 실측 (2026-04-28~2026-08-25 전수 76,331건 · 절단일 0)

    [기재정정] 13,959 · [첨부정정] 311 · [발행조건확정] 166 ·
    [첨부추가] 105 · [변경등록] 51 · [정정제출요구] 30 · [정정명령부과] 3

접미가 붙은 변형은 **하나도 없다**. 그래서 `[^\]]*` 꼬리를 떼도 잃는 것이
없고 규제기관 조치 둘만 빠진다.

⚠ `[첨부정정]`은 **여기 넣지 않는다** — 지금도 이 패턴에 안 걸리고 한정층
R5가 강등해 화면에 남는다. 넣으면 보이던 것이 사라진다(첫 수정에서 실제로
그렇게 만들었다가 되돌렸다).
"""
import pytest

from dart_risk_mcp.core.qualifiers import parse_report_name, qualify_signals
from dart_risk_mcp.core.signals import is_amendment_disclosure, match_signals


def _tier(nm):
    m = match_signals(nm)
    q = qualify_signals(m, parse_report_name(nm), {"report_nm": nm, "flr_nm": "회사"})
    return [x["key"] for x in m], [x.tier for x in q]


class TestAmendmentClassification:
    @pytest.mark.parametrize("nm", [
        "[기재정정]주요사항보고서(전환사채권발행결정)",
        "[첨부추가]주요사항보고서(유상증자결정)",
        "[정정]주요사항보고서(감자결정)",
    ])
    def test_진짜_정정은_그대로_정정이다(self, nm):
        assert is_amendment_disclosure(nm) is True
        assert match_signals(nm) == []

    @pytest.mark.parametrize("nm", [
        "[정정명령부과]주요사항보고서(회사합병결정)",
        "[정정제출요구]주요사항보고서(유상증자결정)",
    ])
    def test_규제기관_조치는_정정이_아니다(self, nm):
        assert is_amendment_disclosure(nm) is False
        keys, _ = _tier(nm)
        assert keys, "신호가 되살아나야 한다"

    def test_규제기관_조치는_관찰로_남는다(self):
        """당국이 정정을 명령한 사실은 사후 보고도 절차도 아니다."""
        _, tiers = _tier("[정정명령부과]주요사항보고서(회사합병결정)")
        assert tiers == ["observed"]

    def test_정정명령과_기재정정이_겹치면_강등된다(self):
        """실측 2건 — 두 태그가 함께 붙는다. 이건 정정이기도 하다."""
        keys, tiers = _tier("[정정명령부과][기재정정]주요사항보고서(회사합병결정)")
        assert keys and set(tiers) == {"procedural"}

    def test_첨부정정은_종전대로_강등이다(self):
        """정정 패턴에 넣지 않는다 — 넣으면 보이던 것이 사라진다."""
        assert is_amendment_disclosure("[첨부정정]주요사항보고서(회사합병결정)") is False
        keys, tiers = _tier("[첨부정정]주요사항보고서(회사합병결정)")
        assert keys and set(tiers) == {"procedural"}

    @pytest.mark.parametrize("nm", [
        "[발행조건확정]증권신고서(채무증권)",
        "[변경등록]증권신고서(집합투자증권)",
    ])
    def test_정정이_아닌_다른_태그는_불변(self, nm):
        assert is_amendment_disclosure(nm) is False


class TestNoWorkaroundLeft:
    def test_우회가_제거됐다(self):
        """`is_false_amendment`를 부르는 곳이 남아 있으면 두 판정이 갈린다."""
        import pathlib

        root = pathlib.Path(__file__).resolve().parents[1]
        for rel in ["dart_risk_mcp/server.py", "docs/tool/index.html"]:
            src = root.joinpath(rel).read_text(encoding="utf-8")
            code = "\n".join(
                ln for ln in src.splitlines()
                if not ln.lstrip().startswith(("#", "//"))
            )
            assert "isFalseAmendment(" not in code, rel
            assert "is_false_amendment(" not in code, rel

    def test_뷰어가_같은_패턴을_받는다(self):
        """뷰어는 `signals-data.json`의 `amendment_pattern`을 쓴다 —
        core 수정이 자동으로 넘어가는지 확인한다."""
        import json
        import pathlib
        import re

        root = pathlib.Path(__file__).resolve().parents[1]
        data = json.loads((root / "docs" / "tool" / "signals-data.json")
                          .read_text(encoding="utf-8"))
        pat = re.compile(data["amendment_pattern"])
        assert pat.match("[기재정정]주요사항보고서(유상증자결정)")
        assert not pat.match("[정정명령부과]주요사항보고서(회사합병결정)")
        assert not pat.match("[첨부정정]주요사항보고서(회사합병결정)")
