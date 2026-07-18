"""라이브 리스크 도구(docs/tool/)용 신호 데이터 codegen.

signals.py·taxonomy.py를 유일한 진실(source of truth)로 두고, 브라우저가
읽는 docs/tool/signals-data.json을 생성한다. Python 로직과 JS 도구 사이의
키워드 이중 관리를 방지한다.

공개 아티팩트 경계 (v0.8.5 무점수 원칙의 공개 데이터 확장):
- 신호의 내부 정렬용 score, 패턴의 severity/field_evidence는 내보내지 않는다.
- 인물 관련 데이터는 애초에 포함 대상이 아니다.

사용:
    python scripts/export_tool_data.py          # docs/tool/signals-data.json 생성
"""
import json
import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dart_risk_mcp.core.signals import (  # noqa: E402
    SIGNAL_TYPES,
    SIGNAL_KEY_TO_TAXONOMY,
    CAPITAL_EVENT_KEYS,
    _AMENDMENT_RE,
)
from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS  # noqa: E402

# taxonomy ID 첫 자리 → 사용자용 카테고리 라벨 (CLAUDE.md 카테고리 표와 동일)
CATEGORY_LABELS = {
    "0": "기타",
    "1": "CB/채권",
    "2": "자본구조",
    "3": "경영권",
    "4": "거버넌스",
    "5": "기업활동",
    "6": "회계/재무",
    "7": "시장조작",
    "8": "위기/부실",
}


def _taxonomy_of(signal_key: str) -> str:
    """taxonomy ID 반환 — 복수 매핑(list)이면 첫 항목."""
    tax = SIGNAL_KEY_TO_TAXONOMY.get(signal_key, "")
    if isinstance(tax, (list, tuple)):
        tax = tax[0] if tax else ""
    return tax


def _category_of(signal_key: str) -> int:
    tax_id = _taxonomy_of(signal_key)
    head = tax_id.split(".")[0] if tax_id else ""
    return int(head) if head.isdigit() else 0


def build_signals_data() -> dict:
    """docs/tool/signals-data.json 내용 생성 (score·severity 미포함)."""
    signals = [
        {
            "key": s["key"],
            "label": s["label"],
            "keywords": list(s["keywords"]),
            "taxonomy": _taxonomy_of(s["key"]),
            "category": _category_of(s["key"]),
        }
        for s in SIGNAL_TYPES
    ]
    patterns = [
        {
            "key": slug,
            "name": p["name"],
            "description": p["description"],
            "signal_sequence": list(p["signal_sequence"]),
            "timeline_months": p["timeline_months"],
        }
        for slug, p in CROSS_SIGNAL_PATTERNS.items()
    ]
    return {
        "signals": signals,
        "patterns": patterns,
        "categories": CATEGORY_LABELS,
        "capital_event_keys": sorted(CAPITAL_EVENT_KEYS),
        "amendment_pattern": _AMENDMENT_RE.pattern,
    }


def main() -> int:
    out_path = os.path.join(os.path.dirname(__file__), "..",
                            "docs", "tool", "signals-data.json")
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    data = build_signals_data()
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    print(f"signals-data.json 생성: 신호 {len(data['signals'])}종, "
          f"패턴 {len(data['patterns'])}종 → {os.path.normpath(out_path)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
