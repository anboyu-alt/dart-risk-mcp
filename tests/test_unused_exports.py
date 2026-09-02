"""`core.__all__`의 **쓰이지 않는 공개 함수**를 못 박는다.

위험 목록 4번을 제작자 승인으로 처리한 결과(2026-08-30).

## 무엇이 문제였나

`core/__all__`에 있어 **공개 API처럼 보이는데** 프로덕션에서 아무도 부르지
않는 함수들이 있었다. 위험 목록은 5개를 지목했는데 AST 전수로 재보니
**7개**였고, 지목된 것 중 `build_note_summary`는 **실제로 쓰이고 있었다**
(`server.py`). 목록이 두 방향으로 틀렸다.

## 지우지 않은 이유

이 패키지는 **PyPI에 배포된다**(`publish-pypi.yml` · README `pip install
dart-risk-mcp`). `core.__all__`은 외부에서 import 가능한 진짜 공개 API라,
삭제는 되돌리기 어려운 외부 영향이다. 게다가 이것들은 **테스트가 있다**
(17~21개 호출) — 「검증 안 된」 코드가 아니라 「검증됐지만 안 쓰는」 코드다.

대신 셋을 했다.
  ① 각 함수 독스트링에 「현재 프로덕션 소비처 0」을 명시
  ② `server.py`의 **죽은 import 2개** 제거(내부 변경이라 위험 없음) —
     `calculate_risk_score`·`estimate_crisis_timeline`
  ③ 이 테스트로 목록을 못 박아 **새로 생기면 잡히게** 한다

## 왜 이 테스트가 진짜 고침인가

위험 목록이 적은 문제는 「남기면 있는 줄 알고 새 코드가 기댄다」였다.
목록을 고정하면 **새 죽은 export는 실패로 드러나고**, 근거를 적어야 통과한다.
"""
import ast
import pathlib

import pytest

import dart_risk_mcp.core as core

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_PROD_DIRS = ("dart_risk_mcp", "scripts", "tool_server", "api")

# 2026-08-30 AST 전수 측정 결과. **줄이는 것은 환영, 늘리는 것은 근거 필요.**
#
#   calculate_risk_score        v0.8.5가 점수 노출을 금지하며 렌더에서 빠졌다
#   estimate_crisis_timeline    「위기 타임라인」이 v0.8.5로 출력에서 제거됐다
#   fetch_executive_roster      `_detail` 판으로 대체됐다(직위·등기 여부 보존)
#   fetch_indicator_history     폐기된 SE(#239) 화면용
#   is_false_amendment          2026-08-26 근본 수정으로 우회가 불필요해졌다
#   resolve_disclosure_row_…    이름 그대로 하위 호환 래퍼
#   summarize_note_sections     도구가 `classify_note_title`+`scan_note_titles`를 직접 쓴다
#   glossary_footer             용어 사전(과제 1)만 이 라운드에 들어간다 — 리포트
#                                말미에 붙이는 배선은 후속 과제의 몫이다
KNOWN_UNUSED = frozenset({
    "calculate_risk_score",
    "estimate_crisis_timeline",
    "fetch_executive_roster",
    "fetch_indicator_history",
    "is_false_amendment",
    "resolve_disclosure_row_from_rcept_no",
    "summarize_note_sections",
    "glossary_footer",
})


def _called_names() -> set:
    """생산 코드에서 **실제로 호출되는** 이름 (ast.Call만).

    ⚠ 정규식으로 세면 주석·import까지 「사용」으로 잡힌다 — 처음에 그렇게
    재서 `build_note_summary`를 죽은 것으로 오인할 뻔했다.
    """
    called = set()
    for d in _PROD_DIRS:
        p = _ROOT / d
        if not p.exists():
            continue
        for f in p.rglob("*.py"):
            try:
                tree = ast.parse(f.read_text(encoding="utf-8"))
            except SyntaxError:
                continue
            for node in ast.walk(tree):
                if isinstance(node, ast.Call):
                    fn = node.func
                    n = getattr(fn, "id", None) or getattr(fn, "attr", None)
                    if n:
                        called.add(n)
    return called


def _exported_functions() -> set:
    out = set()
    for n in getattr(core, "__all__", []):
        obj = getattr(core, n, None)
        if callable(obj) and not isinstance(obj, type):
            out.add(n)
    return out


def test_검사가_실제로_무언가를_본다():
    """호출 이름을 못 모으면 모든 export가 「미사용」이 되어 무의미하다."""
    called = _called_names()
    assert len(called) > 200, f"호출 이름 {len(called)}개 — 스캔이 헛돈다"
    assert len(_exported_functions()) > 80


def test_새로운_죽은_export가_생기지_않았다():
    unused = _exported_functions() - _called_names()
    새로 = sorted(unused - KNOWN_UNUSED)
    assert not 새로, (
        f"프로덕션에서 아무도 부르지 않는 공개 함수가 새로 생겼다: {새로}\n"
        "  — 쓰거나, 내보내지 말거나, 근거를 적고 KNOWN_UNUSED에 넣어라."
    )


def test_쓰이게_된_것은_목록에서_빼라():
    """줄어든 것을 방치하면 목록이 다시 낡는다 — 오늘 겪은 그 문제다."""
    unused = _exported_functions() - _called_names()
    살아남 = sorted(KNOWN_UNUSED - unused)
    assert not 살아남, (
        f"이제 쓰이고 있다: {살아남} — KNOWN_UNUSED에서 빼고 독스트링의 "
        "「소비처 0」 문구도 지워라"
    )


def test_build_note_summary는_죽지_않았다():
    """위험 목록이 죽은 것으로 지목했지만 `server.py`가 부른다."""
    assert "build_note_summary" not in KNOWN_UNUSED
    assert "build_note_summary" in _called_names()


@pytest.mark.parametrize("name", sorted(KNOWN_UNUSED))
def test_독스트링이_소비처_0을_밝힌다(name):
    """다음 사람이 「있으니 쓰면 되겠지」 하지 않도록."""
    obj = getattr(core, name, None)
    assert obj is not None, f"{name}이 core에서 사라졌다"
    doc = obj.__doc__ or ""
    assert "프로덕션 소비처 0" in doc, f"{name} 독스트링에 상태 표기가 없다"


def test_server가_죽은_import를_들고_있지_않다():
    """점수·타임라인 함수는 v0.8.5로 출력에서 빠졌다 — import도 지웠다."""
    src = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
    for name in ("calculate_risk_score", "estimate_crisis_timeline"):
        assert name not in src, f"server.py가 {name}을 다시 들고 있다"


def test_지우지_않은_이유가_남아_있다():
    """PyPI 배포 패키지라는 사실이 이 판단의 근거다."""
    wf = _ROOT / ".github" / "workflows" / "publish-pypi.yml"
    assert wf.exists(), "PyPI 배포가 사라졌다면 삭제 판단을 다시 하라"
