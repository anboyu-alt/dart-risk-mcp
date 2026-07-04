import unittest
from unittest.mock import patch


class TestRefreshKnownActors(unittest.TestCase):
    def test_collect_matches_registered_actor(self):
        import scripts.refresh_known_actors as rk

        discs = [{"rcept_no": "R1", "report_nm": "전환사채권발행결정",
                  "corp_name": "△△전자", "corp_code": "c1", "rcept_dt": "20260612"}]

        def _match(rnm):
            return [{"key": "CB_BW"}] if "전환사채" in rnm else []

        with patch.object(rk, "fetch_market_disclosures", return_value=discs), \
             patch.object(rk, "match_signals", side_effect=_match), \
             patch.object(rk, "extract_cb_investors", return_value=[{"name": "이준민"}]), \
             patch.object(rk, "extract_rights_offering_investors", return_value=[]):
            matches = rk.collect_auto_matches("key", {"이준민"}, window_days=2, max_pages=1)

        self.assertIn("이준민", matches)
        self.assertEqual(matches["이준민"][0]["status"], "auto_matched")
        self.assertEqual(matches["이준민"][0]["rcept_no"], "R1")
        self.assertEqual(matches["이준민"][0]["companies"], ["△△전자"])
        self.assertEqual(matches["이준민"][0]["url"],
                         "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=R1")

    def test_collect_matches_case_variant_of_registered_actor(self):
        # 레지스트리 'Yoo Andy C' vs 공시 'YOO ANDY C' — 표기 정규화로 매칭,
        # 결과 키는 레지스트리 등재 표기 그대로 반환(merge가 그 키로 병합하므로)
        import scripts.refresh_known_actors as rk
        discs = [{"rcept_no": "R1", "report_nm": "전환사채권발행결정",
                  "corp_name": "△△전자", "corp_code": "c1", "rcept_dt": "20260612"}]
        with patch.object(rk, "fetch_market_disclosures", return_value=discs), \
             patch.object(rk, "match_signals", return_value=[{"key": "CB_BW"}]), \
             patch.object(rk, "extract_cb_investors",
                          return_value=[{"name": "YOO  ANDY C"}]), \
             patch.object(rk, "extract_rights_offering_investors", return_value=[]):
            matches = rk.collect_auto_matches("key", {"Yoo Andy C"},
                                              window_days=2, max_pages=1)
        self.assertIn("Yoo Andy C", matches)
        self.assertEqual(matches["Yoo Andy C"][0]["rcept_no"], "R1")

    def test_collect_scans_amendment_filings(self):
        # 정정공시도 접두사를 벗겨 유형 판별 후 스캔한다 (확정 명단이 정정본에 실림)
        import scripts.refresh_known_actors as rk
        discs = [{"rcept_no": "R2", "report_nm": "[기재정정]전환사채권발행결정",
                  "corp_name": "△△전자", "corp_code": "c1", "rcept_dt": "20260612"}]

        def _match(rnm):
            # strip_amendment_prefix가 적용됐다면 접두사 없는 제목이 들어온다
            assert not rnm.startswith("["), f"접두사 미제거: {rnm}"
            return [{"key": "CB_BW"}] if "전환사채" in rnm else []

        with patch.object(rk, "fetch_market_disclosures", return_value=discs), \
             patch.object(rk, "match_signals", side_effect=_match), \
             patch.object(rk, "extract_cb_investors", return_value=[{"name": "이준민"}]), \
             patch.object(rk, "extract_rights_offering_investors", return_value=[]):
            matches = rk.collect_auto_matches("key", {"이준민"}, window_days=2, max_pages=1)
        self.assertIn("이준민", matches)
        self.assertEqual(matches["이준민"][0]["rcept_no"], "R2")

    def test_collect_ignores_unregistered(self):
        import scripts.refresh_known_actors as rk
        discs = [{"rcept_no": "R1", "report_nm": "전환사채권발행결정",
                  "corp_name": "X", "corp_code": "c", "rcept_dt": "20260612"}]
        with patch.object(rk, "fetch_market_disclosures", return_value=discs), \
             patch.object(rk, "match_signals", return_value=[{"key": "CB_BW"}]), \
             patch.object(rk, "extract_cb_investors", return_value=[{"name": "낯선사람"}]), \
             patch.object(rk, "extract_rights_offering_investors", return_value=[]):
            matches = rk.collect_auto_matches("key", {"이준민"}, window_days=2, max_pages=1)
        self.assertEqual(matches, {})

    def test_merge_skips_duplicate_rcept(self):
        import scripts.refresh_known_actors as rk
        data = {"version": 1, "actors": {"이준민": [
            {"source": "x", "status": "auto_matched", "rcept_no": "R1"}]}}
        matches = {"이준민": [{"source": "y", "status": "auto_matched", "rcept_no": "R1"},
                            {"source": "z", "status": "auto_matched", "rcept_no": "R2"}]}
        changed = rk.merge_auto_matches(data, matches)
        self.assertTrue(changed)
        rcepts = {r["rcept_no"] for r in data["actors"]["이준민"]}
        self.assertEqual(rcepts, {"R1", "R2"})  # R1 중복 스킵, R2 추가

    def test_merge_ignores_unregistered_name(self):
        import scripts.refresh_known_actors as rk
        data = {"version": 1, "actors": {}}
        changed = rk.merge_auto_matches(data, {"낯선사람": [{"rcept_no": "R1"}]})
        self.assertFalse(changed)
        self.assertEqual(data["actors"], {})


    def test_build_change_summary_includes_counts_and_changes(self):
        import scripts.refresh_known_actors as rk
        data = {"actors": {"신승수": [{"status": "verified"}],
                           "이준민": [{"status": "maintainer_seed"}]}}
        matches = {"이준민": [{"evidence": "△△전자 CB 인수자로 등장", "rcept_no": "R1"}]}
        s = rk.build_change_summary(data, matches)
        self.assertIn("verified 1", s)
        self.assertIn("maintainer_seed 1", s)
        self.assertIn("이준민", s)
        self.assertIn("R1", s)

    def test_send_mail_skips_without_credentials(self):
        import os
        import scripts.refresh_known_actors as rk
        from unittest.mock import patch
        with patch.dict("os.environ", {}, clear=False):
            for k in ("MAIL_USER", "MAIL_APP_PASSWORD", "MAIL_TO"):
                os.environ.pop(k, None)
            with patch.object(rk.smtplib, "SMTP") as smtp:
                ok = rk.send_mail("s", "b")
        self.assertFalse(ok)
        smtp.assert_not_called()

    def test_send_mail_sends_with_credentials(self):
        import scripts.refresh_known_actors as rk
        from unittest.mock import patch, MagicMock
        with patch.dict("os.environ", {"MAIL_USER": "u@gmail.com",
                                       "MAIL_APP_PASSWORD": "p", "MAIL_TO": "t@x.com"}):
            srv = MagicMock()
            srv.__enter__.return_value = srv
            with patch.object(rk.smtplib, "SMTP", return_value=srv):
                ok = rk.send_mail("s", "b")
        self.assertTrue(ok)
        srv.send_message.assert_called_once()


if __name__ == "__main__":
    unittest.main()
