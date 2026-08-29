"""`_category_of` 독스트링의 **예시**가 실제 매핑과 맞는지 잠근다.

카테고리 표기를 쫓다 찾았다(2026-08-30). 「복수 taxonomy면 무거운 쪽」을
설명하는 예시 둘이 **모두 단일 매핑**이 되어 있었다.

    주석  EMBEZZLE ['5.3','8.1'] → 8   실제  ['8.1']
    주석  INQUIRY  ['4.3','7.1'] → 7   실제  ['7.1']

둘 다 이 세션 계열의 수정으로 좁혀진 것이다 — EMBEZZLE은 발화 실적 0으로
키워드가 정리됐고(2026-08-17), INQUIRY는 4.3을 떼어냈다(v1.12.1). 즉 **규칙을
설명하려고 그 규칙을 더는 타지 않는 사례를 들고 있었다.** 게다가 `['5.3','8.1']`은
지금 `FUND_DIVERSION`의 매핑이라, 주석은 남의 값을 옛 주인 이름으로 부르고 있었다.

⚠ 이 세션에서 같은 부류를 세 번째로 만난다(`test_doc_internal_signatures.py`의
내부 함수 표, CLAUDE.md 도구 시그니처). **아무도 안 지키는 설명은 낡는다.**

잡는 것은 두 가지다.
  1. 예시로 든 매핑이 실제와 같은가
  2. 예시가 규칙을 실제로 예시하는가 — 복수 매핑이고 카테고리가 갈리는가
"""
import importlib.util
import pathlib
import re

import pytest

from dart_risk_mcp.core.signals import SIGNAL_KEY_TO_TAXONOMY

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_PATH = _ROOT / "scripts" / "export_tool_data.py"
_SRC = _PATH.read_text(encoding="utf-8")

# `AUDIT ['4.4','8.4'] → 8` 형태. 「예:」줄과 ⚠ 경고문 모두에서 잡힌다.
_EX = re.compile(r"([A-Z][A-Z_]{2,}) \[([^\]]*)\]")


def _load():
    spec = importlib.util.spec_from_file_location("_ex_tool_data", _PATH)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _doc() -> str:
    """독스트링 본문만 — 삼중따옴표 쌍으로 자른다.

    ⚠ 처음엔 `'\\n    \"\"\"'`로 끝을 찾았는데 **여는 따옴표에 먼저 걸려**
    빈 문자열이 나왔고, 그러면 아래 대조 테스트들이 전부 **공허하게 통과**한다
    (실제로 5개가 그렇게 통과했다). `test_예시를_실제로_찾는다`가 그걸 잡는다.
    """
    q = '"""'
    i = _SRC.index("def _category_of(")
    j = _SRC.index(q, i)
    return _SRC[j:_SRC.index(q, j + 3) + 3]


def _taxes(key):
    v = SIGNAL_KEY_TO_TAXONOMY.get(key)
    if isinstance(v, (list, tuple)):
        return list(v)
    return [v] if v else []


def _live_examples():
    """⚠ 경고문의 **옛 예시**는 「지금은 틀리다」를 말하는 것이라 제외한다."""
    doc = _doc()
    cut = doc.find("⚠ 옛 예시")
    return _EX.findall(doc if cut < 0 else doc[:cut])


def test_예시를_실제로_찾는다():
    assert len(_live_examples()) >= 2, "정규식이 헛돈다 — 예시를 못 찾으면 늘 통과한다"


def test_예시의_매핑이_실제와_같다():
    bad = []
    for key, lst in _live_examples():
        claimed = [x.strip().strip("'\"") for x in lst.split(",") if x.strip()]
        actual = _taxes(key)
        if claimed != actual:
            bad.append(f"{key}: 주석 {claimed} · 실제 {actual}")
    assert not bad, "독스트링 예시가 낡았다:\n  " + "\n  ".join(bad)


def test_예시가_규칙을_실제로_예시한다():
    """단일 매핑을 예로 들면 「무거운 쪽을 고른다」가 아무것도 보여주지 못한다."""
    bad = []
    for key, _ in _live_examples():
        heads = {int(t.split(".")[0]) for t in _taxes(key) if t.split(".")[0].isdigit()}
        if len(heads) < 2:
            bad.append(f"{key}: 카테고리 {sorted(heads)} — 갈리지 않아 예시가 안 된다")
    assert not bad, "\n  ".join(bad)


@pytest.mark.parametrize("key,want", [("AUDIT", 8), ("FUND_DIVERSION", 8)])
def test_예시가_실제로_그_값을_낸다(key, want):
    assert _load()._category_of(key) == want


def test_옛_예시가_되살아나지_않는다():
    """둘 다 단일 매핑이 된 뒤로는 이 규칙의 예시가 될 수 없다."""
    for key in ("EMBEZZLE", "INQUIRY"):
        heads = {int(t.split(".")[0]) for t in _taxes(key)}
        assert len(heads) == 1, (
            f"{key}가 다시 복수 카테고리가 됐다 — 이중 매핑은 오탐을 증폭시킨다"
            "(2026-08-21 한탑 실사고). 되살릴 거면 근거를 남겨라"
        )
