"""merge_sightings_files — 동시 push 충돌 복구용 두 파일 union 병합 검증."""
import json
import subprocess
import sys
from pathlib import Path


def _write(p, obj):
    Path(p).write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")


def _run(ours, base):
    root = Path(__file__).resolve().parents[1]
    subprocess.run([sys.executable, "-m", "scripts.merge_sightings_files",
                    str(ours), str(base)], cwd=root, check=True)


def test_union_and_backfill_marker_taken_from_ours(tmp_path):
    ours = tmp_path / "ours.json"
    base = tmp_path / "base.json"
    # ours = 5년 재스윕 진행분(2021), base = 원격(discover가 추가한 최신 + 옛 마커)
    _write(ours, {"version": 1, "sightings": {
        "홍길동": [{"corp": "A", "corp_code": "001", "date": "2021-08",
                   "rcept_no": "r1", "kind": "person"}]},
        "backfill": {"done_until": "20211231"}})
    _write(base, {"version": 1, "sightings": {
        "김철수": [{"corp": "B", "corp_code": "002", "date": "2026-06",
                   "rcept_no": "r2", "kind": "person"}]},
        "backfill": {"done_until": "20260703"}})
    _run(ours, base)
    out = json.loads(base.read_text(encoding="utf-8"))
    # 합집합
    assert sorted(out["sightings"]) == ["김철수", "홍길동"]
    # 백필 마커는 '우리 run'의 것으로 덮음 (옛 20260703이 5년 재스윕을 막지 않도록)
    assert out["backfill"]["done_until"] == "20211231"


def test_dedup_same_record(tmp_path):
    ours = tmp_path / "ours.json"
    base = tmp_path / "base.json"
    rec = {"corp": "A", "corp_code": "001", "date": "2024-01",
           "rcept_no": "r1", "kind": "person"}
    _write(ours, {"version": 1, "sightings": {"홍길동": [rec]},
                  "backfill": {"done_until": "20240101"}})
    _write(base, {"version": 1, "sightings": {"홍길동": [dict(rec)]}})
    _run(ours, base)
    out = json.loads(base.read_text(encoding="utf-8"))
    # 같은 (rcept_no, corp_code)라 중복 없이 1건
    assert len(out["sightings"]["홍길동"]) == 1
