"""공시 기반 행위자 자동 발굴.

매일 시장 공시에서 세 가지 sighting 수집원을 무조건 누적(private repo,
12개월 윈도우)한다:
  1. 자금조달(CB/BW·EB·유상증자, 정정 포함)의 개인·조합·법인 인수자
  2. 자금유출성 거래(금전대여·채무보증·담보제공·유형자산양수)의 affiliated/
     external 상대방 (v1.8.0, subsidiary·제도권 금융기관 제외)
  3. 최대주주변경(정정 제외)의 신규 최대주주 (v1.8.0, "외 N인" 접미 제거 후
     제도권 금융기관 제외)

문제 회사 필터는 수집 시점이 아니라 등재(promote) 시점에 평가한다 — 작전
시퀀스에서 인물 투입(자금조달·자금유출·최대주주변경)이 불안정 신호(감사의견
등)보다 먼저 오는 경우, 수집 시점 필터로는 그 인물을 영영 놓치기 때문이다.

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
import re
from datetime import datetime, timedelta
from pathlib import Path

from dart_risk_mcp.core.dart_client import (
    fetch_market_disclosures,
    fetch_company_disclosures,
    fetch_outflow_detail,
    classify_outflow_relation,
    fetch_control_change_detail,
    strip_holder_suffix,
    resolve_decision_type,
    fetch_major_decision,
)
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
    fold_variants,
    load_known_actors,
    add_registry_record,
    notion_credentials_configured,
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

# sighting 레코드의 출처("src" 필드, 없으면 "funding" 기본 취급) → evidence
# 표시 라벨. 순서 고정(등재 evidence에서 항상 이 순서로 나열) — "kind"라는
# 이름은 이미 각 레코드의 person/fund/corp 분류 필드로 쓰이고 있어(merge_
# sightings·backfill_exits.py가 그 의미로 읽는다) 충돌을 피하려 별도 필드명
# "src"를 쓴다.
SRC_LABELS = {"funding": "인수자", "outflow": "유출 상대방", "control": "신규 최대주주"}
_SRC_ORDER = ("funding", "outflow", "control")

# outflow·control 수집원 전용 제외어 — classify_actor의 institution 패턴에는
# '신탁'(부동산신탁 등 단독 표기)이 없어 별도로 게이트한다.
_EXTRA_INSTITUTION_KW = ("신탁",)


def classify_tracked_entity(name: str) -> "str | None":
    """자금유출 상대방·신규 최대주주 전용 분류 — 노이즈·제도권 금융기관 제외.

    funding 경로(collect_funding_sightings_range)는 should_store를 써서
    자산운용·보험 등 '기타기관'을 보존한다(정상적인 자금조달 투자자일 수
    있어서). 반면 이 두 수집원(자금유출 상대방·신규 최대주주)은 은행·증권·
    캐피탈·저축은행·금고·보험·신탁 등 제도권 금융기관을 전부 제외한다 —
    대여·담보·최대주주 자리에 금융기관이 오는 건 정상적인 대주·수탁 관계일
    뿐 추적 대상 '행위자'가 아니다(classify_actor의 institution 판정 +
    '신탁' 확장). person/fund/corp는 모두 반환한다 — 무자본 M&A 세력은
    SPC·조합·법인 명의가 핵심이므로 법인도 추적 대상이다.

    Returns: classify_actor 결과("person"|"fund"|"corp") 또는 제외 시 None.
    """
    n = (name or "").strip()
    if not n:
        return None
    kind = classify_actor(n)
    if kind in ("noise", "institution"):
        return None
    if any(kw in n for kw in _EXTRA_INSTITUTION_KW):
        return None
    return kind


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


# ── 자금유출 상대방 수집 (v1.8.0) ────────────────────────────────────
# 금감원 무자본 M&A 합동점검 사례(아틀라스링크→로아앤코홀딩스 등)처럼, 인수
# 세력은 CB·유상증자로 회사를 장악한 뒤 회사 자금을 대여·담보·자산양수 형태로
# 자신의 다른 SPC로 빼돌린다. 이 상대방도 CB 인수자와 동일한 고정점이다.
#
# 실측(2026-08, 최근 30일 시장 스캔): 금전대여결정·채무보증결정·담보제공결정은
# 거래소공시(pblntf_ty='I')에 실린다. 채무보증·담보제공은 코스피 상장사가
# 주요사항보고서(pblntf_ty='B')에도 병행 공시하는 사례가 실측 확인돼(코스피
# 의무공시 요건) 두 유형 모두 스캔한다. 유형자산양수결정은 DS005 주요사항
# 보고서(B) 전용으로, 거래소공시(I)에서는 0건이었다.
_OUTFLOW_TANGIBLE_KW = ("유형자산양수",)


def _fetch_outflow_row(rn: str, base_nm: str, api_key: str, corp_code: str) -> tuple[str, str]:
    """자금유출 공시 1건에서 (상대방, 관계 분류)를 조회한다.

    유형자산양수결정은 DS005(fetch_major_decision)로, 나머지(금전대여·
    채무보증·담보제공)는 원문 직접 파싱(fetch_outflow_detail)으로 조회한다
    — server.py의 _confirm_outflow_counterparties와 동일한 두 경로 분기.
    """
    if any(kw in base_nm for kw in _OUTFLOW_TANGIBLE_KW):
        dtype = resolve_decision_type(base_nm)
        r = {}
        if dtype:
            try:
                r = fetch_major_decision(rn, api_key, dtype, corp_code) or {}
            except Exception:
                r = {}
        if "error" in r:
            r = {}
        relation = r.get("relation_text") or ""
        cls = (classify_outflow_relation(relation) if relation
               else ("affiliated" if r.get("related_party") else "unknown"))
        return r.get("counterparty") or "", cls
    try:
        detail = fetch_outflow_detail(rn, api_key) or {}
    except Exception:
        detail = {}
    return detail.get("counterparty", ""), classify_outflow_relation(detail.get("relation", ""))


def collect_outflow_sightings_range(api_key, bgn_de, end_de,
                                    max_pages=MAX_PAGES, pace_sec=0.0):
    """지정 구간(YYYYMMDD)의 자금유출성 거래 공시에서 상대방 sighting 수집.

    금전대여·채무보증·담보제공·유형자산양수 4계열(FUND_OUTFLOW 신호) 중
    classify_outflow_relation이 "affiliated"|"external"로 판정한 건만
    수집한다 — subsidiary(종속회사·자회사, 세력 추적 대상 아님)와 unknown
    (관계 확인 불가)은 설계상 제외한다. 상대방이 공시 회사 자신과 같은
    이름이거나(파싱 오류 방어) 제도권 금융기관이면 제외한다.

    Returns:
        (sightings, stats) — stats: {"scanned", "outflow", "extracted", "truncated"}
    """
    import time as _time
    discs_i = fetch_market_disclosures(
        api_key, bgn_de, end_de, pblntf_ty="I", max_pages=max_pages) or []
    discs_b = fetch_market_disclosures(
        api_key, bgn_de, end_de, pblntf_ty="B", max_pages=max_pages) or []

    sightings = []
    seen_rcept: set = set()
    n_outflow = 0
    for d in discs_i + discs_b:
        rn = d.get("rcept_no", "")
        rnm = d.get("report_nm", "")
        corp = d.get("corp_name", "")
        cc = d.get("corp_code", "")
        if not rn or rn in seen_rcept:
            continue
        base_nm = strip_amendment_prefix(rnm)
        keys = {s["key"] for s in (match_signals(base_nm) or [])}
        if "FUND_OUTFLOW" not in keys:
            continue
        seen_rcept.add(rn)
        n_outflow += 1

        counterparty, cls = _fetch_outflow_row(rn, base_nm, api_key, cc)
        if pace_sec:
            _time.sleep(pace_sec)

        nm = (counterparty or "").strip()
        if not nm or cls not in ("affiliated", "external"):
            continue
        if fold_name(nm) == fold_name(corp):
            continue  # 공시 회사 자신과 동일 명칭 (파싱 오류 방어)
        kind = classify_tracked_entity(nm)
        if kind is None:
            continue

        rdt = d.get("rcept_dt", "") or ""
        date = f"{rdt[:4]}-{rdt[4:6]}" if len(rdt) >= 6 else ""
        cls_tag = (d.get("corp_cls") or "").strip()
        sightings.append({
            "name": nm, "corp": corp, "corp_code": cc, "corp_cls": cls_tag,
            "date": date, "rcept_no": rn, "kind": kind, "src": "outflow",
            "signals": ["FUND_OUTFLOW"],
        })

    stats = {
        "scanned": len(discs_i) + len(discs_b),
        "outflow": n_outflow,
        "extracted": len(sightings),
        "truncated": len(discs_i) >= max_pages * 100 or len(discs_b) >= max_pages * 100,
    }
    return sightings, stats


def collect_outflow_sightings(api_key, window_days=WINDOW_DAYS, max_pages=MAX_PAGES):
    """최근 window_days 자금유출성 거래 공시의 상대방 sighting 수집 (일일 크론용)."""
    end = datetime.now()
    start = end - timedelta(days=max(1, window_days))
    return collect_outflow_sightings_range(
        api_key, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), max_pages=max_pages)


# ── 신규 최대주주 수집 (v1.8.0) ──────────────────────────────────────
# 금감원 무자본 M&A 합동점검(2019-12-19): 적발 24사의 신규 최대주주 82%가
# 비외감법인·투자조합이었다. 신규 최대주주 명의 자체가 CB 인수자·자금유출
# 상대방과 나란한 고정점이다.
#
# 실측(2026-08, 최근 30일 시장 스캔): 최대주주변경 공시는 거래소공시
# (pblntf_ty='I')에서만 확인됐다(B·D·E·A·C는 0건).
_CONTROL_CHANGE_TITLE_RE = re.compile(r"최대주주\s*변경")
# 예고성 공시("최대주주 변경을 수반하는 주식양수도 계약 체결/해제")는
# "1. 변경내용" 구조 자체가 없어 fetch_control_change_detail이 빈 dict를
# 반환한다(server.py의 _CONTROL_CHANGE_PRECURSOR_RE와 동일한 관찰) — 원문
# 조회 낭비를 줄이려 제목 단계에서 미리 걸러낸다.
_CONTROL_CHANGE_PRECURSOR_RE = re.compile(r"계약")


def collect_control_change_sightings_range(api_key, bgn_de, end_de,
                                           max_pages=MAX_PAGES, pace_sec=0.0):
    """지정 구간(YYYYMMDD)의 최대주주변경 공시(정정 제외)에서 신규 최대주주 수집.

    "외 N인"/"외N명" 접미는 strip_holder_suffix로 제거한 대표 명의만
    저장한다. 신규 최대주주 미기재("-")·제도권 금융기관은 제외한다.

    Returns:
        (sightings, stats) — stats: {"scanned", "control", "extracted", "truncated"}
    """
    import time as _time
    discs = fetch_market_disclosures(
        api_key, bgn_de, end_de, pblntf_ty="I", max_pages=max_pages) or []

    sightings = []
    n_control = 0
    for d in discs:
        rn = d.get("rcept_no", "")
        rnm = d.get("report_nm", "") or ""
        corp = d.get("corp_name", "")
        cc = d.get("corp_code", "")
        if not rn:
            continue
        if is_amendment_disclosure(rnm):
            continue
        if not _CONTROL_CHANGE_TITLE_RE.search(rnm) or _CONTROL_CHANGE_PRECURSOR_RE.search(rnm):
            continue
        n_control += 1

        try:
            detail = fetch_control_change_detail(rn, api_key) or {}
        except Exception:
            detail = {}
        if pace_sec:
            _time.sleep(pace_sec)

        new_holder = strip_holder_suffix(detail.get("new_holder", ""))
        nm = (new_holder or "").strip()
        if not nm or set(nm) <= {"-"}:
            continue
        if fold_name(nm) == fold_name(corp):
            continue
        kind = classify_tracked_entity(nm)
        if kind is None:
            continue

        rdt = d.get("rcept_dt", "") or ""
        date = f"{rdt[:4]}-{rdt[4:6]}" if len(rdt) >= 6 else ""
        cls_tag = (d.get("corp_cls") or "").strip()
        sightings.append({
            "name": nm, "corp": corp, "corp_code": cc, "corp_cls": cls_tag,
            "date": date, "rcept_no": rn, "kind": kind, "src": "control",
            "signals": ["SHAREHOLDER"],
        })

    stats = {
        "scanned": len(discs),
        "control": n_control,
        "extracted": len(sightings),
        "truncated": len(discs) >= max_pages * 100,
    }
    return sightings, stats


def collect_control_change_sightings(api_key, window_days=WINDOW_DAYS, max_pages=MAX_PAGES):
    """최근 window_days 최대주주변경 공시의 신규 최대주주 sighting 수집 (일일 크론용)."""
    end = datetime.now()
    start = end - timedelta(days=max(1, window_days))
    return collect_control_change_sightings_range(
        api_key, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"), max_pages=max_pages)


def _is_dup(lst, rec):
    """같은 접수·회사·이벤트 유형이면 중복(진입/이탈은 event로 구분)."""
    return any(e.get("rcept_no") == rec.get("rcept_no") and
               e.get("corp_code") == rec.get("corp_code") and
               e.get("event", "in") == rec.get("event", "in") for e in lst)


def merge_sightings(data: dict, new: list, window_months: int = WINDOW_MONTHS) -> bool:
    """new sighting을 data에 병합. (corp_code,rcept_no) 중복 스킵, window 밖 제거. 변경 여부."""
    s = data.setdefault("sightings", {})
    aliases = data.get("aliases") or {}   # {정규화 별칭: 정규화 정본} — 같은 인물 합치기
    changed = False
    _FIELDS = ("corp", "corp_code", "corp_cls", "date", "rcept_no",
               "signals", "kind", "via", "event", "event_type", "pct", "src")

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
            # 병기 표기('정소영(DING SHAO YING)'·'…(구. 옛이름)')는 구성 표기
            # 폴드로도 그룹에 참여 → 단독 표기 키와 같은 실체로 접힌다.
            for f in fold_variants(k):
                folds.setdefault(f, []).append(k)
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

    # 개명 이력 병합 — 같은 corp_code에 붙은 서로 다른 회사 표기(사명 변경)가
    # 각각 행위자 키로도 존재하면 같은 실체로 별칭 등록. DART list.json은
    # 조회 시점의 '현재' 사명을 주므로, 개명 후 신규 수집분과 개명 전 저장분이
    # 어긋나기 시작할 때 corp_code 불변성을 다리로 self-heal한다.
    cc_label_folds: dict = {}
    for recs in s.values():
        for r in recs:
            cc, corp = r.get("corp_code"), (r.get("corp") or "").strip()
            if cc and corp:
                cc_label_folds.setdefault(cc, set()).add(fold_name(corp))
    rename_added = 0
    for fset in cc_label_folds.values():
        if len(fset) < 2:
            continue
        ks = sorted({k for f in fset for k in folds.get(f, [])})
        if len(ks) < 2:
            continue
        cands = [k for k in ks if k not in aliases] or ks
        canon = max(cands, key=lambda k: len(s[k]))
        for k in ks:
            if k != canon and aliases.get(k) != canon:
                aliases[k] = canon
                rename_added += 1
    if rename_added:
        data["aliases"] = aliases
        changed = True
        print(f"[RENAME] 개명 이력 별칭 등록: {rename_added}건")

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


def _corp_name_index(api_key: str) -> dict:
    """corpCode 명부 → {fold_name(현재 사명): set(corp_code)}.

    reconcile_corp_renames의 입력. 24시간 파일 캐시(_load_corp_codes) 재사용
    — 추가 API 호출 없음(일일 첫 실행만 1회 다운로드).
    """
    from dart_risk_mcp.core import dart_client as _dc
    _dc._load_corp_codes(api_key)
    idx: dict = {}
    for name, info in (_dc._corp_cache or {}).items():
        cc = info.get("corp_code")
        if cc:
            idx.setdefault(fold_name(name), set()).add(cc)
    return idx


def _legacy_name_index(data: dict) -> dict:
    """sightings의 corp_renames(상호변경 백필) → {fold(과거 사명): set(corp_code)}.

    reconcile_corp_renames의 legacy_index 입력. 모호 가드(len==1)는 reconcile이
    수행하므로 여기선 전체 매핑을 그대로 반환한다.
    """
    idx: dict = {}
    for cc, ent in (data.get("corp_renames") or {}).items():
        for nm in ent.get("names", []):
            f = fold_name(nm)
            if f:
                idx.setdefault(f, set()).add(cc)
    return idx


def _alias_name_index() -> dict:
    """공개 corp-aliases.json(주간 corp-map diff) → {fold(옛 사명): set(corp_code)}.

    reconcile_corp_renames의 legacy_index 보조 소스. '상호변경안내' 공시 백필은
    사실상 코스닥 전용이라(corp_renames 610사 중 K 354 vs Y 2, 2026-08-03 실측)
    KOSPI 개명을 못 잡는데, 명부 diff 기반 별칭 맵은 시장 무관하게 향후 개명을
    커버한다. corp_code는 DART corpCode.xml 원본 그대로라 별도 근거가 필요 없다.
    로드 실패 시 빈 dict (graceful — 기존 corp_renames 경로에 영향 없음).
    """
    try:
        from dart_risk_mcp.core.dart_client import load_corp_aliases
        amap = load_corp_aliases() or {}
    except Exception:
        return {}
    idx: dict = {}
    for old, info in amap.items():
        cc = (info or {}).get("corp_code")
        f = fold_name(old)
        if cc and f:
            idx.setdefault(f, set()).add(cc)
    return idx


def _combined_legacy_index(data: dict) -> dict:
    """corp_renames(공시 백필+수동 시드) ∪ corp-aliases(명부 diff) 합집합.

    같은 옛 사명이 두 소스에서 다른 corp_code를 가리키면 합집합으로 남긴다 —
    reconcile의 모호 가드(len==1)가 해석을 거부하는 보수적 동작을 그대로 탄다.
    """
    idx = _legacy_name_index(data)
    for f, ccs in _alias_name_index().items():
        idx.setdefault(f, set()).update(ccs)
    return idx


_MANUAL_RENAMES_NAME = "manual_renames.json"
_RCEPT_NO_RE = re.compile(r"^\d{14}$")
_CORP_CODE_RE = re.compile(r"^\d{8}$")


def load_manual_renames(path) -> "tuple[dict, list]":
    """수동 개명 시드 파일 → (corp_renames 병합용 dict, 오류 목록).

    '상호변경안내' 백필이 못 잡는 개명(KOSPI 주총 의결 등)을 운영자가 직접
    등재하는 얇은 경로. 스키마는 corp_renames와 동일하며 **근거 rcept_no 없는
    entry는 기계적으로 거부**한다(출처 없는 데이터 등재 금지 기조) —
    rcept_no는 해당 corp_code가 옛 사명 명의로 제출했거나 개명 사실을 담은
    공시여야 한다(merge_manual_renames.py가 DART 대조 검증).

    형식: {"version": 1, "renames": {corp_code: {"names": [...], "events":
    [{"rcept_no": 14자리, "after": 현재 사명, "date"/"before"/"src"/"note"}]}}}
    위반 entry는 제외하고 오류만 기록한다(유효 entry는 살아남음).
    파일이 없으면 ({}, []) — 시드는 선택 사항.
    """
    p = Path(path)
    if not p.exists():
        return {}, []
    try:
        doc = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        return {}, [f"JSON 파싱 실패: {e}"]
    renames: dict = {}
    errors: list = []
    for cc, ent in (doc.get("renames") or {}).items():
        if not _CORP_CODE_RE.match(str(cc)):
            errors.append(f"{cc}: corp_code는 8자리 숫자여야 함")
            continue
        names = [n for n in (ent.get("names") or []) if n and str(n).strip()]
        events = ent.get("events") or []
        if not names:
            errors.append(f"{cc}: names가 비어 있음")
            continue
        if not events:
            errors.append(f"{cc}: 근거 events가 비어 있음 — rcept_no 필수")
            continue
        bad = [e for e in events
               if not _RCEPT_NO_RE.match(str(e.get("rcept_no", "")))
               or not str(e.get("after", "")).strip()]
        if bad:
            errors.append(f"{cc}: rcept_no(14자리)·after 없는 event {len(bad)}건"
                          " — 전체 entry 거부")
            continue
        renames[cc] = {"names": names, "events": events}
    return renames, errors


def apply_manual_renames(sdata: dict, seed_path) -> bool:
    """수동 시드를 sightings의 corp_renames에 병합 (idempotent).

    daily cron(main)이 sightings.json 옆의 manual_renames.json을 자동
    반영한다 — 운영자는 private repo에 시드만 커밋하면 된다. 병합 로직은
    backfill_renames.merge_renames 재사용(rcept_no 기준 dedup).
    """
    renames, errors = load_manual_renames(seed_path)
    for e in errors:
        print(f"[MANUAL-RENAMES] 무시된 entry — {e}")
    if not renames:
        return False
    from scripts.backfill_renames import merge_renames  # 순환 회피 지연 import
    return merge_renames(sdata, renames)


def reconcile_corp_renames(data: dict, corp_index: dict,
                           legacy_index: dict | None = None) -> bool:
    """corpCode 명부로 행위자 키(법인·조합)를 corp_code로 해석해 영속 추적.

    행위자명은 공시 원문 파싱이라 제출 시점 사명으로 동결된다 — 개명하면
    옛 사명 키와 새 사명 키로 갈라진다. corp_code는 개명 불변이므로,
    {corp_code: 행위자 키} 맵(actor_corp_ids)을 sightings에 영속 저장하고
    같은 corp_code로 해석되는 키들을 같은 실체로 별칭 등록 + 병합한다.

    legacy_index: {fold(과거 사명): set(corp_code)} — '상호변경안내' 공시
    백필(backfill_renames.py)이 만든 소급 개명 맵. 현재 명부에서 해석
    실패한 키만 이 맵으로 2차 해석한다. 정본은 항상 현재 명부 쪽 키.

    가드: 개인 키는 해석 안 함, 한 fold가 복수 corp_code면(동명 회사) 제외.
    """
    s = data.get("sightings", {})
    aliases = data.setdefault("aliases", {})
    ids = data.setdefault("actor_corp_ids", {})
    changed = False
    renamed = 0

    def _resolve(k):
        """키 → (corp_code|None, 현재 명부 여부). 모호(복수 cc)는 None."""
        ccs: set = set()
        for f in fold_variants(k):
            ccs |= corp_index.get(f, set())
        if len(ccs) == 1:
            return next(iter(ccs)), True
        if not ccs and legacy_index:
            lcs: set = set()
            for f in fold_variants(k):
                lcs |= legacy_index.get(f, set())
            if len(lcs) == 1:
                return next(iter(lcs)), False
        return None, False

    # 1패스: corp_code별 현재/과거 사명 키 그룹
    groups: dict = {}
    for k in s:
        if classify_actor(k) == "person":
            continue
        cc, is_cur = _resolve(k)
        if cc:
            groups.setdefault(cc, {"cur": [], "old": []})[
                "cur" if is_cur else "old"].append(k)

    # 2패스: 그룹별 정본 결정(현재 명부 키 우선, 동률이면 레코드 최다) + 별칭
    for cc, g in groups.items():
        keys = g["cur"] + g["old"]
        cands = g["cur"] or keys
        canon = max(cands, key=lambda k: len(s[k]))
        prev = ids.get(cc)
        for k in keys:
            if k != canon and aliases.get(k) != canon:
                aliases[k] = canon
                renamed += 1
        if prev and prev != canon and prev in s and aliases.get(prev) != canon:
            aliases[prev] = canon         # 이전 실행 키가 개명으로 대체됨
            renamed += 1
        if ids.get(cc) != canon:
            ids[cc] = canon
            changed = True
    if renamed:
        print(f"[RENAME] corp_code 재해석 개명 병합: {renamed}건")
        for k in list(s.keys()):          # 방금 등록된 별칭 즉시 재키잉
            canon = aliases.get(k)
            if canon and canon != k:
                dst = s.setdefault(canon, [])
                for rec in s[k]:
                    if not _is_dup(dst, rec):
                        dst.append(rec)
                del s[k]
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
        # 문제 회사 등장 기록의 출처(src) 혼합을 evidence에 반영 — 인수자·
        # 유출 상대방·신규 최대주주 중 실제 등장한 것만, 고정 순서로 나열.
        present_srcs = {r.get("src") or "funding" for r in recs
                        if r.get("corp_code") in problem_codes}
        src_label = "·".join(SRC_LABELS[s] for s in _SRC_ORDER if s in present_srcs) \
            or SRC_LABELS["funding"]
        actors.setdefault(nm, []).append({
            "source": "자동 발굴",
            "status": "auto_matched",
            "evidence": f"문제 회사 {len(problem_codes)}곳 등장({src_label}): {'·'.join(corp_names[:5])}",
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
                       stats: dict | None = None, watch: list | None = None,
                       outflow_stats: dict | None = None,
                       control_stats: dict | None = None) -> str:
    """매일 발송하는 heartbeat 요약(변경 없어도 작동 확인용).

    stats가 있으면 수집 규모를 함께 표기한다 — '신규 등재 0명'이 정상
    (수집은 됐지만 반복 인물이 없음)인지 이상(수집 자체가 죽음)인지
    리포트만 보고 판별할 수 있게 한다. outflow_stats·control_stats는
    v1.8.0에서 추가된 두 수집원(자금유출 상대방·신규 최대주주)의 통계로,
    없으면(기존 호출자) 해당 줄을 생략한다(하위 호환).
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
    if outflow_stats:
        lines.append(
            f"· 수집(자금유출 상대방): 공시 {outflow_stats.get('scanned', 0)}건 스캔 · "
            f"자금유출성거래 {outflow_stats.get('outflow', 0)}건 · "
            f"상대방 {outflow_stats.get('extracted', 0)}건 추출"
        )
        if outflow_stats.get("truncated"):
            lines.append("· ⚠️ 자금유출 수집 페이지 상한 도달 — 공시 일부 누락 가능")
    if control_stats:
        lines.append(
            f"· 수집(신규 최대주주): 공시 {control_stats.get('scanned', 0)}건 스캔 · "
            f"최대주주변경 {control_stats.get('control', 0)}건 · "
            f"신규 최대주주 {control_stats.get('extracted', 0)}건 추출"
        )
        if control_stats.get("truncated"):
            lines.append("· ⚠️ 최대주주변경 수집 페이지 상한 도달 — 공시 일부 누락 가능")
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

    # v1.8.0: 자금유출 상대방 + 신규 최대주주 — 기존 funding과 같은 윈도우로
    # 수집해 sightings에 합류. 문제 회사 필터는 여기서도 적용하지 않는다
    # (등재 시점 지연 평가는 아래 promote_repeat_actors가 공통 수행).
    outflow_new, outflow_stats = collect_outflow_sightings(key)
    if merge_sightings(sdata, outflow_new):
        s_changed = True
    control_new, control_stats = collect_control_change_sightings(key)
    if merge_sightings(sdata, control_new):
        s_changed = True

    # 수동 개명 시드(sightings 옆 manual_renames.json) 자동 반영 —
    # KOSPI 개명 등 '상호변경안내' 백필이 못 잡는 케이스의 운영자 등재 경로
    if apply_manual_renames(sdata, sightings_path.parent / _MANUAL_RENAMES_NAME):
        s_changed = True

    # 법인 행위자 개명 추적 — corpCode 명부(24h 캐시) + 상호변경 백필 맵
    # (corp_renames, backfill_renames.py) + corp-aliases(명부 diff) 기반.
    # 추가 API 호출 없음(corp-aliases는 레포 동봉/24h 캐시)
    if reconcile_corp_renames(sdata, _corp_name_index(key),
                              _combined_legacy_index(sdata)):
        s_changed = True

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
                                watch=watch, outflow_stats=outflow_stats,
                                control_stats=control_stats)
    if promoted:
        if written == len(promoted):
            note = ""
        elif not notion_credentials_configured():
            # 자격증명이 실제로 없을 때만 이 원인을 지목한다 — add_registry_record는
            # 이 경우 요청 자체를 보내지 않고 조용히 False를 반환하므로, 여기서
            # 확인한 사실(설정 안 됨)과 그 반환값이 항상 일치한다.
            note = " — NOTION_TOKEN/DB_KNOWN_ACTORS 미설정(요청 자체가 나가지 않음)"
        else:
            # 자격증명은 있는데 일부만 성공 — 레이트리밋(429)·일시 장애(5xx)·
            # 기타 오류 가능성. 원인은 add_registry_record가 남긴 WARNING 로그
            # (상태코드 + Notion 오류코드/메시지)를 봐야 알 수 있다. 자격증명을
            # 지목하는 건 오진단이다(2026-07-29 사고, refresh_known_actors 동일 결함).
            note = " — 자격증명은 정상, 일부 기록 실패(원인은 로그 확인)"
        report += f"\n※ Notion 레지스트리 기록: {written}/{len(promoted)}건{note}"
    sent = send_mail("[known_actors] 일일 자동 발굴 리포트", report)

    print(f"공시 {stats['scanned']}건 · 자금조달 {stats['funding']}건 · sighting {stats['extracted']}건"
          f" · 자금유출 {outflow_stats['outflow']}건(상대방 {outflow_stats['extracted']}건)"
          f" · 최대주주변경 {control_stats['control']}건(신규주주 {control_stats['extracted']}건)"
          f" · sightings {'갱신' if s_changed else '무변경'} · 신규 등재 {len(promoted)}건"
          + (" · 리포트 발송" if sent else " · 리포트 스킵(자격증명 없음)"))


if __name__ == "__main__":
    main()
