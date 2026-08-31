"""백필 스크립트가 **목록 상한에 닿았다는 사실**을 알리는지 고정한다.

위험 목록 6번을 제작자 승인으로 처리한 결과(2026-08-30, 선택지 (a) — 보고만
추가, 동작 불변).

## 무엇이 문제였나

`backfill_corp_aliases.py`·`backfill_renames.py`는 30일 청크 × `max_pages=60`
(= 6,000건)으로 거래소공시를 훑는다. 두 독스트링 다 「90일이면 상한에 걸리므로
30일 청크로 순회한다(**누락 방지**)」라 적는데, **그 30일 청크가 다시 상한에
닿았는지는 보지 않았다**. 닿으면 그 청크 뒷부분이 조용히 사라진다 —

- `backfill_corp_aliases` → 그 회사는 **옛 이름으로 검색되지 않는다**
- `backfill_renames` → `corp_renames`가 비어 행위자 이름 병합이 그만큼 빠진다

`backfill_sightings.py`는 같은 상황에서 이미 청크별 `truncated`를 세어
「⚠️목록 상한」을 찍고 있었다 — 셋 중 둘만 빠져 있었다.

## 무엇을 하지 않았나

**상한을 올리지 않았다.** 이 스크립트들은 cron으로 돌며 비공개 데이터를
만들고, 나는 그 데이터를 볼 수 없다. 예산·실행 시간도 달라진다.

**자료구조도 바꾸지 않았다.** 처음엔 `collect_renames`의 반환 dict에
`_truncated_chunks` 키를 넣었는데, 그 dict는 **키가 corp_code**라
`main`의 `e["names"]`가 죽고 `merge_renames`가 그 키를 **비공개 sightings
파일에 써 넣는다**. 되돌리고 로그로만 알린다. `backfill_corp_aliases`는
이미 `stats` dict를 따로 반환하므로 거기 담았다.
"""
import ast
import pathlib

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SCRIPTS = _ROOT / "scripts"

# (파일, 청크 순회 함수)
CHUNKED = [
    ("backfill_corp_aliases.py", "collect_renames"),
    ("backfill_renames.py", "collect_renames"),
]


def _func(fname: str, func: str) -> str:
    src = (_SCRIPTS / fname).read_text(encoding="utf-8")
    tree = ast.parse(src)
    for n in ast.walk(tree):
        if isinstance(n, ast.FunctionDef) and n.name == func:
            return ast.get_source_segment(src, n) or ""
    raise AssertionError(f"{fname}에 {func}가 없다")


@pytest.mark.parametrize("fname,func", CHUNKED)
def test_상한_도달을_판정한다(fname, func):
    """`len(discs) >= max_pages*100`을 실제로 계산해야 한다."""
    body = _func(fname, func)
    assert "cap_rows" in body, f"{fname}:{func} — 상한 도달 판정이 없다"
    assert "max_pages * 100" in body, (
        f"{fname}:{func} — 상한 행수를 max_pages에서 유도하지 않는다"
        " (상수를 손으로 적으면 max_pages를 바꿀 때 조용히 어긋난다)")


@pytest.mark.parametrize("fname,func", CHUNKED)
def test_닿았으면_알린다(fname, func):
    body = _func(fname, func) + (_SCRIPTS / fname).read_text(encoding="utf-8")
    assert "상한" in body and ("truncated" in body or "truncated_chunks" in body)


def test_renames는_반환_dict를_오염시키지_않는다():
    """반환값의 키는 corp_code뿐이다 — 밑줄 키를 넣으면 비공개 데이터가 오염된다."""
    body = _func("backfill_renames.py", "collect_renames")
    assert 'renames["_truncated_chunks"]' not in body, (
        "반환 dict에 진단 키를 넣었다 — main의 e[\"names\"]가 죽고 "
        "merge_renames가 그것을 sightings 파일에 써 넣는다")


def test_sightings_백필은_원래_보고하고_있었다():
    """셋 중 하나는 이미 옳았다 — 그 관례가 사라지지 않게 함께 잠근다."""
    src = (_SCRIPTS / "backfill_sightings.py").read_text(encoding="utf-8")
    assert "truncated_chunks" in src and "목록 상한" in src


def test_상한_자체는_그대로다():
    """보고만 추가했다 — 값을 올리면 API 예산·실행 시간이 달라진다."""
    for fname, _ in CHUNKED:
        src = (_SCRIPTS / fname).read_text(encoding="utf-8")
        assert "max_pages: int = 60" in src, f"{fname}: 상한이 바뀌었다"
        assert "timedelta(days=29)" in src, f"{fname}: 청크 길이가 바뀌었다"
