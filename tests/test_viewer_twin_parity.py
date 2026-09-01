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
    classify_mezzanine_filing,
    mezzanine_overhang,
    parse_mezzanine_row,
    summarize_mezzanine,
    _is_amended_document,
    _issuance_date8,
    _looks_like_nation,
    classify_holder_type,
    classify_issuance_type,
    classify_outflow_relation,
    match_affiliate_row,
    pick_common_stock_total,
    parse_outflow_detail,
    strip_holder_suffix,
    summarize_affiliate_stake,
    summarize_dilution,
)
from dart_risk_mcp.server import (
    _find_latest_control_change,
    _format_affiliate_stake_line,
    _is_asset_disposal_title,
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
    # 2026-08-31 추가 — 이름으로 짝지어지는 46쌍 중 **양쪽을 함께 검사하는
    # 테스트가 없던** 6쌍. `test_viewer_affiliate_conduit_js.py`는 node를
    # 돌리지만 core를 임포트하지 않아 JS를 고정 기대값과만 대조한다(패리티가
    # 아니다). 나머지 둘은 양쪽 테스트가 각자 따로 있었다.
    "function matchAffiliateRow(",
    "function summarizeAffiliateStake(",
    "function formatAffiliateStakeLine(",
    "function findLatestControlChange(",
    "function isAmendedDocument(",
    "function isAssetDisposalTitle(",
    # 2026-08-31 희석 추적 이식 — 위 가드가 즉시 신고해 함께 넣었다.
    "function classifyIssuanceType(",
    "function issuanceDate8(",
    "function pickCommonStockTotal(",
    "function summarizeDilution(",
    # 2026-09-01 메자닌 이식 — 위 가드가 즉시 6쌍을 신고했다.
    "function classifyMezzanineFiling(",
    "function parseMezzanineRow(",
    "function summarizeMezzanine(",
    "function mezzanineOverhang(",
)

# 이름은 `_FUNCS`에서 뽑는다 — 예전에는 아래 JS의 `const FN = {...}`에도 손으로
# 적어야 해서 한 곳만 고치면 조용히 빠졌다.
_FN_NAMES = tuple(f[len("function "):-1] for f in _FUNCS)


def _cut_decl(html: str, name: str) -> "str | None":
    """`const NAME = …;` 선언 하나를 잘라 온다. 한 줄이면 그 줄, 아니면 중괄호 균형.

    이식본이 기대는 보조 상수(정규식·표)를 손으로 나열하면 뷰어가 바뀔 때마다
    이 파일이 낡는다 — 필요한 것만 이름을 보고 끌어온다.
    """
    m = re.search(r"^(?:const|let|var)\s+" + re.escape(name) + r"\s*=", html, re.M)
    if not m:
        # 보조 선언이 늘 `const`인 것은 아니다 — `affiliateRatio`·`affiliateInt`는
        # 함수 선언이라 위 정규식이 못 찾았고, 그러면 「이식본이 함수 밖의
        # 무언가에 기댄다」는 엉뚱한 실패가 났다(드리프트로 오인하기 쉽다).
        if re.search(r"^function\s+" + re.escape(name) + r"\s*\(", html, re.M):
            return _cut(html, f"function {name}(")
        return None
    i = m.start()
    eol = html.index("\n", i)
    line = html[i:eol]
    if line.rstrip().endswith(";") and line.count("{") == line.count("}"):
        return line
    # ⚠ `_cut`은 **중괄호만** 균형을 본다. 여러 줄 **배열**(`const X = [` …
    #   `];`)을 만나면 다음 `}`까지 훑어 **뒤따르는 선언까지 삼킨다** — 실제로
    #   희석 상수를 이식할 때 `ISSUANCE_DILUTIVE`를 자르다 `ISSUANCE_DECREASE`를
    #   함께 가져와 node가 "already been declared"로 죽었다.
    #   괄호 세 종류를 함께 세고 `;`에서 끝낸다.
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
    return _cut(html, html[i:m.end()])


def _viewer(calls: list, _depth: int = 0) -> list:
    """`[[함수명, 인자...], ...]`를 뷰어 구현으로 돌려 결과 배열을 받는다."""
    html = _HTML.read_text(encoding="utf-8")
    src = "\n".join(_cut(html, f) for f in _FUNCS)
    js = (
        f"const DATA = {_JSON.read_text(encoding='utf-8')};\n"
        'const TIER_OBSERVED = "observed";\n'
        # 뷰어는 부팅 때 `AMEND_RE = new RegExp(DATA.amendment_pattern)`으로
        # 만든다(`let`으로 여러 개를 한 줄에 선언해 `_cut_decl`이 못 집는다).
        # 여기서 같은 방식으로 만들어 준다 — 상수를 손으로 베끼면 배포본과
        # 갈린다. ⚠ core는 `re.match`(앞부분 고정), 뷰어는 `RegExp.test`
        # (아무 데나 검색)라 **패턴이 `^`로 시작할 때만** 두 의미가 같다.
        # 그 앵커는 아래 `test_정정_패턴이_앵커를_유지한다`가 지킨다.
        'const AMEND_RE = new RegExp(DATA.amendment_pattern);\n'
        f"{src}\n"
        f"const CALLS = {json.dumps(calls, ensure_ascii=False)};\n"
        f"const FN = {{{', '.join(_FN_NAMES)}}};\n"
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


# ── 2026-08-31 추가: 패리티가 없던 6쌍 ────────────────────────────────────
#
# 이름으로 짝지어지는 46쌍을 전수로 세어 **양쪽을 함께 검사하는 테스트가 없는**
# 것을 골랐다. CLAUDE.md는 「남은 6쌍」으로 `parse_control_change_detail`·
# `strip_holder_suffix`·`classify_holder_type`·`_pick_account`·`pick_headline`을
# 들었지만, 그건 2026-08-28 기록이고 그 뒤로 대부분 덮였다 — 실제로 비어 있던
# 것은 아래 여섯이다(문서를 믿지 않고 다시 셌다).

# 타법인 출자현황 행 — 필드명은 DART 응답 그대로다
_AFFIL_ROWS = [
    {"inv_prm": "주식회사 한국파일", "frst_acqs_de": "2023.09.15",
     "bsis_blce_qota_rt": "46.3", "trmend_blce_qota_rt": "62.4",
     "incrs_dcrs_acqs_dsps_amount": "1,200,000,000",
     "recent_bsns_year_fnnr_sttus_thstrm_ntpf": "-4,969,000,000",
     "invstmnt_purps": "경영참여"},
    {"inv_prm": "(주)한국파일", "frst_acqs_de": "-",
     "bsis_blce_qota_rt": "-", "trmend_blce_qota_rt": "-",
     "incrs_dcrs_acqs_dsps_amount": "-",
     "recent_bsns_year_fnnr_sttus_thstrm_ntpf": "-", "invstmnt_purps": ""},
    {"inv_prm": "STX리조트㈜", "frst_acqs_de": "2007-12-18",
     "bsis_blce_qota_rt": "100.00", "trmend_blce_qota_rt": "100.00",
     "incrs_dcrs_acqs_dsps_amount": "0",
     "recent_bsns_year_fnnr_sttus_thstrm_ntpf": "3,737,000,000",
     "invstmnt_purps": "경영참여"},
]


def test_출자현황_행_매칭이_같다():
    """법인 표기(㈜·(주)·주식회사) 차이를 양쪽이 같게 접는지."""
    names = ["주식회사 한국파일", "한국파일", "㈜한국파일", "(주) 한국파일",
             "STX리조트", "STX리조트 주식회사", "없는회사", "", "   "]
    calls = [["matchAffiliateRow", _AFFIL_ROWS, n] for n in names]
    got = _viewer(calls)
    for n, g in zip(names, got):
        c = match_affiliate_row(_AFFIL_ROWS, n)
        assert (c or {}).get("inv_prm", None) == (g or {}).get("inv_prm", None), (
            f"매칭이 갈린다: {n!r} core={(c or {}).get('inv_prm')} 뷰어={(g or {}).get('inv_prm')}")


def test_출자현황_요약이_같다():
    """미기재('-')·날짜 구분자 두 형태('.'와 '-')를 양쪽이 같게 읽는지."""
    calls = [["summarizeAffiliateStake", r] for r in _AFFIL_ROWS]
    got = _viewer(calls)
    # 뷰어는 camelCase 키를 쓴다 — 같은 사실을 가리키는 이름끼리 맞춘다
    keymap = {"first_acquired": "firstAcquired", "stake_begin": "stakeBegin",
              "stake_end": "stakeEnd", "added_amount": "addedAmount",
              "recent_net_profit": "recentNetProfit", "purpose": "purpose"}
    for row, g in zip(_AFFIL_ROWS, got):
        c = summarize_affiliate_stake(row)
        for ck, vk in keymap.items():
            assert c[ck] == g.get(vk), (
                f"{row['inv_prm']}의 {ck}가 갈린다: core={c[ck]!r} 뷰어={g.get(vk)!r}")


def test_출자현황_문구가_같다():
    """⚠ 금액 표기는 **의도된 차이**라 비교 대상이 아니다.

    core `_format_amount`는 조원·콤마·반올림, 뷰어 `fmtKRW`는 억 단위까지만
    쓴다(CLAUDE.md에 의도된 차이로 기록). 그래서 「피출자사 최근 순이익 …」
    조각을 뺀 나머지 — 최초취득·지분 증감 — 만 대조한다. 그 둘이 갈리면
    화면이 서로 다른 **사실**을 말하는 것이고, 금액 표기 차이는 같은 사실의
    다른 반올림이다.
    """
    stakes = [summarize_affiliate_stake(r) for r in _AFFIL_ROWS]
    js_stakes = _viewer([["summarizeAffiliateStake", r] for r in _AFFIL_ROWS])
    got = _viewer([["formatAffiliateStakeLine", s] for s in js_stakes])

    def facts(line: str) -> list:
        return [p for p in line.split(" · ") if not p.startswith("피출자사")]

    for row, s, g in zip(_AFFIL_ROWS, stakes, got):
        c = _format_affiliate_stake_line(s)
        assert facts(c) == facts(g), (
            f"{row['inv_prm']}의 사실 조각이 갈린다:\n  core={c}\n  뷰어={g}")


def test_최대주주변경_선택이_같다():
    """어느 공시를 열지가 갈리면 두 화면이 **다른 최대주주**를 보여 준다."""
    discs = [
        {"report_nm": "최대주주변경", "rcept_dt": "20260709", "rcept_no": "A"},
        {"report_nm": "[기재정정]최대주주변경", "rcept_dt": "20260810", "rcept_no": "B"},
        {"report_nm": "최대주주변경을수반하는주식양수도계약체결", "rcept_dt": "20260820",
         "rcept_no": "C"},
        {"report_nm": "최대주주 변경", "rcept_dt": "20260715", "rcept_no": "D"},
        {"report_nm": "주요사항보고서(유상증자결정)", "rcept_dt": "20260901", "rcept_no": "E"},
        # 같은 날짜 두 건 — 동률 처리가 갈리는지 본다
        {"report_nm": "최대주주변경", "rcept_dt": "20260715", "rcept_no": "F"},
    ]
    cases = [discs, discs[:1], [], [discs[2]], [discs[4]]]
    got = _viewer([["findLatestControlChange", c] for c in cases])
    for c, g in zip(cases, got):
        core = _find_latest_control_change(c)
        assert (core or {}).get("rcept_no") == (g or {}).get("rcept_no"), (
            f"고른 공시가 갈린다: core={(core or {}).get('rcept_no')} "
            f"뷰어={(g or {}).get('rcept_no')}")


def test_정정신고_원문_판정이_같다():
    """세 파서 전체를 빈 결과로 떨어뜨리는 게이트다 — 갈리면 한쪽이 **정정 전**
    값을 현재 값으로 보여 준다."""
    texts = [
        "한솔제지/벌금등의부과/(2026.06.12)벌금등의부과 정정신고(보고) 정정일자 2026-06-12",
        "파두/파생상품거래손실발생/ 1. 파생상품 거래계약의 종류 및 내용",
        "정정신고 (보고) 공백 변형",
        "앞쪽 600자를 넘긴 뒤에 나오는 정정일자는 못 본다 " + ("가" * 700) + " 정정일자",
        "",
    ]
    got = _viewer([["isAmendedDocument", t] for t in texts])
    for t, g in zip(texts, got):
        assert _is_amended_document(t) == g, (
            f"정정 판정이 갈린다: core={_is_amended_document(t)} 뷰어={g}  {t[:40]!r}")


def test_자산처분_제목_판정이_같다():
    r"""어느 파서를 쓸지 가르는 게이트다 — 갈리면 한쪽이 상대방을 못 읽는다.

    ⚠ core는 `replace(" ", "")`(공백만), 뷰어는 `replace(/\s/g, "")`(줄바꿈·탭
    포함)라 **공백 종류가 다르면 갈릴 수 있다**. DART 제목에 개행이 섞여 오는
    사례가 이 레포에 여러 번 기록돼 있어(`ofcps`·`nm`) 그 입력을 넣어 본다.
    """
    titles = [
        "유형자산처분결정",
        "주요사항보고서(유형자산양도결정)",
        "비유동자산 처분결정(자율공시)",
        "특수관계인에 대한 자산양도",
        "영업양도결정",
        "타법인주식및출자증권양수결정",
        "유형자산\n처분결정",      # 개행
        "유형자산\t처분결정",      # 탭
        "",
    ]
    got = _viewer([["isAssetDisposalTitle", t] for t in titles])
    bad = [(t, _is_asset_disposal_title(t), g)
           for t, g in zip(titles, got) if _is_asset_disposal_title(t) != g]
    assert not bad, "자산처분 제목 판정이 갈린다:\n" + "\n".join(
        f"  core={c} 뷰어={v}  {t!r}" for t, c, v in bad)


def test_정정_패턴이_앵커를_유지한다():
    """core는 `re.match`(앞부분 고정), 뷰어는 `RegExp.test`(아무 데나 검색)다.

    두 의미가 같은 것은 **패턴이 `^`로 시작하기 때문**이다. 앵커가 빠지면
    「최대주주변경[기재정정]」처럼 태그가 중간에 있는 제목에서 뷰어만 정정으로
    보고, `findLatestControlChange`가 다른 공시를 고른다 — 두 화면이 **다른
    최대주주**를 보여 준다. 지금은 갈리지 않는다는 것을 확인하고 잠근다.
    """
    pat = json.loads(_JSON.read_text(encoding="utf-8"))["amendment_pattern"]
    assert pat.startswith("^"), (
        "배포 패턴이 앵커를 잃었다 — 뷰어의 test()가 제목 중간의 태그도 잡는다")
    assert pat == _sig._AMENDMENT_RE.pattern, "배포본과 core 패턴이 갈렸다"
    for t in ("[기재정정]최대주주변경", "최대주주변경[기재정정]",
              "주요사항보고서(최대주주변경)", "회사합병[첨부추가] 후속"):
        assert _sig.is_amendment_disclosure(t) == bool(re.search(pat, t)), (
            f"core(match)와 뷰어(test)가 갈린다: {t!r}")


def test_이름으로_짝지어지는_쌍은_모두_잠겨_있다():
    """**이 파일이 생긴 이유** — 쌍둥이가 늘어도 아무도 패리티를 강제하지 않았다.

    core를 고쳐도 뷰어는 따라오지 않고, 사용자가 보는 것은 뷰어다. 그래서
    이름으로 짝지어지는 쌍을 전수로 세어, 양쪽을 함께 검사하는 테스트가 없는
    것이 생기면 여기서 신고한다.

    ⚠ **모든 쌍을 이 파일이 들어야 하는 것은 아니다** — 한정층 5종은
    `test_viewer_core_parity.py`가 945종 코퍼스로 이미 잠그고, 회전율·취득
    파서 등은 상위 함수를 대조하는 전용 파일이 있다. 그런 간접 커버는
    `_COVERED_ELSEWHERE`에 근거와 함께 적는다. 이름만 닮고 계약이 다른 쌍
    (`_pick_account` ↔ `pickAccount`)도 여기에 적는다.
    """
    import ast

    # 다른 파일이 잠그는 쌍 — 근거를 함께 적는다(비우면 이 테스트가 무력해진다)
    _COVERED_ELSEWHERE = {
        # 한정층 계열: 945종 코퍼스 전수 대조
        "_adjusted_label": "test_viewer_core_parity.py",
        "_demotion_reason": "test_viewer_core_parity.py",
        "_direction_note": "test_viewer_core_parity.py",
        "_tail_of": "test_viewer_core_parity.py",
        "_is_amendment_tag": "test_viewer_core_parity.py",
        # 상위 함수를 대조하는 전용 파일이 내부까지 함께 덮는다
        "_simple_metric": "test_viewer_turnover_parity.py",
        "_cost_based_metric": "test_viewer_turnover_parity.py",
        "_turnover_yoy_pct": "test_viewer_turnover_parity.py",
        "_split_issuer_nation": "test_acquisition_parser_parity.py",
        "_affiliate_int": "이 파일의 summarizeAffiliateStake 대조에 포함",
        "_affiliate_ratio": "이 파일의 summarizeAffiliateStake 대조에 포함",
        "_mzn_num": "이 파일의 parseMezzanineRow 대조에 포함",
        "_mzn_int": "이 파일의 parseMezzanineRow 대조에 포함",
        "_mzn_date": "이 파일의 parseMezzanineRow 대조에 포함",
    }

    core_funcs: dict = {}
    for f in list((_ROOT / "dart_risk_mcp" / "core").glob("*.py")) + \
             [_ROOT / "dart_risk_mcp" / "server.py"]:
        for n in ast.walk(ast.parse(f.read_text(encoding="utf-8"))):
            if isinstance(n, ast.FunctionDef):
                core_funcs.setdefault(n.name, f.name)

    html = _HTML.read_text(encoding="utf-8")
    viewer = set(re.findall(r"function\s+([A-Za-z_]\w*)\s*\(", html))
    viewer |= set(re.findall(r"(?:const|let)\s+([A-Za-z_]\w*)\s*=\s*(?:async\s*)?\(",
                             html))
    tests = {p.name: p.read_text(encoding="utf-8")
             for p in (_ROOT / "tests").glob("*.py")}

    def camel(s: str) -> str:
        parts = s.lstrip("_").split("_")
        return parts[0] + "".join(p[:1].upper() + p[1:] for p in parts[1:])

    missing = []
    for cn in sorted(core_funcs):
        vn = camel(cn)
        if vn not in viewer and cn not in viewer:
            continue
        vn = vn if vn in viewer else cn
        if cn in _COVERED_ELSEWHERE:
            continue
        if any(cn in body and vn in body for body in tests.values()):
            continue
        missing.append(f"{cn} ↔ {vn}  [{core_funcs[cn]}]")

    assert not missing, (
        "패리티 테스트가 없는 쌍둥이가 생겼다 — core를 고쳐도 뷰어는 "
        "따라오지 않고, 사용자가 보는 것은 뷰어다:\n  " + "\n  ".join(missing) +
        "\n이 파일에 대조를 추가하거나, 다른 파일이 덮는다면 그 근거를 "
        "_COVERED_ELSEWHERE에 적어라."
    )


# ── 희석 추적 (2026-08-31 이식) ──────────────────────────────────────────
#
# 위 `test_이름으로_짝지어지는_쌍은_모두_잠겨_있다`가 이식 직후 이 넷을 즉시
# 신고했다 — 가드가 설계대로 동작한 첫 사례다.

_ISSUANCE_STYLES = [
    # 15개사 실측 형태(빈도순)
    "전환권행사", "신주인수권행사", "주식매수선택권행사",
    "유상증자(제3자배정)", "유상증자(주주배정)", "유상증자(주주우선공모)",
    "유상증자(일반공모)", "무상증자", "무상감자", "주식배당", "주식분할",
    # 경계
    "유상증자", "이익소각", "출자전환", "교환권행사", "-", "", "  ",
]


def test_증감_형태_분류가_같다():
    """⚠ **비례 배분을 희석으로 세는지**가 갈리면 화면의 뜻이 반대가 된다."""
    calls = [["classifyIssuanceType", s] for s in _ISSUANCE_STYLES]
    got = _viewer(calls)
    bad = [(s, classify_issuance_type(s), g)
           for s, g in zip(_ISSUANCE_STYLES, got) if classify_issuance_type(s) != g]
    assert not bad, "형태 분류가 갈린다:\n" + "\n".join(
        f"  {s!r} core={c} 뷰어={v}" for s, c, v in bad)


def test_증감_일자_파싱이_같다():
    raws = ["2023.08.11", "2023-08-11", "2023.8.1", "20230811", "-", "",
            "2023/08/11", "2023.08", "abc"]
    got = _viewer([["issuanceDate8", r] for r in raws])
    bad = [(r, _issuance_date8(r), g)
           for r, g in zip(raws, got) if _issuance_date8(r) != g]
    assert not bad, f"일자 파싱이 갈린다: {bad}"


def test_보통주_발행총수_선택이_같다():
    """「합계」·「비고」를 잡으면 분모가 커진다 — 20/20 회사에 섞여 온다."""
    cases = [
        [{"se": "보통주", "istc_totqy": "88,616,044"},
         {"se": "우선주", "istc_totqy": "-"},
         {"se": "합계", "istc_totqy": "99,999,999"},
         {"se": "비고", "istc_totqy": "-"}],
        [{"se": "의결권 있는 주식", "istc_totqy": "230,960,969"},   # 셀트리온
         {"se": "합계", "istc_totqy": "230,960,969"}],
        [{"se": "보통주식", "istc_totqy": "16,193,835"},            # 두산
         {"se": "종류주식", "istc_totqy": "4,889,500"},
         {"se": "합계", "istc_totqy": "21,083,335"}],
        [{"se": "합계", "istc_totqy": "100"}],                      # 못 고름
        [],
    ]
    got = _viewer([["pickCommonStockTotal", c] for c in cases])
    for c, g in zip(cases, got):
        assert pick_common_stock_total(c) == g, (
            f"발행총수 선택이 갈린다: core={pick_common_stock_total(c)} 뷰어={g}")


def test_희석_집계가_같다():
    """자리 행·창 밖·미분류까지 같은 값이 나오는지."""
    rows = [
        {"isu_dcrs_de": "2025.06.01", "isu_dcrs_stle": "전환권행사",
         "isu_dcrs_stock_knd": "보통주", "isu_dcrs_qy": "1,000,000"},
        {"isu_dcrs_de": "2025.07.01", "isu_dcrs_stle": "무상증자",
         "isu_dcrs_stock_knd": "보통주", "isu_dcrs_qy": "500,000"},
        {"isu_dcrs_de": "2019.01.01", "isu_dcrs_stle": "유상증자(제3자배정)",
         "isu_dcrs_stock_knd": "보통주", "isu_dcrs_qy": "9,000,000"},   # 창 밖
        {"isu_dcrs_de": "2023.12.28", "isu_dcrs_stle": "-",
         "isu_dcrs_stock_knd": "보통주", "isu_dcrs_qy": "73,887,750"},  # 미분류
        {"isu_dcrs_de": "-", "isu_dcrs_stle": "-",
         "isu_dcrs_stock_knd": "-", "isu_dcrs_qy": "-"},                # 자리 행
        {"isu_dcrs_de": "-", "isu_dcrs_stle": "전환권행사",
         "isu_dcrs_stock_knd": "보통주", "isu_dcrs_qy": "7"},           # 일자만 없음
    ]
    totals = [{"se": "보통주", "istc_totqy": "10,000,000"},
              {"se": "합계", "istc_totqy": "99,999,999"}]
    since = "20230101"
    got = _viewer([["summarizeDilution", rows, totals, since]])[0]
    core = summarize_dilution(rows, totals, since=since)

    for k_core, k_js in (("buckets", "buckets"), ("common_total", "commonTotal"),
                         ("earliest", "earliest"), ("latest", "latest"),
                         ("undated", "undated"), ("blank", "blank"),
                         ("in_window", "inWindow")):
        assert core[k_core] == got[k_js], (
            f"{k_core}가 갈린다: core={core[k_core]!r} 뷰어={got[k_js]!r}")
    assert core["dilutive_pct"] == pytest.approx(got["dilutivePct"])
    assert {k: (v["count"], v["shares"], v["kind"])
            for k, v in core["by_type"].items()} == \
           {k: (v["count"], v["shares"], v["kind"]) for k, v in got["byType"].items()}


def test_뷰어도_비례_배분을_희석으로_세지_않는다():
    """core 쪽 안전장치(`test_dilution.py`)의 뷰어 짝 — 뜻이 반대가 되는 자리다."""
    got = _viewer([["classifyIssuanceType", s]
                   for s in ("무상증자", "주식분할", "주식배당")])
    assert got == ["proportional"] * 3


# ── 메자닌 (2026-09-01 이식) ─────────────────────────────────────────────

_MZN_TITLES = [
    "주요사항보고서(전환사채권발행결정)", "주요사항보고서(신주인수권부사채권발행결정)",
    "교환사채권발행결정", "전환가액의조정", "전환가액의조정 (제38회차)",
    "신주인수권행사가액의조정(제37회차)", "전환가액ㆍ신주인수권행사가액ㆍ교환가액의조정(안내공시)",
    "전환청구권행사 (제3회차)", "전환청구권ㆍ신주인수권ㆍ교환청구권행사",
    "전환사채(해외전환사채포함)발행후만기전사채취득", "주요사항보고서(자기전환사채만기전취득결정)",
    "주요사항보고서(자기전환사채매도결정)", "[기재정정]주요사항보고서(자기전환사채매도결정)",
    "유상증자또는주식관련사채등의발행결과(자율공시)",
    # 메자닌이 아닌 것 — 「사채」로 넓히면 딸려온다
    "주요사항보고서(단기사채발행결정)", "회사채발행결정", "최대주주변경", "",
]


def test_메자닌_공시_분류가_같다():
    got = _viewer([["classifyMezzanineFiling", t] for t in _MZN_TITLES])
    bad = []
    for t, g in zip(_MZN_TITLES, got):
        c = classify_mezzanine_filing(t)
        if (c is None) != (g is None):
            bad.append((t, c, g)); continue
        if c and (c["category"] != g["category"] or c["round"] != g["round"]
                  or c["is_amendment"] != g["is_amendment"]):
            bad.append((t, c, g))
    assert not bad, "분류가 갈린다:\n" + "\n".join(
        f"  {t!r}\n    core={c}\n    뷰어={g}" for t, c, g in bad[:5])


_MZN_CB = {
    "rcept_no": "20250115000001", "bd_tm": "4", "bd_fta": "40,000,000,000",
    "bd_intr_ex": "7.5", "bd_intr_sf": "11.2", "bd_mtd": "2028년 01월 15일",
    "bdis_mthn": "사모", "pymd": "2025년 01월 15일", "cv_prc": "1,670",
    "cvisstk_cnt": "23,952,095", "cvisstk_tisstk_vs": "36.55",
    "cvrqpd_bgd": "2026년 01월 15일", "cvrqpd_edd": "2027년 12월 15일",
    "act_mktprcfl_cvprc_lwtrsprc": "1,169", "rmislmt_lt70p": "-",
    "fdpp_op": "30,000,000,000", "fdpp_dtrp": "10,000,000,000",
}
_MZN_BW = {**_MZN_CB, "rcept_no": "b", "ex_prc": "4,293",
           "nstk_isstk_cnt": "2,329,373", "nstk_isstk_tisstk_vs": "18.5",
           "expd_bgd": "2025년 09월 11일", "expd_edd": "2027년 08월 11일",
           "bdwt_div_atn": "분리형"}
_MZN_EB = {"rcept_no": "e", "bd_tm": "1", "ex_prc": "10,000", "extg": "자기주식",
           "extg_tisstk_vs": "3.2", "exrqpd_bgd": "2025년 01월 01일",
           "exrqpd_edd": "2027년 01월 01일", "bd_fta": "5,000,000,000"}


@pytest.mark.parametrize("row,kind", [
    (_MZN_CB, "CB"), (_MZN_BW, "BW"), (_MZN_EB, "EB"),
    # 결측·음수·미기재
    ({"rcept_no": "x", "bd_fta": "-", "cv_prc": "-", "bd_intr_ex": "-"}, "CB"),
])
def test_메자닌_발행조건_파싱이_같다(row, kind):
    got = _viewer([["parseMezzanineRow", row, kind]])[0]
    core = parse_mezzanine_row(row, kind)
    for k in core:
        assert core[k] == got.get(k) or _num(core[k]) == _num(got.get(k)), (
            f"{kind}의 {k}가 갈린다: core={core[k]!r} 뷰어={got.get(k)!r}")


def test_메자닌_집계가_같다():
    """⚠ 하한 버킷이 갈리면 98.8%(리픽싱 여지 없음)와 11.1%(예외)가 뒤섞인다."""
    rows = [
        {**_MZN_CB, "rcept_no": "a", "cv_prc": "4,501",
         "act_mktprcfl_cvprc_lwtrsprc": "500", "_kind": "CB"},      # 11.1%
        {**_MZN_CB, "rcept_no": "b", "cv_prc": "506",
         "act_mktprcfl_cvprc_lwtrsprc": "500", "_kind": "CB"},      # 98.8%
        {**_MZN_EB, "_kind": "EB"},                                  # 서식에 없음
        {**_MZN_CB, "rcept_no": "d", "bd_mtd": "-", "_kind": "CB"},  # 만기 미기재
    ]
    filings = [
        {"rcept_dt": "20260714", "rcept_no": "1",
         "report_nm": "주요사항보고서(전환사채권발행결정)"},
        {"rcept_dt": "20260713", "rcept_no": "2",
         "report_nm": "[기재정정]주요사항보고서(전환사채권발행결정)"},
        {"rcept_dt": "20260712", "rcept_no": "3", "report_nm": "최대주주변경"},
    ]
    totals = [{"se": "보통주", "istc_totqy": "10,000,000"},
              {"se": "합계", "istc_totqy": "99,999,999"}]
    got = _viewer([["summarizeMezzanine", rows, filings, totals, "20260901"]])[0]
    core = summarize_mezzanine(rows, filings, totals, today="20260901")

    assert core["maturity"] == got["maturity"]
    assert core["potential_shares"] == got["potential_shares"]
    assert core["common_total"] == got["common_total"]
    assert core["potential_pct"] == pytest.approx(got["potential_pct"])
    assert core["exercise_open"] == got["exercise_open"]
    assert core["filings_total"] == got["filings_total"]
    assert core["filings_amended"] == got["filings_amended"]
    assert core["filing_counts"] == got["filing_counts"]
    for bucket in ("floors", "lt70", "absent", "no_value"):
        assert [x["rcept_no"] for x in core["refix"][bucket]] == \
               [x["rcept_no"] for x in got["refix"][bucket]], f"{bucket}이 갈린다"
    assert {k: (v["count"], v["face"]) for k, v in core["by_kind"].items()} == \
           {k: (v["count"], v["face"]) for k, v in got["byKind"].items()}


def test_대기물량_계산이_같다():
    """⚠ 「발행 시 기준」만 보면 오버행을 과소평가한다 — 리픽싱으로 가액이
    내려가면 같은 권면총액에서 더 많은 주식이 나온다(크라우드웍스 실측
    16.7% ↔ 하한까지 23.8%). 두 레이어가 갈리면 한쪽이 위험을 덜 보여준다.
    """
    issues = [
        # 크라우드웍스 실측값
        parse_mezzanine_row({**_MZN_CB, "rcept_no": "cb", "bd_tm": "2",
                             "bd_fta": "4,000,000,000", "cv_prc": "2,105",
                             "act_mktprcfl_cvprc_lwtrsprc": "1,474",
                             "cvisstk_cnt": "1,900,237",
                             "bd_mtd": "2029년 07월 13일"}, "CB"),
        parse_mezzanine_row({**_MZN_BW, "rcept_no": "bw", "bd_tm": "1",
                             "bd_fta": "10,000,000,000", "ex_prc": "27,150",
                             "act_mktprcfl_cvprc_lwtrsprc": "19,010",
                             "nstk_isstk_cnt": "368,324",
                             "bd_mtd": "2028년 12월 01일"}, "BW"),
        # 만기 경과 — 대기물량이 아니다
        parse_mezzanine_row({**_MZN_CB, "rcept_no": "old",
                             "bd_mtd": "2020년 01월 01일"}, "CB"),
        # EB — 교환 대상이 이미 발행된 주식이라 신주가 나오지 않는다
        parse_mezzanine_row({**_MZN_EB, "rcept_no": "eb"}, "EB"),
        # 하한 미기재 — 발행가액 기준으로 대체돼야 한다
        parse_mezzanine_row({**_MZN_CB, "rcept_no": "nofloor",
                             "act_mktprcfl_cvprc_lwtrsprc": "-",
                             "bd_mtd": "2029년 01월 01일"}, "CB"),
    ]
    got = _viewer([["mezzanineOverhang", issues, 13_603_176, "20260901"]])[0]
    core = mezzanine_overhang(issues, 13_603_176, today="20260901")

    for k in ("face_total", "shares_at_strike", "shares_at_floor", "common_total",
              "excluded_matured", "excluded_eb", "floor_unknown"):
        assert core[k] == got[k], f"{k}가 갈린다: core={core[k]!r} 뷰어={got[k]!r}"
    assert core["pct_at_strike"] == pytest.approx(got["pct_at_strike"])
    assert core["pct_at_floor"] == pytest.approx(got["pct_at_floor"])
    assert [r["rcept_no"] if "rcept_no" in r else (r["kind"], r["round"])
            for r in core["rows"]] == \
           [r["rcept_no"] if "rcept_no" in r else (r["kind"], r["round"])
            for r in got["rows"]]
    for a, b in zip(core["rows"], got["rows"]):
        assert a["shares_at_strike"] == b["shares_at_strike"]
        assert a["shares_at_floor"] == b["shares_at_floor"]

    # 실측 고정 — 크라우드웍스 두 회차가 DART 공시값과 정확히 일치해야 한다
    #             (권면 ÷ 가액 = `cvisstk_cnt`가 성립하는 것이 이 계산의 근거다)
    _by = {r["round"]: r for r in core["rows"] if r["kind"] in ("CB", "BW")}
    assert _by[2]["shares_at_strike"] == 1_900_237     # CB 40억 ÷ 2,105원
    assert _by[2]["shares_at_floor"] == 2_713_704      # 하한 1,474원
    assert _by[1]["shares_at_strike"] == 368_324       # BW 100억 ÷ 27,150원
    assert _by[1]["shares_at_floor"] == 526_038        # 하한 19,010원
    # 하한 시나리오는 **반드시** 발행가액 기준보다 크거나 같다 — 작아지면
    # 「리픽싱이 희석을 줄인다」는 거짓이 된다(하한 미기재 건을 0으로 두면 그렇게 된다)
    assert core["shares_at_floor"] > core["shares_at_strike"]
    assert core["excluded_matured"] == 1 and core["excluded_eb"] == 1
    assert core["floor_unknown"] == 1
