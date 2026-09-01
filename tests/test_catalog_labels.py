"""카탈로그 한글 라벨 역추출·로드 회귀 테스트.

기존 MD 37개 유형의 한글 제목·정의·위험신호는 v0.7.5 한글화 산출물로 MD에만
존재한다(TAXONOMY의 name은 대부분 영문). MD 재생성 시 영문 퇴행을
막으려면 이 라벨을 별도 자산으로 보존해야 한다.
"""
import re
import unittest
from pathlib import Path

from dart_risk_mcp.core import catalog
from dart_risk_mcp.core.taxonomy import TAXONOMY

from scripts.catalog.extract_labels import parse_md_labels
from scripts.catalog.labels import label_for, load_labels

_MD_DIR = Path(__file__).resolve().parents[1] / "dart_risk_mcp" / "knowledge" / "manipulation_catalog"

# dart-monitor에서 이식한 손수 작성 MD가 담고 있던 37종. 파이프라인 재생성이 이 중
# 하나라도 떨어뜨리면 회귀이므로 명시적으로 고정한다.
# 초기 37종 이후에 신설된 taxonomy. ⚠ 이름에 개수를 넣지 않는다 —
# 「_NEW_8」이던 것이 1.8 신설(2026-09-02)로 9종이 됐다.
_POST_LEGACY = ["1.8", "2.7", "2.8", "3.6", "3.7", "5.6", "5.7", "5.8", "8.5"]
_LEGACY_37 = {
    "1.1", "1.2", "1.3", "1.4", "1.5", "1.6", "1.7",
    "2.1", "2.2", "2.3", "2.4", "2.5", "2.6",
    "3.1", "3.2", "3.3", "3.4", "3.5",
    "4.1", "4.2", "4.3", "4.4",
    "5.1", "5.2", "5.3", "5.4", "5.5",
    "6.1", "6.2", "6.3",
    "7.1", "7.2", "7.3",
    "8.1", "8.2", "8.3", "8.4",
}

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

_SAMPLE_MD_WITH_ARTICLES = _SAMPLE_MD.replace(
    '- **2024-01-23 / 금융감독원** — [제목](https://example.invalid/a)\n',
    '- **2024-01-23 / 금융감독원** — [제목](https://example.invalid/a)\n'
    '\n### 기존 현장 기사 인용\n\n- 위메이드 800억원 CB조기상환\n- 리픽싱모니터\n',
)


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

    def test_field_articles_missing_section_returns_empty_list(self):
        # 기존 현장 기사 인용 섹션이 없는 블록은 빈 리스트여야 한다(호출부가 폴백 결정).
        got = parse_md_labels(_SAMPLE_MD)
        self.assertEqual(got["1.1"]["field_articles"], [])
        self.assertEqual(got["1.2"]["field_articles"], [])

    def test_field_articles_extracted_from_section(self):
        got = parse_md_labels(_SAMPLE_MD_WITH_ARTICLES)
        self.assertEqual(
            got["1.1"]["field_articles"],
            ["위메이드 800억원 CB조기상환", "리픽싱모니터"],
        )

    def test_real_catalog_yields_all_types(self):
        # 실제 카탈로그 8개 파일에서 taxonomy **전종**이 파싱돼야 한다.
        # ⚠ 개수를 하드코딩하지 않는다 — 1.8 신설(2026-09-02) 때
        #    「45」가 세 곳에서 깨졌다. TAXONOMY에서 파생한다.
        from dart_risk_mcp.core.taxonomy import TAXONOMY
        # 기준선이 37이던 시절은 dart-monitor에서 이식한 손수 작성 MD를 쓰던 때이고,
        # 2026-08-17 파이프라인 재생성으로 _LEGACY_37에 없던 8종(2.7·2.8·3.6·3.7·
        # 5.6·5.7·5.8·8.5 — 사례 공백을 메우려던 바로 그 유형들)이 채워졌다.
        merged = {}
        for p in sorted(_MD_DIR.glob("0*.md")):
            merged.update(parse_md_labels(p.read_text(encoding="utf-8")))
        self.assertEqual(len(merged), len(TAXONOMY))
        self.assertEqual(merged["1.1"]["title"], "전환가액 하향조정(리픽싱)")
        self.assertEqual(sorted(set(merged) - _LEGACY_37), _POST_LEGACY)

    def test_real_catalog_field_articles_legacy_37_preserved(self):
        # 재생성이 기존 한글 '현장 기사 인용'을 지우지 않았는지 지키는 가드다.
        # 신규 8종은 이식 원본에 기사가 없었으므로 비어 있는 것이 정상 — 그래서
        # "전부 있어야 한다"가 아니라 "기존 37종은 전부 있어야 한다"로 검사한다.
        merged = {}
        for p in sorted(_MD_DIR.glob("0*.md")):
            merged.update(parse_md_labels(p.read_text(encoding="utf-8")))
        without_articles = [t for t in sorted(_LEGACY_37) if not merged[t]["field_articles"]]
        self.assertEqual(without_articles, [])
        self.assertEqual(
            merged["1.1"]["field_articles"],
            ["위메이드 800억원 CB조기상환", "리픽싱모니터"],
        )
        # 기사 총량도 고정한다 — 유형 수가 늘어도 인용이 새거나 중복되면 안 된다.
        self.assertEqual(sum(len(v["field_articles"]) for v in merged.values()), 49)


class TestLoadLabels(unittest.TestCase):
    def test_all_taxonomy_ids_have_korean_labels(self):
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

    def test_label_for_includes_field_articles(self):
        from dart_risk_mcp.core.taxonomy import TAXONOMY

        labels = {"1.1": {"title": "한글제목", "definition": "한글정의", "red_flags": ["신호"],
                          "field_articles": ["위메이드 800억원 CB조기상환"]}}
        got = label_for("1.1", labels, TAXONOMY)
        self.assertEqual(got["field_articles"], ["위메이드 800억원 CB조기상환"])

    def test_label_for_field_articles_defaults_to_empty_list(self):
        # field_articles는 TAXONOMY에 대응 필드가 없다(수기 자산) — 라벨에 없으면 빈 리스트.
        from dart_risk_mcp.core.taxonomy import TAXONOMY

        got = label_for("1.1", {}, TAXONOMY)
        self.assertEqual(got["field_articles"], [])


if __name__ == "__main__":
    unittest.main()


class TestInstalledArtifactLabels(unittest.TestCase):
    """설치본(휠)에서도 45종 한글 라벨이 나온다.

    `catalog._LABELS_KO_PATH`는 `Path(__file__).parent.parent.parent /
    "data" / "catalog" / "labels_ko.json"` — **패키지 밖**을 가리킨다.
    개발 체크아웃에서는 레포 루트의 파일이 잡히지만, `pip install` 뒤에는
    `site-packages/data/...`가 되어 **존재하지 않는다**.

    2026-08-23 실측(v1.20.0 휠을 임시 디렉터리에 설치해 확인):

        labels_ko 경로 존재: False
        labels_ko 로드 결과: 0종
        한글 라벨이 없는 id: 0종   ← 동봉 MD가 전부 덮는다

    즉 지금은 무사하지만, **라벨이 `labels_ko.json`에만 있고 동봉 MD에는
    없는 taxonomy가 하나라도 생기면 개발에서는 한글, 설치본에서는 영문**이
    된다 — 배포본에서만 조용히 퇴화하는 종류다(CLAUDE.md가 경고하는 지점).

    이 테스트는 그 상황을 흉내 낸다: labels_ko를 못 읽는 상태로 만들고
    45종이 여전히 한글인지 본다.
    """

    def setUp(self):
        self._orig_path = catalog._LABELS_KO_PATH
        self._orig_cache = catalog._labels_ko_cache

    def tearDown(self):
        catalog._LABELS_KO_PATH = self._orig_path
        catalog._labels_ko_cache = self._orig_cache

    def _simulate_installed(self):
        """labels_ko.json이 없는 환경(설치본)을 만든다."""
        catalog._LABELS_KO_PATH = Path("존재하지-않는-경로") / "labels_ko.json"
        catalog._labels_ko_cache = None

    def test_labels_ko_없이도_45종이_한글이다(self):
        self._simulate_installed()
        self.assertEqual(catalog._load_labels_ko(), {},
                         "설치본 흉내가 제대로 안 됐다")
        eng = [t for t in TAXONOMY
               if not re.search(r"[가-힣]", catalog.taxonomy_label_ko(t) or "")]
        self.assertEqual(eng, [], f"설치본에서 영문으로 퇴화하는 id: {eng}")

    def test_labels_ko_없이도_발췌가_나온다(self):
        self._simulate_installed()
        empty = [t for t in TAXONOMY
                 if not (catalog.load_catalog_excerpt([t]) or "").strip()]
        self.assertEqual(empty, [], f"설치본에서 발췌가 비는 id: {empty}")

    def test_동봉_MD가_패키지_안에_있다(self):
        """`_CATALOG_DIR`이 패키지 밖이면 휠에 안 실린다."""
        pkg_root = Path(catalog.__file__).parent.parent
        self.assertTrue(
            str(catalog._CATALOG_DIR).startswith(str(pkg_root)),
            f"카탈로그 디렉터리가 패키지 밖이다: {catalog._CATALOG_DIR}")
        self.assertTrue(any(catalog._CATALOG_DIR.glob("*.md")),
                        "동봉 MD가 없다")
