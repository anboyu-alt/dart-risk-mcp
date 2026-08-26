"""출력이 상한에 걸려 잘렸다면 **잘렸다고 적는지** 잠근다 (2026-08-26).

#317에서 공시 목록 절단이 조용했던 것을 고치고 나서, 같은 종류가 렌더 쪽에도
남아 있는지 `server.py` 전수로 훑어 찾았다. 여섯 곳이 조용했다.

    _decision_all[:10]   DS005 구조화 조회 — 결정 공시가 12건이어도 10건만
    cb_rcept_nos[:3]     CB 인수자 — 「CB 인수자」 목록이 전수처럼 읽혔다
    cb_rcept_list[:3]    같은 것, `build_event_timeline`
    _anomaly_recs[:5]    머리글은 "이상 N건"인데 다섯 건만 나열
    seen.items()[:10]    겸직 명단 — 머리글은 "총 N명"
    cash_dividends[:20]  배당 이력
    drain_flags[:5]      배당 유출 패턴

`find_actor_overlap`은 특히 나빴다 — 결론이 "**겹치는 사람이 없다**"인데
기업당 원문 3건만 열고 그 사실을 "겹침 없음" 분기에서만 적었다. 겹침이
발견된 분기와 「회사별 **전체** 인수자·임원 명단」 머리글은 조용했다.

이미 정직했던 곳도 있다(`procedural_events[:20]` · `recent[:10]` ·
`failed_days[:5]` · `_top3` · 타법인 출자 상위 30건 · 자본 시계열 30건) —
관례는 있었고 지키지 않은 자리가 있었던 것이다.

## 검사 방법

AST로 `NAME[:N]`(N≥3, 리스트로 보이는 이름)을 전부 찾아, 같은 함수 안에
`len(NAME)`을 N 또는 다른 길이와 비교하는 곳이 있는지 본다. 없으면 잘림을
알릴 방법이 없다는 뜻이다.

⚠ **문자열 자르기는 상한이 아니다** — `text[:500]`·`d[:4]`처럼 사람이 읽을
길이를 줄이는 것은 데이터를 버리는 게 아니라 표기를 줄이는 것이다.
이름으로 가린다(아래 `_STRING_SLICES`).
"""
import ast
import pathlib

import pytest

_SRC = (pathlib.Path(__file__).resolve().parents[1]
        / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")

# 문자열을 자르는 슬라이스 — 데이터 손실이 아니라 표기 길이 조정이다.
_STRING_SLICES = {
    "text", "d", "digits", "date", "prev_date", "_bgn", "_end", "nm",
    "report_nm", "name", "s", "raw",
    # 대량보유 보고사유 — 한 줄에 넣으려 길이를 줄이는 것이라 데이터 손실이
    # 아니다(원문은 접수번호로 열어 볼 수 있다). 2026-08-26에 이 검사가
    # 실제로 잡아 줘서 여기 적는다.
    "resn",
}
# 검사 대상 밖 — 근거를 반드시 남긴다.
_ALLOW = {
    # 지도 모드 안내에 예시로 드는 최근 신호 몇 개. 전수 목록이 아니라
    # "이런 달을 넣어 보라"는 예시라 잘림 개념이 없다.
    ("_shallow_notice", "recent", 4),
}


def _bare_caps():
    tree = ast.parse(_SRC)
    out = []
    for fn in [n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)]:
        for n in ast.walk(fn):
            if not (isinstance(n, ast.Subscript) and isinstance(n.slice, ast.Slice)):
                continue
            sl = n.slice
            if sl.lower is not None or sl.step is not None:
                continue
            if not (isinstance(sl.upper, ast.Constant)
                    and isinstance(sl.upper.value, int)):
                continue
            cap = sl.upper.value
            if cap < 3 or not isinstance(n.value, ast.Name):
                continue
            name = n.value.id
            if name in _STRING_SLICES or (fn.name, name, cap) in _ALLOW:
                continue
            if not _has_len_guard(fn, name):
                out.append((fn.name, name, cap, n.lineno))
    return out


def _has_len_guard(fn, name):
    """같은 함수 안에서 `len(name)`을 **재기라도 하는가**.

    비교(`len(x) > 3`)만 보다가 `_top3`을 놓쳤다 — 거긴 뺄셈으로 센다
    (`rest = len(items) - len(shown)`). 재지 않으면 잘림을 알릴 방법이
    없다는 것이 핵심이라, 재는 방식은 묻지 않는다.
    """
    for c in ast.walk(fn):
        if (isinstance(c, ast.Call) and getattr(c.func, "id", "") == "len"
                and c.args and getattr(c.args[0], "id", "") == name):
            return True
    return False


def test_조용한_상한이_없다():
    bare = _bare_caps()
    assert not bare, (
        "잘림을 알리지 않는 상한이 있다 — 목록이 전수처럼 읽힌다:\n"
        + "\n".join(f"  {f}:{ln}  {n}[:{c}]" for f, n, c, ln in bare)
    )


def test_검사가_실제로_무언가를_본다():
    """전부 통과시키는 검사는 통과할수록 위험하다 — 대상을 세어 본다."""
    tree = ast.parse(_SRC)
    n = sum(1 for x in ast.walk(tree)
            if isinstance(x, ast.Subscript) and isinstance(x.slice, ast.Slice))
    assert n >= 15, f"슬라이스를 {n}개밖에 못 찾았다 — 파싱이 헛돈다"


@pytest.mark.parametrize("phrase", [
    "나머지 인수자는 목록에 없습니다",
    "구조화 조회했습니다",
    "원문 조회 상한",
])
def test_안내_문구가_남아_있다(phrase):
    """AST 검사는 `len()` 비교만 본다 — 실제 문장이 사라지면 못 잡는다."""
    assert phrase in _SRC


def test_겸직_명단_머리글이_상한을_반영한다():
    """상한에 걸렸으면 「전체 명단」이 아니다."""
    assert '"━━ 회사별 인수자·임원 명단 (중복 제거) ━━"' in _SRC
    assert '"━━ 회사별 전체 인수자·임원 명단 (중복 제거) ━━"' in _SRC
