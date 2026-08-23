"""뷰어가 DART **오류 상태**를 "자료 없음"으로 렌더하지 않는지 잠근다.

DART는 오류를 HTTP 200 본문의 `status`에 담아 보낸다 — 뷰어의 `dartGet`은
`res.ok`만 보므로 이걸 못 잡는다. 그래서 보조 로더 6곳이 `status !== "000"`을
전부 `continue`로 흘려보내고 부재 문구를 냈다(2026-08-23 감사).

가장 흔한 실패가 **일일 한도 초과(020)**이고, 그건 스캔 **후반부** 호출에서
터진다 — 즉 정확히 이 보조 로더들이다. 화면에는 "배당 기록 없음"이 떴다.

core는 같은 문제를 `FETCH_EMPTY`/`FETCH_ERROR`로 갈라 해결했다. 뷰어는 JS
이식이라 같은 구분을 따로 넣어야 한다(v1.14.0 `classifyOutflowRelation`
드리프트와 같은 교훈 — 이식은 각자 하므로 조용히 어긋난다).

⚠ **013은 오류가 아니다** — "그 조건에 자료가 없다"는 확정 답변이다.
실패로 세면 정말 조용한 회사에 "불러오지 못했다"고 적는 반대 방향의 거짓이 된다.

JS 실행은 이 레포의 관례를 따른다(`test_viewer_detail_parser_parity.py`) —
필요한 함수·상수만 HTML에서 잘라 node로 돌린다.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = _ROOT / "docs" / "tool" / "index.html"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node가 없어 뷰어 JS를 실행할 수 없다"
)

_FUNCS = ("dartFail", "fetchFailHTML", "esc")
_CONSTS = ("DART_ERR",)

# 부재를 말하는 보조 로더 — 전부 오류 상태를 구분해야 한다
_LOADERS = (
    "loadDividendCore", "loadFundChainCore", "loadFinancialCore",
    "loadHoldings", "loadAuditOpinions", "fetchRoster",
)


def _html() -> str:
    return _HTML.read_text(encoding="utf-8")


def _cut(html: str, name: str) -> str:
    """`function name(...) { ... }` 를 중괄호 균형으로 잘라낸다."""
    m = re.search(r"^(async )?function " + name + r"\s*\(", html, re.M)
    assert m, "함수를 찾지 못했다: " + name
    i = m.start()
    depth = 0
    started = False
    for j in range(i, len(html)):
        if html[j] == "{":
            depth += 1
            started = True
        elif html[j] == "}":
            depth -= 1
            if started and depth == 0:
                return html[i:j + 1]
    raise AssertionError("중괄호가 맞지 않는다: " + name)


def _cut_const(html: str, name: str) -> str:
    m = re.search(r"^const " + name + r"\s*=\s*[\s\S]*?^\};\s*$", html, re.M)
    assert m, "상수를 찾지 못했다: " + name
    return m.group(0)


def _run(expr_map: dict) -> dict:
    html = _html()
    src = "\n".join([_cut_const(html, c) for c in _CONSTS]
                    + [_cut(html, f) for f in _FUNCS])
    body = ",\n".join(f"  {json.dumps(k)}: {v}" for k, v in expr_map.items())
    js = src + "\nconsole.log(JSON.stringify({\n" + body + "\n}));\n"
    tf = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    tf.write(js)
    tf.close()
    try:
        r = subprocess.run([shutil.which("node"), tf.name],
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, "node 실패:\n" + (r.stderr or "")[:2000]
        return json.loads(r.stdout)
    finally:
        os.unlink(tf.name)


@pytest.fixture(scope="module")
def out():
    return _run({
        "ok": 'dartFail({status: "000", list: []})',
        "nodata": 'dartFail({status: "013"})',
        "nullish": "dartFail(null)",
        "quota": 'dartFail({status: "020"})',
        "badkey": 'dartFail({status: "010"})',
        "inactive": 'dartFail({status: "011"})',
        "maint": 'dartFail({status: "800"})',
        "unknown": 'dartFail({status: "900", message: "인증키 오류"})',
        "notice": 'fetchFailHTML("오늘 이 키의 조회 한도를 초과했습니다")',
        "xss": 'fetchFailHTML("<img src=x onerror=alert(1)>")',
    })


def test_정상과_자료없음은_실패가_아니다(out):
    assert out["ok"] is None
    assert out["nodata"] is None, "013을 실패로 세면 주말·휴장일마다 거짓 경고가 뜬다"
    assert out["nullish"] is None


@pytest.mark.parametrize("key,part", [
    ("quota", "한도"),
    ("badkey", "등록되지 않은"),
    ("inactive", "사용할 수 없는"),
    ("maint", "점검"),
])
def test_오류_상태는_사람이_읽을_메시지가_된다(out, key, part):
    assert out[key] and part in out[key], out[key]


def test_모르는_오류코드도_실패로_본다(out):
    assert out["unknown"] and "900" in out["unknown"]


def test_실패_안내에_부재가_아님이_명시된다(out):
    assert "조회하지 못했습니다" in out["notice"]
    assert "자료가 없다는 뜻이 아닙니다" in out["notice"]


def test_실패_안내가_HTML을_이스케이프한다(out):
    assert "<img" not in out["xss"]
    assert "&lt;img" in out["xss"]


@pytest.mark.parametrize("fn", _LOADERS)
def test_부재를_말하는_로더가_오류를_구분한다(fn):
    """새 로더가 부재 문구만 쓰고 `dartFail`을 안 부르면 여기서 걸린다."""
    assert "dartFail" in _cut(_html(), fn), f"{fn}이 오류 상태를 구분하지 않는다"


def test_겸직비교가_못_읽은_연도를_알린다():
    js = _html()
    assert "임원현황을 불러오지 못한 연도" in js
    assert "겹치는 인물이 없다는 뜻이 아닙니다" in js


def test_메인_스캔은_이미_오류를_던진다():
    """회귀 방지 — 메인 목록 조회는 처음부터 옳았다. 되돌아가지 않게 잠근다."""
    js = _html()
    assert 'if (j.status === "013") break;' in js
    assert 'if (j.status !== "000") throw new Error(DART_ERR[j.status]' in js
