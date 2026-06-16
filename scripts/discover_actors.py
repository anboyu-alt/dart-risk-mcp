"""문제 회사 기반 행위자 자동 발굴.

매일 시장 '문제 회사'(자금조달 + 불안정 신호 동반)의 개인 인수자를 sightings로
누적(private repo, 12개월 윈도우)하고, 서로 다른 문제 회사 N=2곳+ 에 반복 등장하는
인물을 known_actors(public)에 auto_matched로 자동 등재한다. 임원·조합명은 제외.

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
from dart_risk_mcp.core.signals import match_signals, is_amendment_disclosure
from scripts.refresh_known_actors import send_mail, _api_key

FUNDING_KEYS = {"CB_BW", "EB", "3PCA", "RIGHTS_UNDER", "RCPS"}
INSTABILITY_KEYS = {"SHAREHOLDER", "REVERSE_SPLIT", "GAMJA_MERGE", "INQUIRY",
                    "AUDIT", "MGMT_DISPUTE", "DISCLOSURE_VIOL"}
WINDOW_DAYS = 2
MAX_PAGES = 5
WINDOW_MONTHS = 12
N_THRESHOLD = 2

KNOWN_PATH = Path(__file__).resolve().parents[1] / "dart_risk_mcp" / "data" / "known_actors.json"
_DEFAULT_SIGHTINGS = Path(__file__).resolve().parents[1] / "tmp" / "sightings.json"

# 개인명이 아닌(법인·조합) 패턴
_ORG_PAT = re.compile(
    r"조합|투자|신탁|펀드|주식회사|\(주\)|㈜|유한|법인|파트너스|캐피탈|자산운용|"
    r"벤처|컴퍼니|코프|홀딩스|그룹|Co\.|Ltd|LLC|Inc")


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
    """개인명 여부(법인·조합 패턴 제외)."""
    if not name or not name.strip():
        return False
    return not _ORG_PAT.search(name)


def collect_problem_sightings(api_key, window_days=WINDOW_DAYS, max_pages=MAX_PAGES):
    """최근 window_days 자금조달 공시 중 문제 회사의 개인 인수자 sighting 목록."""
    end = datetime.now()
    start = end - timedelta(days=max(1, window_days))
    discs = fetch_market_disclosures(
        api_key, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"),
        pblntf_ty="B", max_pages=max_pages) or []
    sightings = []
    problem_cache = {}  # corp_code -> bool
    for d in discs:
        rn = d.get("rcept_no", "")
        rnm = d.get("report_nm", "")
        corp = d.get("corp_name", "")
        cc = d.get("corp_code", "")
        if not rn or is_amendment_disclosure(rnm):
            continue
        keys = {s["key"] for s in (match_signals(rnm) or [])}
        if not (keys & FUNDING_KEYS):
            continue
        if cc not in problem_cache:
            problem_cache[cc] = is_problem_company(company_signal_keys(cc, api_key))
        if not problem_cache[cc]:
            continue
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
    return sightings


def merge_sightings(data: dict, new: list, window_months: int = WINDOW_MONTHS) -> bool:
    """new sighting을 data에 병합. (corp_code,rcept_no) 중복 스킵, window 밖 제거. 변경 여부."""
    s = data.setdefault("sightings", {})
    changed = False
    for rec in new:
        nm = rec.get("name", "")
        if not nm:
            continue
        lst = s.setdefault(nm, [])
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


def promote_repeat_actors(sightings_data: dict, known_data: dict, n: int = N_THRESHOLD) -> list:
    """서로 다른 corp_code n개+ 인물을 known_actors에 auto_matched(자동 발굴)로 등재."""
    actors = known_data.setdefault("actors", {})
    promoted = []
    for nm, recs in sightings_data.get("sightings", {}).items():
        corp_codes = {r.get("corp_code") for r in recs if r.get("corp_code")}
        if len(corp_codes) < n:
            continue
        if any(r.get("source") == "자동 발굴" for r in actors.get(nm, [])):
            continue  # 이미 발굴 등재
        corp_names = sorted({r.get("corp") for r in recs if r.get("corp")})
        actors.setdefault(nm, []).append({
            "source": "자동 발굴",
            "status": "auto_matched",
            "evidence": f"문제 회사 {len(corp_codes)}곳 인수자 반복 등장: {'·'.join(corp_names[:5])}",
            "url": "https://dart.fss.or.kr",
            "date": "",
            "tags": ["자동 발굴", "동명이인 미확인", "반복 등장"],
        })
        promoted.append(nm)
    return promoted


def build_daily_report(sdata: dict, kdata: dict, s_changed: bool, promoted: list) -> str:
    """매일 발송하는 heartbeat 요약(변경 없어도 작동 확인용)."""
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
        f"· sightings: {'갱신' if s_changed else '무변경'}",
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

    new = collect_problem_sightings(key)
    s_changed = merge_sightings(sdata, new)
    promoted = promote_repeat_actors(sdata, kdata)

    if s_changed:
        sightings_path.parent.mkdir(parents=True, exist_ok=True)
        sdata["updated"] = datetime.now().strftime("%Y-%m-%d")
        sightings_path.write_text(json.dumps(sdata, ensure_ascii=False, indent=1), encoding="utf-8")
    if promoted:
        KNOWN_PATH.write_text(json.dumps(kdata, ensure_ascii=False, indent=1), encoding="utf-8")

    # 변경 여부와 무관하게 매일 heartbeat 리포트 발송 (작동 확인용)
    report = build_daily_report(sdata, kdata, s_changed, promoted)
    sent = send_mail("[known_actors] 일일 자동 발굴 리포트", report)

    print(f"sightings {'갱신' if s_changed else '무변경'} · 신규 등재 {len(promoted)}건"
          + (" · 리포트 발송" if sent else " · 리포트 스킵(자격증명 없음)"))


if __name__ == "__main__":
    main()
