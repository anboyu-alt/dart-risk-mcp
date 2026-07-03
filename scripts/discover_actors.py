"""자금조달 공시 기반 행위자 자동 발굴.

매일 시장 자금조달 공시(CB/BW·EB·유상증자, 정정 포함)의 개인 인수자를
sightings로 무조건 누적(private repo, 12개월 윈도우)한다. 문제 회사 필터는
수집 시점이 아니라 등재(promote) 시점에 평가한다 — 작전 시퀀스에서 인물
투입(자금조달)이 불안정 신호(최대주주변경·감사의견 등)보다 먼저 오는 경우,
수집 시점 필터로는 그 인물을 영영 놓치기 때문이다.

등재 기준: 서로 다른 '문제 회사'(자금조달+불안정 신호 동반) N=2곳+ 에
반복 등장하는 개인을 known_actors(public)에 auto_matched로 자동 등재.
임원·조합·법인명은 제외.

사용: python scripts/discover_actors.py
환경: DART_API_KEY, SIGHTINGS_PATH(private repo의 sightings.json), MAIL_*(선택).
"""
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from dart_risk_mcp.core.dart_client import fetch_market_disclosures, fetch_company_disclosures
from dart_risk_mcp.core.cb_extractor import extract_cb_investors
from dart_risk_mcp.core.investor_extractor import extract_rights_offering_investors
from dart_risk_mcp.core.signals import (
    match_signals,
    is_amendment_disclosure,
    strip_amendment_prefix,
)
from dart_risk_mcp.core.known_actors import normalize_name
from scripts.refresh_known_actors import send_mail, _api_key

FUNDING_KEYS = {"CB_BW", "EB", "3PCA", "RIGHTS_UNDER", "RCPS"}
INSTABILITY_KEYS = {"SHAREHOLDER", "REVERSE_SPLIT", "GAMJA_MERGE", "INQUIRY",
                    "AUDIT", "MGMT_DISPUTE", "DISCLOSURE_VIOL"}
WINDOW_DAYS = 2
MAX_PAGES = 10
WINDOW_MONTHS = 12
N_THRESHOLD = 2
# 등재 시점 문제 회사 판정용 lookback — sightings 윈도우(12개월)를 덮도록 설정.
PROBLEM_LOOKBACK_DAYS = 365

KNOWN_PATH = Path(__file__).resolve().parents[1] / "dart_risk_mcp" / "data" / "known_actors.json"
_DEFAULT_SIGHTINGS = Path(__file__).resolve().parents[1] / "tmp" / "sightings.json"

# 개인명이 아닌(법인·조합·기관) 패턴 — 영문 약어는 대소문자 무관 매칭
_ORG_PAT = re.compile(
    r"조합|투자|신탁|펀드|주식회사|\(주\)|㈜|유한|법인|파트너스|캐피탈|자산운용|"
    r"벤처|컴퍼니|코프|홀딩스|그룹|은행|공사|기금|시스템|"
    r"\b(?:co|ltd|llc|inc|corp)\b\.?|"
    r"limited|holdings|investment|bank|fund|trust|partners|capital|company",
    re.IGNORECASE,
)

# 개인명치고 지나치게 많은 공백 분리 토큰 — 프로그램/기관명 설명구(괄호 등) 필터
_MAX_PERSON_TOKENS = 4


def company_signal_keys(corp_code: str, api_key: str, lookback_days: int = 180) -> set:
    """회사 최근 공시의 신호 키 집합(정정 제외)."""
    keys = set()
    for d in (fetch_company_disclosures(corp_code, api_key, lookback_days) or []):
        rnm = d.get("report_nm", "")
        if is_amendment_disclosure(rnm):
            continue
        for s in (match_signals(rnm) or []):
            keys.add(s["key"])
    return keys


def is_problem_company(signal_keys) -> bool:
    """자금조달 신호 AND 불안정 신호가 함께 있으면 문제 회사."""
    ks = set(signal_keys)
    return bool(ks & FUNDING_KEYS) and bool(ks & INSTABILITY_KEYS)


def _is_person(name: str) -> bool:
    """개인명 여부(법인·조합·기관 패턴, 숫자 포함, 다단어 기관/프로그램명 제외)."""
    if not name or not name.strip():
        return False
    if re.search(r"\d", name):
        return False
    if _ORG_PAT.search(name):
        return False
    if len(re.split(r"\s+", name.strip())) > _MAX_PERSON_TOKENS:
        return False
    return True


def collect_funding_sightings_range(api_key, bgn_de, end_de,
                                    max_pages=MAX_PAGES, pace_sec=0.0):
    """지정 구간(YYYYMMDD)의 자금조달 공시(정정 포함)에서 개인 인수자 sighting 수집.

    문제 회사 필터는 여기서 적용하지 않는다 — promote 시점에 재평가.
    정정공시([기재정정] 등)도 접두사를 벗겨 유형을 판별하고 추출한다.
    실전에서 인수자 확정 명단(대상자 변경·납입일 연기)은 정정본에 실리는
    경우가 많아, 정정을 버리면 최종 인수자를 놓친다.

    Args:
        pace_sec: 자금조달 공시 1건 추출 후 대기 시간(초). 백필처럼 대량
            구간을 돌 때 DART 분당 상한을 피하기 위한 페이싱.

    Returns:
        (sightings, stats) — stats는 heartbeat 리포트용 수집 통계:
        {"scanned": 스캔 공시 수, "funding": 자금조달 공시 수,
         "extracted": 추출된 개인 sighting 수, "truncated": 페이지 상한 도달 여부}
    """
    import time as _time
    discs = fetch_market_disclosures(
        api_key, bgn_de, end_de, pblntf_ty="B", max_pages=max_pages) or []
    sightings = []
    n_funding = 0
    for d in discs:
        rn = d.get("rcept_no", "")
        rnm = d.get("report_nm", "")
        corp = d.get("corp_name", "")
        cc = d.get("corp_code", "")
        if not rn:
            continue
        base_nm = strip_amendment_prefix(rnm)
        keys = {s["key"] for s in (match_signals(base_nm) or [])}
        if not (keys & FUNDING_KEYS):
            continue
        n_funding += 1
        invs = []
        if keys & {"CB_BW", "EB"}:
            invs += extract_cb_investors(rn, api_key, cc) or []
        if keys & {"3PCA", "RIGHTS_UNDER"}:
            invs += extract_rights_offering_investors(rn, api_key, cc) or []
        rdt = d.get("rcept_dt", "") or ""
        date = f"{rdt[:4]}-{rdt[4:6]}" if len(rdt) >= 6 else ""
        for inv in invs:
            nm = (inv.get("name") or "").strip()
            if not _is_person(nm):
                continue
            sightings.append({
                "name": nm, "corp": corp, "corp_code": cc,
                "date": date, "rcept_no": rn,
                "signals": sorted(keys & (FUNDING_KEYS | INSTABILITY_KEYS)),
            })
        if pace_sec:
            _time.sleep(pace_sec)
    stats = {
        "scanned": len(discs),
        "funding": n_funding,
        "extracted": len(sightings),
        "truncated": len(discs) >= max_pages * 100,
    }
    return sightings, stats


def collect_funding_sightings(api_key, window_days=WINDOW_DAYS, max_pages=MAX_PAGES):
    """최근 window_days 자금조달 공시의 개인 인수자 sighting 수집 (일일 크론용)."""
    end = datetime.now()
    start = end - timedelta(days=max(1, window_days))
    return collect_funding_sightings_range(
        api_key, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), max_pages=max_pages)


def merge_sightings(data: dict, new: list, window_months: int = WINDOW_MONTHS) -> bool:
    """new sighting을 data에 병합. (corp_code,rcept_no) 중복 스킵, window 밖 제거. 변경 여부."""
    s = data.setdefault("sightings", {})
    changed = False
    for rec in new:
        nm = rec.get("name", "")
        if not nm:
            continue
        key = normalize_name(nm)
        lst = s.setdefault(key, [])
        if any(e.get("rcept_no") == rec.get("rcept_no") and
               e.get("corp_code") == rec.get("corp_code") for e in lst):
            continue
        lst.append({k: rec[k] for k in ("corp", "corp_code", "date", "rcept_no", "signals") if k in rec})
        changed = True
    cutoff = (datetime.now() - timedelta(days=window_months * 30)).strftime("%Y-%m")
    for nm in list(s.keys()):
        kept = [e for e in s[nm] if (e.get("date") or "9999-99") >= cutoff]
        if len(kept) != len(s[nm]):
            changed = True
        if kept:
            s[nm] = kept
        else:
            del s[nm]
            changed = True
    return changed


def promote_repeat_actors(sightings_data: dict, known_data: dict,
                          n: int = N_THRESHOLD, is_problem_fn=None) -> list:
    """서로 다른 '문제 회사' n곳+ 에 등장한 개인을 known_actors에 등재.

    Args:
        is_problem_fn: corp_code -> bool. 등재 후보의 회사만 지연 평가한다
            (sightings는 무조건 수집이므로, 회사 상태 판정은 이 시점에 수행).
            None이면 회사 상태 필터 없이 corp_code 수만으로 판정.
    """
    actors = known_data.setdefault("actors", {})
    promoted = []
    for nm, recs in sightings_data.get("sightings", {}).items():
        if not _is_person(nm):
            continue  # 과거 수집분에 섞인 법인·기관명 방어
        corp_codes = {r.get("corp_code") for r in recs if r.get("corp_code")}
        if len(corp_codes) < n:
            continue
        if any(r.get("source") == "자동 발굴" for r in actors.get(nm, [])):
            continue  # 이미 발굴 등재
        if is_problem_fn is not None:
            problem_codes = {cc for cc in corp_codes if is_problem_fn(cc)}
        else:
            problem_codes = corp_codes
        if len(problem_codes) < n:
            continue
        corp_names = sorted({r.get("corp") for r in recs
                             if r.get("corp") and r.get("corp_code") in problem_codes})
        actors.setdefault(nm, []).append({
            "source": "자동 발굴",
            "status": "auto_matched",
            "evidence": f"문제 회사 {len(problem_codes)}곳 인수자 반복 등장: {'·'.join(corp_names[:5])}",
            "url": "https://dart.fss.or.kr",
            "date": "",
            "tags": ["자동 발굴", "동명이인 미확인", "반복 등장"],
        })
        promoted.append(nm)
    return promoted


def build_daily_report(sdata: dict, kdata: dict, s_changed: bool, promoted: list,
                       stats: dict | None = None) -> str:
    """매일 발송하는 heartbeat 요약(변경 없어도 작동 확인용).

    stats가 있으면 수집 규모를 함께 표기한다 — '신규 등재 0명'이 정상
    (수집은 됐지만 반복 인물이 없음)인지 이상(수집 자체가 죽음)인지
    리포트만 보고 판별할 수 있게 한다.
    """
    counts = {"verified": 0, "maintainer_seed": 0, "auto_matched": 0}
    for recs in kdata.get("actors", {}).values():
        for r in recs:
            st = r.get("status", "")
            if st in counts:
                counts[st] += 1
    lines = [
        f"known_actors 일일 자동 발굴 리포트 ({datetime.now().strftime('%Y-%m-%d')})",
        "",
        "· 오늘 실행: 정상",
    ]
    if stats:
        lines.append(
            f"· 수집: 공시 {stats.get('scanned', 0)}건 스캔 · "
            f"자금조달 {stats.get('funding', 0)}건 · "
            f"개인 인수자 {stats.get('extracted', 0)}명 추출"
        )
        if stats.get("truncated"):
            lines.append("· ⚠️ 수집 페이지 상한 도달 — 공시 일부 누락 가능")
    lines += [
        f"· sightings: {'갱신' if s_changed else '무변경'} "
        f"(추적 인물 {len(sdata.get('sightings', {}))}명)",
        f"· 신규 등재: {len(promoted)}명" + (": " + ", ".join(promoted) if promoted else ""),
        f"· 현재 등재: verified {counts['verified']} · "
        f"maintainer_seed {counts['maintainer_seed']} · auto_matched {counts['auto_matched']}",
        "",
        "자동 발굴은 동명이인 미확인 — 원본 공시로 확인 필요. 판정 아님.",
    ]
    return "\n".join(lines)


def _load(path: Path, empty: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(empty)


def main():
    key = _api_key()
    if not key:
        raise SystemExit("DART_API_KEY 또는 tmp/_apikey.txt 필요")
    sightings_path = Path(os.environ.get("SIGHTINGS_PATH") or _DEFAULT_SIGHTINGS)
    sdata = _load(sightings_path, {"version": 1, "sightings": {}})
    kdata = _load(KNOWN_PATH, {"version": 1, "actors": {}})

    new, stats = collect_funding_sightings(key)
    s_changed = merge_sightings(sdata, new)

    # 문제 회사 판정은 등재 후보에 한해 지연 평가 (실행 내 캐시)
    problem_cache: dict = {}

    def _is_problem(cc: str) -> bool:
        if cc not in problem_cache:
            problem_cache[cc] = is_problem_company(
                company_signal_keys(cc, key, lookback_days=PROBLEM_LOOKBACK_DAYS))
        return problem_cache[cc]

    promoted = promote_repeat_actors(sdata, kdata, is_problem_fn=_is_problem)

    if s_changed:
        sightings_path.parent.mkdir(parents=True, exist_ok=True)
        sdata["updated"] = datetime.now().strftime("%Y-%m-%d")
        sightings_path.write_text(json.dumps(sdata, ensure_ascii=False, indent=1), encoding="utf-8")
    if promoted:
        KNOWN_PATH.write_text(json.dumps(kdata, ensure_ascii=False, indent=1), encoding="utf-8")

    # 변경 여부와 무관하게 매일 heartbeat 리포트 발송 (작동 확인용)
    report = build_daily_report(sdata, kdata, s_changed, promoted, stats=stats)
    sent = send_mail("[known_actors] 일일 자동 발굴 리포트", report)

    print(f"공시 {stats['scanned']}건 · 자금조달 {stats['funding']}건 · sighting {stats['extracted']}건"
          f" · sightings {'갱신' if s_changed else '무변경'} · 신규 등재 {len(promoted)}건"
          + (" · 리포트 발송" if sent else " · 리포트 스킵(자격증명 없음)"))


if __name__ == "__main__":
    main()
