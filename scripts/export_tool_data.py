"""라이브 리스크 도구(docs/tool/)용 신호 데이터 codegen.

signals.py·taxonomy.py를 유일한 진실(source of truth)로 두고, 브라우저가
읽는 docs/tool/signals-data.json을 생성한다. Python 로직과 JS 도구 사이의
키워드 이중 관리를 방지한다.

공개 아티팩트 경계 (v0.8.5 무점수 원칙의 공개 데이터 확장):
- 신호의 내부 정렬용 score, 패턴의 severity(CRITICAL/HIGH 등급)는
  내보내지 않는다 — 등급·판정으로 읽히기 때문이다.
- 패턴의 field_evidence(금감원 보도자료·실제 사례 인용, 예: "2025-03-10
  금감원: 사모CB·BW 허위자금조달 조직적 세력 적발 — 검찰 고발")는
  SE-13 Task 2부터 내보낸다. severity와 달리 이건 날짜·기업명·규제기관
  조치·금액의 사실 서술이지 우리가 매긴 판정이 아니다 — "왜 이 패턴이
  등록됐는지"를 뒷받침하는 근거이지 기업 위험도 등급이 아니다. 9종 전체
  원문을 v0.8.5 판정 어휘 기준으로 실측 검사해 통과한 뒤 그대로(왜곡
  없이) 반영했다. 재리뷰(2026-07-30)에서 기계적 검사망을 통과하고도
  남은 평가적 어구 2건(debt_spiral의 "돌려막기", related_party_hollowing의
  "경영권 방어용")이 발견돼 export 계층에서만 트리밍한다 —
  `_FIELD_EVIDENCE_EXPORT_TRIM` 참고. core taxonomy.py 원문은 그대로 두고
  나머지 7종은 여전히 core와 byte-for-byte 동일하다.
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
from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS, TAXONOMY  # noqa: E402
from dart_risk_mcp.core.explain import (  # noqa: E402
    signal_to_prose,
    pattern_to_prose,
    pattern_checkpoints,
)
from dart_risk_mcp.core.dart_client import _FS_ALIASES  # noqa: E402
from dart_risk_mcp.core import qualifiers as _q  # noqa: E402
from dart_risk_mcp.core.signals import AMBIGUOUS_SIGNAL_KEYS  # noqa: E402

# 뷰어 심화 블록(재무 핵심)에서 쓰는 계정 별칭 부분집합
_FS_ALIAS_KEYS = ("매출", "영업이익", "당기순이익", "자본총계", "자본금")

# 뷰어 전용 추가 별칭 — core _FS_ALIASES에 없는 계정 (fnlttSinglAcnt 주요계정)
_VIEWER_EXTRA_ALIASES = {
    "이익잉여금": ["이익잉여금", "이익잉여금(결손금)", "이익잉여금(결손금)계"],
}

# taxonomy ID 첫 자리 → 사용자용 카테고리 라벨 (CLAUDE.md 카테고리 표와 동일)
CATEGORY_LABELS = {
    "0": "기타",
    "1": "CB/채권",
    "2": "자본구조",
    "3": "경영권",
    "4": "거버넌스",
    "5": "기업활동",
    "6": "회계/재무",
    "7": "시장감시",  # '시장조작'은 단정적 → 감시 대상 유형이라는 중립 표현
    "8": "위기/부실",
}

# field_evidence export-layer 트리밍 (Task 2 리뷰 지적 2건, 2026-07-30).
#
# Task 2 게이트는 CROSS_SIGNAL_PATTERNS 9종의 field_evidence 전체를 "판정
# 어휘 없는 사실 인용"으로 실측 검사한 뒤 내보내기로 했으나, 재리뷰에서
# 기계적 검사망(_SCORE_GRADE_PATTERNS·_SEVERITY_EMOJI)을 통과하고도 남은
# 평가적 표현 2건이 발견됐다:
#   - debt_spiral: "돌려막기" — 규제기관 인용이 아닌 구어체·경멸적 뉘앙스
#     (금융 셸게임 함의). 같은 개념의 중립적 구조 용어는 이 코드베이스가
#     이미 쓰는 "차환"(taxonomy.py 1.5 keywords, CB_ROLLOVER 개념) — 새
#     단어를 만들지 않고 기존 용어로 치환.
#   - related_party_hollowing: "경영권 방어용" — 회생신청 "동기"를 단정.
#     근거 인용 없이 의도를 읽는 서술이라 동기절만 삭제, 사실(기업명·
#     이벤트·날짜)은 보존.
#
# core CROSS_SIGNAL_PATTERNS(taxonomy.py) 원문은 건드리지 않는다 — MCP
# 도구 프로즈(find_pattern_match 등)는 이 계획의 Global Constraints상
# 서사적 어휘 허용 범위가 더 넓어 트리밍 대상이 아니다. 이 딕셔너리는
# **export 산출물에서만** 해당 문자열을 치환한다(정확히 일치할 때만 —
# 원문 그대로를 key로 둔다). core 쪽 문구가 바뀌면 이 매핑은 조용히
# no-op이 된다(_export_field_evidence가 dict.get(item, item) fallback을
# 쓴다) — 예외로 드러나지 않으므로 실제 가드는
# test_trimmed_field_evidence_removes_judgment_phrases다: core 원문이
# 바뀌면 트리밍된 문자열이 더 이상 나오지 않아 이 테스트가 실패한다.
_FIELD_EVIDENCE_EXPORT_TRIM: dict[str, dict[str, str]] = {
    "debt_spiral": {
        "위메이드: CB/EB 돌려막기 (20250903)": "위메이드: CB/EB 차환 (20250903)",
    },
    "related_party_hollowing": {
        "동성제약: 경영권 방어용 회생신청 (20251014)": "동성제약: 회생신청 (20251014)",
    },
}


def _export_field_evidence(slug: str, evidence: list[str]) -> list[str]:
    """core field_evidence를 export용으로 변환 — 위 트림맵에 있는 패턴의
    해당 문자열만 치환, 나머지는 core와 완전히 동일(list()로 복사)."""
    trims = _FIELD_EVIDENCE_EXPORT_TRIM.get(slug, {})
    return [trims.get(item, item) for item in evidence]


# SE 표시 전용 — 위험 신호가 아닌 고빈도 정기 보고 (SE-7 Task 3).
# core SIGNAL_TYPES에는 절대 넣지 않는다(계획 Global Constraints: 위험
# 신호 8분류와 다른 층위라 섞으면 calculate_risk_score 등 위험 신호
# 집계가 오염된다). 임원 개개인이 지분 1주만 바뀌어도 각자 내는 개별
# 보고처럼 정례적으로 나오고 위험 신호가 아닌 게 맞는 유형만 담는다 —
# "기타"(모른다)가 아니라 "안다, 정기 보고다"(안다 + 위험 신호 아님)라는
# 별도 사실 범주다. 실측(task-3-brief.md): 삼성전자 "기타" 982건 중
# 924건이 아래 목록 첫 항목 하나 때문이었고, insider_timeline 섹션이
# 이미 그 데이터를 별도로 다룬다 — 여기서는 목록 색칠에서 중복
# 강조하지 않고 "기타"와만 구분한다.
ROUTINE_FILING_KEYWORDS = [
    "임원ㆍ주요주주특정증권등소유상황보고서",
    "최대주주등소유주식변동신고서",
    "사업보고서",
    "반기보고서",
    "분기보고서",
    "주주총회소집공고",
    "주주총회소집결의",
    "기업설명회",
]

# 위 목록에 매칭된 공시가 받는 카테고리 번호. 위험 신호(SIGNAL_TYPES)의
# taxonomy 카테고리는 0(기타)~8(위기/부실)만 쓰므로 9는 절대 충돌하지
# 않는다 — docs/tool/se/app.js의 classifyDisclosureCategory가 위험 신호
# 키워드 매칭에 전부 실패한 뒤에만(위험 신호가 항상 먼저 이긴다) 이
# 번호를 반환한다.
ROUTINE_FILING_CATEGORY = 9
ROUTINE_FILING_LABEL = "정기 보고"  # 사실 라벨 — 판정 어휘 아님(v0.8.5)


# severity 2단계 접기 (뷰어 '주의/참고' 배지용) — severity 문자열 원값은
# 계속 미노출한다. CRITICAL/HIGH → 주의(true), 그 외 → 참고(false)의
# 불리언 하나만 내보내 "등급"으로 읽힐 표면을 없앤다. 라벨 문자열
# ("주의"/"참고")은 뷰어 JS에만 둔다.
#
# 패턴(CROSS_SIGNAL_PATTERNS)에는 넣지 않는다 — 9종 전원이 CRITICAL/HIGH라
# 불리언이 상수가 되고(정보량 0), 상수 배지는 경고 중첩 노이즈만 만든다.
_CAUTION_SEVERITIES = frozenset({"CRITICAL", "HIGH"})


def _caution_of(signal_key: str) -> bool:
    """신호의 taxonomy 중 하나라도 CRITICAL/HIGH severity면 주의(true)."""
    return any(
        TAXONOMY.get(tax_id, {}).get("severity") in _CAUTION_SEVERITIES
        for tax_id in _taxonomies_of(signal_key)
    )


def _taxonomies_of(signal_key: str) -> list[str]:
    """신호의 taxonomy ID 전체 목록 (단일 매핑도 리스트로 정규화)."""
    tax = SIGNAL_KEY_TO_TAXONOMY.get(signal_key, "")
    if isinstance(tax, (list, tuple)):
        return [t for t in tax if t]
    return [tax] if tax else []


def _category_of(signal_key: str) -> int:
    """대표 카테고리 — 복수 taxonomy면 무거운 쪽(높은 번호).

    카테고리 번호는 대체로 뒤로 갈수록 무겁다(7 시장조작, 8 위기/부실).
    예: EMBEZZLE ['5.3','8.1'] → 8, INQUIRY ['4.3','7.1'] → 7.
    """
    cats = []
    for tax_id in _taxonomies_of(signal_key):
        head = tax_id.split(".")[0]
        if head.isdigit():
            cats.append(int(head))
    return max(cats) if cats else 0


def build_signals_data() -> dict:
    """docs/tool/signals-data.json 내용 생성 (score·severity 미포함)."""
    # 배열 순서 = 내부 우선순위 (헤드라인 선정용) — 숫자 score 자체는 미노출
    signals = [
        {
            "key": s["key"],
            "label": s["label"],
            "keywords": list(s["keywords"]),
            "taxonomies": _taxonomies_of(s["key"]),
            "category": _category_of(s["key"]),
            "prose": signal_to_prose(s["key"]),
            "caution": _caution_of(s["key"]),
        }
        for s in sorted(SIGNAL_TYPES, key=lambda x: -x["score"])
    ]
    patterns = [
        {
            "key": slug,
            "name": p["name"],
            "description": p["description"],
            "signal_sequence": list(p["signal_sequence"]),
            "timeline_months": p["timeline_months"],
            # 사실 인용(날짜·기업명·규제기관 조치) — severity는 계속 제외.
            # 2개 패턴(debt_spiral·related_party_hollowing)은 재리뷰에서
            # 발견된 평가적 어구 2건을 export 계층에서만 트리밍한다 —
            # _FIELD_EVIDENCE_EXPORT_TRIM 주석 참고. 나머지 7종은 원문 그대로.
            "field_evidence": _export_field_evidence(slug, p["field_evidence"]),
            # SE-14 후속: 서술 강화 — prose(비전문가용 2~3문장 산문)와
            # checkpoints(원문에서 확인할 지점 불릿). 둘 다 core/explain.py
            # PATTERN_PROSE·PATTERN_CHECKPOINTS가 유일한 진실. 판정 어휘
            # 없음(v0.8.5 원칙 그대로).
            "prose": pattern_to_prose(slug),
            "checkpoints": pattern_checkpoints(slug),
        }
        for slug, p in CROSS_SIGNAL_PATTERNS.items()
    ]
    # 위험 신호 카테고리(0~8) 라벨은 그대로 두고, 정기 보고 카테고리 하나만
    # 얹는다 — CATEGORY_LABELS 자체는 taxonomy 파생값이라는 원래 뜻을
    # 유지하도록 복사본에만 추가한다(원본을 바꾸지 않는다).
    categories = dict(CATEGORY_LABELS)
    categories[str(ROUTINE_FILING_CATEGORY)] = ROUTINE_FILING_LABEL
    return {
        "signals": signals,
        "patterns": patterns,
        "categories": categories,
        "capital_event_keys": sorted(CAPITAL_EVENT_KEYS),
        "amendment_pattern": _AMENDMENT_RE.pattern,
        # 위험 신호(signals)와 층위가 다른 별도 키다 — 이름에 "signal"·
        # "risk"를 넣지 않는다(브리프: 위험 신호가 아니라는 게 이 태스크의
        # 요점이다).
        "routine_filing_keywords": list(ROUTINE_FILING_KEYWORDS),
        "fs_aliases": {**{k: list(_FS_ALIASES[k]) for k in _FS_ALIAS_KEYS},
                       **_VIEWER_EXTRA_ALIASES},
        # 신호 한정층 규칙 — 데이터만 내보내고 로직은 뷰어 JS가 이식한다.
        # 문자열 목록의 이중 관리를 막는 것이 목적이다(키워드와 동일한 원칙).
        "qualifier_rules": {
            "third_party_titles": list(_q.THIRD_PARTY_TITLES),
            "phase_tails": list(_q.PHASE_TAILS),
            "subsidiary_subtitles": list(_q.SUBSIDIARY_SUBTITLES),
            "related_party_prefix": _q.RELATED_PARTY_PREFIX,
            "amendment_tags": list(_q.AMENDMENT_TAGS),
            "tails": list(_q.TAILS),
            "label_overrides": {
                k: dict(v) for k, v in _q.LABEL_OVERRIDES.items()
            },
            "direction_notes": {
                k: {"markers": list(v["markers"]), "note": v["note"]}
                for k, v in _q.DIRECTION_NOTES.items()
            },
        },
        "ambiguous_signal_keys": sorted(AMBIGUOUS_SIGNAL_KEYS),
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
