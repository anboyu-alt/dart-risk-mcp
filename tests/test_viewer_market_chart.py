"""뷰어 「공시와 시장」 차트 — `marketChartModel`·`marketChartSVG`의 계약.

설계: `docs/superpowers/specs/2026-09-23-viewer-market-chart-design.md`.
core에 쌍둥이가 없는 뷰어 전용 순수 함수라(이름을 `Model`/`SVG` 접미로 두어
패리티 가드와 짝지어지지 않는다) 여기서 직접 잠근다 — ① 모델: 빈틈(미조회)은
잇지 않는다 · 휴장일 접수 마커는 다음 거래일 · 같은 날 신호는 마커 하나 ·
거래량 0 연속 구간 · 코스닥 소속부 변경 · **기준가 조정일마다 지수를 종목에
다시 맞춘다** · 지수가 없으면 종목만 · 창 밖 사건은 버리되 센다 ② SVG:
태그 균형 · 판정 어휘 0 · 오르내림 색 없음 · 마커는 원문 링크+title ·
격자는 실선 ③ 상수·문구: 예산·동시성·캐시 상한·차트 폭·패널 문구.
"""
import datetime as _dt
import json
import re

import pytest

from tests.test_viewer_market_panel import _cut, _cut_decl, _html, _node

pytestmark = pytest.mark.skipif(
    __import__("shutil").which("node") is None, reason="node가 없으면 뷰어 쪽을 돌릴 수 없다"
)

_SRC = _html()

_FUNCS = (
    "function marketChartModel(",
    "function niceTicks(",
    "function marketChartSVG(",
    "function fmtVolumeShort(",
    "function marketChartLegendHTML(",
    "function priceBreaks(",
    "function breakLabel(",
    "function fmtDate(",
    "function dartUrl(",
    "function fmtPrice(",
)

# `esc`는 정규식 안의 따옴표(`/[&<>"]/`) 때문에 `_cut`이 끝을 못 찾는다 —
# mezzanine 테스트와 같이 같은 뜻의 얇은 판을 심는다.
_ESC_SHIM = (
    'function esc(s) { return String(s).replace(/[&<>"]/g, '
    '(m) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", \'"\': "&quot;" }[m])); }\n'
)


def _run(js_tail: str) -> dict:
    src = _ESC_SHIM + "\n".join(_cut(_SRC, f) for f in _FUNCS)
    consts = "\n".join(
        _cut_decl(_SRC, n) for n in (
            "MKT_PRIORITY_RANK", "MKT_W", "MKT_PRICE_TOP", "PRICE_BREAK_TOL_PCT",
            "PRICE_BREAK_SHARE_UP", "PRICE_BREAK_SHARE_DOWN", "PRICE_BREAK_PRODUCT_MAX",
            "PRICE_BREAK_PRODUCT_MIN",
        )
    )
    js = consts + "\n" + src + "\n" + js_tail
    pre = ""
    for _ in range(24):
        r = _node(pre + js)
        if r.returncode == 0:
            return json.loads(r.stdout)
        m = re.search(r"ReferenceError: (\w+) is not defined", r.stderr or "")
        if not m:
            raise AssertionError(f"node 실패:\n{(r.stderr or '')[:2000]}")
        d = _cut_decl(_SRC, m.group(1))
        assert d is not None, f"뷰어에서 {m.group(1)} 선언을 찾지 못했다"
        pre = d + "\n" + pre
    raise AssertionError("보조 선언을 24번 끌어와도 안 돈다")


def _weekdays(n: int, start=_dt.date(2026, 1, 5)):
    out, d = [], start
    while len(out) < n:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d += _dt.timedelta(days=1)
    return out


def _rows(n=30, close=10000, volume=1000, list_shrs=1_000_000):
    return [{"date": d, "close": close, "fluc_rt": 0.0, "volume": volume,
             "value": close * volume, "mktcap": close * list_shrs, "list_shrs": list_shrs,
             "sect": None, "gap_before": False} for d in _weekdays(n)]


def _idx(rows, value=100.0):
    return [{"date": r["date"], "close": value, "fluc_rt": 0.0, "mktcap": 1} for r in rows]


def _model(rows, idx_rows, events, opts=None, extra_js=""):
    return _run(
        f"const ROWS = {json.dumps(rows)}; const IDX = {json.dumps(idx_rows)}; "
        f"const EV = {json.dumps(events, ensure_ascii=False)}; const OPTS = {json.dumps(opts or {})};\n"
        "const m = marketChartModel(ROWS, IDX, EV, OPTS);\n"
        + extra_js +
        "console.log(JSON.stringify({m, svg: marketChartSVG(m), legend: marketChartLegendHTML(m, '코스피')}));"
    )


# ── ① 모델 ──────────────────────────────────────────────────────────────

def test_미조회_빈틈은_선을_잇지_않는다():
    rows = _rows(10)
    rows[5]["gap_before"] = True
    out = _model(rows, [], [])
    assert out["m"]["days"][5]["gap"] is True
    price = re.search(r'<path d="([^"]+)" class="mkt-price"', out["svg"]).group(1)
    assert price.count("M") == 2, "빈틈 앞뒤가 한 획으로 이어졌다"


def test_휴장일_접수_마커는_다음_거래일에_놓이고_원_접수일을_남긴다():
    rows = _rows(10)                       # 20260105(월)~
    ev = [{"date": "20260110", "key": "CB_BW", "label": "CB/BW", "count": 1,
           "rcept": "20260110000001", "priority": "watch", "nm": "전환사채권발행결정"}]
    out = _model(rows, [], ev)
    mk = out["m"]["markers"]
    assert len(mk) == 1
    assert mk[0]["date"] == "20260112" and mk[0]["items"][0]["shifted"] is True
    assert mk[0]["items"][0]["origDate"] == "20260110"
    assert "휴장일 접수" in out["svg"]


def test_같은_날_신호는_마커_하나로_묶고_가장_앞선_순서를_따른다():
    rows = _rows(10)
    ev = [
        {"date": "20260107", "key": "A", "label": "A", "count": 2, "rcept": "1", "priority": "context", "nm": ""},
        {"date": "20260107", "key": "B", "label": "B", "count": 1, "rcept": "2", "priority": "first", "nm": ""},
    ]
    out = _model(rows, [], ev)
    mk = out["m"]["markers"]
    assert len(mk) == 1 and mk[0]["count"] == 3 and len(mk[0]["items"]) == 2
    assert mk[0]["priority"] == "first"
    assert "×3" in out["svg"]
    assert 'class="mkt-mk mkt-mk-first"' in out["svg"]


def test_거래량_0_연속_구간을_띠로_센다():
    rows = _rows(12)
    for i in (4, 5, 6):
        rows[i]["volume"] = 0
    rows[9]["volume"] = 0
    out = _model(rows, [], [])
    bands = out["m"]["haltBands"]
    assert [(b["from"], b["to"], b["n"]) for b in bands] == [(4, 6, 3), (9, 9, 1)]
    assert out["svg"].count('class="mkt-halt"') == 2
    assert "거래량 0 · 3거래일" in out["svg"]
    assert "정지" not in _cut(_SRC, "function marketChartSVG(").replace("매매거래정지", "")


def test_코스닥_소속부_변경을_표지로_찍는다():
    rows = _rows(10)
    out = _model(rows, [], [], {"sectChanges": [{"date": "20260109", "from": "중견기업부", "to": "관리종목(소속부없음)"}]})
    sm = out["m"]["sectMarks"]
    assert len(sm) == 1 and sm[0]["i"] == 4
    assert "→ 관리종목(소속부없음)" in out["svg"]
    assert "코스닥 소속부 변경" in out["legend"]


def test_기준가_조정일마다_지수를_종목에_다시_맞춘다():
    """5:1 분할(종가 10000→2000, 주식수 ×5, KRX 등락률 0)이 8번째 날에 있으면 그날
    지수 선이 다시 종목 종가에서 출발해야 한다 — 그러지 않으면 지수가 옛 높이에
    남아 「종목만 80% 빠졌다」로 읽힌다."""
    rows = _rows(16, close=10000, list_shrs=1_000_000)
    for r in rows[8:]:
        r["close"], r["list_shrs"] = 2000, 5_000_000
        r["mktcap"] = 2000 * 5_000_000
    out = _model(rows, _idx(rows, 100.0), [])
    m = out["m"]
    assert len(m["breaks"]) == 1 and m["breaks"][0]["i"] == 8
    assert m["hasIdx"] is True
    assert m["idx"][0] == 10000 and m["idx"][7] == 10000
    assert m["idx"][8] == 2000 and m["idx"][15] == 2000
    assert 'class="mkt-idx"' in out["svg"] and 'class="mkt-break"' in out["svg"]
    assert "기준가 조정일" in out["legend"]


def test_지수가_움직이면_종목_기준으로_환산된다():
    rows = _rows(5, close=1000)
    idx = _idx(rows, 100.0)
    idx[4]["close"] = 110.0
    out = _model(rows, idx, [])
    assert out["m"]["idx"][4] == pytest.approx(1100.0)
    assert out["m"]["idxClose"][4] == 110.0


def test_지수가_없으면_종목만_그린다():
    out = _model(_rows(5), [], [])
    assert out["m"]["hasIdx"] is False
    assert 'class="mkt-idx"' not in out["svg"]
    assert "코스피" not in out["legend"]


def test_창_밖_사건은_버리되_센다():
    rows = _rows(10)                       # ~20260116
    ev = [
        {"date": "20251230", "key": "A", "label": "A", "count": 1, "rcept": "1", "priority": "watch", "nm": ""},
        {"date": "20260301", "key": "B", "label": "B", "count": 1, "rcept": "2", "priority": "watch", "nm": ""},
        {"date": "20260108", "key": "C", "label": "C", "count": 1, "rcept": "3", "priority": "watch", "nm": ""},
    ]
    out = _model(rows, [], ev)
    assert out["m"]["dropped"] == 2 and len(out["m"]["markers"]) == 1


def test_창_밖_행은_모델에_들어오지_않는다():
    rows = _rows(20)
    out = _model(rows, [], [], {"startDd": rows[5]["date"], "endDd": rows[14]["date"]})
    assert len(out["m"]["days"]) == 10
    assert out["m"]["days"][0]["date"] == rows[5]["date"]


def test_자료가_없으면_빈_문자열():
    out = _run("const m = marketChartModel([], [], []); console.log(JSON.stringify({n: m.days.length, svg: marketChartSVG(m)}));")
    assert out["n"] == 0 and out["svg"] == ""


# ── ② SVG ────────────────────────────────────────────────────────────────

def _balanced(svg: str, tag: str) -> bool:
    return len(re.findall(rf"<{tag}[\s>]", svg)) == svg.count(f"</{tag}>")


def test_svg_태그가_균형이고_마커는_원문_링크와_title을_가진다():
    rows = _rows(10)
    ev = [{"date": "20260107", "key": "A", "label": "유상증자", "count": 1,
           "rcept": "20260107000001", "priority": "watch", "nm": "유상증자결정"}]
    out = _model(rows, [], ev)
    svg = out["svg"]
    for tag in ("svg", "a", "title", "defs", "pattern"):
        assert _balanced(svg, tag), f"<{tag}> 태그 불균형"
    assert 'href="https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260107000001"' in svg
    assert "<title>유상증자 — 유상증자결정 (접수 2026.01.07)</title>" in svg
    assert 'class="mkt-hit"' in svg, "24px 명중 영역이 없다"
    assert 'class="mkt-xhair"' in svg
    assert 'role="img"' in svg and "aria-label" in svg


def test_판정_어휘와_오르내림_색이_없다():
    body = "\n".join(_cut(_SRC, f) for f in (
        "function marketChartModel(", "function marketChartSVG(",
        "function marketChartLegendHTML(", "function attachMarketChartHover("))
    for bad in ("급등", "급락", "이상", "과열", "위험"):
        assert bad not in body, f"차트 함수에 판정 어휘 '{bad}'가 있다"
    for color in ("--green", "--red", "--c7"):
        assert color not in body, f"차트가 {color}를 쓴다 — 오르내림·위험도를 색으로 칠하지 않는다"
    css_start = _SRC.index(".mkt-wrap {")
    css = _SRC[css_start:_SRC.index(".factwarn {", css_start)]
    for color in ("--green", "--red", "--c7"):
        assert color not in css


def test_격자는_실선이고_점선은_표지에만_쓴다():
    css_start = _SRC.index(".mkt-wrap {")
    css = _SRC[css_start:_SRC.index(".factwarn {", css_start)]
    grid = re.search(r"\.mkt-grid \{[^}]*\}", css).group(0)
    assert "dasharray" not in grid
    assert "dasharray" in re.search(r"\.mkt-break \{[^}]*\}", css).group(0)


def test_텍스트는_텍스트_색이다():
    css_start = _SRC.index(".mkt-wrap {")
    css = _SRC[css_start:_SRC.index(".factwarn {", css_start)]
    for cls in (".mkt-ax", ".mkt-note", ".mkt-cnt"):
        rule = re.search(re.escape(cls) + r" \{[^}]*\}", css).group(0)
        assert "--amber" not in rule and "--tx)" in rule or "--dim" in rule


# ── ③ 상수·문구 ─────────────────────────────────────────────────────────

def test_예산_동시성_캐시_상수():
    assert "const KRX_CALL_BUDGET = 270;" in _SRC, "차트 창 평일 261일을 한 번에 받는 예산"
    assert "const KRX_CONCURRENCY = 6;" in _SRC, (
        "동시 호출 수를 올리기 전에 KRX 차단(403)을 다시 재야 한다 — 2026-09-23 실측")
    assert "const KRX_ROWS_MAX = 6000;" in _SRC
    assert "const KRX_CHART_DAYS = 365;" in _SRC
    assert "KRX_ROWS_MAX" in _cut(_SRC, "function krxSaveRowsCache(")
    assert "3000" not in _cut(_SRC, "function krxSaveRowsCache("), "캐시 상한 리터럴이 부활했다"
    for gone in ("KRX_EVENT_MAX", "KRX_BASELINE_DAYS", "KRX_INDEX_CALL_BUDGET"):
        assert gone not in _SRC, f"대조표·지수 호출용 상수 {gone}이 남았다"


def test_차트_마커는_상한_없이_전부다():
    loader = _cut(_SRC, "async function loadMarketReaction(")
    assert "pickMarketEvents((CUR && CUR.observedEvents) || [], Infinity)" in loader


def test_지수_파일_실패는_종목만이라고_밝히고_스캔_창_절단을_적는다():
    loader = _cut(_SRC, "async function loadMarketReaction(")
    assert "자료가 없다는 뜻이 아닙니다(차트는 종목만)" in loader
    assert "최근 ${KRX_CHART_DAYS}일만 그립니다" in loader
    render = _cut(_SRC, "function marketReactionHTML(")
    assert "일 미조회" in render and "자료가 없다는 뜻이 아닙니다" in render


def test_차트_폭은_패널_폭을_따른다():
    """전폭 배치라 viewBox를 760으로 고정하면 세로가 과하게 커진다 — 패널 폭(px)을
    모델에 싣고 SVG·호버가 같은 값을 쓴다."""
    out = _model(_rows(10), [], [], {"width": 1400})
    assert out["m"]["W"] == 1400
    assert 'viewBox="0 0 1400 ' in out["svg"]
    hover = _cut(_SRC, "function attachMarketChartHover(")
    assert "const W = m.W || MKT_W;" in hover


def test_패널_제목과_펼침_문구():
    assert "MARKET — 공시와 시장 (1년 주가·거래량·지수)" in _SRC
    assert "1년 주가·거래량 위에 관찰 신호를 표시하고 코스피·코스닥 지수를 겹칩니다" in _SRC
