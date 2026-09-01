"""릴리스 커밋이 있는 버전은 CHANGELOG에도 있어야 한다.

## 왜 만들었나

`1.20.25`~`1.20.42` **18개 버전이 실재했는데 CHANGELOG 항목이 없었다.**
릴리스 커밋은 빠짐없이 있었고 문서 작성만 그 구간에서 누락됐다 — 아무도
기계로 대조하지 않아 **15일간 드러나지 않았다**.

2026-09-02에 커밋에서 재구성해 메웠다(위험 목록 13번, 선택지 (b)). 각 줄은
커밋 **제목 그대로**이고 PR 링크를 붙였으며, 요약·해석·측정 수치를 덧붙이지
않았다 — 그것이 「없는 근거를 지어낼 위험」이다.

## 이 테스트가 실패하면

릴리스 커밋을 올리면서 CHANGELOG를 빠뜨린 것이다. 릴리스 절차(CLAUDE.md
「릴리스 커밋」)의 2단계를 건너뛰면 여기서 걸린다.

⚠ **git이 없는 환경에서는 건너뛴다** — 배포된 sdist에는 `.git`이 없다.
"""
import pathlib
import re
import shutil
import subprocess

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CHANGELOG = _ROOT / "CHANGELOG.md"

pytestmark = pytest.mark.skipif(
    shutil.which("git") is None or not (_ROOT / ".git").exists(),
    reason="git 저장소가 아니면 릴리스 커밋을 셀 수 없다",
)


def _released_versions() -> set:
    """`chore(release): vX.Y.Z` 커밋에서 버전을 뽑는다."""
    out = subprocess.run(
        ["git", "log", "--format=%s", "--grep=chore(release): v"],
        cwd=_ROOT, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    ).stdout
    return set(re.findall(r"chore\(release\): v(\d+\.\d+\.\d+)", out))


def _documented_versions() -> set:
    text = _CHANGELOG.read_text(encoding="utf-8")
    return set(re.findall(r"^## \[(\d+\.\d+\.\d+)\]", text, re.M))


def test_릴리스한_버전은_모두_CHANGELOG에_있다():
    released, documented = _released_versions(), _documented_versions()
    if not released:            # 얕은 클론 등
        pytest.skip("릴리스 커밋을 찾지 못했다 — 얕은 클론일 수 있다")
    missing = released - documented
    assert not missing, (
        f"릴리스 커밋은 있는데 CHANGELOG에 없는 버전 {len(missing)}개: "
        f"{sorted(missing, key=lambda v: [int(p) for p in v.split('.')])}\n"
        "릴리스 절차(CLAUDE.md 「릴리스 커밋」) 2단계를 빠뜨렸다.")


def test_1_20_구간에_구멍이_없다():
    """실제로 뚫렸던 구간을 따로 못 박는다 — 되돌아가면 즉시 걸린다."""
    doc = _documented_versions()
    gap = [f"1.20.{n}" for n in range(25, 43) if f"1.20.{n}" not in doc]
    assert not gap, f"1.20.25~1.20.42 공백이 되살아났다: {gap}"


def test_재구성_사실이_명시돼_있다():
    """재구성한 항목을 「그때 쓴 것」처럼 보이게 두면 안 된다."""
    text = _CHANGELOG.read_text(encoding="utf-8")
    assert "커밋에서 재구성" in text, (
        "1.20.25~1.20.42가 커밋에서 재구성됐다는 사실이 사라졌다")
    # 재구성 고지는 그 항목들보다 **앞에** 있어야 읽힌다
    assert text.index("커밋에서 재구성") < text.index("## [1.20.42]")


# ⚠ **역방향 검사(「CHANGELOG에만 있는 유령 버전」)는 두지 않는다.**
#
# 두 번 시도했다가 뺐다. 이 레포는 `chore(release): vX` 커밋 관례를 **연속적으로
# 쓰지 않았다** — 그 관례가 쓰인 버전은 74개(1.10.2~1.21.25)이고, CHANGELOG에는
# 그 밖에 45개가 더 있다(0.1.0부터 시작해 1.11.0·1.12.0·1.14.0 등 중간에도 있다).
# 즉 「문서에 있는데 릴리스 커밋이 없다」가 곧 결함은 아니다.
#
# 처음엔 `startswith("1.2")`로 걸렀는데 그것이 옛 `1.2.0`·`1.2.1`을 잡았고
# (문자열 접두는 버전 비교가 아니다), 최소 릴리스 버전을 경계로 바꿨더니
# 45개가 그대로 남았다. **임계를 맞춰 통과시키는 대신 검사를 뺀다** — 실제
# 결함(릴리스했는데 문서가 없다)은 위 두 테스트가 잡는다.
