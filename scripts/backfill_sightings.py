"""sightings 베이스 데이터 백필 — 과거 자금조달 공시를 청크 단위로 수집.

일일 크론(discover_actors)은 최근 2일만 스캔하므로, 도입 초기에는 반복 등장
판정의 베이스가 될 과거 데이터가 없다. 이 스크립트는 지정 구간(기본: 최근
365일)을 chunk_days 단위로 나눠 수집하고 sightings.json에 병합한다.

- 재개(resume): 진행 상황을 sightings.json의 backfill.done_until에 기록.
  중단·재실행 시 그 다음 청크부터 이어간다 (청크 중복은 rcept_no+corp_code
  dedup으로 무해). 단, done_until은 단일 전진 마커라 이미 완료한 구간보다
  더 과거의 --start로 다시 돌리려면 sightings.json에서 backfill 키를 지우고
  실행해야 한다.
- 예산(budget): DART 일일 쿼터(키당 2만 콜) 보호를 위해 자금조달 공시 처리
  건수에 상한을 둔다(건당 API 콜 약 2.5회 — 기본 3,500건 ≈ 9천 콜, 쿼터의
  절반). 초과 시 진행 상황을 저장하고 종료 — 다음 실행이 이어받는다.
- 등재(promote)는 하지 않는다 — 백필 완료 후 다음 일일 크론이 수행.

사용:
    python scripts/backfill_sightings.py [--start YYYY-MM-DD] [--end YYYY-MM-DD]
        [--chunk-days 7] [--max-funding 3500]
환경: DART_API_KEY, SIGHTINGS_PATH(private repo의 sightings.json), MAIL_*(선택).
"""
import argparse
import json
import os
import time
from datetime import datetime, timedelta
from pathlib import Path

from scripts.discover_actors import (
    collect_funding_sightings_range,
    merge_sightings,
    _load,
    _DEFAULT_SIGHTINGS,
)
from scripts.refresh_known_actors import send_mail, _api_key

BACKFILL_DAYS = 365
CHUNK_DAYS = 7
MAX_FUNDING = 3500       # 자금조달 공시 처리 상한 (약 9천 콜 ≈ 일일 쿼터의 절반)
CHUNK_MAX_PAGES = 30     # 청크당 목록 조회 상한 (3,000건)
PACE_SEC = 0.2           # 자금조달 공시 1건 추출 후 대기 (분당 상한 보호)


def make_chunks(start: datetime, end: datetime, chunk_days: int) -> list:
    """[start, end] 구간을 chunk_days 일 단위 (시작, 끝) 튜플 목록으로 분할."""
    chunks = []
    cur = start
    while cur <= end:
        cend = min(cur + timedelta(days=chunk_days - 1), end)
        chunks.append((cur, cend))
        cur = cend + timedelta(days=1)
    return chunks


def run_backfill(api_key: str, sightings_path: Path, start: datetime, end: datetime,
                 chunk_days: int = CHUNK_DAYS, max_funding: int = MAX_FUNDING) -> dict:
    """청크 순회 수집 + 병합 + 청크마다 저장. 진행 요약 dict 반환."""
    sdata = _load(sightings_path, {"version": 1, "sightings": {}})
    state = sdata.setdefault("backfill", {})
    done_until = state.get("done_until", "")

    chunks = make_chunks(start, end, chunk_days)
    total_funding = 0
    total_extracted = 0
    done_chunks = 0
    truncated_chunks = []
    finished = True

    for cstart, cend in chunks:
        if done_until and cend.strftime("%Y%m%d") <= done_until:
            continue  # 이전 실행에서 완료된 청크
        if total_funding >= max_funding:
            finished = False
            print(f"[BUDGET] 자금조달 {total_funding}건 처리 — 예산 도달, 저장 후 중단 "
                  f"(재실행 시 {state.get('done_until', '?')} 다음부터 이어감)")
            break
        sightings, stats = collect_funding_sightings_range(
            api_key, cstart.strftime("%Y%m%d"), cend.strftime("%Y%m%d"),
            max_pages=CHUNK_MAX_PAGES, pace_sec=PACE_SEC)
        merge_sightings(sdata, sightings)
        state["done_until"] = cend.strftime("%Y%m%d")
        sdata["updated"] = datetime.now().strftime("%Y-%m-%d")
        sightings_path.parent.mkdir(parents=True, exist_ok=True)
        sightings_path.write_text(
            json.dumps(sdata, ensure_ascii=False, indent=1), encoding="utf-8")
        total_funding += stats["funding"]
        total_extracted += stats["extracted"]
        done_chunks += 1
        if stats["truncated"]:
            truncated_chunks.append(cstart.strftime("%Y-%m-%d"))
        print(f"[CHUNK] {cstart:%Y-%m-%d}~{cend:%Y-%m-%d}: "
              f"공시 {stats['scanned']}건 · 자금조달 {stats['funding']}건 · "
              f"추출 {stats['extracted']}건"
              + (" · ⚠️목록 상한" if stats["truncated"] else ""))
        time.sleep(1)

    names = sdata.get("sightings", {})
    multi = sum(1 for recs in names.values()
                if len({r.get("corp_code") for r in recs if r.get("corp_code")}) >= 2)
    return {
        "done_chunks": done_chunks,
        "done_until": state.get("done_until", ""),
        "funding": total_funding,
        "extracted": total_extracted,
        "names_total": len(names),
        "names_multi": multi,
        "truncated_chunks": truncated_chunks,
        "finished": finished,
    }


def should_send_report(summary: dict) -> bool:
    """리포트 발송 여부 — 이미 완료된 상태의 no-op 재실행(스케줄 잔여 발화 등)은
    스팸 방지를 위해 조용히 끝낸다. 작업했거나 미완이면 발송."""
    return summary["done_chunks"] > 0 or not summary["finished"]


def build_backfill_report(summary: dict, start: datetime, end: datetime) -> str:
    lines = [
        f"sightings 백필 리포트 ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
        "",
        f"· 대상 구간: {start:%Y-%m-%d} ~ {end:%Y-%m-%d}",
        f"· 이번 실행: 청크 {summary['done_chunks']}개 · "
        f"자금조달 공시 {summary['funding']}건 · 개인 sighting {summary['extracted']}건",
        f"· 진행 상황: {summary['done_until'] or '시작 전'}까지 완료 — "
        + ("전 구간 완료 ✅" if summary["finished"] else "미완 (재실행 시 이어서 진행)"),
        f"· 누적 추적 인물: {summary['names_total']}명 "
        f"(2개사+ 등장 {summary['names_multi']}명 — 다음 일일 크론에서 등재 평가)",
    ]
    if summary["truncated_chunks"]:
        lines.append("· ⚠️ 목록 상한 도달 청크: " + ", ".join(summary["truncated_chunks"])
                     + " — 해당 주는 --chunk-days를 줄여 재수집 권장")
    lines += ["", "자동 발굴은 동명이인 미확인 — 원본 공시로 확인 필요. 판정 아님."]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="sightings 베이스 데이터 백필")
    ap.add_argument("--start", default="", help="수집 시작일 YYYY-MM-DD (기본: 종료일-365일)")
    ap.add_argument("--end", default="", help="수집 종료일 YYYY-MM-DD (기본: 오늘)")
    ap.add_argument("--chunk-days", type=int, default=CHUNK_DAYS)
    ap.add_argument("--max-funding", type=int, default=MAX_FUNDING,
                    help="자금조달 공시 처리 상한 (쿼터 보호)")
    args = ap.parse_args()

    key = _api_key()
    if not key:
        raise SystemExit("DART_API_KEY 또는 tmp/_apikey.txt 필요")

    end = datetime.strptime(args.end, "%Y-%m-%d") if args.end else datetime.now()
    start = (datetime.strptime(args.start, "%Y-%m-%d") if args.start
             else end - timedelta(days=BACKFILL_DAYS))
    if start > end:
        raise SystemExit(f"시작일({start:%Y-%m-%d})이 종료일({end:%Y-%m-%d})보다 늦음")

    sightings_path = Path(os.environ.get("SIGHTINGS_PATH") or _DEFAULT_SIGHTINGS)
    summary = run_backfill(key, sightings_path, start, end,
                           chunk_days=args.chunk_days, max_funding=args.max_funding)

    report = build_backfill_report(summary, start, end)
    print(report)
    if should_send_report(summary):
        sent = send_mail("[known_actors] sightings 백필 리포트", report)
        print("리포트 발송" if sent else "리포트 스킵(자격증명 없음)")
    else:
        print("no-op 실행 (이미 완료) — 리포트 스킵")


if __name__ == "__main__":
    main()
