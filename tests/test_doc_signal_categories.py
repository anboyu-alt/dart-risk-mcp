"""CLAUDE.md **신호 키 카테고리 표**를 taxonomy와 대조한다.

뷰어가 「위기/부실」로 보여주는 신호를 문서에서 찾다 발견했다(2026-08-30).

    문서  | Cat 7 시장조작 | `INQUIRY`, `EMBEZZLE` |
    실제  EMBEZZLE → taxonomy ['8.1'] → Cat 8 위기/부실

`EMBEZZLE`은 옛 이중 매핑(`['5.3','8.1']`)이 정리된 뒤에도 표에 남아 있었는데,
**5도 8도 아닌 7**에 적혀 있었으니 이 칸은 어느 시점에도 taxonomy와 맞은 적이
없다. 표를 읽고 「횡령은 시장조작 계열」이라 이해하면 틀린다.

⚠ 이 세션에서 **네 번째** 문서 드리프트다 — 내부 함수 시그니처, 도구
시그니처, `_category_of` 독스트링 예시, 그리고 이 표. 공통점은 **아무도 안
지키는 설명**이라는 것이다. 그래서 기계로 잡는다.

## 잡지 않는 것

문서가 **일부 키만** 적는 것은 허용한다. 57개 중 36개만 표에 있고, 나머지는
구조화 데이터로 만들어지는 합성 신호(`AR_SURGE`·`DECISION_*`·`CAPITAL_CHURN`
등)라 「공시 제목 신호 키 목록」에 넣을 자리가 아니다. 잡는 것은 **적힌 키가
엉뚱한 칸에 있는 것**과 **없는 키를 적는 것** 둘뿐이다.
"""
import pathlib
import re

from dart_risk_mcp.core.signals import SIGNAL_KEY_TO_TAXONOMY

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_MD = (_ROOT / "CLAUDE.md").read_text(encoding="utf-8")

# ⚠ 표 행은 목록 안에 들여쓰여 있다 — `^\|`로 잡으면 0개가 나오고 모든
# 대조가 공허하게 통과한다(실제로 처음에 그랬다). 앞 공백을 허용한다.
_ROW = re.compile(r"\s*\|\s*Cat\s*(\d+)([^|]*)\|(.*?)\|?\s*$")


def _table():
    i = _MD.index("| 카테고리 | 키 목록 |")
    return _MD[i:_MD.index("\n\n", i)]


def _entries():
    out = []
    for line in _table().splitlines():
        m = _ROW.match(line)
        if m:
            out += [(int(m.group(1)), k) for k in re.findall(r"`(\w+)`", m.group(3))]
    return out


def _heads(key):
    v = SIGNAL_KEY_TO_TAXONOMY.get(key)
    v = v if isinstance(v, (list, tuple)) else ([v] if v else [])
    return {int(t.split(".")[0]) for t in v if t and t.split(".")[0].isdigit()}


def test_표를_실제로_읽는다():
    """0개를 읽으면 아래 대조가 전부 공허하게 통과한다."""
    assert len(_entries()) >= 30, f"{len(_entries())}개만 읽었다 — 파싱이 헛돈다"


def test_표에_적힌_키가_모두_코드에_있다():
    bad = [k for _, k in _entries() if k not in SIGNAL_KEY_TO_TAXONOMY]
    assert not bad, f"코드에 없는 키를 적었다: {bad}"


def test_카테고리_칸이_taxonomy와_맞는다():
    bad = []
    for cat, key in _entries():
        heads = _heads(key)
        if cat not in heads:
            bad.append(f"{key}: 문서 Cat{cat} · taxonomy {sorted(heads)}")
    assert not bad, "표의 카테고리가 taxonomy와 다르다:\n  " + "\n  ".join(bad)


def test_헤더의_건수가_표와_같다():
    m = re.search(r"사용 가능한 신호 키 \(아래 표 (\d+)개", _MD)
    assert m, "건수 표기가 사라졌다"
    assert int(m.group(1)) == len(_entries()), (
        f"헤더는 {m.group(1)}개라는데 표에는 {len(_entries())}개가 있다"
    )


def test_EMBEZZLE이_되돌아가지_않는다():
    assert (8, "EMBEZZLE") in _entries()
    assert (7, "EMBEZZLE") not in _entries()


def test_NON_TITLE_경고문이_실제_집합과_같다():
    """제목으로 발화하지 않는 키 목록도 같은 부류로 낡을 수 있다."""
    from dart_risk_mcp.core.signals import NON_TITLE_SIGNALS
    # ⚠ 넉넉히 잡으면 옆 줄의 `SIGNAL_KEY_TO_TAXONOMY` 같은 **식별자**가
    # 섞여 들어온다 — 키 목록은 그 문장의 괄호 안에만 있으므로 줄 앞부터 자른다.
    i = _MD.index("**공시 제목으로 발화하지 않는다**")
    line_start = _MD.rindex("\n", 0, i) + 1
    doc = set(re.findall(r"`(\w+)`", _MD[line_start:i]))
    n = re.search(r"아래 키 중 (\d+)종", _MD[line_start:i])
    assert n and int(n.group(1)) == len(NON_TITLE_SIGNALS), (
        f"문구는 {n and n.group(1)}종이라는데 코드는 {len(NON_TITLE_SIGNALS)}종이다"
    )
    assert doc == set(NON_TITLE_SIGNALS), (
        f"문서에만: {sorted(doc - set(NON_TITLE_SIGNALS))} · "
        f"코드에만: {sorted(set(NON_TITLE_SIGNALS) - doc)}"
    )
