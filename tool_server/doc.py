"""공시 원문 추출 — 공개 뷰어의 /api/doc 몸통.

DART document.xml ZIP은 CORS도 없고 브라우저에서 해제하기도 무겁다.
서버에서 ZIP을 받아 구조 보존 텍스트만 JSON으로 내려준다
(`fetch_disclosure_full` 재사용 — SE 2단 파이프라인과 동일 코어 경로).

HTTP 껍데기(api/doc.py)와 분리된 순수 함수라 단위 테스트가 가능하다.
"""
import re

from dart_risk_mcp.core.dart_client import fetch_disclosure_full

_RCEPT_RE = re.compile(r"^\d{14}$")

# 실패 문구는 se_server/api/handlers.py의 _DART_FETCH_FAILED_MSG와 같은
# 취지 — DART 쪽 실패를 우리 서버 오류(500)로 오해시키지 않는다.
_DART_FETCH_FAILED_MSG = (
    "DART에서 공시 원문을 받지 못했습니다. 잠시 후 다시 시도하거나 "
    "DART 원문 링크를 이용하세요."
)

MAX_CHARS_MIN = 1000
MAX_CHARS_MAX = 20000
MAX_CHARS_DEFAULT = 8000


def _clamp_max_chars(raw: str | None) -> int:
    try:
        value = int(raw) if raw is not None and raw != "" else MAX_CHARS_DEFAULT
    except (TypeError, ValueError):
        return MAX_CHARS_DEFAULT
    return max(MAX_CHARS_MIN, min(MAX_CHARS_MAX, value))


def handle_doc(query: dict, api_key: str) -> tuple[int, dict]:
    """(status, body) 반환. query는 단일 값 dict (예: {"rcept_no": "..."}).

    실패 판별은 se_server/api/handlers.py `_disclosure`에서 검증된 규칙을
    복제한다(se_server import 금지 — 신뢰 모델 분리):
    - core는 실패를 예외 대신 빈 결과로 삼킨다. ZIP 자체를 못 받으면
      files가 비고(→502), ZIP은 받았는데 본문이 비면 text가 빈다(→404).
    """
    if not api_key:
        return 400, {"error": "X-DART-Key 헤더가 필요합니다"}

    rcept_no = (query.get("rcept_no") or "").strip()
    if not _RCEPT_RE.match(rcept_no):
        return 400, {"error": "rcept_no는 14자리 숫자여야 합니다"}

    max_chars = _clamp_max_chars(query.get("max_chars"))

    try:
        result = fetch_disclosure_full(rcept_no, api_key, max_chars=max_chars) or {}
    except Exception:
        return 502, {"error": _DART_FETCH_FAILED_MSG}

    if not result.get("files"):
        return 502, {"error": _DART_FETCH_FAILED_MSG}

    text = result.get("text") or ""
    if not text:
        return 404, {"error": "공시 원문을 찾을 수 없습니다"}

    return 200, {
        "rcept_no": rcept_no,
        "text": text,
        "char_count": result.get("char_count", len(text)),
        "truncated": bool(result.get("truncated")),
    }
