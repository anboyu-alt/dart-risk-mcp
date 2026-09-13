"""공개 뷰어 쿼터 — 전역 일일 상한과 IP별 스캔 상한(서버 측 카운터).

릴레이가 **운영자 키**로 DART를 대신 호출해 주게 되면서 생긴 장치다. 키 없는
방문자도 도구를 쓸 수 있게 하되, 운영자의 하루 2만건(OpenDART 개인 인증키)을
뷰어가 다 먹어 배치 cron과 MCP 취재가 굶는 것을 막는다.

## 두 층이 하는 일이 다르다

- **전역 상한**(`DAILY_GLOBAL_CAP`)이 예산 방어선이다. 개인 한도가 얼마나 새든
  이 선에서 멈추므로 남는 몫이 지켜진다.
- **IP 상한**(`DAILY_IP_SCANS`)은 공평 분배 장치다. 한 사람이 하루치를 독식하지
  않게 한다. 브라우저 `localStorage` 카운터를 지우거나 시크릿 창을 열어 우회하는
  경로를 여기서 받는다 — **시크릿 창은 IP가 바뀌지 않는다.**

완전한 차단은 목표가 아니다. 우회하려면 VPN이나 회선 전환이 필요한데, 그 수고보다
자기 키를 발급받는 편이 싸다(개인 키는 증빙 없이 즉시 발급된다). 우회 비용이 정규
경로보다 비싸면 우회할 이유가 없다.

## 무엇을 저장하지 않는가

**"어느 방문자가 어느 회사를 조회했는가"는 저장하지 않는다.** 저장하는 것은 날짜별
숫자 둘뿐이다.

    q:g:<YYYYMMDD>        전역 DART 호출 수
    q:s:<ip>:<YYYYMMDD>   그 IP가 시작한 스캔 횟수

⚠ IP 층이 "기업 수"가 아니라 **"스캔 횟수"**인 것은 이 원칙의 결과다. 기업 수로
세려면 IP별 종목 집합을 들고 있어야 하는데 그게 곧 조회 이력이다. 정밀도를 조금
잃는 대신(같은 회사 재조회도 1회로 센다) 이력을 만들지 않는다. 브라우저 쪽
카운터는 자기 목록을 갖고 있으므로 거기서는 (종목, 창) 단위로 정확히 센다.

스캔 시작은 `list.json`의 **첫 페이지** 요청으로 식별한다 — 모든 스캔이 거기서
시작하고, 2페이지 이후는 같은 스캔의 연속이라 세지 않는다.

## 저장소가 없거나 실패하면 통과시킨다

쿼터는 예산 보호 장치이지 가용성을 깎을 이유가 없다. `UPSTASH_REDIS_REST_URL`·
`UPSTASH_REDIS_REST_TOKEN`이 없으면 조용히 비활성화되고(로컬 개발·셀프호스트),
네트워크 실패도 같은 취급이다. 그때 예산을 지키는 것은 전역 상한이 아니라
DART 자신의 `020`(한도 초과) 응답이며, `FetchList.fetch_failed` 경로가 그것을
"자료 없음"과 구분해 표기한다.
"""
from __future__ import annotations

import json
import os
import urllib.error
import urllib.request
from datetime import datetime, timedelta, timezone

# 하루 2만건(개인 인증키) 중 뷰어 몫. 나머지 4천은 릴레이를 거치지 않는 둘이
# 쓴다 — GitHub Actions cron(`secrets.DART_API_KEY`)과 운영자 본인의 MCP 취재.
# 그 둘은 이 카운터에 잡히지 않으므로 미리 떼어 둔다.
DAILY_GLOBAL_CAP = 16000

# IP당 하루 스캔 횟수. 브라우저 쪽 개인 한도(5곳)의 다섯 배로 잡았다 — 사무실·
# 학교의 공유 IP에서 여러 명이 동시에 써도 걸리지 않을 만큼 넉넉하되, 시크릿 창을
# 반복해 여는 우회는 막힌다.
DAILY_IP_SCANS = 25

# 날짜가 바뀌어도 하루치는 조회 가능하도록 이틀을 남긴다.
_TTL_SECONDS = 48 * 3600

_KST = timezone(timedelta(hours=9))
_TIMEOUT = 2.0

# 쿼터 판정 결과
ALLOW = "allow"            # 통과
DENY_GLOBAL = "global"     # 전역 상한 도달 — 방문자 탓이 아니다
DENY_IP = "ip"             # 이 IP가 오늘 몫을 다 썼다


def kst_day(now: datetime | None = None) -> str:
    """오늘 날짜를 KST 기준 YYYYMMDD로.

    ⚠ UTC로 세면 화면의 "오늘"과 어긋난다. 뷰어가 시간축을 KST로 정리하면서
    `end_de`가 하루 밀려 그날 오전 공시를 통째로 누락하던 문제를 고친 전례가
    있다(`docs/tool/index.html`의 `kstDate`) — 같은 축을 쓴다.
    """
    return (now or datetime.now(timezone.utc)).astimezone(_KST).strftime("%Y%m%d")


def enabled() -> bool:
    """저장소 자격증명이 있는가. 없으면 쿼터 자체가 비활성이다."""
    return bool(os.environ.get("UPSTASH_REDIS_REST_URL")
                and os.environ.get("UPSTASH_REDIS_REST_TOKEN"))


def _pipeline(commands: list[list[str]]) -> list | None:
    """Upstash REST 파이프라인 호출. 실패하면 None(= 판정 불가, 통과 취급).

    SDK를 쓰지 않고 REST를 직접 부른다 — 이 레포는 `requests`와 `mcp` 외
    의존성을 추가하지 않으며(CLAUDE.md 「코딩 규칙」), Vercel 함수 번들 크기가
    Functions Storage 한도에 걸린 전례가 있다(2026-09-07, `mcp` 제거).
    표준 라이브러리만 쓴다.
    """
    url = (os.environ.get("UPSTASH_REDIS_REST_URL") or "").rstrip("/")
    token = os.environ.get("UPSTASH_REDIS_REST_TOKEN") or ""
    if not url or not token:
        return None
    body = json.dumps(commands).encode("utf-8")
    req = urllib.request.Request(
        f"{url}/pipeline",
        data=body,
        headers={"Authorization": f"Bearer {token}",
                 "Content-Type": "application/json"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except (urllib.error.URLError, OSError, ValueError, TimeoutError):
        return None


def _result_int(entry) -> int | None:
    """Upstash 파이프라인 한 항목에서 정수 결과를 꺼낸다.

    항목이 `{"error": ...}`이거나 모양이 다르면 None — 판정 불가다.
    """
    if not isinstance(entry, dict):
        return None
    try:
        return int(entry.get("result"))
    except (TypeError, ValueError):
        return None


def check_and_count(client_ip: str | None, *, is_scan_start: bool,
                    day: str | None = None) -> str:
    """호출 하나를 세고 통과 여부를 돌려준다.

    `is_scan_start`가 참이면 IP 카운터도 함께 올린다(= `list.json` 첫 페이지).

    저장소가 없거나 실패하면 `ALLOW`다 — 판정할 수 없는 것을 거절로 바꾸지
    않는다. 「빈 값이 「없다」로 읽히면 안 된다」와 같은 계열의 판단이다.
    """
    if not enabled():
        return ALLOW
    d = day or kst_day()
    cmds: list[list[str]] = [["INCR", f"q:g:{d}"], ["EXPIRE", f"q:g:{d}", str(_TTL_SECONDS)]]
    ip_key = f"q:s:{client_ip}:{d}" if (is_scan_start and client_ip) else None
    if ip_key:
        cmds += [["INCR", ip_key], ["EXPIRE", ip_key, str(_TTL_SECONDS)]]
    out = _pipeline(cmds)
    if not isinstance(out, list) or not out:
        return ALLOW

    total = _result_int(out[0])
    if total is not None and total > DAILY_GLOBAL_CAP:
        return DENY_GLOBAL
    if ip_key and len(out) >= 3:
        scans = _result_int(out[2])
        if scans is not None and scans > DAILY_IP_SCANS:
            return DENY_IP
    return ALLOW


def deny_payload(reason: str) -> dict:
    """거절 사유를 화면이 구분해 적을 수 있는 형태로.

    ⚠ **전역 상한과 IP 상한을 같은 문구로 적으면 안 된다.** "공용 조회가 오늘
    한도에 도달했습니다"와 "이 회선에서 오늘 몫을 다 쓰셨습니다"는 다른 사실이고,
    섞이면 방문자가 남의 소진을 자기 탓으로 오해한다.
    """
    if reason == DENY_GLOBAL:
        return {
            "status": "quota",
            "quota": "global",
            "message": "공용 조회가 오늘 한도에 도달했습니다. "
                       "내일 다시 열리며, 지금 보시려면 DART 인증키를 입력하세요.",
        }
    return {
        "status": "quota",
        "quota": "ip",
        "message": "이 회선에서 오늘 무료 조회 몫을 모두 쓰셨습니다. "
                   "DART 인증키를 입력하면 제한 없이 조회할 수 있습니다.",
    }


def client_ip_from(headers) -> str | None:
    """프록시 체인의 첫 주소를 클라이언트 IP로 본다.

    `tool_server/track.py`의 `client_ip`와 같은 규칙이다 — 두 곳이 다른 답을
    내면 통계와 쿼터가 서로 다른 사람을 가리킨다.
    """
    chain = ""
    try:
        chain = (headers.get("x-forwarded-for") or "").strip()
    except AttributeError:
        return None
    if not chain:
        return None
    first = chain.split(",")[0].strip()
    return first or None
