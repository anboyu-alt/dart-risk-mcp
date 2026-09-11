# -*- coding: utf-8 -*-
"""자금사용 접기 — 같은 조달건이 보고서마다 다른 모습으로 와도 접힌다.

2026-09-11 제보(기사 작성 중 발견). CSA 코스믹 3년 창이 **17건**을 냈는데
같은 회사 2025 사업보고서의 사모 자금사용은 **5건**이다.
`_collapse_fund_snapshots`가 **한 건도 접지 못했다**(고유 키 17/17).

원인이 셋이고 전부 DART 원본이다(라이브 확인).

1. **회차 칸이 보고서마다 다르다.** 같은 조달건(납입일 2023.07.12)이
   사업보고서에는 `tm="17"`, 분기·반기보고서에는 `tm="-"`로 온다.
2. **계획 용도 칸에 금액이 온다.** 2025 사업보고서는
   `mtrpt_cptal_use_plan_useprps="24,999"`(백만원)이고 2026 보고서는
   같은 칸이 `"운영자금"`이다 — 제출사가 그 칸을 다르게 채운다.
3. **계획 금액도 흔든다.** 같은 회차가 24,999,000,000 ↔ 25,000,000,000.

옛 키는 (조달유형, 회차, 납입일, 계획용도, 계획금액)이라 셋 중 어느 하나만
달라도 갈린다. 새 키는 **조달건**(조달유형·납입일·회차)으로 묶고, 그 그룹에서
**가장 최신 보고서 스냅샷의 행을 전부** 남긴다.

⚠ **한 스냅샷 안의 행은 절대 뭉개지 않는다.** 옛 키는 그것도 뭉개고 있었다 —
HLB 2026 반기 공모에서 `pay_de=""`·`plan_useprps=""`·`plan_amount=0`인
집행 행 8줄(타법인증권취득자금 132억·156억·449억…)이 키가 전부 같아
**한 줄로 접혔다**. 그래서 HLB는 새 키에서 21 → 40건으로 **늘어난다**.
이건 역행이 아니라 복구다.

실측(2026-09-11 · 30개사 · 2023~2026 · 4개 보고서코드 · raw 3,881건):
옛 876건 → 새 665건. CSA 코스믹 17 → 11.
"""
import unittest

from dart_risk_mcp.core import dart_client as dc


def _r(kind="private", year=2025, rc="11011", tm="-", pay_de="",
       plan="", amt=0, real="", realamt=0):
    return {
        "kind": kind, "year": year, "reprt_code": rc, "tm": tm,
        "pay_de": pay_de, "stlm_dt": "", "pay_pending": False,
        "pay_amount": 0, "plan_useprps": plan, "plan_amount": amt,
        "real_dtls_cn": real, "real_dtls_amount": realamt,
        "dffrnc_resn": "", "plan_cats": [], "real_cats": [], "flags": [],
    }


class TestCollapseAcrossReportShapes(unittest.TestCase):
    def test_회차_표기가_다른_같은_조달건은_한_건이다(self):
        """분기보고서 tm='-' ↔ 사업보고서 tm='17'."""
        recs = [
            _r(rc="11012", tm="-", pay_de="2023.07.12", plan="24,999", amt=24_999_000_000),
            _r(rc="11011", tm="17", pay_de="2023.07.12", plan="24,999", amt=24_999_000_000),
        ]
        out = dc._collapse_fund_snapshots(recs)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["tm"], "17", "최신 스냅샷(사업보고서)을 대표로")

    def test_계획용도_칸이_금액이어도_접힌다(self):
        """2025 '24,999' ↔ 2026 '운영자금' — 같은 조달건이다."""
        recs = [
            _r(year=2025, tm="17", pay_de="2023.07.12", plan="24,999", amt=24_999_000_000),
            _r(year=2026, tm="17", pay_de="2023.07.12", plan="운영자금", amt=25_000_000_000),
        ]
        out = dc._collapse_fund_snapshots(recs)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["year"], 2026)

    def test_같은_납입일의_다른_회차는_갈라둔다(self):
        """실측 CSA 코스믹 2025.12.24 — 제19회차(48억)와 제3회차(30억)."""
        recs = [
            _r(year=2026, tm="19", pay_de="2025.12.24", plan="운영자금", amt=4_800_000_000),
            _r(year=2026, tm="3", pay_de="2025.12.24", plan="운영자금", amt=3_000_000_000),
        ]
        self.assertEqual(len(dc._collapse_fund_snapshots(recs)), 2)

    def test_회차_둘_이상이면_빈_회차를_흡수하지_않는다(self):
        """어느 쪽 것인지 모르면 추정하지 않는다."""
        recs = [
            _r(year=2026, tm="19", pay_de="2025.12.24", amt=4_800_000_000),
            _r(year=2026, tm="3", pay_de="2025.12.24", amt=3_000_000_000),
            _r(year=2025, tm="-", pay_de="2025.12.24", amt=4_800_000_000),
        ]
        self.assertEqual(len(dc._collapse_fund_snapshots(recs)), 3)

    def test_한_스냅샷_안의_여러_행은_전부_남는다(self):
        """HLB 실측 — 계획 칸이 비고 실제만 있는 집행 행 여럿."""
        recs = [
            _r(kind="public", year=2026, rc="11012", real="타법인증권취득자금",
               realamt=13_210_000_000),
            _r(kind="public", year=2026, rc="11012", real="타법인증권취득자금",
               realamt=15_659_000_000),
            _r(kind="public", year=2026, rc="11012", real="타법인증권취득자금",
               realamt=44_920_000_000),
        ]
        out = dc._collapse_fund_snapshots(recs)
        self.assertEqual(len(out), 3, "같은 보고서의 서로 다른 집행이 뭉개졌다")

    def test_분기_순서대로_사업보고서가_최신이다(self):
        """1Q → 반기 → 3Q → 사업보고서."""
        recs = [
            _r(rc="11011", tm="17", pay_de="2023.07.12", real="사업"),
            _r(rc="11013", tm="17", pay_de="2023.07.12", real="1분기"),
            _r(rc="11014", tm="17", pay_de="2023.07.12", real="3분기"),
            _r(rc="11012", tm="17", pay_de="2023.07.12", real="반기"),
        ]
        out = dc._collapse_fund_snapshots(recs)
        self.assertEqual(len(out), 1)
        self.assertEqual(out[0]["real_dtls_cn"], "사업")

    def test_연도가_보고서코드보다_우선한다(self):
        recs = [
            _r(year=2026, rc="11013", tm="17", pay_de="2023.07.12", real="새해 1분기"),
            _r(year=2025, rc="11011", tm="17", pay_de="2023.07.12", real="작년 사업"),
        ]
        out = dc._collapse_fund_snapshots(recs)
        self.assertEqual(out[0]["real_dtls_cn"], "새해 1분기")

    def test_공모와_사모는_섞지_않는다(self):
        recs = [
            _r(kind="public", tm="1", pay_de="2025.01.01"),
            _r(kind="private", tm="1", pay_de="2025.01.01"),
        ]
        self.assertEqual(len(dc._collapse_fund_snapshots(recs)), 2)

    def test_보고서코드가_없어도_죽지_않는다(self):
        """옛 레코드(reprt_code 없음)도 그대로 다룬다."""
        recs = [{"kind": "private", "year": 2025, "tm": "1",
                 "pay_de": "2025.01.01", "plan_useprps": "a", "plan_amount": 1}]
        self.assertEqual(len(dc._collapse_fund_snapshots(recs)), 1)

    def test_정규화가_보고서코드를_싣는다(self):
        rec = dc._normalize_fund_usage({"tm": "17"}, "private", 2025, "11012")
        self.assertEqual(rec["reprt_code"], "11012")


class TestOrderIsStable(unittest.TestCase):
    def test_입력_순서를_보존한다(self):
        recs = [
            _r(tm="1", pay_de="2025.01.01"),
            _r(tm="2", pay_de="2025.02.02"),
            _r(tm="3", pay_de="2025.03.03"),
        ]
        out = dc._collapse_fund_snapshots(recs)
        self.assertEqual([r["tm"] for r in out], ["1", "2", "3"])


if __name__ == "__main__":
    unittest.main()
