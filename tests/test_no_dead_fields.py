"""**죽은 필드**를 잠근다 — 우리가 읽기만 하고 아무도 넣지 않는 키 (2026-08-26).

같은 결함이 **세 번** 나왔다. 셋 다 테스트는 통과하고 있었다.

| 언제 | 무엇 | 결과 |
|---|---|---|
| #315 | `remndr_amount` 등 | `track_debt_balance`가 **통째로 죽어 있었다** |
| #327 | `corp_cls_nm` | 「법인구분」이 **모든 회사에서 「-」** |
| #328 | `reprt_nm` | 「5% 대량보유자」의 **이름 자리가 늘 비어 있었다** |

공통점: 응답에 없는 키를 읽으니 `.get(k, 기본값)`이 조용히 기본값을 돌려주고,
그 자리가 영원히 비어 있어도 아무도 죽지 않는다. 눈으로 안 보면 못 찾는다.

## 어떻게 잡나

`tests/fixtures/api/response_keys.json`에 **42개 엔드포인트를 실제로 호출해
받은 키 385종**을 고정해 뒀다. 소스에서 `x.get("k")`·`x["k"]`로 읽는 키
중에서

  · 우리 코드가 dict 리터럴로 **만드는** 키도 아니고
  · 실제 응답 키에도 없고
  · DART 필드처럼 생겼으면(소문자+밑줄)

의심으로 신고한다. 아래 `_ACCEPTED`에 근거를 적어야 통과한다.

⚠ 픽스처의 `unsampled`는 **표본에 자료가 없어 확인하지 못한** 엔드포인트다
('키가 없다'가 아니다). 그 엔드포인트의 필드는 여기서 판정할 수 없다.
"""
import ast
import json
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_FILES = ["dart_risk_mcp/server.py", "dart_risk_mcp/core/dart_client.py"]
_KEYS = json.loads((_ROOT / "tests" / "fixtures" / "api" / "response_keys.json")
                   .read_text(encoding="utf-8"))
_API = {k for v in _KEYS["endpoints"].values() for k in v}

# 읽지만 응답에도 없고 우리가 만들지도 않는 키 — 근거를 적고 넣는다.
_ACCEPTED = {
    # 표본에 자료가 없어 확인 못 한 엔드포인트(dfOcr·dsRsOcr)의 필드.
    # 2026-08-04 사고 때 `rq_rs`를 실측으로 고친 전례가 있어 남겨 둔다.
    "df_amt", "df_bnk", "df_cn", "ds_rs",
    # 표본이 없던 DS005 엔드포인트(양수도·분할 일부)의 필드.
    "ast_rt",
    # 다른 모듈(taxonomy.py·qualifiers.py)이 만드는 키 — 이 스캔은 두 파일만
    # 훑어서 '만드는 곳'을 못 본다.
    "alias_note", "fake_new_biz", "fetch_failed", "n_matched", "n_total",
    "outside_window", "pattern_id", "signal_sequence", "zombie_ma",
    # elestock 구필드 폴백 — 응답에 없다는 사실을 코드 주석이 이미 적고 있다.
    "stkqy_rt",
}


def _scan():
    read, written = {}, set()
    for f in _FILES:
        tree = ast.parse((_ROOT / f).read_text(encoding="utf-8"))
        for n in ast.walk(tree):
            if isinstance(n, ast.Dict):
                for k in n.keys:
                    if isinstance(k, ast.Constant) and isinstance(k.value, str):
                        written.add(k.value)
            lit = None
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr in ("get", "setdefault", "pop") and n.args
                    and isinstance(n.args[0], ast.Constant)
                    and isinstance(n.args[0].value, str)):
                lit = n.args[0].value
            elif (isinstance(n, ast.Subscript)
                  and isinstance(n.slice, ast.Constant)
                  and isinstance(n.slice.value, str)):
                lit = n.slice.value
            if lit:
                read.setdefault(lit, (f, getattr(n, "lineno", 0)))
    return read, written


def test_죽은_필드가_없다():
    read, written = _scan()
    dead = {
        k: v for k, v in read.items()
        if k not in written and k not in _API and k not in _ACCEPTED
        and k.islower() and "_" in k and not k.startswith("_")
    }
    assert not dead, (
        "응답에 없고 우리가 만들지도 않는 키를 읽는다 — 그 자리는 영원히 빈다.\n"
        "실제 응답 키를 떠서 확인하고, 맞으면 근거와 함께 _ACCEPTED에 넣으세요:\n"
        + "\n".join(f"  {v[0].split('/')[-1]}:{v[1]}  {k}" for k, v in sorted(dead.items()))
    )


def test_과거_세_건이_재발하지_않는다():
    read, _ = _scan()
    for k, why in [("corp_cls_nm", "#327 법인구분"),
                   ("reprt_nm", "#328 대량보유자 이름"),
                   ("remndr_amount", "#315 채무증권 잔액")]:
        assert k not in read, f"{why} — 죽은 필드가 되살아났다: {k}"


def test_픽스처가_비어_있지_않다():
    """전부 통과시키는 검사는 통과할수록 위험하다."""
    assert len(_API) > 300, f"응답 키가 {len(_API)}종뿐이다 — 픽스처가 비었나?"
    assert len(_KEYS["endpoints"]) > 40


def test_미확인_엔드포인트를_숨기지_않는다():
    """빈 배열은 '키가 없다'가 아니라 '확인 못 했다'는 뜻이다."""
    unsampled = set(_KEYS["unsampled"])
    empty = {k for k, v in _KEYS["endpoints"].items() if not v}
    assert unsampled == empty, "unsampled 목록과 실제 빈 항목이 어긋난다"


# ── 엔드포인트별 대조 ────────────────────────────────────────────────
#
# 위 검사는 **키 합집합**과 맞춘다. 그래서 어느 한 엔드포인트에만 있는
# 이름은, 정작 읽는 쪽 응답에 없어도 통과한다 — `corp_name`이 그랬다
# (#340: `fnlttMultiAcnt` 응답에 없는데 다른 엔드포인트엔 있어서
# 폴백이 항상 걸렸고, 「━━ 005930 ━━」처럼 종목코드만 나왔다).
#
# `dart_client.py`의 fetch 함수는 대개 엔드포인트가 하나로 특정되므로
# **그 엔드포인트의 키하고만** 맞출 수 있다. `fetch_debt_balance`의
# `remndr_amount`(#315)를 소스에서 바로 잡았을 검사다.
_EP_RE = re.compile(r"([A-Za-z][A-Za-z0-9]*)\.json")


def _single_endpoint_funcs():
    src = (_ROOT / "dart_risk_mcp" / "core" / "dart_client.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        body = ast.get_source_segment(src, fn) or ""
        eps = {m.group(1) for m in _EP_RE.finditer(body)} & set(_KEYS["endpoints"])
        # 표본이 없는 엔드포인트는 판정할 수 없다(「키가 없다」가 아니다)
        eps = {e for e in eps if _KEYS["endpoints"][e]}
        if len(eps) == 1:
            yield fn, eps.pop()


def test_엔드포인트별로도_죽은_필드가_없다():
    envelope = set(_KEYS["endpoints"].get("_envelope", []))
    bad = []
    for fn, ep in _single_endpoint_funcs():
        have = set(_KEYS["endpoints"][ep]) | envelope
        reads, made = set(), set()
        for n in ast.walk(fn):
            if isinstance(n, ast.Dict):
                made |= {k.value for k in n.keys
                         if isinstance(k, ast.Constant) and isinstance(k.value, str)}
            if (isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "get" and n.args
                    and isinstance(n.args[0], ast.Constant)
                    and isinstance(n.args[0].value, str)):
                reads.add(n.args[0].value)
        for r in sorted(reads - have - made - _ACCEPTED):
            if r.islower() and "_" in r and not r.startswith("_"):
                bad.append((fn.name, ep, r))
    assert not bad, (
        "그 엔드포인트 응답에 없는 키를 읽는다:\n"
        + "\n".join(f"  {f}() [{e}] → {k}" for f, e, k in bad)
    )


def test_대조_대상이_비어_있지_않다():
    """짝지을 함수를 하나도 못 찾으면 검사가 헛돈다."""
    n = len(list(_single_endpoint_funcs()))
    assert n >= 8, f"엔드포인트가 특정되는 함수가 {n}개뿐이다"
