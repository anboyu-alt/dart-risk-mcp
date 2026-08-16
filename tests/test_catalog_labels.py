"""카탈로그 한글 라벨 역추출·로드 회귀 테스트.

기존 MD 37개 유형의 한글 제목·정의·위험신호는 v0.7.5 한글화 산출물로 MD에만
존재한다(TAXONOMY의 name은 45개 중 41개가 영문). MD 재생성 시 영문 퇴행을
막으려면 이 라벨을 별도 자산으로 보존해야 한다.
"""
import unittest
from pathlib import Path

from scripts.catalog.extract_labels import parse_md_labels
from scripts.catalog.labels import label_for, load_labels

_MD_DIR = Path(__file__).resolve().parents[1] / "dart_risk_mcp" / "knowledge" / "manipulation_catalog"

_SAMPLE_MD = """# 전환사채·부채 조작
> 카테고리: Convertible Bond & Debt Manipulation
> 생성일: 2026-04-20
> 포함 유형: 1.1, 1.2

---

## 1.1: 전환가액 하향조정(리픽싱)

- **Severity**: HIGH
- **Base Score**: 3
- **Crisis Timeline**: 12개월

### 정의
DART 공시 없이 전환가액을 아래쪽으로 조정해 전환 시 지분 희석을 키우는 행위입니다.

### 탐지 키워드
리픽싱, 전환가액조정

### 위험 신호
- 한 번에 10% 이상의 큰 폭 하향 조정
- 6개월 안에 두 번 이상 반복되는 리픽싱

### 금감원·금융위 적발 사례

- **2024-01-23 / 금융감독원** — [제목](https://example.invalid/a)

## 1.2: 콜옵션 남용

- **Severity**: HIGH
- **Base Score**: 3
- **Crisis Timeline**: 12개월

### 정의
콜옵션을 최대주주에게 몰아주는 행위입니다.

### 탐지 키워드
콜옵션

### 위험 신호
- 콜옵션 행사자가 최대주주
"""


class TestParseMdLabels(unittest.TestCase):
    def test_parses_title_definition_and_red_flags(self):
        got = parse_md_labels(_SAMPLE_MD)
        self.assertEqual(sorted(got), ["1.1", "1.2"])
        self.assertEqual(got["1.1"]["title"], "전환가액 하향조정(리픽싱)")
        self.assertTrue(got["1.1"]["definition"].startswith("DART 공시 없이"))
        self.assertEqual(len(got["1.1"]["red_flags"]), 2)
        self.assertEqual(got["1.2"]["red_flags"], ["콜옵션 행사자가 최대주주"])

    def test_definition_excludes_following_sections(self):
        got = parse_md_labels(_SAMPLE_MD)
        self.assertNotIn("탐지 키워드", got["1.1"]["definition"])
        self.assertNotIn("###", got["1.1"]["definition"])

    def test_real_catalog_yields_37_types(self):
        # 실제 카탈로그 8개 파일에서 37개 유형이 파싱돼야 한다(실측 기준선).
        merged = {}
        for p in sorted(_MD_DIR.glob("0*.md")):
            merged.update(parse_md_labels(p.read_text(encoding="utf-8")))
        self.assertEqual(len(merged), 37)
        self.assertEqual(merged["1.1"]["title"], "전환가액 하향조정(리픽싱)")


class TestLoadLabels(unittest.TestCase):
    def test_all_45_taxonomy_ids_have_korean_labels(self):
        from dart_risk_mcp.core.taxonomy import TAXONOMY

        labels = load_labels()
        missing = [t for t in TAXONOMY if t not in labels]
        self.assertEqual(missing, [], f"한글 라벨 누락: {missing}")

    def test_label_for_prefers_labels_over_taxonomy(self):
        from dart_risk_mcp.core.taxonomy import TAXONOMY

        labels = {"1.1": {"title": "한글제목", "definition": "한글정의", "red_flags": ["신호"]}}
        got = label_for("1.1", labels, TAXONOMY)
        self.assertEqual(got["title"], "한글제목")

    def test_label_for_falls_back_to_taxonomy(self):
        from dart_risk_mcp.core.taxonomy import TAXONOMY

        got = label_for("1.1", {}, TAXONOMY)
        self.assertEqual(got["title"], TAXONOMY["1.1"]["name"])
        self.assertEqual(got["red_flags"], TAXONOMY["1.1"]["red_flags"])


if __name__ == "__main__":
    unittest.main()
