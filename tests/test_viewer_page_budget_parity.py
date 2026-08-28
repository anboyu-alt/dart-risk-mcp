"""뷰어의 페이지 상한이 core `_page_budget`과 같은지 잠근다 (2026-08-26).

core를 고칠 때 뷰어가 안 따라오는 것이 이 저장소의 되풀이되는 결함이다
(`classifyOutflowRelation` 드리프트 v1.14.0, 라벨 보정 #277 등). 이번에는
**뷰어가 core보다 더 나빴다** — 옛 값 10/20/30은 core의 옛 공식보다도
낮아서, 화면이 core보다 더 많이 잘린 채로 결론을 냈다.

실측(2026-08-26, list.json total_count):

    삼성전자      1년 2,894   → 옛 뷰어 1,000건만 (65% 누락)
    미래에셋증권   5년 8,452   → 옛 뷰어 3,000건만 (65% 누락)

list.json은 최신순이라 잘리는 쪽은 언제나 오래된 쪽이다 — "5년 스캔"이
실제로는 최근 몇 달이 된다.

⚠ **소스 문자열 검색으로 확인하지 않는다.** 이번 세션에서 그 방법이 주석
자기참조로 세 번 실패했다. node로 **실제 값**을 계산해 본다.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

import dart_risk_mcp.server as srv

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")
_NODE = shutil.which("node")


def _viewer_max_pages(days: int) -> int:
    m = re.search(r"^function maxPages\(\).*$", _HTML, re.M)
    assert m, "maxPages를 찾지 못했다"
    script = f"let LOOKBACK_DAYS = {days};\n{m.group(0)}\nprocess.stdout.write(String(maxPages()));"
    out = subprocess.run([_NODE, "-e", script], capture_output=True, text=True,
                         encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return int(out.stdout)


@pytest.mark.skipif(not _NODE, reason="node가 없어 뷰어 값을 계산할 수 없습니다")
@pytest.mark.parametrize("days", [30, 365, 1095, 1825])
def test_뷰어와_core가_같은_상한을_쓴다(days):
    assert _viewer_max_pages(days) == srv._page_budget(days)


@pytest.mark.skipif(not _NODE, reason="node가 없어 뷰어 값을 계산할 수 없습니다")
def test_실측_최대치를_덮는다():
    """미래에셋증권 5년 8,452건 — 옛 뷰어 상한 30페이지로는 3,000건뿐이었다."""
    assert _viewer_max_pages(1825) * 100 >= 8452
    assert 30 * 100 < 8452


@pytest.mark.skipif(not _NODE, reason="node가 없어 뷰어 값을 계산할 수 없습니다")
def test_1년도_옛_상한으로는_모자랐다():
    assert _viewer_max_pages(365) * 100 >= 2894
    assert 10 * 100 < 2894


def test_절단_안내가_덮인_구간을_적는다():
    """"최근 N건"만 적으면 그 N건이 5년치인지 두 달치인지 알 수 없다."""
    assert "coveredFrom" in _HTML
    assert "실제로 덮인 구간" in _HTML


@pytest.mark.skipif(not _NODE, reason="node가 없어 뷰어 값을 계산할 수 없습니다")
def test_coveredFrom이_가장_오래된_날을_고른다():
    m = re.search(r"^function coveredFrom\(items\).*?\n\}", _HTML, re.M | re.S)
    fmt = re.search(r"^function fmtDate\(d8\).*$", _HTML, re.M)
    assert m and fmt
    script = (f"{fmt.group(0)}\n{m.group(0)}\n"
              'process.stdout.write(coveredFrom(['
              '{rcept_dt:"20260826"},{rcept_dt:"20250101"},{rcept_dt:"20260101"}]));')
    out = subprocess.run([_NODE, "-e", script], capture_output=True, text=True,
                         encoding="utf-8")
    assert out.returncode == 0, out.stderr
    assert out.stdout == "2025.01.01"


def test_키가_없으면_요청을_보내지_않는다():
    """`localStorage.getItem`은 키가 없을 때 `null`을 주고, URLSearchParams가
    그걸 **문자열 "null"로 바꿔 DART에 보낸다**. 실제로 나갔다 —

        GET /api/list.json?crtfc_key=null&corp_code=00118521&…

    DART는 010「등록되지 않은 API 키입니다」로 답하고, 화면은 키가 **틀렸다**고
    말한다. 키가 없는 것과 틀린 것은 사용자가 할 일이 다르다.

    ⚠ 2026-08-28: 가드 조건이 `!key` → `!key && !SERVER_KEY`로 넓어졌다.
    로컬 개발 릴레이(`scripts/dev_relay.py`)가 환경변수 키를 채워 줄 때는
    브라우저에 키가 없어도 되기 때문이다. **의도는 그대로다** — 키가 없을 때
    `crtfc_key`를 아예 보내지 않는다(빈 값도, "null"도 아니다).
    """
    i = _HTML.index("async function dartGet(")
    body = _HTML[i:_HTML.index("\n}", i)]
    assert "if (!key && !SERVER_KEY)" in body, "키 없음 가드가 사라졌다"
    assert "crtfc_key: key" in body, "정제한 키를 써야 한다"
    assert "crtfc_key: localStorage.getItem" not in body
    # 키가 없으면 파라미터 자체를 넣지 않는다 — 릴레이가 채우거나 위 가드가 막는다
    assert "key ? { crtfc_key: key, ...params } : { ...params }" in body
