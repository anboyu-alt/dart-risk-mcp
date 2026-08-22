"""뷰어 '주의' 배지 파생 규칙 (2026-08-22).

배지는 taxonomy severity에서 파생됐는데, 이 레포에서 severity는 "얼마나
심각한가"가 아니라 사실상 **"점수를 매기느냐"**로 쓰여 왔다(OBSERVATION =
base_score 0 = 사실 표기 전용). 두 의미가 달라서 무점수로 설계된 신호가
그대로 '참고'로 내려앉았다.

90일 코퍼스(공시 48,646건) 관찰 신호 2,913건 중 「상장폐지 결정·정리매매
개시」와 「관리종목 지정요건」 295건(10.1%)이 배지 없이 떴고, 같은 화면에서
「조회공시 요구」는 '주의'로 떴다.
"""
import json
import pathlib

import pytest

from dart_risk_mcp.core.taxonomy import TAXONOMY

import importlib.util

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_JSON = _ROOT / "docs" / "tool" / "signals-data.json"

_spec = importlib.util.spec_from_file_location(
    "export_tool_data", _ROOT / "scripts" / "export_tool_data.py"
)
_mod = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_mod)


@pytest.fixture(scope="module")
def exported():
    return {s["key"]: s for s in json.loads(_JSON.read_text(encoding="utf-8"))["signals"]}


class TestForcedPromotion:
    def test_퇴출_절차_신호가_주의로_표시된다(self, exported):
        """이용자가 가장 먼저 봐야 하는 사실이다."""
        for key in ("DELISTING_RISK", "WATCH_ISSUE", "DISTRESS_EVENT"):
            assert exported[key]["caution"] is True, key

    def test_승격_목록의_근거는_severity가_아니다(self):
        """승격 없이는 셋 다 '참고'로 내려앉는다 — 규칙이 실제로 필요함을 고정."""
        for key in _mod._CAUTION_FORCE_KEYS:
            sevs = [TAXONOMY.get(t, {}).get("severity")
                    for t in _mod._taxonomies_of(key)]
            assert not any(s in _mod._CAUTION_SEVERITIES for s in sevs), (
                f"{key}의 severity가 올라갔다면 승격 목록에서 빼는 것을 검토하라: {sevs}"
            )

    def test_같은_taxonomy라도_손익구조는_승격하지_않는다(self, exported):
        """8.5를 공유하지만 증가인지 감소인지조차 제목으로 알 수 없다."""
        assert exported["EARNINGS_SHOCK"]["caution"] is False
        assert "8.5" in _mod._taxonomies_of("EARNINGS_SHOCK")
        assert "8.5" in _mod._taxonomies_of("DELISTING_RISK")


class TestNoRegression:
    def test_기존_주의_신호가_그대로다(self, exported):
        for key in ("CB_BW", "SHAREHOLDER", "AUDIT", "INQUIRY", "GOING_CONCERN"):
            assert exported[key]["caution"] is True, key

    def test_양면적_신호는_참고를_유지한다(self, exported):
        """AMBIGUOUS_SIGNAL_KEYS와 같은 태도 — 배지가 붙으면 노이즈가 된다."""
        for key in ("FUND_OUTFLOW", "ACQ_REVIEW", "TREASURY", "TREASURY_TRUST"):
            assert exported[key]["caution"] is False, key

    def test_severity_원값은_여전히_미노출이다(self):
        raw = _JSON.read_text(encoding="utf-8")
        for banned in ("CRITICAL", "OBSERVATION", "base_score", "severity"):
            assert banned not in raw, banned
