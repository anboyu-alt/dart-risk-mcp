"""v0.7.4 — 골드 파일에 대한 내부 코드·영문 약어 누출 회귀 검증.

실 API 호출 없이 `tests/fixtures/sample_outputs/` 안의 `.txt`만 스캔한다.
렌더러가 내부 키·영문 메타·영문 약어를 출력 경계 밖으로 흘리면 실패한다.

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
