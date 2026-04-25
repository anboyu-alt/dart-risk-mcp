"""v0.8.6 — fetch_insider_timeline 분기 보고 보강 + INSIDER_PRE_DISCLOSURE.

검증:
1. fetch_insider_timeline이 신규 두 엔드포인트(hyslrChgSttus, tesstkAcqsDspsSttus)를
   4개 분기 reprt_code(11011·11012·11013·11014)로 호출하고 source 라벨로 구분한다.
2. 일부 엔드포인트 실패는 다른 결과를 막지 않는다.
3. detect_insider_pre_disclosure는 매도 이벤트 ±30일 내 부정적 공시(AUDIT/INSOLVENCY/
   EMBEZZLE/INQUIRY/GOING_CONCERN 등)가 있으면 INSIDER_PRE_DISCLOSURE 플래그를 부여한다.
4. signals.py / taxonomy.py에 INSIDER_PRE_DISCLOSURE(3.6) 키와 슬롯이 등록돼 있다.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from dart_risk_mcp.core import dart_client
from dart_risk_mcp.core.signals import SIGNAL_KEY_TO_TAXONOMY, SIGNAL_TYPES
from dart_risk_mcp.core.taxonomy import TAXONOMY


# ---------- helpers ----------

def _resp(status: str = "000", lst: list | None = None) -> MagicMock:
    r = MagicMock()
    r.json.return_value = {
        "status": status,
        "message": "정상" if status == "000" else "데이터 없음",
        "list": lst or [],
    }
    return r


def _make_side_effect_v086(
    elestock_lst: list | None = None,
    hyslr_lst: list | None = None,
    hyslr_chg_lst: list | None = None,
    exec_treas_lst: list | None = None,
):
    """엔드포인트별로 다른 응답을 반환. 분기 reprt_code 무관."""
    elestock_lst = elestock_lst or []
    hyslr_lst = hyslr_lst or []
    hyslr_chg_lst = hyslr_chg_lst or []
    exec_treas_lst = exec_treas_lst or []

    def _side(method, url, **kwargs):
        if "elestock" in url:
            return _resp(lst=elestock_lst)
        if "hyslrSttus" in url:
            return _resp(lst=hyslr_lst)
        if "hyslrChgSttus" in url:
            return _resp(lst=hyslr_chg_lst)
        if "tesstkAcqsDspsSttus" in url:
            return _resp(lst=exec_treas_lst)
        return _resp(status="013")

    return _side


# ---------- TestFetchInsiderTimelineV086 ----------

class TestFetchInsiderTimelineV086(unittest.TestCase):

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_tags_hyslr_chg_source(self, mock_retry):
        # mock는 url 매칭으로 모든 (연도×분기) 호출에 동일 응답을 반환하므로
        # source 라벨 부착 자체와 핵심 필드 보존만 검증한다.
        mock_retry.side_effect = _make_side_effect_v086(
            hyslr_chg_lst=[{
                "rcept_no": "20250410000123",
                "change_on": "20250408",
                "mxmm_shrholdr_nm": "홍길동",
                "qota_rt": "12.34",
                "change_cause": "장내매수",
            }],
        )
        records = dart_client.fetch_insider_timeline("00000001", "KEY", 1)
        chg = [r for r in records if r.get("source") == "hyslr_chg"]
        self.assertGreater(len(chg), 0)
        self.assertEqual(chg[0]["change_on"], "20250408")
        self.assertEqual(chg[0]["mxmm_shrholdr_nm"], "홍길동")

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_tags_exec_treasury_source(self, mock_retry):
        mock_retry.side_effect = _make_side_effect_v086(
            exec_treas_lst=[{
                "rcept_no": "20250317000929",
                "stock_knd": "보통주",
                "acqs_mth1": "배당가능이익범위 이내 취득",
                "acqs_mth2": "직접취득",
                "acqs_mth3": "장내직접취득",
                "bsis_qy": "1000000",
            }],
        )
        records = dart_client.fetch_insider_timeline("00000001", "KEY", 1)
        et = [r for r in records if r.get("source") == "exec_treasury"]
        self.assertGreater(len(et), 0)
        self.assertEqual(et[0]["stock_knd"], "보통주")
        self.assertEqual(et[0]["acqs_mth2"], "직접취득")

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_calls_four_quarter_reprt_codes(self, mock_retry):
        """신규 엔드포인트는 11011·11012·11013·11014 4개 분기 코드 모두 호출."""
        mock_retry.side_effect = _make_side_effect_v086()  # 모두 빈 응답
        dart_client.fetch_insider_timeline("00000001", "KEY", 1)

        # hyslrChgSttus URL에 대해 호출된 reprt_code 집합 수집
        codes_chg = set()
        codes_exec = set()
        for call in mock_retry.call_args_list:
            url = call.args[1] if len(call.args) > 1 else call.kwargs.get("url", "")
            params = call.kwargs.get("params") or {}
            rc = params.get("reprt_code")
            if "hyslrChgSttus" in url and rc:
                codes_chg.add(rc)
            if "tesstkAcqsDspsSttus" in url and rc:
                codes_exec.add(rc)

        self.assertEqual(codes_chg, {"11011", "11012", "11013", "11014"})
        self.assertEqual(codes_exec, {"11011", "11012", "11013", "11014"})

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_partial_endpoint_failure_isolated(self, mock_retry):
        """신규 엔드포인트가 모두 실패해도 elestock/hyslrSttus 결과는 보존."""
        def _side(method, url, **kwargs):
            if "elestock" in url:
                return _resp(lst=[{"rcept_no": "20250101", "stkqy_rt": "5.5", "repror": "A"}])
            if "hyslrSttus" in url:
                return _resp(lst=[{"nm": "최대주주A", "trmend_posesn_stock_qota_rt": "30.0"}])
            # 신규 두 개 모두 실패
            return _resp(status="800")
        mock_retry.side_effect = _side

        records = dart_client.fetch_insider_timeline("00000001", "KEY", 1)
        sources = [r.get("source") for r in records]
        self.assertIn("elestock", sources)
        self.assertIn("hyslr", sources)
        # 신규 두 source는 실패해서 0건
        self.assertEqual(sum(1 for s in sources if s in {"hyslr_chg", "exec_treasury"}), 0)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_quarter_failure_silent(self, mock_retry):
        """일부 분기에서 status=013이어도 다른 분기는 정상 반환."""
        call_count = {"chg": 0}

        def _side(method, url, **kwargs):
            if "hyslrChgSttus" in url:
                call_count["chg"] += 1
                # 짝수 호출만 데이터 반환
                if call_count["chg"] % 2 == 0:
                    return _resp(lst=[{
                        "rcept_no": f"2025040800012{call_count['chg']}",
                        "change_on": "20250408",
                        "mxmm_shrholdr_nm": "홍길동",
                        "qota_rt": "12.34",
                    }])
                return _resp(status="013")
            return _resp(status="013")

        mock_retry.side_effect = _side
        records = dart_client.fetch_insider_timeline("00000001", "KEY", 1)
        chg = [r for r in records if r.get("source") == "hyslr_chg"]
        self.assertGreater(len(chg), 0, "분기 부분 실패가 전체를 막아선 안 됨")


# ---------- TestDetectInsiderPreDisclosure ----------

class TestDetectInsiderPreDisclosure(unittest.TestCase):
    """detect_insider_pre_disclosure(insider_records, signal_events, window_days=30)."""

    def test_flags_sell_within_window_of_negative_disclosure(self):
        """매도 이벤트 + ±30일 내 AUDIT/INSOLVENCY 등 부정 공시 → 플래그."""
        insider_records = [
            {"holder": "홍길동", "rcept_dt": "20250410", "delta_pct": -1.2,
             "source": "hyslr_chg"},
        ]
        signal_events = [
            {"key": "AUDIT", "rcept_dt": "20250420", "report_nm": "감사보고서"},
        ]
        flags = dart_client.detect_insider_pre_disclosure(insider_records, signal_events)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["holder"], "홍길동")
        self.assertEqual(flags[0]["sell_date"], "20250410")
        self.assertEqual(flags[0]["disclosure_key"], "AUDIT")

    def test_no_flag_when_disclosure_outside_window(self):
        insider_records = [
            {"holder": "홍길동", "rcept_dt": "20250101", "delta_pct": -1.2,
             "source": "hyslr_chg"},
        ]
        signal_events = [
            {"key": "AUDIT", "rcept_dt": "20250601", "report_nm": "감사보고서"},
        ]
        flags = dart_client.detect_insider_pre_disclosure(insider_records, signal_events)
        self.assertEqual(flags, [])

    def test_no_flag_for_buy_event(self):
        insider_records = [
            {"holder": "홍길동", "rcept_dt": "20250410", "delta_pct": +1.2,
             "source": "hyslr_chg"},
        ]
        signal_events = [
            {"key": "INSOLVENCY", "rcept_dt": "20250420"},
        ]
        flags = dart_client.detect_insider_pre_disclosure(insider_records, signal_events)
        self.assertEqual(flags, [])

    def test_ignores_non_negative_signal_keys(self):
        """CB_BW 같은 일반 신호는 부정 공시로 보지 않음."""
        insider_records = [
            {"holder": "홍길동", "rcept_dt": "20250410", "delta_pct": -1.2},
        ]
        signal_events = [
            {"key": "CB_BW", "rcept_dt": "20250415"},
        ]
        flags = dart_client.detect_insider_pre_disclosure(insider_records, signal_events)
        self.assertEqual(flags, [])

    def test_empty_inputs(self):
        self.assertEqual(dart_client.detect_insider_pre_disclosure([], []), [])
        self.assertEqual(
            dart_client.detect_insider_pre_disclosure(
                [{"holder": "A", "rcept_dt": "20250410", "delta_pct": -1.0}], []
            ),
            [],
        )


# ---------- TestSignalsRegistration ----------

class TestInsiderPreDisclosureRegistration(unittest.TestCase):

    def test_signal_key_in_taxonomy_map(self):
        self.assertIn("INSIDER_PRE_DISCLOSURE", SIGNAL_KEY_TO_TAXONOMY)
        self.assertEqual(SIGNAL_KEY_TO_TAXONOMY["INSIDER_PRE_DISCLOSURE"], ["3.6"])

    def test_signal_type_registered(self):
        keys = {s["key"] for s in SIGNAL_TYPES}
        self.assertIn("INSIDER_PRE_DISCLOSURE", keys)

    def test_taxonomy_3_6_exists(self):
        self.assertIn("3.6", TAXONOMY)
        node = TAXONOMY["3.6"]
        self.assertEqual(node.get("id"), "3.6")
        # 사실 표기만(점수 가산 없음)
        self.assertEqual(node.get("base_score"), 0)
        self.assertTrue(node.get("category"), "category 라벨 누락")


if __name__ == "__main__":
    unittest.main()
