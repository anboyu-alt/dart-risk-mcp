"""메자닌 공시 목록이 **전건**을 싣고 세 축으로 정렬되는지 고정한다.

## 무엇이 문제였나

제작자 피드백: *"지금은 최근 12건만 보여주고 링크를 걸어주는데 그러지 말고
검색기간 내 공시 나온 건 다 붙여줘. 딱 봤을 때 눈에 들어오지 않더라고."*

뷰어의 공시 목록은 `MZN_LIST_MAX = 12`로 잘렸다. 실측에서 **코아스 111건 ·
제이스코홀딩스 119건**이므로 **100건 넘게 「생략」으로 사라졌다**.

## 회차 정렬의 한계 — 재지 말고 여기를 읽어라

1년 전수(271,141건)의 메자닌 공시 4,825건에서 **회차가 제목에 있는 것은
15.2%뿐**이다.

    조정 33.5% · 전환·행사 28.9% · 회수 24.9%
    **발행 0.8%** · 자기사채 매도 1.9% · 결과 0.3%

CLAUDE.md의 「⚠ 회차 join을 하지 않는다 — 제목에 회차가 적힌 것만 잇고 없는
것을 추정하지 않는다」가 그대로 적용된다. 그래서 **회차 없음은 맨 뒤로 모으고**,
100% 채워지는 **구분(6분류)** 축을 함께 뒀다.

## 왜 목록만 따로 그리나

정렬할 때 `mezzanineBlockHTML` 전체를 다시 부르면 **아래 발행 조건
`<details>`가 매번 닫힌다**. 그래서 `mezzanineFilingsHTML`을 떼어내
`#mznFilings`만 다시 그린다.
"""
import json
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = _ROOT / "docs" / "tool" / "index.html"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node가 없으면 뷰어 쪽을 돌릴 수 없다"
)

# 이 파일이 node로 실어 돌리는 뷰어 함수들(순수 함수만)
_FUNCS = (
    "function sortMznFilings(",
    "function mznGroupKey(",
    "function mezzanineFilingsHTML(",
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
    """`const/let NAME = …;` 선언 하나를 잘라 온다(여러 줄 객체·배열 포함)."""
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


def _viewer(calls: list):
    """`[[함수명, 인자...], ...]`를 뷰어 구현으로 돌려 결과 배열을 받는다."""
    html = _HTML.read_text(encoding="utf-8")
    src = "\n".join(_cut(html, f) for f in _FUNCS)
    names = [f[len("function "):-1] for f in _FUNCS]
    # ⚠ `esc`·`fmtDate`·`dartUrl`은 **잘라 오지 않고 심는다**. `_cut`은 중괄호
    #    균형으로 함수를 자르는데 `esc`의 본문에 정규식 리터럴이 있고 그 안의
    #    따옴표를 **문자열 시작으로 오인**한다(실제로 걸렸다). 이 파일이 재는
    #    것은 정렬과 표 구조이지 이스케이프가 아니다 — `esc`의 동작은
    #    `test_viewer_render_invariants.py`가 따로 지킨다.
    shim = (
        'const esc = (s) => String(s).split("&").join("&amp;")'
        '.split("<").join("&lt;").split(">").join("&gt;");\n'
        'const fmtDate = (d) => String(d);\n'
        'const dartUrl = (r) => "https://dart.fss.or.kr/x?rcpNo=" + r;\n'
    )
    js = (
        f"{shim}{src}\n"
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
            raise AssertionError(f"node 실패:\n{(r.stderr or '')[:1200]}")
        d = _cut_decl(html, m.group(1))
        assert d is not None, (
            f"뷰어에서 {m.group(1)} 선언을 찾지 못했다 — 이식본이 함수 밖의 "
            "무언가에 기대고 있다")
        pre = d + "\n" + pre
    raise AssertionError("보조 선언을 24번 끌어와도 안 돈다")


def _node(code: str):
    tf = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    tf.write(code)
    tf.close()
    try:
        return subprocess.run([shutil.which("node"), tf.name], capture_output=True,
                              text=True, encoding="utf-8", errors="replace")
    finally:
        pathlib.Path(tf.name).unlink(missing_ok=True)


# 데이터 행의 시작 — 그룹 머리(`<tr class="mzn-grp">`)·`<thead>`와 구분된다
_ROW = '<tr><td class="date">'


def _f(date, cat, rnd=None, amend=False, nm=None):
    return {"date": date, "category": cat, "round": rnd, "is_amendment": amend,
            "rcept_no": date + "000001", "report_nm": nm or f"{cat} 공시",
            "label": cat}


# 실측 제목 구성을 본뜬 표본 — 회차가 있는 것과 없는 것이 섞여 있다
_SAMPLE = [
    _f("20260714", "issue"),                 # 발행은 회차가 거의 없다(실측 0.8%)
    _f("20260327", "redeem", 1),
    _f("20260316", "redeem", 1),
    _f("20250902", "exercise", 3),
    _f("20250904", "exercise", 3),
    _f("20251215", "refix"),
    _f("20260101", "refix", 2),
    _f("20250814", "result", amend=True),
]


def test_시기_정렬은_최근순이다():
    got = _viewer([["sortMznFilings", _SAMPLE, "date"]])[0]
    dates = [f["date"] for f in got]
    assert dates == sorted(dates, reverse=True)


def test_회차_정렬은_오름차순이고_회차_없음은_뒤로_간다():
    got = _viewer([["sortMznFilings", _SAMPLE, "round"]])[0]
    rounds = [f["round"] for f in got]
    withr = [r for r in rounds if r is not None]
    assert withr == sorted(withr), f"회차가 오름차순이 아니다: {rounds}"
    # 회차 없음은 전부 뒤쪽에 몰려 있어야 한다
    first_none = rounds.index(None)
    assert all(r is None for r in rounds[first_none:]), (
        f"회차 없음이 사이에 끼었다: {rounds}")


def test_같은_회차_안에서는_최근순이다():
    got = _viewer([["sortMznFilings", _SAMPLE, "round"]])[0]
    r1 = [f["date"] for f in got if f["round"] == 1]
    assert r1 == sorted(r1, reverse=True), r1


def test_구분_정렬은_생애주기_순이다():
    got = _viewer([["sortMznFilings", _SAMPLE, "category"]])[0]
    order = ["issue", "refix", "exercise", "redeem", "resell", "result"]
    seen = [f["category"] for f in got]
    idx = [order.index(c) for c in seen]
    assert idx == sorted(idx), f"생애주기 순이 아니다: {seen}"


@pytest.mark.parametrize("mode", ["date", "round", "category"])
def test_정렬이_건을_잃지_않는다(mode):
    """정렬은 순서만 바꾼다 — 하나라도 사라지면 화면이 거짓을 말한다."""
    got = _viewer([["sortMznFilings", _SAMPLE, mode]])[0]
    assert len(got) == len(_SAMPLE)
    assert {f["rcept_no"] for f in got} == {f["rcept_no"] for f in _SAMPLE}


def test_전건을_그린다():
    """실측 최대(코아스 111 · 3년 130)를 넘겨도 전부 나와야 한다."""
    big = [_f(f"2026{(i % 12) + 1:02d}{(i % 28) + 1:02d}",
              ["issue", "refix", "exercise", "redeem"][i % 4],
              (i % 5) or None) for i in range(130)]
    html = _viewer([["mezzanineFilingsHTML", big, "date"]])[0]
    # ⚠ `<tr>`을 세면 `<thead>`의 것까지 들어간다(처음에 그렇게 썼다가 걸렸다).
    #    데이터 행은 `<tr><td class="date">`로 시작한다.
    assert html.count(_ROW) == 130, html.count(_ROW)
    assert "전체 130건 (전부 표시" in html


def test_생략_문구가_없다():
    """조용한 절단 재발 방지 — 자를 것이 없으니 「생략」이 나오면 안 된다."""
    html = _viewer([["mezzanineFilingsHTML", _SAMPLE, "date"]])[0]
    assert "생략" not in html
    assert "전체 8건 (전부 표시" in html
    assert "정정 1건 포함" in html, "정정 건수를 밝히지 않는다"


@pytest.mark.parametrize("mode", ["round", "category"])
def test_그룹_머리의_건수_합이_전체와_같다(mode):
    """⚠ 머리에 적힌 수와 그 아래 행 수가 어긋나면 화면이 제 데이터와 다르다."""
    html = _viewer([["mezzanineFilingsHTML", _SAMPLE, mode]])[0]
    heads = re.findall(r'<tr class="mzn-grp"><td colspan="3">[^<]*?· (\d+)건</td>', html)
    assert heads, f"{mode} 정렬에 그룹 머리가 없다"
    assert sum(int(n) for n in heads) == len(_SAMPLE)
    assert html.count(_ROW) == len(_SAMPLE), "그룹 머리를 뺀 행 수가 다르다"


def test_date_모드에는_그룹_머리가_없다():
    html = _viewer([["mezzanineFilingsHTML", _SAMPLE, "date"]])[0]
    assert "mzn-grp" not in html


def test_상한_상수가_되살아나지_않았다():
    """`MZN_LIST_MAX`가 다시 생기면 목록이 또 조용히 잘린다."""
    src = _HTML.read_text(encoding="utf-8")
    # ⚠ **선언**만 본다 — 주석에는 「옛 MZN_LIST_MAX = 12는…」처럼 근거로 남아
    #    있고 그건 지워야 할 것이 아니다.
    assert not re.search(r"^\s*(?:const|let|var)\s+MZN_LIST_MAX\s*=", src, re.M), (
        "공시 목록 상한이 되살아났다 — 전건 표시가 제작자 결정이다")
    assert "d.filings.slice(" not in src, "목록을 다시 자르고 있다"
    assert "MZN_ISSUE_MAX" in src, "발행 조건 상한(8건)까지 지우면 안 된다"


def test_스크롤_상자와_고정_헤더가_있다():
    src = _HTML.read_text(encoding="utf-8")
    assert ".mzn-scroll {" in src and "max-height: 420px" in src
    # ⚠ `split(".mzn-scroll")[1]`은 두 규칙 **사이**만 집는다(처음에 그렇게 썼다가
    #    걸렸다) — 고정 헤더 규칙 자체를 찾는다.
    assert re.search(r"\.mzn-scroll thead th \{[^}]*position: sticky", src), (
        "헤더 고정이 없으면 130행에서 무엇을 보는지 알 수 없다")


def test_색은_종류_구분이지_위험도가_아니다():
    """⚠ 빨강(--c7)을 쓰면 한 종류가 「위험」으로 읽힌다(v0.8.5)."""
    src = _HTML.read_text(encoding="utf-8")
    block = src.split("const MZN_CAT_DOT")[1].split("};")[0]
    assert "--c7" not in block, "빨강이 카테고리 색에 들어왔다"
    for word in ("위험", "주의", "경고"):
        assert word not in block


def test_판정_어휘가_없다():
    html = _viewer([["mezzanineFilingsHTML", _SAMPLE, "category"]])[0]
    for word in ("고위험", "매우위험", "위험도", "점수", "등급"):
        assert word not in html, f"판정 어휘: {word}"


# ── 정정 접기 토글 (2026-09-02, 제작자 요청) ──────────────────────────────
#
# 라이브에서 **코아스는 109건 중 67건이 정정**이라 목록의 절반 이상이
# `[정정]`으로 채워진다. 접을 수 있게 했다.
#
# ⚠ **거르는 것은 자르는 것이다.** 숨기면 꼬리말이 몇 건을 숨겼는지 반드시
#   말해야 한다(조용한 절단 금지). 기본은 **끄기**(전부 표시)다 — 기본을 켜면
#   사용자가 요청하지도 않았는데 화면에서 절반이 사라진다.

def test_기본은_전부_표시다():
    """`hideAmend`를 안 주면 옛 동작 그대로여야 한다."""
    a = _viewer([["mezzanineFilingsHTML", _SAMPLE, "date"]])[0]
    b = _viewer([["mezzanineFilingsHTML", _SAMPLE, "date", False]])[0]
    assert a == b
    assert a.count(_ROW) == len(_SAMPLE)


def test_접으면_정정이_사라진다():
    html = _viewer([["mezzanineFilingsHTML", _SAMPLE, "date", True]])[0]
    keep = [f for f in _SAMPLE if not f["is_amendment"]]
    assert html.count(_ROW) == len(keep)
    assert "[정정]" not in html


def test_접었으면_숨긴_건수를_밝힌다():
    """⚠ 조용한 절단 금지 — 전체와 표시와 숨김을 다 말한다."""
    html = _viewer([["mezzanineFilingsHTML", _SAMPLE, "date", True]])[0]
    amended = sum(1 for f in _SAMPLE if f["is_amendment"])
    assert f"전체 {len(_SAMPLE)}건 중 {len(_SAMPLE) - amended}건 표시" in html
    assert f"정정 {amended}건 숨김" in html


def test_접지_않았으면_전부_실었다고_말한다():
    html = _viewer([["mezzanineFilingsHTML", _SAMPLE, "date", False]])[0]
    assert "숨김" not in html
    assert "전부 표시" in html


@pytest.mark.parametrize("mode", ["round", "category"])
def test_접었을_때_그룹_건수가_보이는_행과_맞는다(mode):
    """⚠ 머리에 적힌 수와 그 아래 행 수가 어긋나면 화면이 제 데이터와 다르다.

    거르기를 **정렬·집계보다 먼저** 하지 않으면 여기서 걸린다.
    """
    html = _viewer([["mezzanineFilingsHTML", _SAMPLE, mode, True]])[0]
    keep = [f for f in _SAMPLE if not f["is_amendment"]]
    heads = re.findall(r'<tr class="mzn-grp"><td colspan="3">[^<]*?· (\d+)건</td>', html)
    assert sum(int(n) for n in heads) == len(keep)
    assert html.count(_ROW) == len(keep)


def test_정정이_없으면_칩을_내지_않는다():
    """0건짜리 토글은 소음이다."""
    src = _HTML.read_text(encoding="utf-8")
    # 칩 마크업이 `d.filings_amended` 진위에 걸려 있어야 한다
    i = src.index("data-mznamend")
    ctx = src[max(0, i - 400):i]
    assert "d.filings_amended" in ctx, "정정 0건에도 칩이 나온다"


def test_칩에_건수가_적혀_있다():
    """누르기 전에 무엇이 사라지는지 알 수 있어야 한다."""
    src = _HTML.read_text(encoding="utf-8")
    i = src.index("data-mznamend")
    assert "정정 접기 (${d.filings_amended})" in src[i:i + 300]


def test_기본값이_끄기다():
    src = _HTML.read_text(encoding="utf-8")
    assert re.search(r"let MZN_HIDE_AMEND = false;", src), (
        "기본을 켜면 요청하지도 않은 절반이 화면에서 사라진다")
