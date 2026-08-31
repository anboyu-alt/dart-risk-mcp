"""릴리스 제안 판정을 고정한다 — **제안만 하고 배포하지 않는다**는 경계 포함.

## 왜 생겼나

`chore(release)` 커밋으로 버전을 올려도 배포되지 않는다 — PyPI와 .mcpb의
방아쇠는 **GitHub Release 게시**뿐이다. 2026-08-31 실측: master `1.21.20` ↔
PyPI `1.12.0`(2026-08-16), 그 사이 **222개 변경**이 사용자에게 가지 않고
있었다. 워크플로우가 실패한 게 아니라 **호출된 적이 없었다**.

제작자 요청은 *"릴리스를 제안해주면 좋을 듯. 아주 작은 수정까지 다 릴리스 할
필요는 없으니"* — 그래서 자동 배포가 아니라 **제안**이고, 버전이 하나 앞섰다는
것만으로는 제안하지 않는다.
"""
import importlib.util
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SPEC = importlib.util.spec_from_file_location(
    "propose_release", _ROOT / "scripts" / "propose_release.py")
pr = importlib.util.module_from_spec(_SPEC)
_SPEC.loader.exec_module(pr)


def _facts(*, feats=0, versions=0, days=0, subjects=1, tool_delta=""):
    return {"feats": [f"feat: x{i}" for i in range(feats)],
            "n_versions": versions, "days": days,
            "subjects": [f"s{i}" for i in range(subjects)],
            "kinds": {}, "tool_delta": tool_delta}


def test_배포가_최신이면_제안하지_않는다():
    ok, why = pr.decide("1.21.20", "1.21.20", _facts())
    assert not ok and "최신" in why


def test_PyPI를_못_물어보면_제안하지_않는다():
    """네트워크 실패는 「배포가 뒤처졌다」가 아니라 「모른다」다.

    빈 값을 「없다」로 읽지 않는다는 이 프로젝트의 원칙과 같은 판단 —
    모르는 상태에서 제안하면 방금 배포한 직후에도 이슈가 열린다.
    """
    ok, why = pr.decide("1.21.20", None, _facts(feats=3, versions=50))
    assert not ok and "물어보지 못했다" in why


def test_작은_수정만_쌓이면_제안하지_않는다():
    """제작자 요청의 핵심 — 패치 몇 개로는 부르지 않는다."""
    ok, why = pr.decide("1.21.3", "1.21.0", _facts(versions=3, subjects=4))
    assert not ok
    assert "작은 변경" in why


def test_새_기능이_있으면_제안한다():
    ok, why = pr.decide("1.22.0", "1.21.20", _facts(feats=1, versions=2))
    assert ok and "새 기능" in why


def test_도구_목록이_바뀌면_제안한다():
    """사용자가 쓰는 표면이 달라진 것 — 기능 커밋이 없어도 알린다."""
    ok, why = pr.decide("1.21.25", "1.21.20",
                        _facts(versions=5, tool_delta="+track_x"))
    assert ok and "도구 목록" in why


def test_많이_쌓이면_기능이_없어도_제안한다():
    ok, why = pr.decide("1.21.40", "1.21.20", _facts(versions=20, subjects=40))
    assert ok and "미배포 버전" in why


def test_실제_누락_상황을_재현하면_제안한다():
    """2026-08-31에 실제로 있었던 상태 — 이 도구가 있었으면 잡았어야 한다."""
    ok, why = pr.decide(
        "1.21.20", "1.12.0", _facts(feats=30, versions=68, days=15, subjects=222))
    assert ok
    assert "새 기능 30건" in why and "미배포 버전 68개" in why


def test_오래됐어도_변경이_없으면_제안하지_않는다():
    """시간만으로는 부르지 않는다 — 낼 것이 없는데 이슈가 열리면 소음이다."""
    ok, why = pr.decide("1.21.21", "1.21.20", _facts(versions=1, days=90, subjects=0))
    assert not ok


@pytest.mark.parametrize("bad", ["publish", "upload", "twine", "gh release create"])
def test_배포_동작을_스스로_하지_않는다(bad):
    """이 스크립트는 제안만 한다 — 배포 명령이 들어오면 경계가 무너진다."""
    src = (_ROOT / "scripts" / "propose_release.py").read_text(encoding="utf-8")
    code = "\n".join(l for l in src.splitlines()
                     if not l.strip().startswith("#"))
    body = code.split('"""', 2)[-1]      # 모듈 독스트링 제외(설명에 낱말이 나온다)
    assert bad not in body, f"제안 스크립트에 배포 동작이 들어왔다: {bad}"


def test_워크플로우가_릴리스를_게시하지_않는다():
    wf = (_ROOT / ".github" / "workflows" / "propose-release.yml").read_text(
        encoding="utf-8")
    for bad in ("gh release create", "release:", "pypa/gh-action"):
        assert bad not in wf, f"제안 워크플로우가 배포를 한다: {bad}"
    assert "issues: write" in wf and "contents: read" in wf, (
        "권한이 넓어졌다 — 이 워크플로우는 이슈만 쓴다")


def test_simple_index를_본다():
    """`/pypi/<pkg>/json`의 최신 버전은 캐시가 뒤처진다 — 실측으로 확인했다.

    2026-08-31에 1.21.20을 올린 직후에도 그 API는 1.12.0을 돌려줬다.
    설치가 실제로 읽는 simple index를 봐야 한다.
    """
    src = (_ROOT / "scripts" / "propose_release.py").read_text(encoding="utf-8")
    assert "pypi.org/simple/" in src
    assert "vnd.pypi.simple" in src
