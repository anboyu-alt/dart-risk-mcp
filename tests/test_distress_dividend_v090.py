"""v0.9.0 — 부실 후속(#7) + 배당 이상(#10) 흡수 검증.

검증:
1. fetch_distress_events는 4개 엔드포인트(dfOcr·bsnSp·ctrcvsBgrq·dsRsOcr)를
   lookback_years 기간으로 호출하고 subtype 라벨로 구분한다.
2. 응답에 rcept_dt 누락 시 rcept_no[:8]로 폴백.
3. 일부 엔드포인트 실패는 다른 결과를 막지 않는다.
4. fetch_dividend_history는 alotMatter를 분기 4코드 × N년으로 호출해
   각 record에 bsns_year/reprt_code 부착.
5. detect_dividend_drain은 (당기 적자 AND 배당 양수)이면 DIVIDEND_DRAIN 플래그.
6. signals.py / taxonomy.py에 DISTRESS_EVENT(8.5), DIVIDEND_DRAIN(5.6) 등록.
"""
from __future__ import annotations

import unittest
from unittest.mock import MagicMock, patch

from dart_risk_mcp.core import dart_client
from dart_risk_mcp.core.signals import SIGNAL_KEY_TO_TAXONOMY, SIGNAL_TYPES
from dart_risk_mcp.core.taxonomy import TAXONOMY


def _resp(status: str = "000", lst: list | None = None) -> MagicMock:
    r = MagicMock()
    r.json.return_value = {
        "status": status,
        "message": "정상" if status == "000" else "데이터 없음",
        "list": lst or [],
    }
    return r


# ---------- TestFetchDistressEvents ----------

class TestFetchDistressEvents(unittest.TestCase):
    def setUp(self):
        cache = getattr(dart_client, "_distress_events_cache", None)
        if cache is not None:
            cache.clear()

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_normalizes_each_subtype(self, mock_retry):
        def _side(method, url, **kwargs):
            if "dfOcr" in url:
                return _resp(lst=[{
                    "rcept_no": "20250520000001",
                    "rcept_dt": "20250520",
                    "df_cn": "당좌거래정지",
                    "df_amt": "1500000000",
                    "df_bnk": "K은행",
                    "dfd": "20250515",
                }])
            if "bsnSp" in url:
                return _resp(lst=[{
                    "rcept_no": "20250620000002",
                    "rcept_dt": "20250620",
                    "bsnsp_cn": "관리종목 사유 영업정지",
                    "bsnspd": "20250619",
                }])
            if "ctrcvsBgrq" in url:
                return _resp(lst=[{
                    "rcept_no": "20250720000003",
                    "rcept_dt": "20250720",
                    "rs": "회생절차 개시신청",
                }])
            if "dsRsOcr" in url:
                return _resp(lst=[{
                    "rcept_no": "20250820000004",
                    "rcept_dt": "20250820",
                    "ds_rs": "주총 해산결의",
                    "ds_rsd": "20250815",
                }])
            return _resp(status="013")

        mock_retry.side_effect = _side
        events = dart_client.fetch_distress_events("00000001", "KEY", 3)

        subtypes = {e["subtype"] for e in events}
        self.assertEqual(subtypes,
                         {"default", "business_susp", "rehabilitation", "dissolution"})
        for e in events:
            self.assertEqual(e["key"], "DISTRESS_EVENT")
            self.assertTrue(e["rcept_dt"])
            self.assertTrue(e["summary"])

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_falls_back_to_rcept_no(self, mock_retry):
        def _side(method, url, **kwargs):
            if "dfOcr" in url:
                return _resp(lst=[{"rcept_no": "20250520000099", "df_cn": "X"}])
            return _resp(status="013")

        mock_retry.side_effect = _side
        events = dart_client.fetch_distress_events("00000001", "KEY", 3)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["rcept_dt"], "20250520")

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_partial_endpoint_failure_isolated(self, mock_retry):
        def _side(method, url, **kwargs):
            if "dfOcr" in url:
                return _resp(lst=[{"rcept_no": "20250520000001",
                                   "rcept_dt": "20250520", "df_cn": "x"}])
            return _resp(status="800")

        mock_retry.side_effect = _side
        events = dart_client.fetch_distress_events("00000001", "KEY", 3)
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["subtype"], "default")

    def test_rejects_empty_inputs(self):
        self.assertEqual(dart_client.fetch_distress_events("", "KEY", 3), [])
        self.assertEqual(dart_client.fetch_distress_events("X", "", 3), [])


# ---------- TestFetchDividendHistory ----------

class TestFetchDividendHistory(unittest.TestCase):
    def setUp(self):
        cache = getattr(dart_client, "_dividend_history_cache", None)
        if cache is not None:
            cache.clear()

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_collects_alot_matter_with_year_label(self, mock_retry):
        def _side(method, url, **kwargs):
            if "alotMatter" not in url:
                return _resp(status="013")
            params = kwargs.get("params") or {}
            year = params.get("bsns_year")
            return _resp(lst=[{
                "rcept_no": f"{year}05200000",
                "se": "주당 현금배당금(원)",
                "stock_knd": "보통주",
                "thstrm": "500",
                "frmtrm": "300",
                "lwfr": "200",
                "stlm_dt": f"{year}-12-31",
            }])

        mock_retry.side_effect = _side
        recs = dart_client.fetch_dividend_history("00000001", "KEY", 2)
        # 분기 4코드 × N년이지만 일부 엔드포인트는 status=013으로 빠지므로
        # 최소 1건 이상 보장. bsns_year 라벨은 record에 부착됨.
        self.assertGreater(len(recs), 0)
        for r in recs:
            self.assertTrue(r.get("bsns_year"))
            self.assertEqual(r["se"], "주당 현금배당금(원)")

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_skips_non_zero_status(self, mock_retry):
        mock_retry.side_effect = lambda *a, **kw: _resp(status="013")
        self.assertEqual(
            dart_client.fetch_dividend_history("00000001", "KEY", 2), []
        )


# ---------- TestDetectDividendDrain ----------
#
# v1.6.x 재설계: alotMatter(dividend_records) 자체가 같은 (bsns_year,
# reprt_code) 그룹 안에 현금배당금총액(백만원)과 (연결)/(별도)
# 당기순이익(백만원)을 함께 담고 있다는 사실(2026-07-30 두산 실측,
# corp_code=00117212)에 기대 — 별도 current_fs 인자 없이 dividend_records
# 하나만 받는다. se는 느슨한 substring이 아니라 정확히 일치해야 한다
# ("주당 현금배당금(원)"은 단가·원 단위라 총액·백만원 단위인
# "현금배당금총액(백만원)"과 다른 개념 — 실측으로 확정).

def _mk_rec(bsns_year, reprt_code, se, thstrm):
    return {"bsns_year": bsns_year, "reprt_code": reprt_code, "se": se, "thstrm": thstrm}


class TestDetectDividendDrain(unittest.TestCase):
    def test_flags_cfs_when_loss_and_dividend(self):
        dividend_records = [
            _mk_rec("2024", "11011", "현금배당금총액(백만원)", "35,772"),
            _mk_rec("2024", "11011", "(연결)당기순이익(백만원)", "-581,169"),
            _mk_rec("2024", "11011", "(별도)당기순이익(백만원)", "175,466"),
        ]
        flags = dart_client.detect_dividend_drain(dividend_records)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["bsns_year"], "2024")
        self.assertEqual(flags[0]["reprt_code"], "11011")
        self.assertEqual(flags[0]["fs_div"], "CFS")
        self.assertEqual(flags[0]["dividend"], 35772.0)
        self.assertEqual(flags[0]["net_income"], -581169.0)

    def test_flags_both_cfs_and_ofs_separately_when_both_negative(self):
        # 두산(00117212) 2023 실측 재현: 연결·별도 둘 다 음수 + 배당 존재
        # → 병합된 판정이 아니라 fs_div별로 각각 별개 플래그가 나와야 한다.
        dividend_records = [
            _mk_rec("2023", "11011", "현금배당금총액(백만원)", "35,772"),
            _mk_rec("2023", "11011", "(연결)당기순이익(백만원)", "-388,279"),
            _mk_rec("2023", "11011", "(별도)당기순이익(백만원)", "-111,873"),
        ]
        flags = dart_client.detect_dividend_drain(dividend_records)
        self.assertEqual(len(flags), 2)
        by_div = {f["fs_div"]: f for f in flags}
        self.assertIn("CFS", by_div)
        self.assertIn("OFS", by_div)
        self.assertEqual(by_div["CFS"]["net_income"], -388279.0)
        self.assertEqual(by_div["OFS"]["net_income"], -111873.0)
        # 두 플래그 다 같은 배당액을 참조하되 병합되지 않고 분리돼 있다.
        self.assertEqual(by_div["CFS"]["dividend"], 35772.0)
        self.assertEqual(by_div["OFS"]["dividend"], 35772.0)

    def test_no_flag_when_one_side_profitable(self):
        # CFS만 적자, OFS는 흑자 → OFS 쪽은 플래그가 나오면 안 된다
        # (한쪽이 흑자라고 다른 쪽 플래그가 사라지지도, 억지로 합쳐지지도 않음).
        dividend_records = [
            _mk_rec("2022", "11011", "현금배당금총액(백만원)", "35,772"),
            _mk_rec("2022", "11011", "(연결)당기순이익(백만원)", "-581,169"),
            _mk_rec("2022", "11011", "(별도)당기순이익(백만원)", "175,466"),
        ]
        flags = dart_client.detect_dividend_drain(dividend_records)
        self.assertEqual(len(flags), 1)
        self.assertEqual(flags[0]["fs_div"], "CFS")

    def test_no_flag_when_profitable(self):
        dividend_records = [
            _mk_rec("2024", "11011", "현금배당금총액(백만원)", "500"),
            _mk_rec("2024", "11011", "(연결)당기순이익(백만원)", "1,000"),
            _mk_rec("2024", "11011", "(별도)당기순이익(백만원)", "900"),
        ]
        flags = dart_client.detect_dividend_drain(dividend_records)
        self.assertEqual(flags, [])

    def test_no_flag_when_zero_or_dash_dividend(self):
        dividend_records = [
            _mk_rec("2024", "11011", "현금배당금총액(백만원)", "-"),
            _mk_rec("2024", "11011", "(연결)당기순이익(백만원)", "-1,000"),
        ]
        flags = dart_client.detect_dividend_drain(dividend_records)
        self.assertEqual(flags, [])

    def test_does_not_match_per_share_dividend_field(self):
        # 느슨한 "현금배당금" in se 매칭이면 "주당 현금배당금(원)"(단가,
        # 원 단위)도 걸려들었다 — 정확히 "현금배당금총액(백만원)"만 대상.
        dividend_records = [
            _mk_rec("2024", "11011", "주당 현금배당금(원)", "2,000"),
            _mk_rec("2024", "11011", "(연결)당기순이익(백만원)", "-1,000"),
        ]
        flags = dart_client.detect_dividend_drain(dividend_records)
        self.assertEqual(flags, [])

    def test_does_not_mix_different_reprt_code_groups(self):
        # 같은 사업연도라도 다른 reprt_code(분기 보고)의 순이익과 배당을
        # 섞어 짝짓지 않는다 — (bsns_year, reprt_code) 쌍으로 그룹핑.
        dividend_records = [
            _mk_rec("2024", "11011", "현금배당금총액(백만원)", "500"),
            _mk_rec("2024", "11012", "(연결)당기순이익(백만원)", "-1,000"),
        ]
        flags = dart_client.detect_dividend_drain(dividend_records)
        self.assertEqual(flags, [])

    def test_empty_inputs(self):
        self.assertEqual(dart_client.detect_dividend_drain([]), [])
        self.assertEqual(dart_client.detect_dividend_drain(None), [])

    def test_quarterly_cumulative_reports_do_not_produce_duplicate_year_flags(self):
        # 최종 리뷰 지적(Important) 재현: SK하이닉스(corp_code=00164779)
        # lookback_years=3 실측(2026-07-30) — alotMatter는 사업연도당
        # reprt_code 4종(11011 사업·11012 반기·11013 1분기·11014 3분기)을
        # 각각 별도 호출하는데, 배당·순이익을 실제로 지급/보고하는 회사는
        # 4개 reprt_code 모두 "-"가 아닌 값을 채운다(반기/분기는 그 시점까지의
        # 누적치). 옛 구현은 이 4건을 전부 독립된 사업연도 결과인 것처럼
        # 8개 플래그(같은 2023년, CFS/OFS × 4 reprt_code)로 쏟아냈다 — 사업
        # 보고서(11011)만 그 해의 진짜 연간 확정치이고 나머지 3개는 반기까지의
        # 누적액일 뿐인데 렌더에서 구분이 안 됐다. 사업보고서(11011)만 남아야
        # 한다.
        dividend_records = [
            _mk_rec("2023", "11011", "현금배당금총액(백만원)", "825,721"),
            _mk_rec("2023", "11011", "(연결)당기순이익(백만원)", "-9,112,428"),
            _mk_rec("2023", "11011", "(별도)당기순이익(백만원)", "-4,836,170"),
            _mk_rec("2023", "11012", "현금배당금총액(백만원)", "412,845"),
            _mk_rec("2023", "11012", "(연결)당기순이익(백만원)", "-5,571,590"),
            _mk_rec("2023", "11012", "(별도)당기순이익(백만원)", "-3,003,260"),
            _mk_rec("2023", "11013", "현금배당금총액(백만원)", "206,418"),
            _mk_rec("2023", "11013", "(연결)당기순이익(백만원)", "-2,580,409"),
            _mk_rec("2023", "11013", "(별도)당기순이익(백만원)", "-1,296,209"),
            _mk_rec("2023", "11014", "현금배당금총액(백만원)", "619,280"),
            _mk_rec("2023", "11014", "(연결)당기순이익(백만원)", "-7,755,323"),
            _mk_rec("2023", "11014", "(별도)당기순이익(백만원)", "-3,742,914"),
        ]
        flags = dart_client.detect_dividend_drain(dividend_records)
        self.assertEqual(
            len(flags), 2,
            f"사업보고서(11011) 외 분기 누적치까지 플래그로 새는 회귀입니다: {flags}",
        )
        for fl in flags:
            self.assertEqual(fl["reprt_code"], "11011")
            self.assertEqual(fl["bsns_year"], "2023")
        by_div = {f["fs_div"]: f for f in flags}
        self.assertEqual(by_div["CFS"]["net_income"], -9112428.0)
        self.assertEqual(by_div["OFS"]["net_income"], -4836170.0)
        self.assertEqual(by_div["CFS"]["dividend"], 825721.0)


# ---------- TestSignalRegistration ----------

class TestSignalRegistrationV090(unittest.TestCase):
    def test_distress_event_registered(self):
        self.assertIn("DISTRESS_EVENT", SIGNAL_KEY_TO_TAXONOMY)
        self.assertEqual(SIGNAL_KEY_TO_TAXONOMY["DISTRESS_EVENT"], ["8.5"])
        keys = {s["key"] for s in SIGNAL_TYPES}
        self.assertIn("DISTRESS_EVENT", keys)

    def test_dividend_drain_registered(self):
        self.assertIn("DIVIDEND_DRAIN", SIGNAL_KEY_TO_TAXONOMY)
        self.assertEqual(SIGNAL_KEY_TO_TAXONOMY["DIVIDEND_DRAIN"], ["5.6"])
        keys = {s["key"] for s in SIGNAL_TYPES}
        self.assertIn("DIVIDEND_DRAIN", keys)

    def test_taxonomy_8_5_exists(self):
        self.assertIn("8.5", TAXONOMY)
        node = TAXONOMY["8.5"]
        self.assertEqual(node.get("id"), "8.5")
        self.assertEqual(node.get("base_score"), 0)

    def test_taxonomy_5_6_exists(self):
        self.assertIn("5.6", TAXONOMY)
        node = TAXONOMY["5.6"]
        self.assertEqual(node.get("id"), "5.6")
        self.assertEqual(node.get("base_score"), 0)


if __name__ == "__main__":
    unittest.main()
