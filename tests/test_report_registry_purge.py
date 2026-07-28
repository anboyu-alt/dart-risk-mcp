import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

# SE-5b 리뷰 Finding 3: scripts/report_registry_purge.py에는 테스트가
# 하나도 없었다 — 차집합 로직(_filter_institutions가 거른 결과와 원본의
# 차이)이 깨져도 아무것도 잡지 못한다. build_report()는 순수 함수가
# 아니라 known_actors._load_raw()(환경변수 DART_KNOWN_ACTORS_PATH가
# 최우선)를 통해 레지스트리를 읽으므로, tests/test_known_actors.py와
# 동일한 관례(임시 JSON 파일 + 환경변수 패치)로 네트워크 없이 결정적으로
# 돌린다.

_NH_INSTITUTION = (
    "엔에이치투자증권 주식회사 "
    "(밸류시스템 코스닥벤처FAST 전문투자형 사모투자신탁의 신탁업자 지위에서)"
)


class TestReportRegistryPurge(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._path = str(Path(self._tmp.name) / "ka.json")
        self._env = patch.dict("os.environ", {"DART_KNOWN_ACTORS_PATH": self._path})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def _write(self, data):
        Path(self._path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_excludes_institution_with_only_auto_matched(self):
        import scripts.report_registry_purge as rrp
        self._write({"version": 1, "actors": {
            _NH_INSTITUTION: [
                {"source": "자동 발굴", "evidence": "e", "status": "auto_matched",
                 "companies": ["가", "나"]}],
            "홍길동": [{"source": "s", "evidence": "e", "status": "auto_matched"}],
        }})
        report = rrp.build_report()
        self.assertEqual(report["total"], 2)
        self.assertEqual(report["excluded_count"], 1)
        names = {e["name"] for e in report["excluded"]}
        self.assertEqual(names, {_NH_INSTITUTION})

    def test_keeps_institution_with_a_verified_record(self):
        # 제작자가 직접 판단해 넣은 기록(verified/maintainer_seed)이 하나라도
        # 있으면 기관이라도 제외 대상이 아니다 — _filter_institutions와 동일
        # 원칙을 build_report도 따라야 한다(로직 재구현이 아니라 그 함수를
        # 그대로 부르므로 드리프트가 없어야 함을 이 테스트로 고정).
        import scripts.report_registry_purge as rrp
        self._write({"version": 1, "actors": {
            _NH_INSTITUTION: [
                {"source": "자동 발굴", "evidence": "e1", "status": "auto_matched"},
                {"source": "확인", "evidence": "e2", "status": "verified"},
            ],
        }})
        report = rrp.build_report()
        self.assertEqual(report["excluded_count"], 0)
        self.assertEqual(report["excluded"], [])

    def test_excludes_institution_with_blank_status(self):
        # 빈 status는 화이트리스트 밖 → 기계 등재로 강등(actor_status) →
        # 제외 대상. 동등비교(`== "auto_matched"`)였다면 빈 문자열이
        # "사람이 넣은 것"으로 잘못 분류돼 제외되지 않았을 것이다.
        import scripts.report_registry_purge as rrp
        self._write({"version": 1, "actors": {
            _NH_INSTITUTION: [{"source": "자동 발굴", "evidence": "e", "status": ""}],
        }})
        report = rrp.build_report()
        self.assertEqual(report["excluded_count"], 1)
        self.assertEqual(report["excluded"][0]["name"], _NH_INSTITUTION)

    def test_keeps_non_institution_auto_matched(self):
        # 기관이 아닌 실체(조합·법인·개인)는 auto_matched뿐이어도 남는다.
        import scripts.report_registry_purge as rrp
        self._write({"version": 1, "actors": {
            "시너지파트너스 주식회사": [
                {"source": "자동 발굴", "evidence": "e", "status": "auto_matched"}],
        }})
        report = rrp.build_report()
        self.assertEqual(report["total"], 1)
        self.assertEqual(report["excluded_count"], 0)

    def test_company_count_dedupes_across_records(self):
        import scripts.report_registry_purge as rrp
        self._write({"version": 1, "actors": {
            _NH_INSTITUTION: [
                {"source": "s", "evidence": "e1", "status": "auto_matched",
                 "companies": ["가", "나"]},
                {"source": "s", "evidence": "e2", "status": "auto_matched",
                 "companies": ["나", "다"]},  # "나" 중복
            ],
        }})
        report = rrp.build_report()
        excl = report["excluded"][0]
        self.assertEqual(excl["company_count"], 3)  # 가·나·다 (중복 제거)
        self.assertEqual(excl["record_count"], 2)   # 기록 자체는 안 합침

    def test_reason_reflects_classify_and_sector(self):
        import scripts.report_registry_purge as rrp
        self._write({"version": 1, "actors": {
            _NH_INSTITUTION: [{"source": "s", "evidence": "e", "status": "auto_matched"}],
        }})
        report = rrp.build_report()
        self.assertEqual(report["excluded"][0]["reason"], "institution/증권")

    def test_sort_order_by_company_count_desc_then_name(self):
        # 실측 표와 동일한 정렬(등장 회사 수 내림차순, 동률이면 이름순) —
        # 보고서가 상위 노이즈부터 보여줘야 제작자가 우선순위를 바로 안다.
        import scripts.report_registry_purge as rrp
        bank = "은행A (신탁업자 지위에서)"
        bank2 = "은행B (신탁업자 지위에서)"
        self._write({"version": 1, "actors": {
            bank: [{"source": "s", "evidence": "e", "status": "auto_matched",
                    "companies": ["가"]}],
            bank2: [{"source": "s", "evidence": "e", "status": "auto_matched",
                     "companies": ["가", "나", "다"]}],
        }})
        report = rrp.build_report()
        self.assertEqual([e["name"] for e in report["excluded"]], [bank2, bank])

    def test_empty_registry(self):
        import scripts.report_registry_purge as rrp
        self._write({"version": 1, "actors": {}})
        report = rrp.build_report()
        self.assertEqual(report, {"total": 0, "excluded_count": 0, "excluded": []})

    def test_print_table_no_exclusions(self):
        import io
        import scripts.report_registry_purge as rrp
        report = {"total": 3, "excluded_count": 0, "excluded": []}
        buf = io.StringIO()
        with patch("sys.stdout", buf):
            rrp.print_table(report)
        out = buf.getvalue()
        self.assertIn("0명", out)
        self.assertIn("3명", out)
        self.assertIn("제외 대상 없음", out)


if __name__ == "__main__":
    unittest.main()
