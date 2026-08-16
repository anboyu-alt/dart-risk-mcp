"""카탈로그 한글 표시 라벨 로더.

TAXONOMY의 name·description은 상당수가 영문이라 사용자 노출용으로 쓸 수 없다
(name 45개 중 41개 영문 — 2026-08-16 실측). labels_ko.json이 한글 표시 텍스트의
단일 출처이며, 누락 시에만 TAXONOMY로 폴백한다.
"""
from __future__ import annotations

import json
from pathlib import Path

_DEFAULT_PATH = Path(__file__).resolve().parents[2] / "data" / "catalog" / "labels_ko.json"


def load_labels(path: Path | None = None) -> dict[str, dict]:
    """labels_ko.json을 읽는다. 파일이 없으면 빈 dict(전부 TAXONOMY 폴백)."""
    p = path or _DEFAULT_PATH
    if not p.exists():
        return {}
    return json.loads(p.read_text(encoding="utf-8"))


def label_for(tid: str, labels: dict[str, dict], taxonomy: dict[str, dict]) -> dict:
    """유형 하나의 표시 라벨을 결정한다. 라벨 우선, 없으면 TAXONOMY 폴백."""
    entry = taxonomy.get(tid, {})
    lab = labels.get(tid) or {}
    return {
        "title": lab.get("title") or entry.get("name", tid),
        "definition": lab.get("definition") or entry.get("description", ""),
        "red_flags": lab.get("red_flags") or list(entry.get("red_flags") or []),
    }
