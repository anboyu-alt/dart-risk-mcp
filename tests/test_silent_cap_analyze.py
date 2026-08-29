"""`analyze_company_risk`의 남은 **조용한 절단** 두 곳을 잠근다.

상한 리터럴을 전수로 훑어 「상한에 닿아도 아무 말 없는 자리」를 찾다 나왔다
(2026-08-30). 이미 안내가 있던 곳(인물 10명 「외 N명」, 이상 5건 「외 N건」)과
달리 이 둘은 침묵했다.

## 주요 결정 상대방

헤더가 「(최근 순, **최대 10건**)」이라 적었지만 **전체가 몇 건이었는지**는
말하지 않았다. 결정이 15건인 회사에서 10건만 보이고 5건은 흔적이 없다 —
사용자는 그 회사에 결정이 10건뿐이라고 읽는다.

    두산  전체 15건 중 최근 10건 표시 · 5건 생략

## CB 인수자

「최근 3건까지」가 **코드 주석에만** 있었다. 화면에는 「━━ CB 인수자 ━━」뿐이다.

    HLB  CB/BW 공시 **28건** 중 최근 3건의 원문에서 추출 · 25건 미조회

28건 중 3건만 보고 아무 말이 없으면, 거기서 나온 인수자 명단이 전부라고
읽힌다. 이 도구의 목적이 「누가 돈을 댔나」라 특히 위험하다.

⚠ 상한 자체는 그대로 둔다 — 원문 ZIP 조회 비용이 있고, 이건 **표기** 문제다.
자금사용 목록에 적용한 원칙과 같다(「전체 N건 중 M건 표시 · … 생략」).
"""
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SRC = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")


def test_주요_결정_상한이_상수로_있다():
    assert "_DECISION_SHOW_MAX = 10" in _SRC
    assert "_decision_all[:_DECISION_SHOW_MAX]" in _SRC, "리터럴이 남아 있다"


def test_주요_결정이_전체_건수와_생략분을_밝힌다():
    i = _SRC.index("📑 **주요 결정 상대방**")
    body = _SRC[i - 200:i + 400]
    assert "_decision_omitted" in body
    assert "len(_decision_all)" in body, "전체 건수를 말하지 않는다"
    assert "생략" in body


def test_생략이_없으면_생략_문구를_붙이지_않는다():
    """3건뿐인 회사에 「0건 생략」이라 적으면 소음이다."""
    i = _SRC.index("📑 **주요 결정 상대방**")
    body = _SRC[i - 200:i + 400]
    assert "if _decision_omitted else" in body


def test_CB_인수자_상한이_상수로_있다():
    assert "_CB_EXTRACT_MAX = 3" in _SRC
    assert "cb_rcept_nos[:_CB_EXTRACT_MAX]" in _SRC, "리터럴이 남아 있다"


def test_CB_인수자가_미조회_건수를_밝힌다():
    i = _SRC.index("━━ CB 인수자 ━━")
    body = _SRC[i - 100:i + 400]
    assert "_cb_omitted" in body
    assert "len(cb_rcept_nos)" in body, "전체 CB 건수를 말하지 않는다"
    assert "미조회" in body


def test_CB_생략이_없으면_문구를_붙이지_않는다():
    i = _SRC.index("━━ CB 인수자 ━━")
    body = _SRC[i - 100:i + 400]
    assert 'if _cb_omitted else ""' in body


def test_이미_있던_안내는_그대로다():
    """인물 10명·이상 5건은 처음부터 「외 N」을 적고 있었다 — 회귀 방지."""
    assert re.search(r"외 \{len\(_people\) - 10\}명", _SRC)
    assert re.search(r"외 \{len\(_anomaly_recs\) - 5\}건", _SRC)
