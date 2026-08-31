"""CLAUDE.md의 「N개사 실측」이 가리키는 **표본 목록**을 고정한다.

위험 목록 5번을 제작자 승인으로 처리한 결과(2026-08-30).

## 무엇이 문제였나

CLAUDE.md에 「39개사 실측」·「25개사에서」 같은 수가 여럿인데 **그 표본이
어느 회사였는지 남아 있지 않았다**. 지금 다시 재면 시장이 달라져 다른 수가
나오고, 그러면 문서를 고쳐야 할지 그대로 둬야 할지 판단할 근거가 없다.

## 실제로 재 보니 전제가 절반은 틀렸다

「N개사」 51건을 전수로 훑었다.

    같은 줄에 측정 시점(날짜·버전) 있음   47 / 51
    문단 안에 재현 근거 경로 있음          32 / 51

즉 「시점을 병기한다」는 선택지는 이미 92% 되어 있었다. 진짜 빠진 것은
**표본 목록**이었고, 그것은 측정 스크립트에서 그대로 복원됐다.

## 무엇을 고정하나

`tests/fixtures/samples/measurement_cohorts.json`에 회사 이름을 그대로 담았다.
**값이 아니라 표본을 고정한다** — 시장이 달라지면 건수는 바뀌는 게 맞고,
바뀌었는지 알려면 같은 회사를 다시 재야 한다.

⚠ 이 테스트는 「그 수가 옳다」를 검사하지 않는다(그러려면 매번 DART를 쳐야
한다). 검사하는 것은 **표본이 남아 있고 문서의 N과 개수가 맞는가**다.
"""
import json
import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_FX = json.loads(
    (_ROOT / "tests" / "fixtures" / "samples" / "measurement_cohorts.json")
    .read_text(encoding="utf-8"))
_COHORTS = _FX["cohorts"]
_CLAUDE = (_ROOT / "CLAUDE.md").read_text(encoding="utf-8")


@pytest.mark.parametrize("key", sorted(_COHORTS))
def test_이름_개수가_키의_N과_맞는다(key):
    """`tools_12`인데 11사면 어딘가에서 한 곳이 조용히 빠진 것이다."""
    coh = _COHORTS[key]
    n_in_key = int(re.search(r"(\d+)$", key).group(1))
    assert coh["n"] == n_in_key == len(coh["companies"]), (
        f"{key}: 키 {n_in_key} · n {coh['n']} · 실제 {len(coh['companies'])}")


@pytest.mark.parametrize("key", sorted(_COHORTS))
def test_중복도_빈_이름도_없다(key):
    names = _COHORTS[key]["companies"]
    assert all(n.strip() for n in names), f"{key}: 빈 이름"
    dup = [n for n in set(names) if names.count(n) > 1]
    assert not dup, f"{key}: 중복 {dup} — 개수가 부풀려진다"


@pytest.mark.parametrize("key", sorted(_COHORTS))
def test_근거_주석에_측정_시점이_있다(key):
    """언제 잰 표본인지 없으면 나중에 어느 문장과 짝인지 알 수 없다."""
    note = _COHORTS[key]["note"]
    assert re.search(r"20\d\d-\d\d-\d\d", note), f"{key}: 시점 없음 — {note}"


def test_문서가_그_수를_실제로_말한다():
    """픽스처만 있고 문서에 그 수가 없으면 짝이 없는 표본이다.

    ⚠ **표본 크기(`n`)와 문서가 보고한 수(`doc_n`)는 다를 수 있다** — 이
    테스트를 처음 돌렸을 때 실제로 갈렸다. 매입채무 별칭은 39사를 넘겼는데
    코드 주석·CLAUDE.md는 「38개사」라 적는다. 어느 쪽을 지울지는 재측정
    전에는 알 수 없으므로 **두 수를 따로 들고** 사유를 note에 남긴다.
    """
    missing = [k for k, c in _COHORTS.items()
               if f"{c['doc_n']}개사" not in _CLAUDE]
    assert not missing, (
        f"CLAUDE.md에 없는 표본: {missing} — 문서에서 그 수가 사라졌다면 "
        "표본도 함께 정리하거나, 어느 문장을 받치는지 note에 적어라")


@pytest.mark.parametrize("key", sorted(_COHORTS))
def test_표본_크기와_보고_수가_다르면_사유가_있다(key):
    coh = _COHORTS[key]
    if coh["n"] == coh["doc_n"]:
        return
    assert str(coh["doc_n"]) in coh["note"], (
        f"{key}: 표본 {coh['n']}사 · 보고 {coh['doc_n']}사인데 note가 "
        "그 차이를 설명하지 않는다")


def test_선행_표본과의_관계가_사실이다():
    """25사의 note가 20사와의 차이를 말한다 — 그 말이 맞는지 대조한다.

    처음 적을 때 「대형주 5사 추가」라고 썼는데 실제로는 **6곳 추가·1곳 제외**
    였다. 주석이 데이터와 어긋나는 것은 이 프로젝트에서 반복된 결함이다.
    """
    a = set(_COHORTS["capital_churn_20"]["companies"])
    b = set(_COHORTS["capital_churn_25"]["companies"])
    assert len(b - a) == 6 and len(a - b) == 1, (
        f"추가 {sorted(b - a)} · 제외 {sorted(a - b)} — note를 함께 고쳐라")
    assert "포승그린파워" in a - b


def test_계정_표본은_포함_관계다():
    """39사는 38사에 KT&G를 더한 것이다 — 별개 표본이 아니다."""
    a = set(_COHORTS["fs_accounts_38"]["companies"])
    b = set(_COHORTS["fs_accounts_39"]["companies"])
    assert a < b and b - a == {"KT&G"}
