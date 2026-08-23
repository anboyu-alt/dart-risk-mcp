"""라이브 리스크 도구용 데이터 codegen(scripts/export_tool_data.py) 검증.

signals.py·taxonomy.py를 유일한 진실로 두고 docs/tool/signals-data.json을
생성한다. 공개 아티팩트에는 내부 점수(score)·패턴 등급(severity)이
포함되면 안 된다 (v0.8.5 무점수 원칙의 공개 데이터 확장).
"""
import json
import os
import sys
import unittest
from collections import Counter
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from export_tool_data import (  # noqa: E402
    build_signals_data,
    build_catalog_data,
    _load_catalog_records,
    CATEGORY_LABELS,
    ROUTINE_FILING_CATEGORY,
    ROUTINE_FILING_KEYWORDS,
    ROUTINE_FILING_LABEL,
    _FIELD_EVIDENCE_EXPORT_TRIM,
)

from dart_risk_mcp.core.signals import (  # noqa: E402
    SIGNAL_TYPES,
    CAPITAL_EVENT_KEYS,
)
from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS, TAXONOMY  # noqa: E402


class TestBuildSignalsData(unittest.TestCase):
    def setUp(self):
        self.data = build_signals_data()

    def test_all_signal_types_exported(self):
        self.assertEqual(len(self.data["signals"]), len(SIGNAL_TYPES))
        keys = {s["key"] for s in self.data["signals"]}
        self.assertIn("CB_BW", keys)
        self.assertIn("GOING_CONCERN", keys)

    def test_no_internal_score_or_severity(self):
        """v0.8.5 무점수 원칙: score(내부 정렬용)·severity(등급)는 판정으로
        읽히므로 계속 미노출. field_evidence(사실 인용)는 SE-13 Task 2부터
        노출 대상 — 별도 테스트(test_field_evidence_exported_matches_core)."""
        for s in self.data["signals"]:
            self.assertNotIn("score", s)
            self.assertNotIn("severity", s)
        for p in self.data["patterns"]:
            self.assertNotIn("severity", p)

    def test_priority_on_all_signals(self):
        """관찰 우선순위 — 모든 신호에 priority가 있고 세 값 중 하나다.

        옛 `caution` 불리언(severity 2단계 접기)을 대체한다. severity가 이
        레포에서 '심각도'가 아니라 '점수를 매기느냐'로 쓰여 온 탓에 배지가
        뒤집혔다 — 근거·실측은 tests/test_observation_priority.py 참고.
        패턴에는 넣지 않는다(9종 전원 CRITICAL/HIGH라 상수 — 정보량 0).
        """
        for s in self.data["signals"]:
            self.assertIn("priority", s)
            self.assertIn(s["priority"], ("first", "watch", "context"))
            self.assertNotIn("caution", s)
        for p in self.data["patterns"]:
            self.assertNotIn("priority", p)

    def test_priority_matches_core(self):
        """export는 core `observation_priority`를 그대로 옮긴다(파생 없음)."""
        from dart_risk_mcp.core.signals import observation_priority
        for s in self.data["signals"]:
            self.assertEqual(s["priority"], observation_priority(s["key"]),
                             msg=s["key"])

    def test_field_evidence_exported_matches_core(self):
        """SE-13 Task 2: field_evidence(금감원 보도자료·사례 인용)는 사실
        서술이라 판정(severity)과 달리 export 대상. core 원문과 완전히
        일치해야 한다(왜곡·재구성 없이 그대로).

        예외 2건(재리뷰 2026-07-30): debt_spiral·related_party_hollowing은
        core 문구에 평가적 어구("돌려막기"/"경영권 방어용")가 섞여 있어
        export 계층에서만 의도적으로 트리밍한다(core taxonomy.py는 그대로,
        MCP 도구 프로즈는 더 넓은 어휘 허용 범위를 유지). 이 두 슬러그는
        byte-for-byte 비교 대상에서 제외하고 별도 테스트
        (test_trimmed_field_evidence_removes_judgment_phrases)로 검증한다.
        이건 회귀가 아니라 의도된 export-layer 정책이다 — 나머지 7종은
        여전히 이 테스트로 core와 완전히 동일함을 강제한다."""
        by_key = {p["key"]: p for p in self.data["patterns"]}
        self.assertEqual(set(by_key), set(CROSS_SIGNAL_PATTERNS))
        for slug, core_pattern in CROSS_SIGNAL_PATTERNS.items():
            exported = by_key[slug]
            self.assertIn("field_evidence", exported)
            self.assertIsInstance(exported["field_evidence"], list)
            if slug in _FIELD_EVIDENCE_EXPORT_TRIM:
                continue
            self.assertEqual(exported["field_evidence"],
                              list(core_pattern["field_evidence"]))

    def test_trimmed_field_evidence_removes_judgment_phrases(self):
        """재리뷰 지적 2건: 규제기관 인용이 아닌 평가적 어구는 export에서
        빠지되, 사실 부분(기업명·날짜·이벤트)은 그대로 남아야 한다."""
        by_key = {p["key"]: p for p in self.data["patterns"]}

        debt_evidence = by_key["debt_spiral"]["field_evidence"]
        self.assertNotIn(
            "돌려막기", " ".join(debt_evidence),
            "debt_spiral field_evidence에 구어체·경멸적 표현 '돌려막기'가 남아 있음")
        self.assertTrue(
            any("위메이드" in e and "20250903" in e for e in debt_evidence),
            "위메이드 사실 인용(기업명·날짜)이 트리밍 과정에서 유실됨")
        # 다른 항목(SKAI 연속 적자)은 트리밍 대상이 아니므로 그대로 보존
        self.assertEqual(
            list(CROSS_SIGNAL_PATTERNS["debt_spiral"]["field_evidence"])[1:],
            debt_evidence[1:])

        rph_evidence = by_key["related_party_hollowing"]["field_evidence"]
        self.assertNotIn(
            "경영권 방어용", " ".join(rph_evidence),
            "related_party_hollowing field_evidence에 동기 단정 '경영권 방어용'이 남아 있음")
        self.assertTrue(
            any("동성제약" in e and "회생신청" in e and "20251014" in e
                for e in rph_evidence),
            "동성제약 사실 인용(기업명·이벤트·날짜)이 트리밍 과정에서 유실됨")
        # 다른 항목(파마리서차 RCPS)은 트리밍 대상이 아니므로 그대로 보존
        self.assertEqual(
            list(CROSS_SIGNAL_PATTERNS["related_party_hollowing"]["field_evidence"])[:1],
            rph_evidence[:1])

    def test_trimmed_field_evidence_passes_hygiene_vocabulary_check(self):
        """Task 2가 쓴 것과 같은 판정 어휘 배너드 리스트로 트리밍 결과를
        재검사 — 단, 이 어구들은 애초에 그 리스트가 잡아내는 유형이 아니라
        기계 검사가 아닌 수동 판단으로 걸러졌다는 점이 이 테스트의 요점."""
        sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
        from test_golden_output_hygiene import (  # noqa: E402
            _SCORE_GRADE_PATTERNS,
            _SEVERITY_EMOJI,
        )
        import re

        by_key = {p["key"]: p for p in self.data["patterns"]}
        for slug in _FIELD_EVIDENCE_EXPORT_TRIM:
            text = " ".join(by_key[slug]["field_evidence"])
            for pattern, desc in _SCORE_GRADE_PATTERNS:
                self.assertIsNone(re.search(pattern, text),
                                   f"{slug} field_evidence에 {desc} 잔존")
            for emoji in _SEVERITY_EMOJI:
                self.assertNotIn(emoji, text)

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
        # EMBEZZLE ['5.3','8.1'] → 8(위기/부실), INQUIRY ['7.1'] → 7(시장조작).
        # INQUIRY는 2026-08-21에 ['4.3','7.1'] → ['7.1']로 좁혔다(조회공시는 공시·보고
        # 의무 위반이 아니다 — 4.3은 DISCLOSURE_VIOL 담당). 카테고리는 그대로 7이다.
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

    def test_patterns_have_prose_and_checkpoints(self):
        """패턴 서술 강화(무판정 원칙 유지): 11종 패턴 전부 prose(문자열)·
        checkpoints(불릿 리스트)를 갖는다. core/explain.py의
        PATTERN_PROSE·PATTERN_CHECKPOINTS가 유일한 진실 — 값도 그대로
        일치해야 한다."""
        from dart_risk_mcp.core.explain import PATTERN_PROSE, PATTERN_CHECKPOINTS

        by_key = {p["key"]: p for p in self.data["patterns"]}
        self.assertEqual(set(by_key), set(CROSS_SIGNAL_PATTERNS))
        for slug in CROSS_SIGNAL_PATTERNS:
            exported = by_key[slug]
            self.assertIn("prose", exported)
            self.assertIsInstance(exported["prose"], str)
            self.assertTrue(exported["prose"], f"{slug} prose가 비어 있음")
            self.assertEqual(exported["prose"], PATTERN_PROSE.get(slug, ""))

            self.assertIn("checkpoints", exported)
            self.assertIsInstance(exported["checkpoints"], list)
            self.assertTrue(exported["checkpoints"], f"{slug} checkpoints가 비어 있음")
            for cp in exported["checkpoints"]:
                self.assertIsInstance(cp, str)
            self.assertEqual(exported["checkpoints"],
                              list(PATTERN_CHECKPOINTS.get(slug, [])))

    def test_pattern_prose_and_checkpoints_no_score_or_grade_vocabulary(self):
        """prose·checkpoints도 v0.8.5 무판정 원칙 대상 — 등급·점수 어휘가
        새로 들어오지 않았는지 기존 hygiene 검사기로 재확인."""
        sys.path.insert(0, os.path.join(os.path.dirname(__file__)))
        from test_golden_output_hygiene import (  # noqa: E402
            _SCORE_GRADE_PATTERNS,
            _SEVERITY_EMOJI,
        )
        import re

        for p in self.data["patterns"]:
            text = p["prose"] + " " + " ".join(p["checkpoints"])
            for pattern, desc in _SCORE_GRADE_PATTERNS:
                self.assertIsNone(re.search(pattern, text),
                                   f"{p['key']} prose/checkpoints에 {desc} 잔존")
            for emoji in _SEVERITY_EMOJI:
                self.assertNotIn(emoji, text)

    def test_capital_keys_and_amendment_regex(self):
        self.assertEqual(sorted(self.data["capital_event_keys"]),
                         sorted(CAPITAL_EVENT_KEYS))
        # JS RegExp로 그대로 쓸 수 있는 문자열
        self.assertTrue(self.data["amendment_pattern"].startswith("^"))

    def test_json_serializable(self):
        json.dumps(self.data, ensure_ascii=False)

    def test_export_includes_qualifier_rules(self):
        from dart_risk_mcp.core import qualifiers as q

        rules = self.data["qualifier_rules"]
        self.assertEqual(rules["third_party_titles"], list(q.THIRD_PARTY_TITLES))
        self.assertEqual(rules["phase_tails"], list(q.PHASE_TAILS))
        self.assertEqual(rules["subsidiary_subtitles"], list(q.SUBSIDIARY_SUBTITLES))
        # related_party_prefix는 뜻이 반대인 규칙이라 2026-08-23에 뺐다
        # (core qualifiers.py의 해당 자리 주석 = 원문 실측 근거).
        self.assertNotIn("related_party_prefix", rules)
        self.assertEqual(rules["amendment_tags"], list(q.AMENDMENT_TAGS))
        self.assertEqual(rules["tails"], list(q.TAILS))

    def test_export_includes_label_overrides_and_notes(self):
        from dart_risk_mcp.core import qualifiers as q

        rules = self.data["qualifier_rules"]
        exported = rules["label_overrides"]["3PCA"]
        live = q.LABEL_OVERRIDES["3PCA"]
        # 하드코딩 리터럴이 아니라 core 상수와 직접 비교한다 — core가 바뀌면
        # 이 테스트도 같이 따라가고, 드리프트가 생기면 실패한다.
        self.assertEqual(exported["label"], live["label"])
        self.assertEqual(exported["missing_marker"], live["missing_marker"])
        # confirm_markers(Task 10 후속) — 원문 확인 버튼이 찾는 배정방식
        # 후보 전체. missing_marker와 달리 라벨 보정 여부에는 관여하지
        # 않지만, 내보내기가 끊기면 뷰어가 "제3자배정"만 확인할 수 있는
        # 소수 케이스로 조용히 퇴행한다 — 그래서 여기서 명시적으로 검증한다.
        self.assertEqual(exported["confirm_markers"], list(live["confirm_markers"]))
        self.assertIn("제3자배정", exported["confirm_markers"])
        self.assertIn("주주배정", exported["confirm_markers"])
        # 마커 목록은 실측으로 늘어난다(2026-08-22 확장) — 값을 손으로 박아
        # 두면 core를 고칠 때마다 여기가 깨진다. core와 일치하는지만 본다.
        from dart_risk_mcp.core.qualifiers import DIRECTION_NOTES as _DN

        for key in ("CB_BW", "EB", "RCPS"):
            self.assertIn(key, rules["direction_notes"], f"{key} direction_note 미노출")
            self.assertEqual(
                rules["direction_notes"][key]["markers"], list(_DN[key]["markers"])
            )
            self.assertEqual(rules["direction_notes"][key]["note"], _DN[key]["note"])
        # RCPS에 '상환'을 넣으면 상품명(상환전환우선주)에 걸려 전 건에 안내가 붙는다
        self.assertNotIn("상환", rules["direction_notes"]["RCPS"]["markers"])
        # 포장 제목 규칙(R2b)도 뷰어가 그대로 읽는다
        from dart_risk_mcp.core.qualifiers import WRAPPER_BODIES as _WB

        self.assertEqual(rules["wrapper_bodies"], list(_WB))

    def test_export_includes_ambiguous_keys(self):
        from dart_risk_mcp.core.signals import AMBIGUOUS_SIGNAL_KEYS

        self.assertEqual(self.data["ambiguous_signal_keys"], sorted(AMBIGUOUS_SIGNAL_KEYS))

    def test_export_does_not_leak_score_or_severity_in_rules(self):
        """무점수 원칙 — 기존 경계가 유지되는지 재확인."""
        blob = json.dumps(self.data, ensure_ascii=False)
        self.assertNotIn('"score"', blob)
        self.assertNotIn('"severity"', blob)


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


class TestCatalogData(unittest.TestCase):
    """금감원 적발 사례(catalog_classified.jsonl) → signals-data.json의
    "catalog" 키. 뷰어 배선 작업 1(2026-08-17). 점수·등급 미노출 원칙은
    이 카탈로그 파이프라인의 confidence 필드에도 동일하게 적용된다."""

    def setUp(self):
        self.data = build_signals_data()
        self.catalog = self.data["catalog"]
        self.records = _load_catalog_records()
        self.tagged = [r for r in self.records if r.get("taxonomy_ids")]

    def test_total_cases_matches_tagged_record_count(self):
        self.assertEqual(self.catalog["total_cases"], len(self.tagged))
        # 브리프 실측값 — 회귀 시 즉시 드러나도록 고정값도 함께 확인.
        self.assertEqual(self.catalog["total_cases"], 277)

    def test_by_taxonomy_n_matches_direct_count(self):
        expected: Counter = Counter()
        for r in self.tagged:
            for tid in r["taxonomy_ids"]:
                expected[tid] += 1
        by_tax = self.catalog["by_taxonomy"]
        self.assertEqual(set(by_tax.keys()), set(expected.keys()))
        for tid, n in expected.items():
            self.assertEqual(by_tax[tid]["n"], n, msg=tid)

    def test_tax_labels_cover_all_45_taxonomy_ids(self):
        self.assertEqual(set(self.catalog["tax_labels"].keys()), set(TAXONOMY.keys()))
        self.assertEqual(len(self.catalog["tax_labels"]), 45)
        for tid, label in self.catalog["tax_labels"].items():
            self.assertIsInstance(label, str)
            self.assertTrue(label, msg=tid)

    def test_recent_capped_at_3_sorted_desc_with_only_dtu_fields(self):
        for tid, bucket in self.catalog["by_taxonomy"].items():
            recent = bucket["recent"]
            self.assertLessEqual(len(recent), 3, msg=tid)
            dates = [r["d"] for r in recent]
            self.assertEqual(dates, sorted(dates, reverse=True), msg=tid)
            for r in recent:
                self.assertEqual(set(r.keys()), {"d", "t", "u"}, msg=tid)

    def test_tech_and_laws_capped(self):
        for tid, bucket in self.catalog["by_taxonomy"].items():
            self.assertLessEqual(len(bucket["tech"]), 5, msg=tid)
            self.assertLessEqual(len(bucket["laws"]), 3, msg=tid)
            for item in bucket["tech"]:
                self.assertEqual(len(item), 2)
                self.assertIsInstance(item[0], str)
                self.assertIsInstance(item[1], int)
            for item in bucket["laws"]:
                self.assertEqual(len(item), 2)

    def test_no_score_severity_confidence_leak_in_full_export(self):
        """v0.8.5 무점수 원칙 — signals-data.json 전체 문자열에 판정성
        키(severity/base_score/confidence)가 어디에도 없어야 한다."""
        blob = json.dumps(self.data, ensure_ascii=False)
        self.assertNotIn('"severity"', blob)
        self.assertNotIn('"base_score"', blob)
        self.assertNotIn('"confidence"', blob)

    def test_catalog_graceful_when_jsonl_missing(self):
        """카탈로그 파일이 없어도(경로 오타·미생성) build_catalog_data가
        예외 없이 빈 구조를 반환해야 한다 — 뷰어가 catalog 키를 항상
        참조할 수 있게."""
        import export_tool_data as mod

        original_path = mod._CATALOG_JSONL
        try:
            mod._CATALOG_JSONL = os.path.join(
                os.path.dirname(__file__), "does_not_exist.jsonl")
            result = mod.build_catalog_data()
            self.assertEqual(result["total_cases"], 0)
            self.assertEqual(result["by_taxonomy"], {})
            self.assertEqual(len(result["tax_labels"]), 45)
        finally:
            mod._CATALOG_JSONL = original_path

    def test_json_serializable_with_catalog(self):
        json.dumps(self.data, ensure_ascii=False)


if __name__ == "__main__":
    unittest.main()


class TestViewerVersionMeta(unittest.TestCase):
    """뷰어 하단 버전 표기의 단일 출처 고정.

    버전이 세 곳(`dart_risk_mcp/__init__.py`·`pyproject.toml`·내보낸
    `signals-data.json`)에 흩어져 있어 릴리스 때 한 곳만 올리면 뷰어가 옛
    버전을 계속 보여준다. 세 값의 일치를 기계적으로 고정한다.
    """

    def test_meta_version_matches_package_and_pyproject(self) -> None:
        import tomllib

        from dart_risk_mcp import __version__ as pkg_version

        root = Path(__file__).resolve().parents[1]
        cfg = tomllib.loads((root / "pyproject.toml").read_text(encoding="utf-8"))
        pyproject_version = cfg["project"]["version"]
        exported = json.loads(
            (root / "docs" / "tool" / "signals-data.json").read_text(encoding="utf-8")
        )

        self.assertEqual(pkg_version, pyproject_version)
        self.assertEqual(exported["meta"]["version"], pkg_version)

    def test_meta_has_no_timestamp(self) -> None:
        """재생성마다 diff가 나는 값(타임스탬프 등)을 meta에 넣지 않는다."""
        root = Path(__file__).resolve().parents[1]
        exported = json.loads(
            (root / "docs" / "tool" / "signals-data.json").read_text(encoding="utf-8")
        )
        self.assertEqual(set(exported["meta"]), {"version"})
