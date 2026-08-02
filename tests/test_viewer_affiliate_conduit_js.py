"""후속 3위: 공개 뷰어(docs/tool/index.html)의 종속회사 경유 유출 사실 병기.

matchAffiliateRow/summarizeAffiliateStake/formatAffiliateStakeLine은 core
dart_client.py·server.py의 동명 함수를 이식한 순수 함수(DOM 접근 없음)다.
node 서브프로세스로 실제 실행해 검증한다 — index.html은 CommonJS 모듈이
아니라 인라인 <script>이므로, 함수 정의 구간만 텍스트로 잘라내
(브레이스 매칭) node -e로 평가한다. fixture는
tests/test_affiliate_conduit_facts.py와 같은 아틀라스링크 실측 row를
공유한다.

fmtKRW(억원 반올림)를 뷰어가 이미 전역에서 쓰고 있어(loadFinancialCore 등),
formatAffiliateStakeLine의 억원 표기는 core _format_amount(절삭)와 값이
다를 수 있다(-4,969,000,000원 → 뷰어 -50억원 vs core -49억원) — 각 레이어가
기존에 쓰던 금액 포맷 유틸을 그대로 재사용한 의도된 차이다.
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
    "const AFFIL_CORP_SUFFIX_RE",
    "function foldCorpName",
    "function matchAffiliateRow",
    "const AFFIL_DASH_VALUES",
    "function affiliateInt",
    "function affiliateRatio",
    "function summarizeAffiliateStake",
    "function formatAffiliateStakeLine",
]

# 뷰어가 전역에서 이미 쓰는 금액 포맷 유틸 — index.html의 정의를 그대로 복사
# (formatAffiliateStakeLine이 fmtWon을 호출하므로 실행 환경에 있어야 한다).
_FMT_HELPERS = """
function fmtKRW(n) {
  if (n === null) return "―";
  const sign = n < 0 ? "-" : "";
  const a = Math.abs(n);
  if (a >= 1e12) return sign + (a / 1e12).toFixed(1) + "조";
  if (a >= 1e8) return sign + Math.round(a / 1e8).toLocaleString() + "억";
  return n.toLocaleString() + "원";
}
function fmtWon(n) {
  const s = fmtKRW(n);
  return s.endsWith("원") ? s : s + "원";
}
"""


def _extract_script() -> str:
    html = _INDEX_HTML.read_text(encoding="utf-8")
    m = re.search(r"<script(?:\s[^>]*)?>(.*?)</script>", html, re.DOTALL)
    if not m:
        raise AssertionError("index.html에서 <script> 블록을 찾지 못했습니다")
    return m.group(1)


def _extract_block(name: str, src: str) -> str:
    idx = src.index(name)
    if name.startswith("const"):
        end = src.index(";", idx)
        return src[idx:end + 1]
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


def run_js(expression: str):
    """추출한 함수 정의 + fmtKRW/fmtWon을 전역에 얹고 표현식을 평가한다."""
    src = _extracted_source()
    script = (
        f"{_FMT_HELPERS}\n{src}\n"
        f"process.stdout.write(JSON.stringify({expression}));"
    )
    out = subprocess.run(
        [_NODE, "-e", script], capture_output=True, text=True, encoding="utf-8"
    )
    if out.returncode != 0:
        raise AssertionError(f"node 실행 실패:\n{out.stderr}")
    return json.loads(out.stdout)


# ── fixture: 아틀라스링크 라이브 실측 row (tests/test_affiliate_conduit_facts.py와 동일) ──
_HANKUK_FILE_ROW_2025 = json.dumps({
    "inv_prm": "(주)한국파일",
    "frst_acqs_de": "2023.09.07",
    "invstmnt_purps": "경영참여",
    "bsis_blce_qota_rt": "46.32",
    "trmend_blce_qota_rt": "62.43",
    "incrs_dcrs_acqs_dsps_amount": "4,900,000,000",
    "recent_bsns_year_fnnr_sttus_thstrm_ntpf": "-4,969,000,000",
}, ensure_ascii=False)

_SEONGWOO_ROW_2024 = json.dumps({
    "inv_prm": "성우기업(주)",
    "frst_acqs_de": "2023.09.07",
    "invstmnt_purps": "경영참여",
    "bsis_blce_qota_rt": "46.32",
    "trmend_blce_qota_rt": "46.32",
    "incrs_dcrs_acqs_dsps_amount": "-",
    "recent_bsns_year_fnnr_sttus_thstrm_ntpf": "1,200,000,000",
}, ensure_ascii=False)


@unittest.skipUnless(_NODE, "node가 없어 index.html의 종속회사 사실 병기 함수를 검증할 수 없습니다")
class ExtractionSanityTest(unittest.TestCase):
    def test_script_and_functions_found(self):
        # index.html이 나중에 리팩터링돼도 함수 자체가 사라지면 여기서 바로
        # 실패해야 한다 — 조용히 스킵되는 것보다 낫다.
        src = _extracted_source()
        for token in ("function matchAffiliateRow", "function summarizeAffiliateStake",
                      "function formatAffiliateStakeLine"):
            self.assertIn(token, src)


@unittest.skipUnless(_NODE, "node가 없어 index.html의 종속회사 사실 병기 함수를 검증할 수 없습니다")
class MatchAffiliateRowJsTest(unittest.TestCase):
    def test_matches_despite_corp_suffix_variants(self):
        for variant in ("(주)한국파일", "㈜한국파일", "주식회사 한국파일", "한국파일"):
            with self.subTest(variant=variant):
                result = run_js(f"matchAffiliateRow([{_HANKUK_FILE_ROW_2025}], {json.dumps(variant, ensure_ascii=False)})")
                self.assertEqual(result["inv_prm"], "(주)한국파일")

    def test_no_match_returns_null(self):
        result = run_js(f"matchAffiliateRow([{_HANKUK_FILE_ROW_2025}], '존재하지않는법인')")
        self.assertIsNone(result)

    def test_empty_rows_returns_null(self):
        result = run_js("matchAffiliateRow([], '한국파일')")
        self.assertIsNone(result)


@unittest.skipUnless(_NODE, "node가 없어 index.html의 종속회사 사실 병기 함수를 검증할 수 없습니다")
class SummarizeAffiliateStakeJsTest(unittest.TestCase):
    def test_live_row_hankuk_file(self):
        stake = run_js(f"summarizeAffiliateStake({_HANKUK_FILE_ROW_2025})")
        self.assertEqual(stake["firstAcquired"], "2023-09")
        self.assertAlmostEqual(stake["stakeBegin"], 46.32)
        self.assertAlmostEqual(stake["stakeEnd"], 62.43)
        self.assertEqual(stake["addedAmount"], 4_900_000_000)
        self.assertEqual(stake["recentNetProfit"], -4_969_000_000)

    def test_dash_amount_parsed_as_null(self):
        stake = run_js(f"summarizeAffiliateStake({_SEONGWOO_ROW_2024})")
        self.assertIsNone(stake["addedAmount"])
        self.assertEqual(stake["stakeBegin"], stake["stakeEnd"])

    def test_malformed_numbers_do_not_throw(self):
        row = json.dumps({
            "inv_prm": "테스트법인", "frst_acqs_de": "N/A",
            "bsis_blce_qota_rt": "abc", "trmend_blce_qota_rt": "-",
            "incrs_dcrs_acqs_dsps_amount": "", "recent_bsns_year_fnnr_sttus_thstrm_ntpf": "-",
            "invstmnt_purps": "",
        }, ensure_ascii=False)
        stake = run_js(f"summarizeAffiliateStake({row})")
        self.assertEqual(stake["firstAcquired"], "")
        self.assertIsNone(stake["stakeBegin"])
        self.assertIsNone(stake["recentNetProfit"])


@unittest.skipUnless(_NODE, "node가 없어 index.html의 종속회사 사실 병기 함수를 검증할 수 없습니다")
class FormatAffiliateStakeLineJsTest(unittest.TestCase):
    def test_full_line_uses_viewer_fmtKRW_convention(self):
        # 뷰어 fmtKRW는 반올림(-50억원) — core _format_amount(절삭, -49억원)와
        # 값이 다르다. 각 레이어가 기존에 쓰던 유틸을 그대로 재사용한 결과다.
        line = run_js(f"formatAffiliateStakeLine(summarizeAffiliateStake({_HANKUK_FILE_ROW_2025}))")
        self.assertEqual(
            line,
            "최초취득 2023-09 · 지분 46.3→62.4% 확대 · 피출자사 최근 순이익 -50억원",
        )

    def test_no_stake_change_omits_segment(self):
        line = run_js(f"formatAffiliateStakeLine(summarizeAffiliateStake({_SEONGWOO_ROW_2024}))")
        self.assertNotIn("지분", line)
        self.assertIn("최초취득 2023-09", line)

    def test_empty_stake_returns_empty_string(self):
        empty = json.dumps({
            "firstAcquired": "", "stakeBegin": None, "stakeEnd": None,
            "addedAmount": None, "recentNetProfit": None, "purpose": "",
        })
        line = run_js(f"formatAffiliateStakeLine({empty})")
        self.assertEqual(line, "")


if __name__ == "__main__":
    unittest.main()
