"""sightings 파일이 없을 때 조용히 새로 시작하지 않는지 잠근다.

일일 cron(`discover_actors`)은 `WINDOW_DAYS=2` — **이틀치**만 수집한다.
그런데 파일은 `WINDOW_MONTHS=140` — **11년치**를 담는다(2015년까지 백필).

`SIGHTINGS_PATH`가 가리키는 자리에 파일이 없으면 옛 `_load`는 빈 스켈레톤을
돌려줬다. 그러면 이틀치를 쓰고, 워크플로의 커밋 스텝이 그대로 커밋한다 —
**오류 하나 없이 11년이 이틀로 바뀐다**. 체크아웃 실패는 액션이 잡지만
파일명 변경·경로 오타는 안 잡힌다.

2026-08-04 감사가 **손상** 파일은 막았는데(B-2) **없는** 파일은 정상 경로로
남겨 뒀다. 같은 크기의 사고인데 한쪽만 막혀 있었다.

이 `_load`는 네 스크립트가 공유한다 — `discover_actors`·`backfill_renames`·
`backfill_sightings`·`merge_manual_renames`.
"""
import json

import pytest

from scripts.discover_actors import _load

EMPTY = {"version": 1, "sightings": {}}
REAL = {"version": 1, "sightings": {"홍길동": [{"corp": "가회사", "date": "2016-03"}]}}


def test_경로를_명시했는데_파일이_없으면_중단한다(tmp_path, monkeypatch):
    p = tmp_path / "sightings.json"
    monkeypatch.setenv("SIGHTINGS_PATH", str(p))
    monkeypatch.delenv("SIGHTINGS_ALLOW_CREATE", raising=False)
    with pytest.raises(SystemExit) as e:
        _load(p, EMPTY)
    msg = str(e.value)
    assert "파일이 없습니다" in msg
    assert "SIGHTINGS_ALLOW_CREATE" in msg, "빠져나갈 방법을 알려줘야 한다"


def test_최초_생성은_운영자가_선언하면_된다(tmp_path, monkeypatch):
    p = tmp_path / "sightings.json"
    monkeypatch.setenv("SIGHTINGS_PATH", str(p))
    monkeypatch.setenv("SIGHTINGS_ALLOW_CREATE", "1")
    assert _load(p, EMPTY) == EMPTY


def test_로컬_기본경로는_그대로_생성한다(tmp_path, monkeypatch):
    """경로를 안 준 개발용 스크래치(`tmp/sightings.json`)까지 막지는 않는다."""
    monkeypatch.delenv("SIGHTINGS_PATH", raising=False)
    monkeypatch.delenv("SIGHTINGS_ALLOW_CREATE", raising=False)
    assert _load(tmp_path / "sightings.json", EMPTY) == EMPTY


def test_있는_파일은_그대로_읽는다(tmp_path, monkeypatch):
    p = tmp_path / "sightings.json"
    p.write_text(json.dumps(REAL, ensure_ascii=False), encoding="utf-8")
    monkeypatch.setenv("SIGHTINGS_PATH", str(p))
    assert _load(p, EMPTY) == REAL


def test_손상_파일은_여전히_중단한다(tmp_path, monkeypatch):
    """2026-08-04 감사(B-2)가 막은 경로 — 되돌아가지 않게 함께 잠근다."""
    p = tmp_path / "sightings.json"
    p.write_text("{ 절단된", encoding="utf-8")
    monkeypatch.setenv("SIGHTINGS_PATH", str(p))
    monkeypatch.setenv("SIGHTINGS_ALLOW_CREATE", "1")   # 생성 허용도 손상을 덮지 않는다
    with pytest.raises(SystemExit) as e:
        _load(p, EMPTY)
    assert "파싱 실패" in str(e.value)


def test_수집창이_보존창보다_훨씬_짧다():
    """이 가드가 필요한 이유 자체를 고정한다 — 둘이 같아지면 위험이 사라진다."""
    from scripts.discover_actors import WINDOW_DAYS, WINDOW_MONTHS

    assert WINDOW_DAYS <= 7, "일일 수집창"
    assert WINDOW_MONTHS >= 120, "보존창(백필 누적)"


def test_워크플로는_생성을_허용하지_않는다():
    """cron이 ALLOW_CREATE를 켜 두면 가드가 무력해진다."""
    import pathlib

    wf = pathlib.Path(__file__).resolve().parents[1] / ".github" / "workflows"
    for f in wf.glob("*.yml"):
        txt = f.read_text(encoding="utf-8")
        if "SIGHTINGS_PATH" in txt:
            assert "SIGHTINGS_ALLOW_CREATE" not in txt, f.name
