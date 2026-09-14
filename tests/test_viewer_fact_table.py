"""뷰어 사실 표 3종(`deltaHTML`·`factTableHTML`·`panelTitleHTML`)의 불변식.

수치 변화를 한 줄 텍스트(「전기 A → 당기 B (전기 대비 C%)」)로만 내던 블록
여섯을 표로 세우면서 들어온 헬퍼다. core에 짝이 없는 뷰어 전용이라 패리티
대상이 아니고 여기서 잠근다.

여기서 조용히 깨질 수 있는 것:

  ① **색이 무엇을 가리키는지 화면이 말하지 않는 것** — 늘었는지 줄었는지는
     사실이라 ▲초록·▼빨강으로 그대로 보인다(막아야 할 판정은 「이 회사가
     좋다·나쁘다」·「투자해라」·점수·등급이다). 다만 지표마다 증가의 뜻이
     달라서(매출 vs 부채비율) ⓐ 증감 열 이름이 「증감」이라고 말하고 ⓑ 읽는
     법 한 줄이 따라붙어야 한다. 색을 `higherIsWorse`로 뒤집는 쪽이 오히려
     「이 변화는 나쁘다」가 되어 금지선을 넘는다.
  ② **결측이 0으로 읽히는 것** — 값이 없는 칸을 빈칸이나 0.0%로 두면 「변화가
     없었다」가 된다. 없는 것은 「―」다.
  ③ **행이 조용히 사라지는 것** — 표를 조립하다 입력 행을 흘리면 아무도
     모른다. 입력 행 수와 `<tr>` 수를 대조한다.
  ④ **셀이 이스케이프되지 않는 것** — 표 셀에는 glossTermsHTML을 태우지
     않으므로(툴팁은 표 밖의 일이다) esc만이 유일한 방어다.
  ⑤ **제목을 가르다 한쪽을 잃는 것** — panelTitleHTML은 절단이 아니라
     가르기다. 양쪽이 모두 출력에 남아야 한다.
"""
import json
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML_PATH = _ROOT / "docs" / "tool" / "index.html"
_HTML = _HTML_PATH.read_text(encoding="utf-8")

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node가 없으면 뷰어 쪽을 돌릴 수 없다"
)


def _cut(src: str, head: str) -> str:
    """선언 하나를 중괄호 균형으로 잘라 온다(test_viewer_sparkline과 같은 방식)."""
    i = src.index(head)
    depth, j, in_s, q = 0, i, False, ""
    while j < len(src):
        c = src[j]
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
                return src[i:j + 1]
        j += 1
    raise AssertionError(f"{head!r}의 끝을 찾지 못했다")


def _delta_note() -> str:
    m = re.search(r'^const DELTA_NOTE = "([^"]*)";$', _HTML, re.M)
    assert m, "DELTA_NOTE 정의를 찾지 못했다"
    return m.group(1)


def _run(exprs: list) -> list:
    """뷰어에서 헬퍼를 떼어 node로 돌린다 — 손으로 베끼면 배포본과 갈린다."""
    m = re.search(r"^function esc\(.*$", _HTML, re.M)
    assert m, "뷰어에서 esc 정의를 찾지 못했다"
    js = (
        m.group(0) + "\n"
        + f'const DELTA_NOTE = {json.dumps(_delta_note(), ensure_ascii=False)};\n'
        + _cut(_HTML, "function deltaHTML(") + "\n"
        + _cut(_HTML, "function factTableHTML(") + "\n"
        + _cut(_HTML, "function panelTitleHTML(") + "\n"
        + "const OUT = [\n" + ",\n".join(exprs) + "\n];\n"
        "console.log(JSON.stringify(OUT));\n"
    )
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False,
                                     encoding="utf-8") as f:
        f.write(js)
        path = f.name
    try:
        # argv로 넘기므로 파일 URL이 아니라 경로 그대로다(ESM import()와 다르다)
        r = subprocess.run(["node", path],
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, r.stderr
        return json.loads(r.stdout)
    finally:
        pathlib.Path(path).unlink(missing_ok=True)


# ── deltaHTML ────────────────────────────────────────────────────────────

def test_방향이_기호와_색으로_함께_나온다():
    up, down, flat = _run([
        "deltaHTML(4.2)", "deltaHTML(-6.6)", "deltaHTML(0)",
    ])
    assert "▲" in up and "+4.2%" in up and "delta up good" in up
    assert "▼" in down and "-6.6%" in down and "delta down bad" in down
    # 0은 방향이 없다 — 화살표를 붙이면 없는 움직임을 만든다
    assert "▲" not in flat and "▼" not in flat
    assert 'class="delta flat"' in flat and "0.0%" in flat


def test_내려가는_쪽이_개선인_지표는_색이_반대다():
    """부채비율·CCC — 6개사 실측에서 12건이 정확히 반대로 칠해져 있었다."""
    down, up = _run([
        'deltaHTML(-3166.1, { unit: "%p", sense: "down" })',
        'deltaHTML(12.5, { sense: "down" })',
    ])
    assert "▼" in down and "delta down good" in down, "하락인데 개선색이 아니다"
    assert "▲" in up and "delta up bad" in up


def test_방향에_좋고_나쁨이_없으면_색을_쓰지_않는다():
    """매입채무·운전자본회전율, 내부자 보유비율 — 실측 39건."""
    for expr in ('deltaHTML(4.2, { sense: "none" })',
                 'deltaHTML(-4.2, { sense: "none" })'):
        out = _run([expr])[0]
        assert "delta" in out and " dir" in out, expr
        assert "good" not in out and "bad" not in out, f"{expr}: 뜻 없는 색이 붙었다"
        # 방향 자체는 남는다 — 색만 빼는 것이지 사실을 지우는 게 아니다
        assert ("▲" in out) or ("▼" in out), expr


def test_모르는_sense는_색을_지어내지_않는다():
    out = _run(['deltaHTML(4.2, { sense: "엉뚱" })'])[0]
    assert " dir" in out and "good" not in out and "bad" not in out


def test_결측은_0이_아니라_대시다():
    for expr in ("deltaHTML(null)", "deltaHTML(undefined)", "deltaHTML(NaN)"):
        out = _run([expr])[0]
        assert "―" in out, expr
        assert "0" not in out, f"{expr}: 결측이 0으로 읽힌다"
        assert "▲" not in out and "▼" not in out, expr


def test_문자열_증감은_방향을_추정하지_않는다():
    # 「흑자 전환」·「적자 확대」는 부호로 환원되지 않는 사실이라 중립으로 둔다
    for text in ("흑자 전환", "적자 확대", "결손 전환"):
        out = _run([f'deltaHTML(null, {{ text: "{text}" }})'])[0]
        assert text in out
        assert 'class="delta flat"' in out, f"{text}: 방향을 지어냈다"
        assert "▲" not in out and "▼" not in out


def test_단위와_자릿수를_호출부가_정한다():
    pp, days, two = _run([
        'deltaHTML(1.5, { unit: "%p" })',
        'deltaHTML(-3, { unit: "일" })',
        # ⚠ 0.815 같은 값을 쓰면 안 된다 — JS `(0.815).toFixed(2)`는 이진
        #   부동소수점 때문에 "0.81"이다(코드가 아니라 기대값이 틀린다)
        'deltaHTML(0.5, { unit: "%p", digits: 2 })',
    ])
    assert "+1.5%p" in pp                 # 비율의 차이는 %가 아니라 %p다
    assert "▼ -3.0일" in days
    assert "+0.50%p" in two


def test_델타도_이스케이프한다():
    out = _run(['deltaHTML(null, { text: "<b>x</b>" })'])[0]
    assert "<b>x</b>" not in out and "&lt;b&gt;" in out


# ── factTableHTML ────────────────────────────────────────────────────────

def test_입력_행을_잃지_않는다():
    out = _run(['factTableHTML(["a", "b"], [["1", "2"], ["3", "4"], ["5", "6"]])'])[0]
    assert out.count("<tr>") == 4          # 헤더 1 + 본문 3
    for v in ("1", "2", "3", "4", "5", "6"):
        assert f"<td class=\"lbl\">{v}</td>" in out or f"<td>{v}</td>" in out


def test_빈_셀은_대시로_채운다():
    out = _run(['factTableHTML(["a", "b"], [["x", null], ["y", ""]])'])[0]
    assert out.count("―") == 2, "빈 칸을 그냥 두면 0으로 읽힌다"


def test_셀을_이스케이프한다():
    out = _run(['factTableHTML(["<h>"], [["<script>alert(1)</script>"]])'])[0]
    assert "<script>" not in out
    assert "&lt;script&gt;" in out and "&lt;h&gt;" in out


def test_raw_셀은_호출부가_만든_HTML을_그대로_받는다():
    out = _run(['factTableHTML(["a"], [[{ raw: deltaHTML(1.0) }]])'])[0]
    assert "delta up good" in out and "&lt;span" not in out


def test_숫자_열은_우측정렬_클래스를_받는다():
    out = _run(['factTableHTML([{ label: "값", num: true }], [["1"]])'])[0]
    assert '<th class="num">값</th>' in out
    assert '<td class="num">1</td>' in out


def test_고지는_출력에_남는다():
    out = _run(['factTableHTML(["a"], [["1"]], { note: "전체 9건 중 3건 표시" })'])[0]
    assert "전체 9건 중 3건 표시" in out
    assert 'class="ftnote"' in out


def test_증감_표에는_읽는_법이_따라붙는다():
    """지표마다 증가의 뜻이 달라서(매출 vs 부채비율) 한 줄이 필요하다."""
    note = _delta_note()
    out = _run(['factTableHTML(["a"], [["1"]], { deltaNote: true })'])[0]
    assert note in out
    plain = _run(['factTableHTML(["a"], [["1"]])'])[0]
    assert note not in plain, "증감이 없는 표까지 달면 같은 문장이 화면을 덮는다"


def test_그룹_머리는_전체_열을_덮는다():
    out = _run([
        'factTableHTML(["a", "b", "c"], [{ group: "홍길동" }, ["1", "2", "3"]])',
        'factTableHTML(["a"], [{ group: { raw: "<i>x</i>" } }])',
    ])
    assert 'class="mzn-grp"' in out[0] and 'colspan="3"' in out[0]
    assert "홍길동" in out[0]
    assert "<i>x</i>" in out[1], "그룹 머리도 raw를 받아야 스파크라인이 들어간다"


def test_죽은_클래스를_새로_쓰지_않는다():
    out = _run(['factTableHTML(["a"], [["1"]])'])[0]
    assert 'class="t"' not in out, "CSS에 정의가 없는 클래스다"
    assert 'class="ftwrap"' in out, "패널이 아니라 표만 감싼다"


# ── panelTitleHTML ───────────────────────────────────────────────────────

def test_제목을_가르되_양쪽을_모두_남긴다():
    out = _run(['panelTitleHTML("▍EARNINGS SHOCK — 손익구조 급변 내역")'])[0]
    assert '<span class="sl-en">▍EARNINGS SHOCK</span>' in out
    assert '<span class="sl-ko">손익구조 급변 내역</span>' in out


def test_구분자가_없는_제목은_눈썹만_낸다():
    out = _run(['panelTitleHTML("▍SCAN INPUT")'])[0]
    assert "▍SCAN INPUT" in out
    assert "sl-ko" not in out, "없는 주제목을 지어내지 않는다"


def test_수식어와_속성을_보존한다():
    cls, style, ident = _run([
        'panelTitleHTML("▍A — 가", { cls: "amber" })',
        'panelTitleHTML("▍A — 가", { style: "margin:0" })',
        'panelTitleHTML("▍A — 가", { id: "keyPanelLabel" })',
    ])
    assert 'class="slabel amber"' in cls
    assert 'style="margin:0"' in style
    assert 'id="keyPanelLabel"' in ident


def test_제목도_이스케이프한다():
    out = _run(['panelTitleHTML("▍A — <b>가</b>")'])[0]
    assert "<b>가</b>" not in out and "&lt;b&gt;" in out


# ── 소스 정적 검사 ────────────────────────────────────────────────────────

def test_증감_열_이름이_증감이라고_말한다():
    """색이 무엇을 가리키는지 열 이름이 먼저 말해야 한다."""
    heads = re.findall(r'\{ label: "([^"]*증감[^"]*)", num: true \}', _HTML)
    assert len(heads) >= 4, f"증감 열 헤더가 너무 적다: {heads}"
    for h in heads:
        assert "증감" in h


def test_읽는_법이_화살표와_색을_따로_설명한다():
    note = _delta_note()
    assert "늘었는지 줄었는지" in note, "▲▼가 무엇인지 말해야 한다"
    assert "개선으로 읽히는" in note, "색이 증감이 아니라 방향의 뜻임을 말해야 한다"
    assert "색 없이" in note, "색이 빠지는 지표가 있다는 것을 말해야 한다"
    # 회사에 대한 단정은 여전히 금지선이다 — 읽는 법은 지표 해석이지 평가가 아니다
    for banned in ("투자", "위험합니다", "부실합니다", "등급", "점수"):
        assert banned not in note, banned


def test_방향_판단을_뷰어가_복제하지_않는다():
    """근거는 core에 있다 — 뷰어가 지표 표를 들고 있으면 core가 바뀔 때 낡는다."""
    body = _cut(_HTML, "function turnoverSense(")
    assert "DATA.turnover_prose" in body, "core가 내보낸 sense를 읽지 않는다"
    assert '"none"' in body, "모르는 키에 기본 방향을 지어내면 안 된다"
    # 회전율 지표 이름을 뷰어에 나열해 두면 그게 곧 복제다
    for hardcoded in ("매입채무회전율", "현금전환주기"):
        assert hardcoded not in body, f"{hardcoded}를 뷰어가 직접 들고 있다"


def test_비율_추세는_higherIsWorse를_색조로_잇는다():
    body = _cut(_HTML, "function ratioTrendLine(")
    assert 'sense: higherIsWorse ? "down" : "up"' in body


def test_내부자_지분은_중립이다():
    i = _HTML.index("직전 보고 대비 증감")
    seg = _HTML[max(0, i - 1400):i]
    assert 'sense: "none"' in seg, "지분 증감에 좋고 나쁨 색이 붙어 있다"


def test_스파크라인은_중립_단색_그대로다():
    """선에는 단일 방향이 없어 칠할 「방향」 자체가 없다 — 대상이 다르다."""
    body = _cut(_HTML, "function sparklineSVG(")
    assert "--red" not in body and "--green" not in body
    assert "delta" not in body


def test_옛_한줄_렌더가_되살아나지_않는다():
    """되돌아가면 표가 조용히 텍스트로 바뀐다 — 그때 이 테스트가 걸린다."""
    assert "전기 ${priTxt} → 당기 ${curTxt}" not in _HTML
    assert "parts.map(esc).join" not in _HTML


def test_여섯_블록이_표를_쓴다():
    assert _HTML.count("factTableHTML(") >= 7   # 선언 1 + 호출 6
