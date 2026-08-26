"""계획↔실제 **용도 묶음**이 갈리면 FUND_DIVERSION이 발화하는지 잠근다.

## 왜 필요했나 — 해설이 약속한 것을 코드가 안 봤다

`FUND_DIVERSION`의 해설은 이렇게 적혀 있다:

    "유상증자나 CB 발행 공시에 적어둔 자금 사용 계획(예: '신규 사업 투자')과
     실제 집행 내역(예: '기존 차입금 상환')이 다르게 기재된 상태입니다."

그런데 판정은 `dffrnc_occrrnc_resn`(차이사유) 문구에 「목적 변경」류 정형
법정 표현이 있는지만 봤다. **계획과 실제를 서로 비교한 적이 없다.**
15개사 429건 표본에서 발화 0건이었고(2026-08-03 기록), CLAUDE.md는 진짜
사례 6건(본느·링크드·형지엘리트·비에스제이홀딩스)이 전부 미포착이라고
적어 두었다.

## 실측 (2026-08-26 · 30개사 2,877건)

양쪽이 다 기재된 2,343건 중 **94%가 분류**되고 **7.2%가 이탈**한다.
도구 판정으로는 2,877건 중 **160건(5.6%) · 14개사**가 발화한다.

    시설·자산 → 운영자금   57      운영자금 → 채무 상환    39
    운영자금 → 타법인 취득  26      채무 상환 → 시설·자산   11

⚠ **묶음을 잘게 쪼개면 안 된다.** 1차 측정에서 여덟 묶음으로 나눴더니
정상 집행이 이탈로 잡혔다 — 원재료 매입·매입채무 결제는 실질이 운영자금
이고(이엠앤아이), "R&D 센터 인프라 투자"는 실질이 시설자금이며(피아이이),
본사 부동산 취득은 시설과 같은 묶음이다. 그래서 넷으로 합쳤다.
"""
import pytest

from dart_risk_mcp.core.dart_client import (
    _detect_fund_anomaly,
    classify_fund_use,
)


def _rec(plan, real, plan_amount=1000, real_amount=1000, dffrnc=""):
    return {
        "plan_useprps": plan, "real_dtls_cn": real,
        "plan_amount": plan_amount, "real_dtls_amount": real_amount,
        "dffrnc_resn": dffrnc,
        "plan_cats": sorted(classify_fund_use(plan)),
        "real_cats": sorted(classify_fund_use(real)),
    }


class TestClassify:
    @pytest.mark.parametrize("text,want", [
        ("운영자금", {"운영자금"}),
        ("운영 자금", {"운영자금"}),
        ("운전자금", {"운영자금"}),
        ("타법인증권취득자금", {"타법인 취득"}),
        ("채무상환자금", {"채무 상환"}),
        ("시설자금", {"시설·자산"}),
        ("자산취득", {"시설·자산"}),
        ("", set()),
        ("-", set()),
        ("기타", set()),
    ])
    def test_실측_표기를_읽는다(self, text, want):
        assert classify_fund_use(text) == want

    def test_줄바꿈이_껴도_읽는다(self):
        """DART 기재는 「운영자금\n(게임개발)」처럼 줄바꿈이 낀다(티쓰리 실측)."""
        assert classify_fund_use("운영자금\n(게임개발)") == {"운영자금"}

    def test_인공물_묶음(self):
        """1차 측정에서 오탐을 만들던 표기가 같은 묶음에 들어간다."""
        assert classify_fund_use("원재료 매입채무 결제") == {"운영자금"}
        assert classify_fund_use("R&D 센터 인프라 투자") == {"시설·자산"}
        assert classify_fund_use("본사 부동산 추가 취득") == {"시설·자산"}


class TestDetect:
    def test_묶음이_갈리면_발화한다(self):
        """링크드 실측 — 계획 「운영자금」, 실제 「타법인증권취득자금」."""
        assert "FUND_DIVERSION" in _detect_fund_anomaly(
            _rec("운영자금", "타법인증권취득자금"))

    def test_같은_묶음이면_발화하지_않는다(self):
        assert "FUND_DIVERSION" not in _detect_fund_anomaly(
            _rec("운영자금", "운영자금"))

    def test_묶음이_겹치기만_해도_발화하지_않는다(self):
        """「운영자금 및 시설자금」 → 「시설자금」은 계획 안의 집행이다."""
        assert "FUND_DIVERSION" not in _detect_fund_anomaly(
            _rec("운영자금 및 시설자금", "시설자금"))

    @pytest.mark.parametrize("plan,real", [
        ("", "채무상환자금"), ("운영자금", ""), ("-", "-"), ("기타", "기타"),
    ])
    def test_못_읽으면_판정하지_않는다(self, plan, real):
        assert "FUND_DIVERSION" not in _detect_fund_anomaly(_rec(plan, real))

    def test_기존_차이사유_경로가_살아_있다(self):
        """묶음이 같아도 차이사유에 「목적변경」이 있으면 종전대로 발화한다."""
        assert "FUND_DIVERSION" in _detect_fund_anomaly(
            _rec("운영자금", "운영자금", dffrnc="자금 사용 목적변경"))

    def test_미보고_판정은_건드리지_않는다(self):
        f = _detect_fund_anomaly(_rec("운영자금", "", real_amount=0))
        assert "FUND_UNREPORTED" in f


class TestPrecisionRationale:
    def test_묶음이_넷이다(self):
        """더 쪼개면 정상 집행이 이탈로 잡힌다 — 실측 근거는 docstring 참고."""
        from dart_risk_mcp.core.dart_client import _FUND_USE_CATEGORIES

        assert len(_FUND_USE_CATEGORIES) == 4

    def test_해설이_이_판정을_설명한다(self):
        """해설과 판정이 어긋나 있던 것이 이 수정의 출발점이다."""
        from dart_risk_mcp.core.explain import flag_to_prose

        _, body = flag_to_prose("FUND_DIVERSION")
        assert "실제 집행 내역" in body

    def test_렌더가_근거를_낸다(self):
        import pathlib

        src = (pathlib.Path(__file__).resolve().parents[1]
               / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
        assert "용도 분류: 계획" in src
