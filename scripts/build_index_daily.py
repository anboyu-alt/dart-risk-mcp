"""코스피·코스닥 일별 종가를 모아 공개 뷰어가 읽는 정적 파일로 만든다.

    python scripts/build_index_daily.py                 # 마지막 날짜 다음부터 어제까지 이어 받기
    python scripts/build_index_daily.py --from 20230101 # 처음 채우기(빈 날만 받는다)

출력: `docs/tool/index-daily.json`
    {"meta": {...}, "kospi": {"YYYYMMDD": 종가}, "kosdaq": {...}, "holidays": [...]}

왜 저장하나(2026-09-23 제작자 결정): 뷰어 「공시와 시장」 차트는 종목 시세 위에
지수를 겹치는데, KRX Open API는 하루치 시장 전체만 주므로 1년 지수에만 약 260번의
호출이 들었다 — 로딩 시간의 절반이 사용자마다 같은 값을 다시 받는 데 쓰였다. 지수는
사람마다 다르지 않아 한 번 받아 두고 정적 파일로 내보낸다. 종목 시세는 여전히 사용자
본인 키로만 받는다(약관 제11조 ② — CLAUDE.md 「KRX Open API 약관 경계」).

⚠ 휴장일은 빈 응답으로 온다. 그런데 **최근 며칠의 빈 응답은 발표 전일 수 있어**
(core `KRX_EMPTY_GRACE_DAYS`와 같은 판단) 휴장일로 적지 않는다 — 적으면 다음 실행이
그날을 다시 받지 않아 영영 비는다.
⚠ 키가 없으면 경고만 남기고 성공으로 끝난다(cron이 시크릿 없이 매일 실패로 뜨지 않게).
⚠ 키 값은 어디에도 출력하지 않는다.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from dart_risk_mcp.core.krx_client import (  # noqa: E402
    KRX_EMPTY_GRACE_DAYS,
    KRX_INDEX_BASE,
    KRX_INDEX_NAMES,
    _normalize_index_row,
)

OUT = ROOT / "docs" / "tool" / "index-daily.json"
# 파일 키 → KRX api. 뷰어는 종목 시장(stk/ksq)으로 이 키를 고른다.
SERIES = {"kospi": "kospi_dd_trd", "kosdaq": "kosdaq_dd_trd"}
DEFAULT_FROM = "20230101"
# ⚠ 실측(2026-09-23): 동시 8로 972일(1,944콜)을 1분 남짓에 보내자(초당 30콜 넘게)
# KRX 앞단이 IP를 막아 모든 호출이 403 Access Denied가 됐고 약 10분 뒤 풀렸다.
# 짧은 구간(120콜)은 동시 24도 괜찮았으니 문제는 순간 동시성이 아니라 지속 속도다.
# 백필은 드물게 한 번이니 느려도 된다 — 4로 두고, 실패가 나면 그 자리에서 멈춘다.
CONCURRENCY = 4
KST = timezone(timedelta(hours=9))


def _key() -> str:
    k = os.environ.get("KRX_API_KEY", "").strip()
    if k:
        return k
    if sys.platform == "win32":  # 제작자 PC는 User 환경변수에만 둔다
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_CURRENT_USER, "Environment") as h:
                return str(winreg.QueryValueEx(h, "KRX_API_KEY")[0]).strip()
        except OSError:
            return ""
    return ""


def _weekdays(start: str, end: str) -> list[str]:
    d = datetime.strptime(start, "%Y%m%d").date()
    e = datetime.strptime(end, "%Y%m%d").date()
    out = []
    while d <= e:
        if d.weekday() < 5:
            out.append(d.strftime("%Y%m%d"))
        d += timedelta(days=1)
    return out


def _fetch_day(sess: requests.Session, key: str, bas_dd: str) -> dict | None:
    """그날 두 지수의 종가. 휴장일이면 {}(빈 dict), 실패면 None."""
    got = {}
    for name, api in SERIES.items():
        for attempt in range(3):
            try:
                r = sess.get(f"{KRX_INDEX_BASE}/{api}", params={"basDd": bas_dd},
                             headers={"AUTH_KEY": key}, timeout=30)
                if r.status_code == 200:
                    break
            except requests.RequestException:
                pass
            time.sleep(1 + attempt)
        else:
            return None
        rows = (r.json() or {}).get("OutBlock_1")
        if not isinstance(rows, list):
            return None
        if not rows:
            return {}
        row = next((x for x in rows if x.get("IDX_NM") == KRX_INDEX_NAMES[api]), None)
        if row is None:
            return None
        close = _normalize_index_row(bas_dd, row)["close"]
        if close is None:
            return None
        got[name] = close
    return got


def load() -> dict:
    if OUT.exists():
        return json.loads(OUT.read_text(encoding="utf-8"))
    return {"meta": {}, "kospi": {}, "kosdaq": {}, "holidays": []}


def save(data: dict) -> None:
    days = sorted(set(data["kospi"]) | set(data["kosdaq"]))
    data["kospi"] = {d: data["kospi"][d] for d in sorted(data["kospi"])}
    data["kosdaq"] = {d: data["kosdaq"][d] for d in sorted(data["kosdaq"])}
    data["holidays"] = sorted(set(data["holidays"]))
    data["meta"] = {
        "source": "한국거래소 통계정보 — KRX Open API idx/kospi_dd_trd · kosdaq_dd_trd",
        "series": {"kospi": "코스피", "kosdaq": "코스닥"},
        "field": "종가(CLSPRC_IDX)",
        "first": days[0] if days else "",
        "last": days[-1] if days else "",
        "days": len(days),
    }
    OUT.write_text(json.dumps(data, ensure_ascii=False, separators=(",", ":")) + "\n",
                   encoding="utf-8")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--from", dest="start", default="")
    args = ap.parse_args()

    key = _key()
    if not key:
        print("::warning::KRX_API_KEY 없음 — 지수 갱신을 건너뜁니다(저장소 시크릿에 등록하세요)")
        return 0

    data = load()
    known = set(data["kospi"]) & set(data["kosdaq"])
    holidays = set(data["holidays"])
    today = datetime.now(KST).date()
    end = (today - timedelta(days=1)).strftime("%Y%m%d")
    start = args.start or data.get("meta", {}).get("first") or DEFAULT_FROM
    grace_floor = (today - timedelta(days=KRX_EMPTY_GRACE_DAYS)).strftime("%Y%m%d")
    todo = [d for d in _weekdays(start, end) if d not in known and d not in holidays]
    print(f"받을 평일 {len(todo)}일 ({start}~{end})")

    sess = requests.Session()
    failed, pending, added, skipped = [], [], 0, 0
    with ThreadPoolExecutor(CONCURRENCY) as ex:
        for i in range(0, len(todo), CONCURRENCY):
            chunk = todo[i:i + CONCURRENCY]
            for d, got in zip(chunk, ex.map(lambda x: _fetch_day(sess, key, x), chunk)):
                if got is None:
                    failed.append(d)
                elif not got:
                    if d >= grace_floor:
                        pending.append(d)       # 발표 전일 수 있다 — 휴장일로 적지 않는다
                    else:
                        holidays.add(d)
                else:
                    data["kospi"][d] = got["kospi"]
                    data["kosdaq"][d] = got["kosdaq"]
                    added += 1
            if failed:
                # 막힌 뒤 계속 보내면 차단만 길어진다 — 받은 것만 저장하고 멈춘다.
                skipped = len(todo) - (i + len(chunk))
                break
            if i % (CONCURRENCY * 25) == 0:
                time.sleep(1)   # 지속 속도를 낮춘다(초당 수 콜)
    data["holidays"] = sorted(holidays)
    save(data)
    print(f"추가 {added}일 · 휴장 누적 {len(holidays)}일 · 발표 전 {len(pending)}일 · 실패 {len(failed)}일"
          + (f" {failed[:10]}" if failed else "")
          + (f" · 실패 뒤 멈춰 {skipped}일 미조회(다음 실행이 이어 받는다)" if skipped else ""))
    print(f"파일 범위 {data['meta']['first']}~{data['meta']['last']} · {data['meta']['days']}거래일")
    return 1 if failed and not added else 0


if __name__ == "__main__":
    sys.exit(main())
