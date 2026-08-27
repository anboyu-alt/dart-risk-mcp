"""core ↔ 뷰어 **쌍둥이 함수**를 같은 입력으로 돌려 결과를 대조한다.

뷰어(`docs/tool/index.html`)는 core의 JS 이식본이라, core를 고쳐도 뷰어는
따라오지 않는다 — 그리고 **사용자가 보는 것은 뷰어다**. 이 드리프트는 이미
여러 번 실물로 나왔다(`classify_outflow_relation`의 부정 표기 우선 검사
누락, `classify_target_listing`의 unknown 폴백으로 카드가 뜰 수 없던 것).

`test_viewer_core_parity.py`는 한정층 계열을 945종 코퍼스로 이미 잠근다.
여기서는 **그 밖의 쌍**을 잠근다.

⚠ 이 파일이 잡아낸 실제 드리프트 두 건(2026-08-28):

    parse_outflow_detail   뷰어에 `자기자본대비(%)` 추출이 아예 없었다.
                           실문서 3건에서 core 12.4·17.3·6.8, 뷰어 공란.
    pickHeadline           목록에 없는 키를 `indexOf`가 -1로 돌려 **맨 앞**에
                           놓았다 — core는 `rank.get(k, len(rank))`로 맨 뒤에
                           놓는다. 뜻이 정반대다.

⚠ 이 파일을 쓰다가 **없는 드리프트를 하나 만들어 냈다**. core가 score
내림차순 순서를 넘긴다는 것까지는 맞았지만, 뷰어가 쓰는 `DATA.signals`를
파이썬 **선언 순서**와 견주어 「1년 4종 55건이 갈린다」고 적었다. 실제로는
`export_tool_data.py`가 그 배열을 이미 score 내림차순으로 내보내고 있어
**차이가 없었다**. 재는 대상은 소스가 아니라 **배포되는 산출물**이어야 한다.
그 암묵적 결합(뷰어 헤드라인이 export의 정렬에 통째로 기댄다)은 아무도
잠그고 있지 않았으므로 아래 `test_export가_헤드라인_순서를_유지한다`로 남긴다.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest

from dart_risk_mcp.core import qualifiers as _q
from dart_risk_mcp.core import signals as _sig
from dart_risk_mcp.core.dart_client import (
    _fold_corp_name,
    _looks_like_nation,
    classify_holder_type,
    classify_outflow_relation,
    parse_outflow_detail,
    strip_holder_suffix,
)

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = _ROOT / "docs" / "tool" / "index.html"
_JSON = _ROOT / "docs" / "tool" / "signals-data.json"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node가 없으면 뷰어 쪽을 돌릴 수 없다"
)


def _cut(html: str, head: str) -> str:
    """`head`로 시작하는 함수/상수 선언 하나를 중괄호 균형으로 잘라 온다."""
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


# 이식본 이름은 core와 다르다(스네이크→카멜, 밑줄 제거). 짝을 여기 명시한다.
_FUNCS = (
    "function foldCorpName(",
    "function looksLikeNation(",
    "function stripHolderSuffix(",
    "function classifyHolderType(",
    "function classifyOutflowRelation(",
    "function parseOutflowDetail(",
    "function pickHeadline(",
)


def _cut_decl(html: str, name: str) -> "str | None":
    """`const NAME = …;` 선언 하나를 잘라 온다. 한 줄이면 그 줄, 아니면 중괄호 균형.

    이식본이 기대는 보조 상수(정규식·표)를 손으로 나열하면 뷰어가 바뀔 때마다
    이 파일이 낡는다 — 필요한 것만 이름을 보고 끌어온다.
    """
    m = re.search(r"^(?:const|let|var)\s+" + re.escape(name) + r"\s*=", html, re.M)
    if not m:
        return None
    i = m.start()
    eol = html.index("\n", i)
    line = html[i:eol]
    if line.rstrip().endswith(";") and line.count("{") == line.count("}"):
        return line
    return _cut(html, html[i:m.end()])


def _viewer(calls: list, _depth: int = 0) -> list:
    """`[[함수명, 인자...], ...]`를 뷰어 구현으로 돌려 결과 배열을 받는다."""
    html = _HTML.read_text(encoding="utf-8")
    src = "\n".join(_cut(html, f) for f in _FUNCS)
    js = (
        f"const DATA = {_JSON.read_text(encoding='utf-8')};\n"
        'const TIER_OBSERVED = "observed";\n'
        f"{src}\n"
        f"const CALLS = {json.dumps(calls, ensure_ascii=False)};\n"
        "const FN = {foldCorpName, looksLikeNation, stripHolderSuffix,\n"
        "  classifyHolderType, classifyOutflowRelation, parseOutflowDetail,\n"
        "  pickHeadline};\n"
        "const out = CALLS.map(([n, ...a]) => FN[n](...a));\n"
        "console.log(JSON.stringify(out));\n"
    )
    # 이식본이 기대는 보조 선언(정규식·표)은 미리 나열하지 않고, node가
    # 이름을 알려줄 때마다 끌어온다 — 손으로 적으면 뷰어가 바뀔 때 낡는다.
    pre = ""
    for _ in range(24):
        r = _node(pre + js)
        if r.returncode == 0:
            return json.loads(r.stdout)
        m = re.search(r"ReferenceError: (\w+) is not defined", r.stderr or "")
        if not m:
            raise AssertionError(f"node 실패:\n{(r.stderr or '')[:1500]}")
        d = _cut_decl(html, m.group(1))
        assert d is not None, (
            f"뷰어에서 {m.group(1)} 선언을 찾지 못했다 — 이식본이 함수 밖의 "
            "무언가에 기대고 있다"
        )
        pre = d + "\n" + pre
    raise AssertionError("보조 선언을 24번 끌어와도 안 돈다")


def _node(code: str):
    tf = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    tf.write(code)
    tf.close()
    try:
        return subprocess.run([shutil.which("node"), tf.name],
                              capture_output=True, text=True, encoding="utf-8")
    finally:
        os.unlink(tf.name)


# ── 순수 문자열 함수 ──────────────────────────────────────────────────────

_NAMES = [
    "㈜한국파일", "(주)한국파일", "주식회사 한국파일", "한국파일 주식회사",
    "로아앤코홀딩스", "에이프로젠", "김철수 외 3인", "박영희외2명",
    "이승만 외 22", "푸른 유아이엘 신기술조합 제1호", "유한회사 대성",
    "SK리츠", "미래에셋글로벌리츠", "Dunamu Inc.", "",
]
_NATIONS = ["대한민국", "미국", "중국", "일본", "KOREA", "JIANGSU",
            "Dunamu Inc.", "Laftel", "가칭", "예정", "케이맨제도", ""]
_RELATIONS = [
    "계열회사", "종속회사", "특수관계인", "타인", "최대주주", "관계회사",
    "특수관계 없음", "최대주주 아님", "해당사항 없음", "자회사", "", "-",
]


def test_문자열_함수_5종이_같다():
    calls, expect = [], []
    for n in _NAMES:
        calls.append(["foldCorpName", n]); expect.append(_fold_corp_name(n))
        calls.append(["stripHolderSuffix", n]); expect.append(strip_holder_suffix(n))
        calls.append(["classifyHolderType", n]); expect.append(classify_holder_type(n))
    for n in _NATIONS:
        calls.append(["looksLikeNation", n]); expect.append(_looks_like_nation(n))
    for r in _RELATIONS:
        calls.append(["classifyOutflowRelation", r])
        expect.append(classify_outflow_relation(r))

    got = _viewer(calls)
    bad = [(c, e, g) for c, e, g in zip(calls, expect, got) if e != g]
    assert not bad, "core와 뷰어가 갈린다:\n" + "\n".join(
        f"  {c[0]}({c[1]!r}) core={e!r} 뷰어={g!r}" for c, e, g in bad[:12]
    )


# ── 원문 파서 ─────────────────────────────────────────────────────────────
#
# ⚠ **두 구현은 같은 문서의 서로 다른 표현을 먹는다** — core는
# `fetch_document_text`의 평문, 뷰어는 `/api/doc`(=`fetch_disclosure_full`)의
# 마크다운 표다. 같은 문자열을 양쪽에 먹이면 파서 차이가 아니라 **입력 차이**를
# 재게 된다(이 함정에 실제로 한 번 걸렸다). 그래서 각자의 표현을 따로 준다.

# core 쪽은 `fetch_document_text`가 주는 대로 **한 줄로 접힌** 평문이다
# (파서의 관계 정규식이 다음 절 번호 `2.`를 뒤보기로 요구한다).
_OUTFLOW_PLAIN = (
    "금전대여 결정 1. 대여 상대방 성명(법인명) 주식회사 한국파일 "
    "- 회사와의 관계 종속회사 "
    "2. 대여 내역 대여금액(원) 5,000,000,000 자기자본대비(%) 12.4"
)

_OUTFLOW_MD = (
    "| 성명(법인명) | 주식회사 한국파일 |\n"
    "| (회사와의 관계) | 종속회사 |\n"
    "| 대여금액(원) | 5,000,000,000 |\n"
    "| 자기자본대비(%) | 12.4 |\n"
)


def _num(v):
    """`12.4`(float)와 `"12.4"`(string)를 같은 값으로 본다 — 표기 계층이 다르다."""
    try:
        return float(str(v).replace(",", "") or 0)
    except ValueError:
        return str(v)


def test_자금유출_파서가_같은_사실을_읽는다():
    core = parse_outflow_detail(_OUTFLOW_PLAIN)
    view = _viewer([["parseOutflowDetail", _OUTFLOW_MD]])[0]
    for ck, vk in [("counterparty", "counterparty"), ("relation", "relation")]:
        assert (core.get(ck) or "") == (view.get(vk) or ""), (
            f"{ck}: core={core.get(ck)!r} 뷰어={view.get(vk)!r}"
        )
    for ck, vk in [("amount", "amount"), ("equity_ratio", "equityRatio")]:
        assert _num(core.get(ck)) == _num(view.get(vk)), (
            f"{ck}: core={core.get(ck)!r} 뷰어={view.get(vk)!r}"
        )


def test_자기자본대비를_실제로_읽는다():
    """이 값이 뷰어에 **아예 없었다**. 빈 값끼리 같아 보이지 않게 못 박는다."""
    assert _num(parse_outflow_detail(_OUTFLOW_PLAIN)["equity_ratio"]) == 12.4
    assert _num(_viewer([["parseOutflowDetail", _OUTFLOW_MD]])[0]["equityRatio"]) == 12.4


# ── 헤드라인 ──────────────────────────────────────────────────────────────


def _core_order():
    return [s["key"] for s in sorted(_sig.SIGNAL_TYPES, key=lambda x: -x["score"])]


def test_export가_헤드라인_순서를_유지한다():
    """뷰어 헤드라인은 `DATA.signals`의 **배열 순서**에 통째로 기댄다.

    그 순서가 `server.py`의 `_order`(score 내림차순)와 같아야 MCP와 뷰어가
    같은 신호를 대표로 내세운다. export가 이 배열을 카테고리순·이름순으로
    바꾸는 순간 뷰어 헤드라인이 **조용히** 달라진다 — 값이 아니라 순서라
    diff에도 잘 안 보인다. 여기서 못 박는다.

    ⚠ score 값 자체는 여전히 내보내지 않는다(v0.8.5).
    """
    data = json.loads(_JSON.read_text(encoding="utf-8"))
    assert [s["key"] for s in data["signals"]] == _core_order(), (
        "signals-data.json의 신호 순서가 server.py의 헤드라인 순서와 다르다 — "
        "export 정렬을 되돌리거나 `pick_headline` 배선을 명시적으로 바꾸세요"
    )
    for s in data["signals"]:
        assert "score" not in s and "severity" not in s, "점수·등급이 새어 나갔다"


def test_헤드라인_선택이_코퍼스_전체에서_같다():
    """945종 실측 제목 중 후보가 2개 이상인 것만 골라 대조한다.

    지금은 갈리지 않는다 — 위 `test_export가_헤드라인_순서를_유지한다`가
    지키는 순서 일치가 깨지면 여기서도 드러난다.
    """
    rows = json.loads(
        (_ROOT / "tests" / "fixtures" / "corpus" / "signal_titles_365d.json")
        .read_text(encoding="utf-8")
    )["titles"]

    order = _core_order()
    calls, expect, seen = [], [], []
    for row in rows:
        title = row["nm"]
        sigs = _sig.match_signals(title)
        if not sigs:
            continue
        qs = _q.qualify_signals(sigs, _q.parse_report_name(title), {})
        cands = [q for q in qs
                 if q.tier == _q.TIER_OBSERVED
                 and q.key not in _sig.AMBIGUOUS_SIGNAL_KEYS]
        if len(cands) < 2:
            continue
        head = _q.pick_headline(qs, order)
        calls.append(["pickHeadline", [
            {"key": q.key, "label": q.label, "tier": q.tier} for q in qs
        ]])
        expect.append(head.key if head else None)
        seen.append(title)

    assert calls, "후보 2개 이상인 제목을 하나도 못 찾았다 — 검사가 헛돈다"
    got = [g["key"] if g else None for g in _viewer(calls)]
    bad = [(t, e, g) for t, e, g in zip(seen, expect, got) if e != g]
    assert not bad, "헤드라인이 갈린다:\n" + "\n".join(
        f"  core={e} 뷰어={g}  {t[:60]}" for t, e, g in bad[:10]
    )


def test_목록에_없는_키는_뒤로_간다():
    """`indexOf`의 -1은 **맨 앞**이라 뜻이 정반대다 — 그 회귀를 막는다."""
    src = _cut(_HTML.read_text(encoding="utf-8"), "function pickHeadline(")
    assert "indexOf" not in src, (
        "pickHeadline이 다시 indexOf를 쓴다 — 모르는 키가 헤드라인이 된다"
    )
