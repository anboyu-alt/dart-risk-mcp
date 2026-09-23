"""뷰어 「공시 전후 시장 반응」(KRX) 패널 — 캐시·예산·발표유예와 패널 문구.

설계 근거: `docs/superpowers/specs/2026-09-23-viewer-krx-panel-design.md`.
순수 함수 쌍둥이(`weekdayCandidates`·`eventWindowFacts`·`windowOverview`)는
`tests/test_viewer_twin_parity.py`가 core와 대조한다. 이 파일은 그 쌍이
아닌 두 가지 — ① `krxFetchSeries`의 캐시·발표유예(grace)·호출 예산이
실제로 동작하는지(로컬스토리지·fetch를 흉내 내 실행) ② 패널이 내는
문구가 스펙이 약속한 사실(키 없음 안내·거래소 출처 고지·판정 어휘 부재·
같은 날 접기)을 담는지 — 를 잠근다.

`fetch`·`localStorage`는 node에 없으므로 `global`에 얇게 흉내 낸다. 실제
릴레이(`api/krx.js` 등)는 다른 에이전트가 별도로 만들고 있고
`tests/test_viewer_krx_relay.py`가 그 계약을 잠근다 — 여기서는 뷰어가
그 계약을 **어떻게 소비하는지**만 본다.
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


def _html() -> str:
    return _HTML.read_text(encoding="utf-8")


def _cut(html: str, head: str) -> str:
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
    m = re.search(r"^(?:const|let|var)\s+" + re.escape(name) + r"\s*=", html, re.M)
    if not m:
        if re.search(r"^(?:async )?function\s+" + re.escape(name) + r"\s*\(", html, re.M):
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


# ── krxFetchSeries 하네스 — fetch·localStorage를 흉내 낸다 ──────────────
#
# `relayBase`는 `location.hostname`을 읽어 브라우저 전용이라 여기서는
# 고정 문자열로 갈아 끼운다(mezzanine 테스트가 `esc`·`fmtDate`를 심는 것과
# 같은 관례) — 이 파일이 재는 것은 캐시·예산이지 릴레이 주소 해석이 아니다.
_KRX_FUNC_HEADS = (
    "async function krxGet(",
    "async function krxResolveMarket(",
    "function weekdayCandidates(",
    "function krxRowsCacheKey(",
    "function krxRowsCache(",
    "function krxSaveRowsCache(",
    "async function krxFetchSeries(",
)

_SHIM = """
const _store = {};
global.localStorage = {
  getItem: (k) => (k in _store ? _store[k] : null),
  setItem: (k, v) => { _store[k] = String(v); },
  removeItem: (k) => { delete _store[k]; },
};
global.relayBase = () => "";
let FETCH_CALLS = [];
global.fetch = async (url) => {
  const u = new URL(url, "http://x");
  const basDd = u.searchParams.get("basDd");
  FETCH_CALLS.push(basDd);
  const resp = (FETCH_RESPONSES[basDd] !== undefined) ? FETCH_RESPONSES[basDd] : DEFAULT_RESPONSE;
  return { ok: true, status: 200, json: async () => resp };
};
"""


def _run_krx(js_tail: str, fetch_responses: dict, default_response: dict,
             initial_cache: "dict | None" = None) -> dict:
    """`krxFetchSeries` 등을 실제로 실행하고 `js_tail`(콘솔에 JSON을 찍는 코드)의
    결과를 돌려준다. 부족한 전역 참조는 `ReferenceError`를 보고 실코드에서
    자동으로 끌어온다(다른 이식 테스트와 같은 관례).
    """
    html = _html()
    src = "\n".join(_cut(html, f) for f in _KRX_FUNC_HEADS)
    # ⚠ 이 상수들(특히 `LS_KRX_KEY`)이 빠지면 `krxGet`이 `ReferenceError`를
    # 던지는데, `krxFetchSeries`의 `runOne`이 그걸 `try/catch`로 **그대로
    # 삼켜** "fetch 실패"로 보이게 만든다 — 아래 자동 끌어오기(ReferenceError
    # 감지)가 표면화되지 않아 조용히 틀린 결과(전부 uncovered)를 낸다. 실제로
    # 이 함정에 한 번 걸렸다 — 그래서 이 넷은 자동 끌어오기에 맡기지 않고
    # 미리 명시적으로 끌어온다.
    # `KRX_INDEX_NAMES`도 같은 함정이다 — `krxGet`이 지수 api인지 가르는 데 쓰는데
    # 없으면 ReferenceError가 `runOne`에 삼켜져 전부 uncovered로 보인다(2026-09-23
    # 차트 도입 때 실제로 그렇게 실패했다).
    consts = "\n".join(
        _cut_decl(html, n) for n in ("LS_KRX_KEY", "LS_KRX_ROWS", "LS_KRX_MKT", "KRX_API_IDS",
                                     "KRX_INDEX_NAMES", "KRX_ROWS_MAX", "KRX_CALL_BUDGET")
    )
    cache_seed = ""
    if initial_cache:
        cache_seed = (
            "_store[" + json.dumps("dart_tool_krx_rows") + "] = "
            + json.dumps(json.dumps(initial_cache, ensure_ascii=False)) + ";\n"
        )
    js = (
        _SHIM
        + consts + "\n"
        + f"const FETCH_RESPONSES = {json.dumps(fetch_responses, ensure_ascii=False)};\n"
        + f"const DEFAULT_RESPONSE = {json.dumps(default_response, ensure_ascii=False)};\n"
        + cache_seed
        + '_store["dart_tool_krx_key"] = "k".repeat(40);\n'
        + src + "\n"
        + js_tail
    )
    pre = ""
    for _ in range(24):
        r = _node(pre + js)
        if r.returncode == 0:
            return json.loads(r.stdout)
        m = re.search(r"ReferenceError: (\w+) is not defined", r.stderr or "")
        if not m:
            raise AssertionError(f"node 실패:\n{(r.stderr or '')[:2000]}")
        d = _cut_decl(html, m.group(1))
        assert d is not None, f"뷰어에서 {m.group(1)} 선언을 찾지 못했다"
        pre = d + "\n" + pre
    raise AssertionError("보조 선언을 24번 끌어와도 안 돈다")


def _row_resp(date8, close=10000):
    return {"ok": True, "found": True, "row": {
        "date": date8, "close": close, "fluc_rt": 0.5, "volume": 100000,
        "value": close * 100000, "mktcap": 10_000_000_000, "list_shrs": 1_000_000,
        "sect": None,
    }}


_EMPTY_RESP = {"ok": True, "found": False, "empty": True}


def _weekday_back(days: int):
    """오늘(시스템 로컬)에서 `days`일 전, 그 날짜가 주말이면 하루씩 더 당긴다."""
    import datetime as _dt
    d = _dt.date.today() - _dt.timedelta(days=days)
    while d.weekday() >= 5:
        d -= _dt.timedelta(days=1)
    return d.strftime("%Y%m%d")


# ── ① 캐시 히트는 fetch를 부르지 않는다 ──────────────────────────────

def test_캐시_히트는_다시_조회하지_않는다():
    d8 = _weekday_back(10)
    cached_row = _row_resp(d8)["row"]
    out = _run_krx(
        'krxFetchSeries("stk_bydd_trd", "005930", D8, D8).then((r) => '
        'console.log(JSON.stringify({r, calls: FETCH_CALLS})));'.replace("D8", json.dumps(d8)),
        fetch_responses={}, default_response=_EMPTY_RESP,
        initial_cache={f"stk_bydd_trd|{d8}|005930": cached_row},
    )
    assert out["calls"] == [], f"캐시가 있는데 fetch를 불렀다: {out['calls']}"
    assert out["r"]["daysCached"] == 1
    assert out["r"]["daysFetched"] == 0
    assert out["r"]["rows"] and out["r"]["rows"][0]["close"] == cached_row["close"]


# ── ② 발표유예(grace) — 최근 며칠의 빈 응답은 캐시하지 않는다 ──────────

def test_최근_빈_응답은_캐시하지_않고_오래된_빈_응답은_캐시한다():
    recent = _weekday_back(1)     # 그레이스(7일) 안 — 발표 전일 수 있다
    old = _weekday_back(40)       # 그레이스 밖 — 진짜 휴장일로 캐시

    def _once(d8):
        return _run_krx(
            'krxFetchSeries("stk_bydd_trd", "005930", D8, D8).then((r) => '
            'console.log(JSON.stringify({r, calls: FETCH_CALLS, '
            'cached: JSON.parse(_store["dart_tool_krx_rows"] || "{}")})));'
            .replace("D8", json.dumps(d8)),
            fetch_responses={}, default_response=_EMPTY_RESP,
        )

    r_recent = _once(recent)
    assert r_recent["r"]["pending"] == [recent], "최근 빈 응답이 pending으로 안 잡혔다"
    assert f"stk_bydd_trd|{recent}|005930" not in r_recent["cached"], (
        "최근 빈 응답을 캐시했다 — 발표 전이 영구 휴장일로 굳는다")

    r_old = _once(old)
    assert r_old["r"]["pending"] == [], "그레이스 밖인데 pending으로 잡혔다"
    assert r_old["cached"].get(f"stk_bydd_trd|{old}|005930") is None, (
        "오래된 빈 응답이 캐시되지 않았다(재조회를 계속 하게 된다)")
    # 두 번째 호출은 캐시를 읽어 fetch를 다시 부르지 않아야 한다.
    r_old2 = _run_krx(
        'krxFetchSeries("stk_bydd_trd", "005930", D8, D8).then((r) => '
        'console.log(JSON.stringify({r, calls: FETCH_CALLS})));'
        .replace("D8", json.dumps(old)),
        fetch_responses={}, default_response=_EMPTY_RESP,
        initial_cache={f"stk_bydd_trd|{old}|005930": None},
    )
    assert r_old2["calls"] == [], "캐시된 휴장일을 다시 조회했다"
    assert r_old2["r"]["daysCached"] == 1


# ── ②b gap_before — 앞 거래일이 미조회면 표시하고, 휴장일은 빈틈이 아니다 ──

def _mon_tue_wed_back(days: int):
    """days일 전 언저리의 (월, 화, 수) 세 평일 — 그레이스(7일) 밖이어야 한다."""
    import datetime as _dt
    d = _dt.date.today() - _dt.timedelta(days=days)
    while d.weekday() != 2:
        d -= _dt.timedelta(days=1)
    f = lambda x: x.strftime("%Y%m%d")
    return f(d - _dt.timedelta(days=2)), f(d - _dt.timedelta(days=1)), f(d)


def test_gap_before는_미조회_다음_행에만_붙고_휴장일은_빈틈이_아니다():
    """core `fetch_price_series`와 같은 계산(2026-09-23) — `priceBreaks`가 며칠치
    움직임을 하루 등락률과 견주지 않게 하는 표시. 화요일 조회가 실패(uncovered)하면
    수요일 행에 gap_before=true, 화요일이 휴장(빈 응답)이면 false."""
    a, b, c = _mon_tue_wed_back(40)
    tail = (
        'const _orig = global.fetch; global.fetch = async (url) => { '
        '  if (String(url).includes("basDd=" + B8)) throw new Error("boom"); return _orig(url); };\n'
        'krxFetchSeries("stk_bydd_trd", "005930", A8, C8).then((r) => '
        'console.log(JSON.stringify({rows: r.rows.map((x) => [x.date, x.gap_before]), '
        'uncovered: r.uncovered})));'
    ).replace("A8", json.dumps(a)).replace("B8", json.dumps(b)).replace("C8", json.dumps(c))
    out = _run_krx(tail, fetch_responses={a: _row_resp(a), c: _row_resp(c)},
                   default_response=_EMPTY_RESP)
    assert out["uncovered"] == [b]
    assert out["rows"] == [[a, False], [c, True]], out

    # 화요일이 휴장(빈 응답)이면 수요일은 빈틈이 아니다
    out2 = _run_krx(
        'krxFetchSeries("stk_bydd_trd", "005930", A8, C8).then((r) => '
        'console.log(JSON.stringify({rows: r.rows.map((x) => [x.date, x.gap_before]), '
        'uncovered: r.uncovered})));'
        .replace("A8", json.dumps(a)).replace("C8", json.dumps(c)),
        fetch_responses={a: _row_resp(a), b: _EMPTY_RESP, c: _row_resp(c)},
        default_response=_EMPTY_RESP)
    assert out2["uncovered"] == []
    assert out2["rows"] == [[a, False], [c, False]], out2


# ── ③ 호출 예산 — 넘는 날짜는 uncovered로 밝힌다 ───────────────────────

def test_예산을_넘으면_오래된_쪽이_uncovered로_남는다():
    import datetime as _dt
    end = _dt.date.today() - _dt.timedelta(days=1)
    while end.weekday() >= 5:
        end -= _dt.timedelta(days=1)
    start = end - _dt.timedelta(days=600)   # 달력 600일 ≈ 평일 428일(예산 320 초과)
    s8, e8 = start.strftime("%Y%m%d"), end.strftime("%Y%m%d")

    out = _run_krx(
        'krxFetchSeries("stk_bydd_trd", "005930", S8, E8).then((r) => '
        'console.log(JSON.stringify({r, calls: FETCH_CALLS, budget: KRX_CALL_BUDGET})));'
        .replace("S8", json.dumps(s8)).replace("E8", json.dumps(e8)),
        fetch_responses={}, default_response=_EMPTY_RESP,
    )
    r, calls, budget = out["r"], out["calls"], out["budget"]
    assert budget == 320, "차트 예산(320)이 바뀌었다 — 스펙과 이 테스트를 함께 고친다"
    assert r["daysRequested"] > budget, "표본 구간이 예산을 못 넘겼다 — 구간을 넓혀야 한다"
    assert len(r["uncovered"]) == r["daysRequested"] - budget
    assert len(calls) <= budget, "예산을 넘겨 fetch를 불렀다"
    # 남는 쪽은 항상 **오래된 날짜**다(최근을 먼저 채운다 — core와 같은 판단).
    if r["uncovered"]:
        assert max(r["uncovered"]) < min(calls), (
            "uncovered가 최근 날짜다 — 오래된 쪽이 남아야 한다")


# ══════════════════════════════════════════════════════════════════════
# 패널 문구 — marketReactionHTML·loadMarketReaction의 정적 사실
# ══════════════════════════════════════════════════════════════════════

_SRC = _html()


def test_키_없음_한_줄이_있다():
    body = _cut(_SRC, "async function loadMarketReaction(")
    assert "krxKey" in body and "KRX 키" in body
    assert re.search(r"if\s*\(!krxKey\)\s*\{", body)


def test_거래소_출처_고지가_있다():
    body = _cut(_SRC, "function marketReactionHTML(")
    assert "KRX_ATTRIBUTION" in body, "거래소 출처 고지(KRX_ATTRIBUTION)가 없다"
    attrib = _cut_decl(_SRC, "KRX_ATTRIBUTION")
    assert attrib and "한국거래소 통계정보" in attrib, (
        "KRX_ATTRIBUTION 상수 값이 「한국거래소 통계정보」가 아니다(약관 제10조 ③)")
    assert "track_market_reaction" in body


def test_판정_어휘가_없다():
    """v0.8.5 — 등락률·배수·회전율·일수만 적고 임계·판정 어휘는 쓰지 않는다."""
    body = _cut(_SRC, "function marketReactionHTML(")
    for bad in ("급등", "급락", "이상", "과열"):
        assert bad not in body, f"marketReactionHTML에 판정 어휘 '{bad}'가 있다"


def test_증감_셀에_색이_없다():
    """등락 방향에 좋고 나쁨이 없다 — deltaHTML을 sense none으로 쓴다."""
    body = _cut(_SRC, "function marketReactionHTML(")
    assert body.count('sense: "none"') >= 3, (
        "D0 등락·전·후 세 칸이 전부 sense:none이어야 한다")


def test_최근_N건만_대조한다는_고지가_있다():
    body = _cut(_SRC, "function marketReactionHTML(")
    assert "KRX_EVENT_MAX" in body


def test_같은_날_같은_신호는_배수로_접는다():
    """`pickMarketEvents`가 (날짜, 첫 관찰 신호 키)로 묶어 count를 올린다."""
    body = _cut(_SRC, "function pickMarketEvents(")
    assert "count++" in body or "count + 1" in body.replace(" ", "")
    render = _cut(_SRC, "function marketReactionHTML(")
    assert "×${g.count}" in render or "g.count > 1" in render


def test_관리종목_규정선_대조_문구가_있다():
    body = _cut(_SRC, "function marketReactionHTML(")
    assert "이 도구의 임계가 아니라 규정 수치입니다" in body


def test_패널이_deepgrid_안에_있다():
    """스펙: `.deepgrid` 안, `<details>` 펼침 시 조회."""
    i = _SRC.index('id="marketDetails"')
    j = _SRC.rindex('<div class="deepgrid">', 0, i)
    k = _SRC.index("// .deepgrid 닫기", i)
    assert j < i < k, "marketDetails가 .deepgrid 격자 밖에 있다"


def test_krx_키_없으면_details_열어도_조회하지_않는다():
    """`loadMarketReaction`은 el.dataset.loaded 가드 뒤 krxKey가 없으면
    krxResolveMarket·krxFetchSeries를 부르지 않고 바로 리턴한다."""
    body = _cut(_SRC, "async function loadMarketReaction(")
    no_key_branch = body[body.index("if (!krxKey)"):]
    no_key_branch = no_key_branch[:no_key_branch.index("return;") + len("return;")]
    assert "krxResolveMarket" not in no_key_branch
    assert "krxFetchSeries" not in no_key_branch
