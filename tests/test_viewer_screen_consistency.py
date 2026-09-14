"""화면끼리·라벨과 값이 어긋나던 네 자리(2026-09-14).

제작자 요청 "다른 화면도 어색한 부분 있는지 찾아봐"로 10개사 라이브를 훑어
찾은 것들이다. 넷 다 같은 부류다 — **화면이 제 데이터와 다른 것을 말한다.**

  ① 최근 스캔 목록의 신호 수가 한정층 **이전** 원자료였다. 같은 회사가
     최근 목록 45, 대시보드 15(삼성전자 · 3배). 한정층은 절차·사후 보고를
     신호로 세지 말자고 만든 것인데 이 자리만 그 앞단에 남아 있었다.
  ② 「신호 감지」 KPI가 신호 1건이면 빨강이라 **10개사 실측 10/10**이 붉었다
     (삼성전자·NAVER·KB금융·이마트 포함). 100%에 붙는 것은 표시가 아니라
     배경이고, 붉은 큰 숫자는 회사에 대한 판정으로 읽힌다(v0.8.5).
  ③ 정정 비율 **하나에 임계가 둘**이었다 — 빨강 20 · 설명 25. 20~25% 구간은
     붉은데 이유가 없었고, 20은 유래가 적혀 있지 않은 반면 25는 실측 근거가
     있다(공시 10건 이상 상장사 488곳 p75 = 23.1%, 2026-08-24).
  ④ 「신호 무게」 라벨이 내는 값은 「이 기간 대표 유형」·「감지됨」·「절차·사후
     보고」·「—」로 전부 **상태**였다. 2026-08-30에 「MAX」→「대표 유형」으로
     같은 부류를 고칠 때 이 자리만 남았다.
"""
import json
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")


def _cut(src: str, head: str) -> str:
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


# ── ① 최근 스캔 목록이 대시보드와 같은 수를 말한다 ────────────────────────

def test_최근_목록이_관찰_신호_수를_저장한다():
    assert "obs: observedEvents.length" in _HTML
    assert "sig: events.length" not in _HTML, (
        "한정층 이전 원자료를 저장하면 대시보드와 다른 수가 나온다"
    )


def test_옛_저장값을_새_라벨로_되살리지_않는다():
    """localStorage에 남은 `sig`는 한정층 이전 값이다 — 섞으면 같은 화면에
    두 기준이 공존하고 사용자는 구분할 수 없다."""
    body = _cut(_HTML, "function renderRecent()")
    assert "x.sig" not in body, "옛 키를 그대로 읽고 있다"
    assert "recentObsLabel(" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_모르는_값은_대시로_적는다():
    js = (_cut(_HTML, "function recentObsLabel(") + "\n"
          + "console.log(JSON.stringify(["
          + "recentObsLabel({obs: 15}), recentObsLabel({sig: 45}),"
          + "recentObsLabel({}), recentObsLabel({obs: 0})]));\n")
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False,
                                     encoding="utf-8") as f:
        f.write(js)
        path = f.name
    try:
        r = subprocess.run(["node", path], capture_output=True, text=True,
                           encoding="utf-8")
        assert r.returncode == 0, r.stderr
        got = json.loads(r.stdout)
    finally:
        pathlib.Path(path).unlink(missing_ok=True)
    assert got[0] == "15"
    assert got[1] == "—", "옛 `sig` 항목을 숫자처럼 보여주면 안 된다"
    assert got[2] == "—"
    assert got[3] == "0", "0은 모르는 것이 아니라 관찰 0건이다"


# ── ② 신호 1건에 빨강을 칠하지 않는다 ─────────────────────────────────────

def test_신호_감지_KPI에_경보색이_없다():
    i = _HTML.index('<div class="k">신호 감지</div>')
    seg = _HTML[max(0, i - 400):i]
    assert "alert" not in seg, (
        "신호 1건이면 빨강이라 10개사 실측 10/10이 붉었다 — 정보가 아니다"
    )


def test_최근_목록도_신호_수로_색을_칠하지_않는다():
    body = _cut(_HTML, "function renderRecent()")
    assert "var(--red)" not in body


# ── ③ 정정 비율의 임계는 하나다 ───────────────────────────────────────────

def test_정정_비율_임계가_하나로_모였다():
    i = _HTML.index('<div class="k">정정 비율</div>')
    seg = _HTML[max(0, i - 300):i]
    assert "AMEND_NOTE_FLOOR" in seg, "근거 있는 문턱을 쓰지 않는다"
    assert "amendRate >= 20" not in _HTML, "유래가 없는 두 번째 임계가 남아 있다"


def test_문턱의_근거가_주석에_남아_있다():
    i = _HTML.index("const AMEND_NOTE_FLOOR")
    seg = _HTML[max(0, i - 500):i]
    assert "488" in seg and "p75" in seg, "실측 근거를 지우면 다음 사람이 또 20을 쓴다"


# ── ④ 라벨이 값과 같은 것을 말한다 ────────────────────────────────────────

def test_상태_칸을_무게라_부르지_않는다():
    # 라벨 자리에서 값 쪽으로 읽는다 — 「이 기간 대표 유형」은 피드 배지에도
    # 쓰여서 그쪽을 앵커로 잡으면 엉뚱한 구간을 문다(첫 판이 실제로 그랬다).
    i = _HTML.index("신호 상태")
    seg = _HTML[i:i + 700]
    assert "이 기간 대표 유형" in seg and "절차·사후 보고" in seg, (
        "라벨과 값이 같은 줄에 있지 않다"
    )
    # 주석으로 사유를 남기는 것은 되지만, 화면에 찍히는 라벨이면 안 된다
    label_like = re.findall(r'>(\s*신호 무게\s*)<', _HTML)
    assert not label_like, "「무게」는 있지도 않은 점수를 약속하는 말이다"


# ── 2차 라운드 (2026-09-14) — 비교 표·자금사용 ─────────────────────────────

def test_대표_유형_칸이_관찰_신호를_부정하지_않는다():
    """headline이 비는 흔한 이유는 관찰 신호가 **전부 양면적 유형**이라
    pickHeadline이 승격시키지 않는 것이고 그건 의도다. 옛 문구
    「관찰 신호 없음」은 같은 행의 「관찰 신호 N건」과 정면으로 모순됐다
    (15개사 중 4곳 — 티쓰리 5건·삼성전자 15건·두산 4건·KB금융 5건,
    관찰 0건인 회사는 표본에 하나도 없었다)."""
    body = _cut(_HTML, "function compareTableHTML(")
    assert "대표 유형 없음" in body
    # 주석으로 옛 문구를 설명하는 것은 되지만 화면에 찍히면 안 된다
    # (「신호 무게」 테스트와 같은 처리 — 렌더되는 형태만 본다).
    assert ">관찰 신호 없음<" not in body, (
        "대표 유형 칸이 관찰 신호의 부재를 주장하고 있다"
    )


def test_자금사용_빈_껍데기_행을_목록에서_뺀다():
    """DART가 모든 칸을 "-"로 준 행. 삼성전자는 그 한 줄이 패널의 전부였고
    「납입일 미상 납입 · 계획 총 0원」으로 보였다(10개사 중 3곳)."""
    assert "function isBlankFundRecord(" in _HTML
    body = _cut(_HTML, "function fundChainPanelHTML(")
    assert "isBlankFundRecord" in body, "배제 함수를 만들어 놓고 쓰지 않는다"
    # ⚠ 조용히 빼지 않는다 — 몇 건을 뺐는지 화면이 말해야 한다
    assert "blankNote" in body and "건은 목록에서 뺐습니다" in body


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_빈_껍데기_판정이_실제로_동작한다():
    js = (_cut(_HTML, "function isBlankFundRecord(") + "\n"
          + "console.log(JSON.stringify(["
          + "isBlankFundRecord({}),"
          + "isBlankFundRecord({pay_de:'', plan_useprps:'', plan_amount:null}),"
          + "isBlankFundRecord({pay_de:'2024.01.24'}),"
          + "isBlankFundRecord({plan_amount: 100})]));\n")
    with tempfile.NamedTemporaryFile("w", suffix=".mjs", delete=False,
                                     encoding="utf-8") as f:
        f.write(js)
        path = f.name
    try:
        r = subprocess.run(["node", path], capture_output=True, text=True,
                           encoding="utf-8")
        assert r.returncode == 0, r.stderr
        got = json.loads(r.stdout)
    finally:
        pathlib.Path(path).unlink(missing_ok=True)
    assert got == [True, True, False, False]


def test_미기재_표기_집합이_core와_같다():
    """「해당없음」이 빠져 있어 뷰어가 그 값을 「집행 차이 사유 보고 있음」으로
    바꿨다 — **뜻이 정반대**였다(NAVER 실측 · 14개사 510행 중 2행).
    두 곳에 흩어진 집합이라 갈리면 한쪽만 조용히 낡는다."""
    core = (_ROOT / "dart_risk_mcp" / "core" / "dart_client.py").read_text(encoding="utf-8")
    m = re.search(r"_FUND_BLANK_TOKENS = \{([^}]*)\}", core)
    assert m, "core 토큰 집합을 찾지 못했다"
    core_set = set(re.findall(r'"([^"]*)"', m.group(1)))
    v = re.search(r"FUND_BLANK_TOKENS = new Set\(\[([^\]]*)\]\)", _HTML)
    assert v, "뷰어 토큰 집합을 찾지 못했다"
    viewer_set = set(re.findall(r'"([^"]*)"', v.group(1)))
    assert core_set == viewer_set, f"core-뷰어 불일치: {core_set ^ viewer_set}"
    assert "해당없음" in core_set
