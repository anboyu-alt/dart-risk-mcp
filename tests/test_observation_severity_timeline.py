# -*- coding: utf-8 -*-
"""OBSERVATION severity 신호는 위기 타임라인 수치를 갖지 않는다.

SEVERITY_LEVELS에 없는 severity(OBSERVATION — 참고 강도 신호 2.8/3.6/5.6/
5.7/5.8/8.5 등)가 MEDIUM으로 폴백돼 "위기 도달 약 12개월·손실 40%" 같은
근거 없는 문장이 find_risk_precedents 류에 렌더되던 문제(2026-08-04 정적
감사 D-2). 알 수 없는 severity는 미상 센티널(999/0)로 반환해 렌더 게이트
(months < 999)가 문장을 생략하게 한다.
"""
import unittest

from dart_risk_mcp.core.taxonomy import (
    TAXONOMY,
    SEVERITY_LEVELS,
    estimate_crisis_timeline,
)


class TestObservationTimeline(unittest.TestCase):
    def test_observation_signals_get_unknown_sentinel(self):
        obs_ids = [tid for tid, s in TAXONOMY.items()
                   if s.get("severity") == "OBSERVATION"]
        self.assertTrue(obs_ids)  # 참고 강도 신호가 실존해야 의미 있는 테스트
        for tid in obs_ids:
            tl = estimate_crisis_timeline(tid)
            self.assertEqual(tl["months_to_impact"], 999, tid)
            self.assertEqual(tl["equity_loss_pct"], 0, tid)

    def test_known_severities_unchanged(self):
        for tid, s in TAXONOMY.items():
            sev = s.get("severity")
            if sev in SEVERITY_LEVELS:
                tl = estimate_crisis_timeline(tid)
                self.assertEqual(tl["months_to_impact"],
                                 SEVERITY_LEVELS[sev]["max_months"], tid)


if __name__ == "__main__":
    unittest.main()
