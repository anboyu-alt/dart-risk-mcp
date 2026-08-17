"""패키징 경계 회귀 테스트.

핵심 계약: pypdf는 scripts 전용 optional이며 런타임 패키지 의존성을 늘리지 않는다.
"""
import subprocess
import tomllib
import unittest
from pathlib import Path

_ROOT = Path(__file__).resolve().parents[1]


class TestPackaging(unittest.TestCase):
    def setUp(self):
        self.cfg = tomllib.loads((_ROOT / "pyproject.toml").read_text(encoding="utf-8"))

    def test_runtime_dependencies_unchanged(self):
        deps = self.cfg["project"]["dependencies"]
        self.assertEqual(len(deps), 2, f"런타임 의존성이 늘었다: {deps}")
        self.assertTrue(any(d.startswith("mcp") for d in deps))
        self.assertTrue(any(d.startswith("requests") for d in deps))

    def test_pypdf_is_optional_only(self):
        optional = self.cfg["project"].get("optional-dependencies", {})
        self.assertIn("catalog", optional)
        self.assertTrue(any("pypdf" in d for d in optional["catalog"]))
        self.assertFalse(any("pypdf" in d for d in self.cfg["project"]["dependencies"]))

    def test_runtime_package_does_not_import_pypdf(self):
        hits = [p for p in (_ROOT / "dart_risk_mcp").rglob("*.py")
                if "pypdf" in p.read_text(encoding="utf-8")]
        self.assertEqual(hits, [], f"런타임 패키지가 pypdf를 참조한다: {hits}")


class TestGitignoreKeepsCumulativeAssets(unittest.TestCase):
    """카탈로그 파이프라인의 누적 자산은 .gitignore가 제외하면 안 된다.

    회귀 배경(2026-08-17 전체 브랜치 리뷰): `data/catalog/*.jsonl`이 이 둘을
    제외하고 있어서, 워크플로우가 매번 깨끗한 러너에서 시작하면 --resume이
    아무 이전 상태도 못 찾아 그 실행분만 수집·분류하고, build_md.py가 그 얇은
    결과로 MD 8개를 무조건 덮어써 누적 사례가 전부 사라진 채 커밋되는 사고가
    났다. `git check-ignore`로 실제 git 동작을 확인한다(문자열 매칭이 아니라
    글롭 규칙 자체가 바뀌어도 이 테스트가 계속 유효하도록).
    """

    def _is_ignored(self, relpath: str) -> bool:
        result = subprocess.run(
            ["git", "check-ignore", "-q", relpath],
            cwd=_ROOT, capture_output=True,
        )
        return result.returncode == 0

    def test_catalog_sources_jsonl_not_ignored(self):
        self.assertFalse(self._is_ignored("data/catalog/catalog_sources.jsonl"))

    def test_catalog_classified_jsonl_not_ignored(self):
        self.assertFalse(self._is_ignored("data/catalog/catalog_classified.jsonl"))

    def test_collect_state_json_not_ignored(self):
        self.assertFalse(self._is_ignored("data/catalog/collect_state.json"))

    def test_labels_ko_json_not_ignored(self):
        self.assertFalse(self._is_ignored("data/catalog/labels_ko.json"))


class TestWorkflow(unittest.TestCase):
    def test_workflow_exists_with_dispatch_and_cron(self):
        wf = (_ROOT / ".github" / "workflows" / "refresh-catalog.yml").read_text(encoding="utf-8")
        self.assertIn("workflow_dispatch", wf)
        self.assertIn("cron", wf)
        self.assertIn("ANTHROPIC_API_KEY", wf)

    def test_workflow_does_not_require_collection_api_keys(self):
        # 수집은 게시판 웹 파싱으로 전환됐다(2026-08-17). FSS 오픈API는 일일 30회
        # 한도가 실증돼 폐기했고, 정책브리핑은 이 파이프라인 범위 밖이다.
        # 워크플로우가 이 키들을 요구하면 없는 Secret을 기다리다 실패한다.
        wf = (_ROOT / ".github" / "workflows" / "refresh-catalog.yml").read_text(encoding="utf-8")
        self.assertNotIn("FSS_API_KEY", wf)
        self.assertNotIn("DATA_GO_KR_API_KEY", wf)

    def test_workflow_installs_catalog_extra(self):
        wf = (_ROOT / ".github" / "workflows" / "refresh-catalog.yml").read_text(encoding="utf-8")
        self.assertIn("[catalog]", wf)

    def test_workflow_commits_intermediate_jsonl_assets(self):
        # git add가 MD·gap report만 잡으면 매 실행이 빈 러너에서 다시 시작한다
        # (Finding 1). data/catalog 전체(중간 산출물 포함)를 커밋 대상에 넣는다.
        wf = (_ROOT / ".github" / "workflows" / "refresh-catalog.yml").read_text(encoding="utf-8")
        self.assertIn("data/catalog", wf)

    def test_workflow_verifies_mapped_case_count_before_commit(self):
        # 발췌 비어있음 가드는 유형 정의가 남아 있으면 통과해버려 카탈로그
        # 백지화를 못 잡는다(Finding 1b). 매핑 건수 하한 체크가 별도로 있어야 한다.
        wf = (_ROOT / ".github" / "workflows" / "refresh-catalog.yml").read_text(encoding="utf-8")
        self.assertIn("catalog_classified.jsonl", wf)
        self.assertIn("MIN_MAPPED_CASES", wf)
        commit_idx = wf.index("Commit updated catalog")
        guard_idx = wf.index("MIN_MAPPED_CASES")
        self.assertLess(guard_idx, commit_idx, "매핑 건수 가드가 커밋 단계보다 먼저 나와야 한다")


if __name__ == "__main__":
    unittest.main()
