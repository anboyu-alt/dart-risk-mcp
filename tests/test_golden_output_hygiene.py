"""v0.7.4 / v0.8.5 — 골드 파일에 대한 내부 코드·영문 약어·점수/등급 누출 회귀 검증.

실 API 호출 없이 `tests/fixtures/sample_outputs/` 안의 `.txt`만 스캔한다.
렌더러가 내부 키·영문 메타·영문 약어·점수/등급/등급 이모지를 출력 경계 밖으로
흘리면 실패한다. v0.8.5에서 점수·등급·이모지 검증 3종이 추가됐다.

재수집 절차: `python tmp/v072_review/regen_fixtures.py` 후 `git diff` 확인.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "sample_outputs"

# 사용자 출력에 절대 노출되면 안 되는 내부 flag 키 (v0.7.1~v0.7.3에서 제거 확정)
_INTERNAL_CODES = [
    "AR_SURGE",
    "INVENTORY_SURGE",
    "CASH_GAP",
    "CAPITAL_IMPAIRMENT",
    "CAPITAL_CHURN",
    "FUND_DIVERSION",
    "FUND_UNREPORTED",
    "DECISION_RELATED_PARTY",
    "DECISION_OVERSIZED",
    "DECISION_NO_EXTVAL",
]
# 카탈로그 MD 원본에 있는 영문 메타 라벨 (v0.7.3 _strip_taxonomy_metadata로 필터링)
_CATALOG_META = [
    "**Severity**",
    "**Base Score**",
    "**Crisis Timeline**",
    "### Red Flags",
]
# v0.7.3에서 한글화된 영문 약어. 공백 포함으로 false-positive(예: 한글 조사 직전의 OCF) 최소화.
_ABBREV = ["OCF "]

# v0.8.5 — 점수·등급·위상 이모지 노출 금지. 기업 위험도를 정량화하지 않는다는 원칙의 기계적 검증.
# 주의: 단순 "점" 글자는 "시점", "관점" 같은 정상 한국어와 충돌하므로 패턴을 좁힌다.
_SCORE_GRADE_PATTERNS = [
    (r"\d+\s*/\s*\d+\s*점", "'N/M점' 형식의 점수 표기"),
    (r"\d+\s*점\s*(?:$|[\s·,\)])", "'N점' 단독 점수 표기"),
    (r"위험\s*등급", "'위험 등급' 라벨"),
    (r"종합\s*스코어", "'종합 스코어' 라벨"),
    (r"종합\s*위험도", "'종합 위험도' 라벨"),
    (r"매우위험|고위험|중위험|저위험", "위험 등급 명칭"),
]
# 위상/위험도를 시각적으로 등급화하던 이모지 세트(v0.8.5에서 전면 제거)
_SEVERITY_EMOJI = ["🔴", "🟠", "🟡", "🟢", "🔵"]


class TestGoldenOutputHygiene(unittest.TestCase):
    def _iter_fixtures(self) -> list[Path]:
        return sorted(FIXTURES.glob("*.txt"))

    def test_no_internal_flag_codes(self) -> None:
        for path in self._iter_fixtures():
            text = path.read_text(encoding="utf-8")
            for code in _INTERNAL_CODES:
                self.assertNotIn(
                    code, text, f"{path.name}에 내부 flag 코드 '{code}' 노출"
                )

    def test_no_catalog_english_metadata(self) -> None:
        for path in self._iter_fixtures():
            text = path.read_text(encoding="utf-8")
            for token in _CATALOG_META:
                self.assertNotIn(
                    token, text, f"{path.name}에 카탈로그 영문 메타 '{token}' 노출"
                )
            # '## N.M: EnglishTitle' 헤더 라인도 0개여야 함
            self.assertFalse(
                re.search(r"^## \d+\.\d+: [A-Z][^\n]+", text, re.MULTILINE),
                f"{path.name}에 카탈로그 taxonomy 헤더 노출",
            )

    def test_no_english_abbreviations(self) -> None:
        for path in self._iter_fixtures():
            text = path.read_text(encoding="utf-8")
            for abbr in _ABBREV:
                self.assertNotIn(
                    abbr, text, f"{path.name}에 영문 약어 '{abbr.strip()}' 노출"
                )

    def test_no_score_or_grade_labels(self) -> None:
        """v0.8.5: 기업 위험도를 정량화하는 점수·등급 표기가 사용자 출력에 노출되면 안 된다."""
        for path in self._iter_fixtures():
            text = path.read_text(encoding="utf-8")
            for pattern, desc in _SCORE_GRADE_PATTERNS:
                self.assertFalse(
                    re.search(pattern, text),
                    f"{path.name}에 {desc} 노출",
                )

    def test_no_severity_emoji(self) -> None:
        """v0.8.5: 위상·위험도를 시각적으로 등급화하던 이모지 전면 금지."""
        for path in self._iter_fixtures():
            text = path.read_text(encoding="utf-8")
            for emoji in _SEVERITY_EMOJI:
                self.assertNotIn(
                    emoji, text, f"{path.name}에 등급 이모지 '{emoji}' 노출"
                )

    def test_fixture_set_non_empty(self) -> None:
        files = self._iter_fixtures()
        self.assertGreaterEqual(
            len(files), 10, "골드 파일이 10개 미만 — 수집이 불완전할 수 있음"
        )
        for p in files:
            self.assertGreater(
                p.stat().st_size, 100, f"{p.name}이 100바이트 미만 — 빈 응답일 가능성"
            )


if __name__ == "__main__":
    unittest.main()
