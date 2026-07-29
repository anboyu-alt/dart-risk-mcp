"""라이브 리스크 도구용 데이터 codegen(scripts/export_tool_data.py) 검증.

signals.py·taxonomy.py를 유일한 진실로 두고 docs/tool/signals-data.json을
생성한다. 공개 아티팩트에는 내부 점수(score)·패턴 등급(severity)이
포함되면 안 된다 (v0.8.5 무점수 원칙의 공개 데이터 확장).
"""
import json
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from export_tool_data import (  # noqa: E402
    build_signals_data,
    CATEGORY_LABELS,
    ROUTINE_FILING_CATEGORY,
    ROUTINE_FILING_KEYWORDS,
    ROUTINE_FILING_LABEL,
)

from dart_risk_mcp.core.signals import (  # noqa: E402
    SIGNAL_TYPES,
    CAPITAL_EVENT_KEYS,
)


class TestBuildSignalsData(unittest.TestCase):
    def setUp(self):
        self.data = build_signals_data()

    def test_all_signal_types_exported(self):
        self.assertEqual(len(self.data["signals"]), len(SIGNAL_TYPES))
        keys = {s["key"] for s in self.data["signals"]}
        self.assertIn("CB_BW", keys)
        self.assertIn("GOING_CONCERN", keys)

    def test_no_internal_score_or_severity(self):
        for s in self.data["signals"]:
            self.assertNotIn("score", s)
        for p in self.data["patterns"]:
            self.assertNotIn("severity", p)
            self.assertNotIn("field_evidence", p)

    def test_signal_fields_and_category(self):
        s = next(x for x in self.data["signals"] if x["key"] == "CB_BW")
        self.assertEqual(s["label"], "CB/BW발행")
        self.assertIn("전환사채", s["keywords"])
        self.assertEqual(s["category"], 1)
        # 카테고리 라벨 맵 (1~8 + 0=기타)
        self.assertEqual(self.data["categories"]["1"], "CB/채권")
        self.assertEqual(self.data["categories"]["8"], "위기/부실")
        # '시장조작'은 단정적 표현이라 공개 라벨은 '시장감시'로 (2026-07 UX 결정)
        self.assertEqual(self.data["categories"]["7"], "시장감시")

    def test_category_uses_heaviest_taxonomy(self):
        # 복수 taxonomy 매핑 신호는 무거운 쪽(높은 카테고리 번호)을 대표로.
        # EMBEZZLE ['5.3','8.1'] → 8(위기/부실), INQUIRY ['4.3','7.1'] → 7(시장조작).
        by_key = {s["key"]: s for s in self.data["signals"]}
        self.assertEqual(by_key["EMBEZZLE"]["category"], 8)
        self.assertEqual(by_key["INQUIRY"]["category"], 7)
        # 패턴 대조용으로 전체 taxonomy 목록도 보존
        self.assertIn("8.1", by_key["EMBEZZLE"]["taxonomies"])
        self.assertIn("5.3", by_key["EMBEZZLE"]["taxonomies"])

    def test_signals_sorted_by_internal_weight(self):
        # 배열 순서 = 내부 우선순위 (숫자 score는 미노출). 헤드라인 선정에 사용.
        scores = {s["key"]: s["score"] for s in SIGNAL_TYPES}
        exported = [s["key"] for s in self.data["signals"]]
        self.assertEqual(exported,
                         sorted(exported, key=lambda k: -scores[k]))

    def test_signal_prose_exported(self):
        by_key = {s["key"]: s for s in self.data["signals"]}
        self.assertIn("횡령", by_key["EMBEZZLE"]["prose"])
        self.assertIn("자사주", by_key["TREASURY"]["prose"])

    def test_fs_aliases_exported(self):
        fa = self.data["fs_aliases"]
        for k in ("매출", "영업이익", "당기순이익", "자본총계", "자본금",
                  "이익잉여금"):
            self.assertIn(k, fa)
            self.assertIsInstance(fa[k], list)
        # 이익잉여금은 결손금 병기 표기도 흡수해야 함
        self.assertIn("이익잉여금(결손금)", fa["이익잉여금"])

    def test_patterns_exported_with_sequence(self):
        p = next(x for x in self.data["patterns"] if x["key"] == "zombie_ma")
        self.assertTrue(p["description"])
        self.assertIsInstance(p["signal_sequence"], list)
        self.assertGreater(p["timeline_months"], 0)

    def test_capital_keys_and_amendment_regex(self):
        self.assertEqual(sorted(self.data["capital_event_keys"]),
                         sorted(CAPITAL_EVENT_KEYS))
        # JS RegExp로 그대로 쓸 수 있는 문자열
        self.assertTrue(self.data["amendment_pattern"].startswith("^"))

    def test_json_serializable(self):
        json.dumps(self.data, ensure_ascii=False)


class TestRoutineFilingCategory(unittest.TestCase):
    """SE-7 Task 3 — 고빈도 정기 보고(임원 지분 1주 변동 보고 등)는 위험
    신호가 아니다. core SIGNAL_TYPES에는 절대 넣지 않고(Global
    Constraints), signals-data.json에 별도 키·별도 카테고리 번호로만
    노출한다(task-3-brief.md)."""

    def setUp(self):
        self.data = build_signals_data()

    def test_routine_filing_keywords_key_exists_and_has_no_signal_or_risk_word(self):
        """브리프: 키 이름에 'signal'·'risk'라는 단어를 넣지 마라 — 위험
        신호가 아니라는 게 이 태스크의 요점이다."""
        self.assertIn("routine_filing_keywords", self.data)
        self.assertIsInstance(self.data["routine_filing_keywords"], list)
        self.assertNotIn("signal", "routine_filing_keywords")
        self.assertNotIn("risk", "routine_filing_keywords")

    def test_routine_filing_keywords_cover_the_live_measured_minimum(self):
        expected = [
            "임원ㆍ주요주주특정증권등소유상황보고서",
            "최대주주등소유주식변동신고서",
            "사업보고서",
            "반기보고서",
            "분기보고서",
            "주주총회소집공고",
            "주주총회소집결의",
            "기업설명회",
        ]
        for kw in expected:
            self.assertIn(kw, self.data["routine_filing_keywords"])

    def test_routine_filing_category_number_does_not_collide_with_risk_categories(self):
        """위험 신호 taxonomy 카테고리는 0(기타)~8(위기/부실)만 쓴다 —
        "9"는 CATEGORY_LABELS(위험 신호 전용 맵)에 원래 없어야 한다."""
        self.assertNotIn(str(ROUTINE_FILING_CATEGORY), CATEGORY_LABELS)
        self.assertEqual(self.data["categories"][str(ROUTINE_FILING_CATEGORY)],
                          ROUTINE_FILING_LABEL)

    def test_routine_filing_label_reads_as_fact_not_verdict(self):
        """v0.8.5 판정 금지 — "정기 보고"는 사실 라벨이지 "안전"·"위험
        없음"으로 읽히는 등급이 아니다."""
        banned = ("안전", "위험", "매우위험", "고위험", "위험도", "위험등급",
                  "의심스", "종합점수", "리스크 점수", "등급 부여", "주의",
                  "양호", "악화", "개선", "부실")
        for word in banned:
            self.assertNotIn(word, ROUTINE_FILING_LABEL,
                              f"정기 보고 라벨에 판정 어휘 '{word}'")
        self.assertNotEqual(ROUTINE_FILING_LABEL, CATEGORY_LABELS["0"],
                             "정기 보고는 '기타'와 구분되는 라벨이어야 합니다")

    def test_all_original_category_labels_still_present(self):
        """기존 위험 신호 카테고리(0~8) 라벨은 하나도 안 바뀌어야 한다."""
        for k, v in CATEGORY_LABELS.items():
            self.assertEqual(self.data["categories"][k], v)


if __name__ == "__main__":
    unittest.main()
