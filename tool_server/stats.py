"""대시보드 집계 조회 — 운영 전용 /api/stats 몸통.

인증은 단일 공유 토큰이다. 공개 뷰어 경로와 섞지 않는다 — 신뢰 모델이
다르고, 섞으면 한쪽 사고가 다른 쪽으로 번진다.

HTTP 껍데기(api/stats.py)와 분리된 순수 함수라 단위 테스트가 가능하다.
"""
from __future__ import annotations

import datetime as _dt
import hmac
import os
import re

from tool_server.supa import select_rows

VIEWS = {"corps", "sources", "traffic", "visitors", "timeline"}
DAYS_DEFAULT = 30
DAYS_MAX = 365
ROW_LIMIT = 500

# PostgREST 필터 값에 그대로 끼워 넣으므로 형태를 제한한다.
_VISITOR_ID_RE = re.compile(r"^[A-Za-z0-9._~-]{1,64}$")


def token_ok(supplied: str) -> bool:
    """상수시간 비교.

    `==`는 첫 불일치에서 끊겨 응답 시간으로 접두사가 새어 나간다.
    """
    expected = os.environ.get("OPS_TOKEN") or ""
    if not expected or not supplied:
        return False
    return hmac.compare_digest(supplied, expected)


def _days(raw) -> int:
    try:
        value = int(raw)
    except (TypeError, ValueError):
        return DAYS_DEFAULT
    return max(1, min(DAYS_MAX, value))


def _since(days: int) -> str:
    cutoff = _dt.datetime.now(_dt.timezone.utc) - _dt.timedelta(days=days)
    return cutoff.date().isoformat()


def _merge_corps(rows: list[dict]) -> list[dict]:
    """뷰는 (회사, 날짜)로 쪼개져 있다. 회사 단위로 다시 합친다.

    `visitors`는 날짜별 순방문자의 합이라 실제 순방문자의 **상한**이다.
    같은 사람이 이틀에 걸쳐 보면 2로 센다 — 대시보드는 이 열을
    "방문 연인원"으로 표기한다. 정확한 순방문자를 내려면 뷰에서 날짜를
    빼야 하는데 그러면 기간 필터가 불가능해진다(의도된 트레이드오프).
    """
    merged: dict[tuple, dict] = {}
    for row in rows:
        key = (row.get("corp_name"), row.get("stock_code"))
        slot = merged.setdefault(
            key,
            {"corp_name": key[0], "stock_code": key[1], "views": 0, "visitors": 0},
        )
        slot["views"] += int(row.get("views") or 0)
        slot["visitors"] += int(row.get("visitors") or 0)
    return sorted(merged.values(), key=lambda r: (-r["views"], r["corp_name"] or ""))


def handle_stats(query: dict, token: str) -> tuple[int, dict]:
    """(status, body).

    토큰을 설정하지 않은 채 배포하면 접속 로그 전체가 열린 상태가 된다 —
    그럴 바엔 503으로 닫는다(열린 채로 도는 것보다 안 도는 게 낫다).
    """
    if not (os.environ.get("OPS_TOKEN") or ""):
        return 503, {"error": "OPS_TOKEN이 설정되지 않았습니다"}
    if not token_ok(token):
        return 401, {"error": "unauthorized"}

    view = (query.get("view") or "corps").strip()
    if view not in VIEWS:
        return 400, {"error": "unknown view"}

    days = _days(query.get("days"))
    since = _since(days)

    if view == "corps":
        rows = select_rows(
            f"v_corp_ranking?day=gte.{since}&order=views.desc&limit={ROW_LIMIT}"
        )
        return 200, {"view": view, "days": days, "rows": _merge_corps(rows)}

    if view == "traffic":
        rows = select_rows(f"v_traffic_daily?day=gte.{since}&order=day.asc")
        return 200, {"view": view, "days": days, "rows": rows}

    if view == "sources":
        rows = select_rows(
            f"v_referrer_summary?day=gte.{since}&order=hits.desc&limit={ROW_LIMIT}"
        )
        return 200, {"view": view, "days": days, "rows": rows}

    if view == "visitors":
        rows = select_rows(
            f"v_visitor_sessions?last_seen=gte.{since}"
            f"&order=last_seen.desc&limit={ROW_LIMIT}"
        )
        return 200, {"view": view, "days": days, "rows": rows}

    visitor_id = (query.get("visitor_id") or "").strip()
    if not _VISITOR_ID_RE.match(visitor_id):
        return 400, {"error": "visitor_id가 필요합니다"}
    rows = select_rows(
        f"viewer_events?visitor_id=eq.{visitor_id}&order=ts.desc&limit={ROW_LIMIT}"
    )
    return 200, {"view": view, "visitor_id": visitor_id, "rows": rows}
