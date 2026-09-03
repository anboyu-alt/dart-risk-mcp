"""공개 뷰어(docs/tool/index.html)의 「읽는 법」 일반화 + 용어 사전 툴팁 검증
(PR-V).

core PR(머지됨)이 `signals-data.json`에 `glossary`·`glossary_aliases`·
`metric_prose`(7패널)를 실었다. 이 파일은 그것을 소비하는 뷰어 쪽 순수
함수 4종(`glossTermsHTML`·`boldMarksHTML`·`proseDetailsHTML`·
`leadSentenceHTML`)을 잠근다 — `tests/test_viewer_mezzanine_sort.py`와
같은 방식으로 함수 정의 구간만 텍스트로 잘라내(브레이스 매칭) node로
돌린다. esc() 세부 규칙(`&quot;` 변환 등)은
`tests/test_viewer_pattern_watch_js.py`가 index.html에서 그대로 복사해 온
것을 재사용한다 — 하네스의 `_cut`은 정규식 리터럴이 섞인 실제 `esc()`
본문을 브레이스 매칭으로 잘못 자를 수 있어(문자열 내 따옴표를 시작으로
오인) 통째로 이식본을 심는다.
"""
import json
import pathlib
import re
import shutil
import subprocess
import tempfile
import unittest

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = _ROOT / "docs" / "tool" / "index.html"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node가 없으면 뷰어 쪽을 돌릴 수 없다"
)

_FUNCS = (
    "function glossTermsHTML(",
    "function boldMarksHTML(",
    "function proseDetailsHTML(",
    "function leadSentenceHTML(",
)

# index.html의 실제 esc() 그대로 — test_viewer_pattern_watch_js.py에서 복사.
# glossTermsHTML이 내부에서 esc(defs[m])을 호출하고, proseDetailsHTML은
# proseTextHTML(내부에서 esc())을 거치므로 나이브한 이스케이프 shim으로는
# "따옴표·꺾쇠 보존" 검증이 무의미해진다.
_ESC_HELPER = (
    'function esc(s) { return String(s).replace(/[&<>"]/g, (m) => '
    '({ "&": "&amp;", "<": "&lt;", ">": "&gt;", \'"\': "&quot;" }[m])); }\n'
)


def _cut(html: str, head: str) -> str:
    """`head`로 시작하는 선언 하나를 중괄호 균형으로 잘라 온다."""
    i = html.index(head)
    depth, j, in_s, q = 0, i, False, ""
    while j < len(html):
        c = html[j]
        if in_s:
            if c == "\\":
                j += 2
                continue
            if c == q:
                in_s = False
        elif c in "\"'`":
            in_s, q = True, c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return html[i:j + 1]
        j += 1
    raise AssertionError(f"뷰어에서 {head!r}의 끝을 찾지 못했다")


def _cut_decl(html: str, name: str) -> "str | None":
    """`const/let NAME = …;` 선언 하나를 잘라 온다(여러 줄 객체·배열 포함).

    `function NAME(...)` 형태면 브레이스 매칭으로 함수 전체를 잘라 온다 —
    `proseDetailsHTML`이 내부에서 부르는 `proseTextHTML`을 이 경로로
    자동으로 끌어온다(아래 `_viewer`의 재시도 루프).
    """
    m = re.search(r"^(?:const|let|var)\s+" + re.escape(name) + r"\s*=", html, re.M)
    if not m:
        if re.search(r"^function\s+" + re.escape(name) + r"\s*\(", html, re.M):
            return _cut(html, f"function {name}(")
        return None
    i = m.start()
    eol = html.index("\n", i)
    line = html[i:eol]
    if line.rstrip().endswith(";") and line.count("{") == line.count("}"):
        return line
    depth, j, in_s, q = 0, i, False, ""
    while j < len(html):
        c = html[j]
        if in_s:
            if c == "\\":
                j += 2
                continue
            if c == q:
                in_s = False
        elif c in "\"'`":
            in_s, q = True, c
        elif c in "{[(":
            depth += 1
        elif c in "}])":
            depth -= 1
        elif c == ";" and depth == 0:
            return html[i:j + 1]
        j += 1
    return None


def _node(code: str):
    tf = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    tf.write(code)
    tf.close()
    try:
        return subprocess.run([shutil.which("node"), tf.name], capture_output=True,
                               text=True, encoding="utf-8", errors="replace")
    finally:
        pathlib.Path(tf.name).unlink(missing_ok=True)


def _viewer(calls: list):
    """`[[함수명, 인자...], ...]`를 뷰어 구현으로 돌려 결과 배열을 받는다."""
    html = _HTML.read_text(encoding="utf-8")
    src = "\n".join(_cut(html, f) for f in _FUNCS)
    names = [f[len("function "):-1] for f in _FUNCS]
    js = (
        f"{_ESC_HELPER}{src}\n"
        f"const CALLS = {json.dumps(calls, ensure_ascii=False)};\n"
        f"const FN = {{{', '.join(names)}}};\n"
        "const out = CALLS.map(([n, ...a]) => FN[n](...a));\n"
        "console.log(JSON.stringify(out));\n"
    )
    pre = ""
    for _ in range(24):
        r = _node(pre + js)
        if r.returncode == 0:
            return json.loads(r.stdout)
        m = re.search(r"ReferenceError: (\w+) is not defined", r.stderr or "")
        if not m:
            raise AssertionError(f"node 실패:\n{(r.stderr or '')[:1600]}")
        d = _cut_decl(html, m.group(1))
        assert d is not None, (
            f"뷰어에서 {m.group(1)} 선언을 찾지 못했다 — 이식본이 함수 밖의 "
            "무언가에 기대고 있다")
        pre = d + "\n" + pre
    raise AssertionError("보조 선언을 24번 끌어와도 안 돈다")


# ── 테스트용 사전 ────────────────────────────────────────────────────────
_GLOSSARY = {
    "신주인수권부사채": "채권과 별도로 새 주식을 살 권리가 딸려 오는 회사채입니다.",
    "신주인수권": "새 주식을 살 수 있는 권리입니다.",
    "전환사채": "돈을 빌리면서 나중에 주식으로 바꿀 권리를 붙인 채권입니다.",
    "용어": '설명에 "따옴표"와 <꺾쇠>가 있습니다.',
}
_ALIASES = {"CB": "전환사채"}


class TestGlossTermsHTMLLongestFirst(unittest.TestCase):
    """긴 낱말 우선 — 「신주인수권부사채」가 「신주인수권」류보다 먼저 매칭돼야
    한다(좌측 우선 교대식에서 긴 표제어를 앞세워야 함)."""

    def test_긴_표제어가_짧은_표제어를_이긴다(self):
        text = "신주인수권부사채를 발행했다"
        out = _viewer([["glossTermsHTML", text, _GLOSSARY, {}]])[0]
        self.assertIn(
            '<span class="term" tabindex="0">신주인수권부사채<span class="term-def"',
            out,
        )
        # 「신주인수권」 단독으로 감싸지지 않는다 — 그러면 「부사채」가 밖에
        # 남아 글자가 잘려 보인다.
        self.assertNotIn(
            '<span class="term" tabindex="0">신주인수권<span class="term-def"', out)


class TestGlossTermsHTMLOncePerCall(unittest.TestCase):
    def test_모든_등장을_감싼다(self):
        """제작자 판단(2026-09-03): 이용자는 리포트를 발췌해 읽으므로 어느
        문장을 집어도 풀이가 있어야 한다. 옛 규칙 「한 호출 안에서 첫 1회만」은
        두 번째 등장을 맨 문장으로 남겼다."""
        text = "전환사채 발행 후 전환사채 재발행"
        out = _viewer([["glossTermsHTML", text, _GLOSSARY, {}]])[0]
        self.assertEqual(out.count('class="term-def"'), 2,
                          f"두 번째 등장이 감싸지지 않았다: {out!r}")


class TestGlossTermsHTMLTagProtection(unittest.TestCase):
    """`<a>`·`<summary>`·`<code>`·`class="term"` 안의 텍스트는 건드리지
    않는다(중첩 대화형 금지) + 멱등(`f(f(x)) === f(x)`)."""

    def test_a_태그_안은_적용하지_않는다(self):
        text = '<a href="#">전환사채</a> 그리고 전환사채'
        out = _viewer([["glossTermsHTML", text, _GLOSSARY, {}]])[0]
        # <a> 안의 「전환사채」는 감싸지지 않는다.
        self.assertIn('<a href="#">전환사채</a>', out)
        # <a> 밖의 「전환사채」는 감싸진다(밖에 하나뿐이라 1).
        self.assertEqual(out.count('class="term-def"'), 1)

    def test_summary_안은_적용하지_않는다(self):
        text = "<summary>전환사채 안내</summary>"
        out = _viewer([["glossTermsHTML", text, _GLOSSARY, {}]])[0]
        self.assertEqual(out, text)

    def test_code_안은_적용하지_않는다(self):
        text = "<code>전환사채</code>"
        out = _viewer([["glossTermsHTML", text, _GLOSSARY, {}]])[0]
        self.assertEqual(out, text)

    def test_이미_감싼_term_span_안은_다시_적용하지_않는다(self):
        # ⚠ 낱말이 **두 번** 나오는 입력이어야 한다 — 옛 테스트는 한 번만 나오는
        # 입력이라, 「첫 1회만」 규칙 아래서 두 번째 적용이 다음 등장을 잡아
        # 낱말당 툴팁이 둘이 되는 결함(v1.22.0 이연 항목 4)을 못 잡았다.
        text = "전환사채 발행 후 전환사채 재발행"
        once = _viewer([["glossTermsHTML", text, _GLOSSARY, {}]])[0]
        twice = _viewer([["glossTermsHTML", once, _GLOSSARY, {}]])[0]
        self.assertEqual(once, twice, "멱등성이 깨졌다 — f(f(x)) != f(x)")
        self.assertEqual(twice.count('class="term-def"'), 2)


class TestGlossTermsHTMLEscapePreserved(unittest.TestCase):
    def test_입력의_엔티티는_한글과_겹치지_않아_보존된다(self):
        text = "&lt;b&gt;전환사채&lt;/b&gt;&amp; 안내"
        out = _viewer([["glossTermsHTML", text, _GLOSSARY, {}]])[0]
        self.assertIn("&lt;b&gt;", out)
        self.assertIn("&amp;", out)

    def test_풀이의_따옴표와_꺾쇠는_이스케이프된다(self):
        out = _viewer([["glossTermsHTML", "용어 설명", _GLOSSARY, {}]])[0]
        self.assertIn("&quot;따옴표&quot;", out)
        self.assertIn("&lt;꺾쇠&gt;", out)
        self.assertNotIn('"따옴표"', out)
        self.assertNotIn("<꺾쇠>", out)


class TestGlossTermsHTMLAlias(unittest.TestCase):
    def test_별칭은_표제어의_풀이를_쓴다(self):
        out = _viewer([["glossTermsHTML", "CB 발행", _GLOSSARY, _ALIASES]])[0]
        self.assertIn('<span class="term" tabindex="0">CB<span class="term-def"', out)
        self.assertIn(_GLOSSARY["전환사채"], out)


class TestGlossTermsHTMLEmptyGlossary(unittest.TestCase):
    def test_빈_사전이면_입력_그대로(self):
        text = "전환사채 발행"
        out = _viewer([["glossTermsHTML", text, {}, {}]])[0]
        self.assertEqual(out, text)

    def test_undefined_사전이면_입력_그대로(self):
        text = "전환사채 발행"
        out = _viewer([["glossTermsHTML", text, None, None]])[0]
        self.assertEqual(out, text)


class TestGlossTermsHTMLMarkup(unittest.TestCase):
    def test_tabindex와_term_def가_있다(self):
        out = _viewer([["glossTermsHTML", "전환사채 발행", _GLOSSARY, {}]])[0]
        self.assertIn('tabindex="0"', out)
        self.assertIn('class="term-def"', out)
        self.assertIn('role="tooltip"', out)


class TestBoldMarksHTML(unittest.TestCase):
    def test_짝이_맞는_굵게는_b태그로(self):
        out = _viewer([["boldMarksHTML", "이것은 **강조**입니다"]])[0]
        self.assertEqual(out, "이것은 <b>강조</b>입니다")

    def test_짝이_안_맞는_별표는_그대로(self):
        out = _viewer([["boldMarksHTML", "이것은 **강조**이고 짝없는 **것도 있다"]])[0]
        self.assertIn("<b>강조</b>", out)
        self.assertIn("**것도 있다", out)


class TestProseDetailsHTML(unittest.TestCase):
    _ENTRIES = [
        {"label": "지표A", "formula": "B ÷ C", "meaning": "뜻A",
         "fall": "내려가면A", "caveat": "⚠ **주의**A"},
        {"label": "지표B", "meaning": "뜻B"},  # formula/fall/caveat 전부 없음
        {"label": "지표C", "meaning": "뜻C", "caveat": "주의C"},
    ]

    def test_항목_수와_mp_수가_같다(self):
        out = _viewer([["proseDetailsHTML", "지표 읽는 법", self._ENTRIES]])[0]
        self.assertEqual(out.count('<div class="mp">'), len(self._ENTRIES))

    def test_formula_없는_항목에_빈_괄호나_빈_mp_f가_없다(self):
        out = _viewer([["proseDetailsHTML", "지표 읽는 법", self._ENTRIES]])[0]
        self.assertNotIn("()", out, "빈 괄호가 렌더됐다")
        # formula가 있는 항목은 1개뿐이라 mp-f도 정확히 1번만 나와야 한다.
        self.assertEqual(out.count('class="mp-f"'), 1)

    def test_출력에_굵게_마크가_남지_않는다(self):
        out = _viewer([["proseDetailsHTML", "지표 읽는 법", self._ENTRIES]])[0]
        self.assertNotIn("**", out)
        self.assertIn("<b>주의</b>", out)

    def test_판정_어휘가_없다(self):
        out = _viewer([["proseDetailsHTML", "지표 읽는 법", self._ENTRIES]])[0]
        for banned in ("고위험", "매우위험", "위험도", "점수", "등급"):
            self.assertNotIn(banned, out)

    def test_entries가_비면_빈_문자열(self):
        out = _viewer([["proseDetailsHTML", "지표 읽는 법", []]])[0]
        self.assertEqual(out, "")


class TestLeadSentenceHTML(unittest.TestCase):
    def test_첫_문장은_lead_나머지는_rest(self):
        out = _viewer([["leadSentenceHTML",
                         "첫 문장입니다. 둘째 문장입니다."]])[0]
        self.assertIn('<span class="lead">첫 문장입니다.</span>', out)
        self.assertIn('<span class="rest">', out)
        self.assertIn("둘째 문장입니다.", out)

    def test_문장부호가_없으면_전부_lead(self):
        out = _viewer([["leadSentenceHTML", "문장부호가 없는 문구"]])[0]
        self.assertEqual(out, '<span class="lead">문장부호가 없는 문구</span>')
        self.assertNotIn('class="rest"', out)


# ── 실 배포 데이터로 종단 확인 ───────────────────────────────────────────
class TestRealSignalsDataGlossary(unittest.TestCase):
    """docs/tool/signals-data.json의 실제 glossary를 하네스에 넣어, 실제
    신호 해설(prose)을 렌더하면 `.term`이 적어도 하나 생기는지 본다."""

    def test_실제_사전으로_신호_해설을_렌더하면_term이_생긴다(self):
        data = json.loads(
            (_ROOT / "docs" / "tool" / "signals-data.json").read_text(encoding="utf-8"))
        gloss = data["glossary"]
        aliases = data.get("glossary_aliases", {})
        # signals[0]은 데이터에 따라 해설(prose)이 빈 문자열일 수 있다(사실
        # 표기 원칙상 신호 절반 가까이가 빈 prose다) — 실제로 사전 용어를
        # 담고 있는 첫 신호를 찾아 렌더한다.
        target = None
        for s in data["signals"]:
            prose = s.get("prose") or ""
            if prose and any(term in prose for term in gloss):
                target = s
                break
        self.assertIsNotNone(
            target, "glossary 용어를 담은 신호 해설을 하나도 찾지 못했다")
        out = _viewer([["glossTermsHTML", target["prose"], gloss, aliases]])[0]
        self.assertGreaterEqual(
            out.count('class="term"'), 1,
            f"{target['key']}의 해설을 실제 사전으로 렌더했는데 .term이 없다")


# ── 정적 검사(node 불필요) ───────────────────────────────────────────────
class TestStaticWiring(unittest.TestCase):
    def setUp(self):
        self.html = _HTML.read_text(encoding="utf-8")

    def test_headline에_overflow_hidden이_없다(self):
        i = self.html.index(".headline {")
        j = self.html.index("}", i)
        block = self.html[i:j]
        self.assertNotIn("overflow: hidden", block,
                          ".headline이 overflow:hidden을 유지하면 용어 사전 "
                          "툴팁이 카드 밖으로 못 나가고 잘린다")

    def test_focus_within_css가_있다(self):
        self.assertIn(".term:focus-within .term-def", self.html)

    def test_여섯_패널_키가_각_렌더러_안에서_metricProseHTML_호출로_쓰인다(self):
        panels = {
            "mezzanine": "function mezzanineBlockHTML(",
            "dilution": "function dilutionBlockHTML(",
            "financial": "async function loadFinancialCore(",
            "fund_usage": "function fundChainPanelHTML(",
            "insider": "async function loadHoldings(",
            "audit": "async function loadAuditOpinions(",
        }
        for panel, func_head in panels.items():
            i = self.html.index(func_head)
            j = self.html.index("\n}", i)
            body = self.html[i:j]
            self.assertIn(
                f'metricProseHTML("{panel}"', body,
                f"{func_head} 안에서 metricProseHTML(\"{panel}\"...)를 호출하지 않는다")

    def test_turnoverProseHTML이_proseDetailsHTML을_호출한다(self):
        i = self.html.index("function turnoverProseHTML()")
        j = self.html.index("\n}", i)
        body = self.html[i:j]
        self.assertIn("proseDetailsHTML(", body)


if __name__ == "__main__":
    unittest.main()
