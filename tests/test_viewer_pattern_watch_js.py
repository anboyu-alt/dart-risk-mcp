"""공개 뷰어(docs/tool/index.html)의 부분 겹침 패턴 함수 검증.

`findPatternOverlaps`/`tidCompare`/`patternOverlapLinesHTML`은 core
find_pattern_overlaps(taxonomy.py)의 JS 이식(순수 함수, DOM 접근 없음).
index.html은 CommonJS 모듈이 아니라 인라인 <script>이므로,
tests/test_viewer_affiliate_conduit_js.py와 같은 방식으로 함수 정의
구간만 텍스트로 잘라내(브레이스 매칭) node로 실행한다.
"""
import json
import pathlib
import re
import shutil
import subprocess
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_INDEX_HTML = _ROOT / "docs" / "tool" / "index.html"
_NODE = shutil.which("node")

_FUNC_NAMES = [
    "function tidCompare",
    # 2026-08-25: 카드 임계가 패턴 크기에 비례하게 바뀌며 신설된 헬퍼.
    # 빠뜨리면 findPatternOverlaps가 정의되지 않은 함수를 부른다.
    "function requiredOverlap",
    "function evidenceCount",
    "function findPatternOverlaps",
    "function patternOverlapLinesHTML",
]

# patternOverlapLinesHTML이 참조하는 esc() — index.html의 정의를 그대로 복사.
_ESC_HELPER = """
function esc(s) { return String(s).replace(/[&<>"]/g, (m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;" }[m])); }
"""


def _extract_script() -> str:
    html = _INDEX_HTML.read_text(encoding="utf-8")
    m = re.search(r"<script(?:\s[^>]*)?>(.*?)</script>", html, re.DOTALL)
    if not m:
        raise AssertionError("index.html에서 <script> 블록을 찾지 못했습니다")
    return m.group(1)


def _extract_block(name: str, src: str) -> str:
    idx = src.index(name)
    brace_start = src.index("{", idx)
    depth = 0
    i = brace_start
    while i < len(src):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[idx:i + 1]
        i += 1
    raise AssertionError(f"{name} 블록의 중괄호 균형을 찾지 못했습니다")


def _extracted_source() -> str:
    script = _extract_script()
    parts = [_extract_block(name, script) for name in _FUNC_NAMES]
    return "\n\n".join(parts)


def run_js(expression: str, data=None):
    """추출한 함수 정의 + esc()를 전역에 얹고 표현식을 평가한다.

    data가 주어지면 전역 DATA(카탈로그 라벨 등)를 그 값으로 설정한다 —
    patternOverlapLinesHTML은 DATA.catalog.tax_labels를 참조한다.
    """
    src = _extracted_source()
    data_line = f"const DATA = {json.dumps(data, ensure_ascii=False)};" if data is not None else "const DATA = {};"
    script = (
        f"{_ESC_HELPER}\n{data_line}\n{src}\n"
        f"process.stdout.write(JSON.stringify({expression}));"
    )
    out = subprocess.run(
        [_NODE, "-e", script], capture_output=True, text=True, encoding="utf-8"
    )
    if out.returncode != 0:
        raise AssertionError(f"node 실행 실패:\n{out.stderr}")
    return json.loads(out.stdout)


@unittest.skipUnless(_NODE, "node가 없어 index.html의 패턴 부분 겹침 함수를 검증할 수 없습니다")
class ExtractionSanityTest(unittest.TestCase):
    def test_script_and_functions_found(self):
        src = _extracted_source()
        for token in _FUNC_NAMES:
            self.assertIn(token, src)


_TWO_PATTERNS = [
    {"key": "pattern_ab", "name": "Pattern AB", "description": "A and B",
     "signal_sequence": ["1.1", "1.2"], "timeline_months": 6,
     "field_evidence": [], "checkpoints": ["체크A", "체크B"]},
    {"key": "pattern_abc", "name": "Pattern ABC", "description": "A, B and C",
     "signal_sequence": ["1.1", "1.2", "2.1"], "timeline_months": 12,
     "field_evidence": [], "checkpoints": []},
]


@unittest.skipUnless(_NODE, "node가 없어 index.html의 패턴 부분 겹침 함수를 검증할 수 없습니다")
class FindPatternOverlapsJsTest(unittest.TestCase):
    def test_below_min_overlap_excluded(self):
        result = run_js(
            f"findPatternOverlaps({json.dumps(_TWO_PATTERNS)}, new Set(['1.1']), 2)"
        )
        self.assertEqual(result, [])

    def test_full_and_partial_match_reported(self):
        result = run_js(
            f"findPatternOverlaps({json.dumps(_TWO_PATTERNS)}, new Set(['1.1', '1.2']), 2)"
        )
        by_key = {r["key"]: r for r in result}
        self.assertEqual(by_key["pattern_ab"]["n_matched"], 2)
        self.assertEqual(by_key["pattern_ab"]["n_total"], 2)
        self.assertEqual(by_key["pattern_ab"]["missing"], [])
        self.assertEqual(by_key["pattern_abc"]["n_matched"], 2)
        self.assertEqual(by_key["pattern_abc"]["n_total"], 3)
        self.assertEqual(by_key["pattern_abc"]["missing"], ["2.1"])

    def test_sort_order_ratio_desc_then_key_asc(self):
        # pattern_ab(2/2=1.0)가 pattern_abc(2/3=0.667)보다 앞서야 한다.
        result = run_js(
            f"findPatternOverlaps({json.dumps(_TWO_PATTERNS)}, new Set(['1.1', '1.2']), 2)"
        )
        keys = [r["key"] for r in result]
        self.assertEqual(keys, ["pattern_ab", "pattern_abc"])

    def test_determinism_regardless_of_set_insertion_order(self):
        r1 = run_js(
            f"findPatternOverlaps({json.dumps(_TWO_PATTERNS)}, new Set(['1.1', '1.2', '2.1']), 2)"
        )
        r2 = run_js(
            f"findPatternOverlaps({json.dumps(_TWO_PATTERNS)}, new Set(['2.1', '1.2', '1.1']), 2)"
        )
        self.assertEqual(r1, r2)

    def test_unknown_taxonomy_in_set_does_not_throw(self):
        result = run_js(
            f"findPatternOverlaps({json.dumps(_TWO_PATTERNS)}, new Set(['99.9', '1.1', '1.2']), 2)"
        )
        self.assertTrue(any(r["key"] == "pattern_ab" for r in result))


@unittest.skipUnless(_NODE, "node가 없어 index.html의 패턴 부분 겹침 함수를 검증할 수 없습니다")
class PatternOverlapLinesHtmlJsTest(unittest.TestCase):
    def test_shows_matched_and_missing_with_korean_labels(self):
        data = {"catalog": {"tax_labels": {"1.1": "라벨A", "1.2": "라벨B", "2.1": "라벨C"}}}
        overlap = {"matched": ["1.1", "1.2"], "missing": ["2.1"]}
        html = run_js(f"patternOverlapLinesHTML({json.dumps(overlap)})", data=data)
        self.assertIn("관찰됨", html)
        self.assertIn("라벨A", html)
        self.assertIn("라벨B", html)
        self.assertIn("안 보임", html)
        self.assertIn("라벨C", html)

    def test_full_match_omits_missing_block(self):
        data = {"catalog": {"tax_labels": {"1.1": "라벨A"}}}
        overlap = {"matched": ["1.1"], "missing": []}
        html = run_js(f"patternOverlapLinesHTML({json.dumps(overlap)})", data=data)
        self.assertIn("관찰됨", html)
        self.assertNotIn("안 보임", html)

    def test_unknown_label_falls_back_to_taxonomy_id(self):
        data = {"catalog": {"tax_labels": {}}}
        overlap = {"matched": ["9.9"], "missing": []}
        html = run_js(f"patternOverlapLinesHTML({json.dumps(overlap)})", data=data)
        self.assertIn("9.9", html)


if __name__ == "__main__":
    unittest.main()
