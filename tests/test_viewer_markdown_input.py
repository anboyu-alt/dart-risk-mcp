"""뷰어 원문 파서에 **뷰어가 실제로 받는 표현**을 먹여 core와 대조한다.

`test_viewer_detail_parser_parity.py`는 같은 평문을 양쪽에 먹인다. 그래서
로직 차이는 잡지만 **입력 표현 차이는 구조적으로 못 잡는다** — 그 문서에
적힌 "라이브 8건 대조"도 core 쪽 표현으로 한 것이었다.

두 구현이 받는 것은 다르다:

    core    `fetch_document_text`      → 태그를 지운 **공백 구분 평문**
    뷰어    `/api/doc`(=`fetch_disclosure_full`) → **마크다운 표**(`| 값 |`)

core의 정규식은 값 사이를 `\\s*`·`\\s+`로 잇는다. 표에서는 그 자리에 `|`와
구분선(`| --- |`)이 들어와 매칭이 끊긴다. 정규식을 그대로 이식한 v1.14.0의
세 파서가 전부 이 이유로 뷰어에서 제 값을 못 읽고 있었다(2026-08-28 실측,
실문서):

    parseEarningsShockDetail   core 3행 → 뷰어 **0행**(블록이 통째로 비었다)
    parseRelatedPartyDetail    1,200억원 차입 → **금액 0 · 관계 공란**,
                               상대방 이름에 `|`가 붙어 나왔다
    parseAssetDisposalDetail   실문서 5건 중 **3건이 금액 0**

`mdToPlain`이 표 구분자·구분선을 지워 core가 보는 모양으로 맞춘다. 이 파일은
**실문서에서 잘라 온 두 표현**을 픽스처로 고정해 재발을 막는다.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest

from dart_risk_mcp.core.dart_client import (
    parse_asset_disposal_detail,
    parse_earnings_shock_detail,
    parse_related_party_detail,
)

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = _ROOT / "docs" / "tool" / "index.html"
_FX = json.loads(
    (_ROOT / "tests" / "fixtures" / "viewer" / "doc_representations.json")
    .read_text(encoding="utf-8")
)

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node가 없으면 뷰어 쪽을 돌릴 수 없다"
)


def _func(html: str, name: str) -> str:
    i = html.index(f"function {name}(")
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
    raise AssertionError(name)


def _consts(html: str, *names: str) -> str:
    lines = html.splitlines()
    out = []
    for n in names:
        i = next(k for k, l in enumerate(lines) if l.startswith(f"const {n} "))
        buf = []
        for l in lines[i:]:
            buf.append(l)
            if l.rstrip().endswith(";"):
                break
        out.append("\n".join(buf))
    return "\n".join(out)


def _run(fn: str, text: str, *, consts=(), funcs=()) -> dict:
    html = _HTML.read_text(encoding="utf-8")
    src = _consts(html, "AMENDED_DOC_MARKERS", "AFFIL_DASH_VALUES", *consts)
    for f in ("mdToPlain", "isAmendedDocument", "affiliateInt", "affiliateRatio",
              *funcs, fn):
        src += "\n" + _func(html, f)
    src += (f"\nconst T={json.dumps(text, ensure_ascii=False)};"
            f"\nconsole.log(JSON.stringify({fn}(T)));")
    tf = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    tf.write(src)
    tf.close()
    try:
        r = subprocess.run([shutil.which("node"), tf.name],
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, f"node 실패:\n{(r.stderr or '')[:1200]}"
        return json.loads(r.stdout)
    finally:
        os.unlink(tf.name)


_RP_CONSTS = ("RP_COUNTERPARTY_RES", "RP_RELATION_RE", "RP_AMOUNT_RE",
              "RP_RATE_RE", "RP_EQUITY_RE", "RP_UNIT_MILLION_RE", "RP_UNIT_EOK_RE")
_DISP_CONSTS = ("DISPOSAL_COUNTERPARTY_RES", "DISPOSAL_RELATION_RE",
                "DISPOSAL_AMOUNT_RE", "DISPOSAL_AMOUNT_BARE_RE",
                "DISPOSAL_UNIT_MILLION_RE", "DISPOSAL_RATIO_RE",
                "DISPOSAL_BOOK_RE", "DISPOSAL_EXTVAL_RE", "RELATION_LOOKS_DIRTY_RE",
                # 상대방 값이 주석 문장을 물면 버린다(2026-08-28)
                "COUNTERPARTY_LOOKS_DIRTY_RE")


@pytest.mark.parametrize("tag", ["related_borrow", "related_invest"])
def test_특수관계인_파서가_표에서도_같은_값을_읽는다(tag):
    fx = _FX[tag]
    core = parse_related_party_detail(fx["plain"])
    view = _run("parseRelatedPartyDetail", fx["md"], consts=_RP_CONSTS)
    assert core["counterparty"] == view["counterparty"]
    assert core["relation"] == view["relation"], "관계는 게이트 판정의 입력이다"
    assert core["amount"] == view["amount"]
    assert str(core["equity_ratio"]) == str(view["equityRatio"])


def test_특수관계인_금액이_0이_아니다():
    """빈 값끼리 같아 보이지 않게 못 박는다 — 이 자리가 실제로 0이었다."""
    core = parse_related_party_detail(_FX["related_borrow"]["plain"])
    view = _run("parseRelatedPartyDetail", _FX["related_borrow"]["md"],
                consts=_RP_CONSTS)
    assert core["amount"] > 0 and view["amount"] > 0
    assert "|" not in view["counterparty"], "표 구분자가 이름에 섞였다"


def test_손익구조_파서가_표에서도_행을_읽는다():
    fx = _FX["earnings"]
    core = parse_earnings_shock_detail(fx["plain"])
    view = _run("parseEarningsShockDetail", fx["md"], consts=("ES_ROW_RE",))
    assert core["rows"], "픽스처에 계정 행이 없다 — 검사가 헛돈다"
    assert len(view["rows"]) == len(core["rows"])
    for a, b in zip(core["rows"], view["rows"]):
        assert a["account"] == b["account"]
        assert a["current"] == b["current"]
        assert a["change_pct"] == b["changePct"]


def test_자산처분_파서가_표에서도_같은_값을_읽는다():
    fx = _FX["disposal"]
    core = parse_asset_disposal_detail(fx["plain"])
    view = _run("parseAssetDisposalDetail", fx["md"], consts=_DISP_CONSTS)
    assert core["amount"] > 0, "픽스처에 금액이 없다 — 검사가 헛돈다"
    assert core["counterparty"] == view["counterparty"]
    assert core["amount"] == view["amount"]
    assert "|" not in view["counterparty"]


def test_mdToPlain이_구분선까지_지운다():
    """`| --- |` 구분선이 남으면 관계 값 뒤보기가 끊긴다(출자·담보 실측)."""
    src = _func(_HTML.read_text(encoding="utf-8"), "mdToPlain")
    assert re.search(r"\^\[.*-.*\]\*\$", src) or "---" in src, (
        "구분선 제거가 사라졌다"
    )
