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
