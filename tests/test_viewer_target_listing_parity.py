"""뷰어의 상장 판정이 core와 **같은 답**을 내는지 잠근다 (2026-08-27).

core ↔ 뷰어 쌍둥이 34쌍 중 **양쪽을 함께 검사하는 테스트가 없는 7쌍**을
지도로 뽑다가 찾았다. 이건 그중 가장 위험한 하나였다.

    core   명부에서 못 찾음 → **unlisted**  (v1.13.1: 「못 찾는 것은 판정
           불가가 아니라 국내 상장사가 아니라는 근거」, 판정률 28% → 93%)
    뷰어   로컬 `CORPS`(corp-map.json = **상장사 스냅샷**)에서 못 찾음
           → **unknown**

`fund_diversion_chain` 게이트는 **unlisted일 때만** 발화한다. 그래서 국적이
해외인 건을 빼면 **뷰어에서는 그 카드가 뜰 수 없었다** — core는 같은 회사에서
띄운다(1년 약 45개사). 같은 제품의 두 화면이 다른 답을 냈다.

「뷰어엔 근거가 없다」는 전제도 더는 참이 아니었다 — `/api/corp`가 이미
**corpCode 전체(비상장 포함)**를 검색하고 있었다(기업 검색 폴백).

⚠ 못 물어봤을 때(키 없음·오프라인)는 여전히 `unknown`이다. 「모른다」와
「아니다」는 다르다.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

from dart_risk_mcp.core.dart_client import classify_target_listing

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")
_NODE = shutil.which("node")


def _js_src():
    def grab(start, end="}"):
        i = _HTML.index(start)
        j = _HTML.index("\n" + end, i)
        return _HTML[i:j + len(end) + 1]

    return "\n".join([
        re.search(r"const AFFIL_CORP_SUFFIX_RE = .*", _HTML).group(0),
        grab("function foldCorpName("),
        grab("async function classifyTargetListing(name, nation) {"),
    ])


def _viewer(name, nation, corps=(), candidates=None, fail=False):
    stub = ("global.fetchCorpFallback = async () => { throw new Error('x'); };"
            if fail else
            f"global.fetchCorpFallback = async () => "
            f"{json.dumps(candidates or [], ensure_ascii=False)};")
    script = (f"global.CORPS = {json.dumps({c: {} for c in corps}, ensure_ascii=False)};\n"
              f"{stub}\n{_js_src()}\n"
              f"classifyTargetListing({json.dumps(name, ensure_ascii=False)}, "
              f"{json.dumps(nation, ensure_ascii=False)})"
              f".then((r) => process.stdout.write(String(r)));")
    out = subprocess.run([_NODE, "-e", script], capture_output=True, text=True,
                         encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return out.stdout


# core 쪽 명부는 {이름: {stock_code, corp_code}} 꼴이다
_CORE_REG = {"셀트리온": {"stock_code": "068270", "corp_code": "1"},
             "비상장주식회사": {"stock_code": "", "corp_code": "2"}}


@pytest.mark.skipif(not _NODE, reason="node가 없어 뷰어 함수를 실행할 수 없습니다")
@pytest.mark.parametrize("name,nation,corps,cands,want", [
    ("셀트리온", "대한민국", ["셀트리온"], [], "listed"),
    ("ACME Inc", "미국", [], [], "unlisted"),
    ("없는회사", "대한민국", [], [], "unlisted"),
    ("비상장주식회사", "대한민국", [], [{"name": "비상장주식회사", "listed": False}], "unlisted"),
    ("상장사", "대한민국", [], [{"name": "상장사", "listed": True}], "listed"),
    ("", "대한민국", [], [], "unknown"),
])
def test_뷰어_판정(name, nation, corps, cands, want):
    assert _viewer(name, nation, corps, cands) == want


@pytest.mark.skipif(not _NODE, reason="node가 없어 뷰어 함수를 실행할 수 없습니다")
@pytest.mark.parametrize("name,nation,want", [
    ("셀트리온", "대한민국", "listed"),
    ("ACME Inc", "미국", "unlisted"),
    ("없는회사", "대한민국", "unlisted"),
    ("비상장주식회사", "대한민국", "unlisted"),
    ("", "대한민국", "unknown"),
])
def test_core와_같은_답을_낸다(name, nation, want):
    assert classify_target_listing(name, nation, _CORE_REG) == want


@pytest.mark.skipif(not _NODE, reason="node가 없어 뷰어 함수를 실행할 수 없습니다")
def test_못_물어봤으면_모른다고_한다():
    """「모른다」와 「아니다」는 다르다 — 조회 실패를 unlisted로 접지 않는다."""
    assert _viewer("아무개", "대한민국", [], fail=True) == "unknown"


def test_로컬_목록만으로_단정하지_않는다():
    """`CORPS`는 상장사 스냅샷이라 「없음」이 곧 비상장이 아니다 —
    전체 명부(`/api/corp`)에 물어본 뒤에 판단해야 한다."""
    i = _HTML.index("async function classifyTargetListing(")
    body = _HTML[i:_HTML.index("\n}", i)]
    assert "fetchCorpFallback(" in body


def test_호출부가_await_한다():
    """async로 바꿔 놓고 await를 빠뜨리면 Promise가 그대로 실려 나간다."""
    assert "await classifyTargetListing(" in _HTML
