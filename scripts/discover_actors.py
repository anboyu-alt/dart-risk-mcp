"""자금조달 공시 기반 행위자 자동 발굴.

매일 시장 자금조달 공시(CB/BW·EB·유상증자, 정정 포함)의 개인 인수자를
sightings로 무조건 누적(private repo, 12개월 윈도우)한다. 문제 회사 필터는
수집 시점이 아니라 등재(promote) 시점에 평가한다 — 작전 시퀀스에서 인물
투입(자금조달)이 불안정 신호(최대주주변경·감사의견 등)보다 먼저 오는 경우,
수집 시점 필터로는 그 인물을 영영 놓치기 때문이다.

등재 기준: 서로 다른 '문제 회사'(자금조달+불안정 신호 동반) N=2곳+ 에
반복 등장하는 개인·조합·법인을 레지스트리(비공개 Notion DB)에 auto_matched로
등재. 제도권 기관(증권사·은행·연기금 등)은 반복 등장이 정상이라 수집에서
제외한다. 레지스트리는 public 레포에 커밋하지 않는다.

사용: python scripts/discover_actors.py
환경: DART_API_KEY, SIGHTINGS_PATH(private repo의 sightings.json),
     NOTION_TOKEN + DB_KNOWN_ACTORS(레지스트리, 미설정 시 등재 기록 스킵),
     MAIL_*(선택).
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from dart_risk_mcp.core.dart_client import fetch_market_disclosures, fetch_company_disclosures
from dart_risk_mcp.core.cb_extractor import extract_cb_investors, extract_fund_backers
from dart_risk_mcp.core.investor_extractor import extract_rights_offering_investors
from dart_risk_mcp.core.signals import (
    match_signals,
    is_amendment_disclosure,
    strip_amendment_prefix,
)
from dart_risk_mcp.core.known_actors import (
    normalize_name,
    canonical_name,
    fold_name,
    load_known_actors,
    add_registry_record,
    classify_actor,
    should_store,
    KIND_LABELS,
    disclosure_url,
)
from scripts.refresh_known_actors import send_mail, _api_key

FUNDING_KEYS = {"CB_BW", "EB", "3PCA", "RIGHTS_UNDER", "RCPS"}
INSTABILITY_KEYS = {"SHAREHOLDER", "REVERSE_SPLIT", "GAMJA_MERGE", "INQUIRY",
                    "AUDIT", "MGMT_DISPUTE", "DISCLOSURE_VIOL"}
WINDOW_DAYS = 2
MAX_PAGES = 10
# sightings 보존 창 — 2015년까지 백필을 담기 위해 140개월(11.7년, 경계 프루닝
# 버퍼 포함). 이보다 좁으면 과거 백필 데이터가 병합 즉시 프루닝된다.
# merge_sightings의 기본값이라 백필·일일 크론 양쪽 프루닝에 적용된다.
WINDOW_MONTHS = 140
N_THRESHOLD = 2
# 등재 시점 문제 회사 판정용 lookback — 최근 불안정 신호 기준이라 1년 유지.
PROBLEM_LOOKBACK_DAYS = 365

_DEFAULT_SIGHTINGS = Path(__file__).resolve().parents[1] / "tmp" / "sightings.json"

# 추적 대상 분류 (classify_actor 결과 기준) — 제도권 기관·노이즈 제외
_TRACKED_KINDS = ("person", "fund", "corp")


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
    """개인명 여부 — classify_actor 래퍼 (하위호환용)."""
    return classify_actor(name) == "person"


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
    n_backers = 0
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
        # 시장 구분(Y=유가/KOSPI, K=코스닥, N=코넥스, E=기타·비상장) — list.json이
        # 이미 실어 주므로 추가 조회 없이 회사 노드 시장 태깅에 활용.
        cls = (d.get("corp_cls") or "").strip()
        filing_new = []
        for inv in invs:
            nm = (inv.get("name") or "").strip()
            if not should_store(nm):
                continue  # 증권·은행·노이즈 제외 (기타 기관은 보존)
            kind = classify_actor(nm)
            filing_new.append({
                "name": nm, "corp": corp, "corp_code": cc, "corp_cls": cls,
                "date": date, "rcept_no": rn, "kind": kind,
                "signals": sorted(keys & (FUNDING_KEYS | INSTABILITY_KEYS)),
            })
        # 조합 인수자의 배후(대표조합원·최대출자자)도 같은 회사 sighting으로
        # 추적 — 회사마다 새 조합을 만드는 '조합 갈아타기' 회피를 GP 단위에서
        # 잡는다. 원문 1회 추가 조회(조합 포함 공시에 한함).
        funds = [s["name"] for s in filing_new if s["kind"] == "fund"]
        if funds:
            seen_nm = {s["name"] for s in filing_new}
            for b in (extract_fund_backers(rn, api_key, funds) or []):
                if not should_store(b["name"]) or b["name"] in seen_nm:
                    continue
                bkind = classify_actor(b["name"])
                seen_nm.add(b["name"])
                n_backers += 1
                filing_new.append({
                    "name": b["name"], "corp": corp, "corp_code": cc, "corp_cls": cls,
                    "date": date, "rcept_no": rn, "kind": bkind,
                    "via": f"{b['fund']} {b['role']}",
                    "signals": sorted(keys & (FUNDING_KEYS | INSTABILITY_KEYS)),
                })
        sightings.extend(filing_new)
        if pace_sec:
            _time.sleep(pace_sec)
    n_persons = sum(1 for s in sightings if s["kind"] == "person")
    stats = {
        "scanned": len(discs),
        "funding": n_funding,
        "extracted": len(sightings),
        "extracted_persons": n_persons,
        "extracted_entities": len(sightings) - n_persons,
        "extracted_backers": n_backers,
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
    aliases = data.get("aliases") or {}   # {정규화 별칭: 정규화 정본} — 같은 인물 합치기
    changed = False
    _FIELDS = ("corp", "corp_code", "corp_cls", "date", "rcept_no",
               "signals", "kind", "via", "event", "event_type", "pct")

    def _is_dup(lst, rec):  # 같은 접수·회사·이벤트 유형이면 중복(진입/이탈은 event로 구분)
        return any(e.get("rcept_no") == rec.get("rcept_no") and
                   e.get("corp_code") == rec.get("corp_code") and
                   e.get("event", "in") == rec.get("event", "in") for e in lst)

    # 기존 키 정규화 재키잉(1회) — normalize_name 강화(역할 괄호 제거)로
    # '증권사 (…신탁업자 지위에서)'처럼 이미 저장된 괄호 키가 기저 실체 키로
    # 수렴한다. 이후 프루닝 루프가 기저가 기관인 키를 제거한다. (별칭 재키잉은
    # 폴드 루프 뒤 기존 루프가 담당하므로 여기선 순수 정규화만 적용한다.)
    for k in list(s.keys()):
        nk = normalize_name(k)
        if nk != k:
            dst = s.setdefault(nk, [])
            for rec in s[k]:
                if not _is_dup(dst, rec):
                    dst.append(rec)
            del s[k]
            changed = True

    for rec in new:
        nm = rec.get("name", "")
        if not nm:
            continue
        key = canonical_name(nm, aliases)   # 별칭이면 정본 키로 합류
        lst = s.setdefault(key, [])
        if _is_dup(lst, rec):
            continue
        lst.append({k: rec[k] for k in _FIELDS if k in rec})
        changed = True

    # 표기 변형 자동 병합 — 접사((주)·주식회사)·공백·라틴↔한글 음차 폴딩이
    # 같은 키들을 별칭으로 자동 등록. 정본은 별칭이 아닌 키 중 레코드 최다 표기.
    # (예: 'DB금융투자 주식회사' 7가지 표기 → 한 노드) 실제 병합은 아래
    # 재키잉 루프가 수행하고, 등록된 별칭은 그래프에 '다른 이름'으로 표시된다.
    folds: dict = {}
    for k in s:
        if should_store(k):
            folds.setdefault(fold_name(k), []).append(k)
    fold_added = 0
    for ks in folds.values():
        if len(ks) < 2:
            continue
        cands = [k for k in ks if k not in aliases] or ks   # 별칭 아닌 키 우선(체인 방지)
        canon = max(cands, key=lambda k: len(s[k]))
        for k in ks:
            if k != canon and aliases.get(k) != canon:
                aliases[k] = canon
                fold_added += 1
    if fold_added:
        data["aliases"] = aliases
        changed = True
        print(f"[FOLD] 표기 변형 자동 별칭 등록: {fold_added}건")

    # 기존 별칭 키 → 정본 키로 합치기 (별칭 맵 갱신 시 과거 데이터 self-heal)
    if aliases:
        for k in list(s.keys()):
            canon = aliases.get(k)
            if canon and canon != k:
                dst = s.setdefault(canon, [])
                for rec in s[k]:
                    if not _is_dup(dst, rec):
                        dst.append(rec)
                del s[k]
                changed = True

    cutoff = (datetime.now() - timedelta(days=window_months * 30)).strftime("%Y-%m")
    for nm in list(s.keys()):
        # 증권·은행·추출 조각 등 비저장 키는 제거 (오염 데이터 자기정화).
        # 기타 기관(자산운용·보험·자문·PE 등)은 should_store가 보존한다.
        if not should_store(nm):
            del s[nm]
            changed = True
            continue
        # '닫힌 관계'(이탈 기록이 있는 회사)는 진입이 오래됐어도 이력으로 보존
        closed_ccs = {e.get("corp_code") for e in s[nm] if e.get("event") == "out"}
        kept = [e for e in s[nm]
                if (e.get("date") or "9999-99") >= cutoff or e.get("corp_code") in closed_ccs]
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
        kind = classify_actor(nm)
        if kind not in _TRACKED_KINDS:
            continue  # 과거 수집분에 섞인 기관명·노이즈 방어
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
        # 문제 회사별 최신 공시 rcept → evidence 회사명 하이퍼링크용
        latest_by_corp: dict = {}
        for r in recs:
            if r.get("corp_code") not in problem_codes:
                continue
            corp, rc = r.get("corp"), r.get("rcept_no")
            if corp and rc and rc > latest_by_corp.get(corp, ""):
                latest_by_corp[corp] = rc
        company_links = {corp: disclosure_url(rc) for corp, rc in latest_by_corp.items()}
        rep_rcept = max(latest_by_corp.values(), default="")
        same_name_tag = "동명이인 미확인" if kind == "person" else "동명 법인·조합 미확인"
        tags = ["자동 발굴", same_name_tag, "반복 등장"]
        vias = sorted({r["via"] for r in recs if r.get("via")})
        if vias:
            tags.append("조합 배후 인물")
        actors.setdefault(nm, []).append({
            "source": "자동 발굴",
            "status": "auto_matched",
            "evidence": f"문제 회사 {len(problem_codes)}곳 인수자 반복 등장: {'·'.join(corp_names[:5])}",
            "url": disclosure_url(rep_rcept) or "https://dart.fss.or.kr",
            "date": "",
            "tags": tags,
            "companies": corp_names,
            "company_links": company_links,
            "kind": KIND_LABELS[kind],
        })
        promoted.append(nm)
    return promoted


def build_daily_report(sdata: dict, kdata: dict, s_changed: bool, promoted: list,
                       stats: dict | None = None, watch: list | None = None) -> str:
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
            f"인수자 {stats.get('extracted', 0)}건 추출"
            f" (개인 {stats.get('extracted_persons', 0)} · "
            f"조합/법인 {stats.get('extracted_entities', 0)} · "
            f"조합 배후 {stats.get('extracted_backers', 0)})"
        )
        if stats.get("truncated"):
            lines.append("· ⚠️ 수집 페이지 상한 도달 — 공시 일부 누락 가능")
    lines += [
        f"· sightings: {'갱신' if s_changed else '무변경'} "
        f"(추적 인물 {len(sdata.get('sightings', {}))}명)",
        f"· 신규 등재: {len(promoted)}명" + (": " + ", ".join(promoted) if promoted else ""),
    ]
    if watch:
        top = " · ".join(f"{nm}({nc}개사, 문제 {np}곳)" for nm, nc, np in watch[:10])
        lines.append(f"· 등재 임박 후보(문제 회사 1곳 더 걸리면 등재): {top}")
    lines += [
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
    kdata = load_known_actors()  # 비공개 Notion 레지스트리 (미설정 시 동봉 스켈레톤)

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

    # 등재 임박 워치 — 2개사+ 등장했지만 문제 회사 수 미달인 후보.
    # promote가 이미 같은 후보군을 평가해 problem_cache가 차 있어 추가 콜 없음.
    watch = []
    for nm, recs in sdata.get("sightings", {}).items():
        if nm in promoted or classify_actor(nm) not in _TRACKED_KINDS:
            continue
        if any(r.get("source") == "자동 발굴" for r in kdata.get("actors", {}).get(nm, [])):
            continue
        ccs = {r.get("corp_code") for r in recs if r.get("corp_code")}
        if len(ccs) < N_THRESHOLD:
            continue
        nprob = sum(1 for cc2 in ccs if _is_problem(cc2))
        if 0 < nprob < N_THRESHOLD:
            watch.append((nm, len(ccs), nprob))
    watch.sort(key=lambda w: (-w[2], -w[1]))

    if s_changed:
        sightings_path.parent.mkdir(parents=True, exist_ok=True)
        sdata["updated"] = datetime.now().strftime("%Y-%m-%d")
        sightings_path.write_text(json.dumps(sdata, ensure_ascii=False, indent=1), encoding="utf-8")

    # 등재는 비공개 Notion 레지스트리에 기록 — env 미설정 시 스킵(메일로만 통지)
    written = 0
    for nm in promoted:
        if add_registry_record(nm, kdata["actors"][nm][-1]):
            written += 1

    # 변경 여부와 무관하게 매일 heartbeat 리포트 발송 (작동 확인용)
    report = build_daily_report(sdata, kdata, s_changed, promoted, stats=stats,
                                watch=watch)
    if promoted:
        report += (f"\n※ Notion 레지스트리 기록: {written}/{len(promoted)}건"
                   + ("" if written == len(promoted)
                      else " — NOTION_TOKEN/DB_KNOWN_ACTORS 설정 확인 필요"))
    sent = send_mail("[known_actors] 일일 자동 발굴 리포트", report)

    print(f"공시 {stats['scanned']}건 · 자금조달 {stats['funding']}건 · sighting {stats['extracted']}건"
          f" · sightings {'갱신' if s_changed else '무변경'} · 신규 등재 {len(promoted)}건"
          + (" · 리포트 발송" if sent else " · 리포트 스킵(자격증명 없음)"))


if __name__ == "__main__":
    main()
