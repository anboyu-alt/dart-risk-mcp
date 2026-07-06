"""known_actors 자동 갱신 — 시장 신규 CB/유상증자 공시에서 등재 인물의 인수 근거 수집.

GitHub Actions cron이 매일 실행. 등재 인물만 대상이며, 자동 매칭은 status=auto_matched
(동명이인 미확인)로 추가하고 verified로 승격하지 않는다.

레지스트리 원본은 비공개 Notion DB(NOTION_TOKEN + DB_KNOWN_ACTORS) —
public 레포에는 어떤 인물 데이터도 커밋하지 않는다. env 미설정 시
근거 기록은 스킵하고 메일 통지만 수행한다.

사용: python scripts/refresh_known_actors.py
API 키: 환경변수 DART_API_KEY 또는 tmp/_apikey.txt.
"""
import os
import smtplib
from datetime import datetime, timedelta
from email.message import EmailMessage
from pathlib import Path

from dart_risk_mcp.core.dart_client import fetch_market_disclosures
from dart_risk_mcp.core.cb_extractor import extract_cb_investors
from dart_risk_mcp.core.investor_extractor import extract_rights_offering_investors
from dart_risk_mcp.core.known_actors import (
    normalize_name,
    load_known_actors,
    fetch_registry_from_notion,
    add_registry_record,
    classify_actor,
    KIND_LABELS,
    disclosure_url,
)
from dart_risk_mcp.core.signals import match_signals, strip_amendment_prefix

WINDOW_DAYS = 2
MAX_PAGES = 10


def _api_key() -> str:
    key = os.environ.get("DART_API_KEY")
    if key:
        return key.strip()
    p = Path(__file__).resolve().parents[1] / "tmp" / "_apikey.txt"
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def collect_auto_matches(api_key, known_names, window_days=WINDOW_DAYS, max_pages=MAX_PAGES):
    """최근 window_days CB/유상증자 공시에서 known_names와 매칭되는 인수자 근거 수집.

    매칭은 표기 정규화(공백·대소문자) 기준 — 레지스트리에 'Yoo Andy C'로
    등재된 인물이 공시에 'YOO ANDY C'로 등장해도 잡는다. 정정공시도
    접두사를 벗겨 스캔한다(대상자 변경 정정본에 확정 명단이 실리므로).

    반환: {레지스트리 등재 표기 그대로의 인물명: [auto_matched record, ...]}
    """
    end = datetime.now()
    start = end - timedelta(days=max(1, window_days))
    discs = fetch_market_disclosures(
        api_key, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"),
        pblntf_ty="B", max_pages=max_pages) or []
    norm_to_canon = {normalize_name(k): k for k in known_names}
    matches = {}
    for d in discs:
        rn = d.get("rcept_no", "")
        rnm = d.get("report_nm", "")
        corp = d.get("corp_name", "")
        cc = d.get("corp_code", "")
        if not rn:
            continue
        keys = {s["key"] for s in (match_signals(strip_amendment_prefix(rnm)) or [])}
        invs = []
        if keys & {"CB_BW", "EB"}:
            invs += [("CB인수", i) for i in (extract_cb_investors(rn, api_key, cc) or [])]
        if keys & {"3PCA", "RIGHTS_UNDER"}:
            invs += [("유상증자", i) for i in (extract_rights_offering_investors(rn, api_key, cc) or [])]
        rdt = (d.get("rcept_dt", "") or "")
        date = f"{rdt[:4]}-{rdt[4:6]}" if len(rdt) >= 6 else ""
        for label, inv in invs:
            nm = (inv.get("name") or "").strip()
            canon = norm_to_canon.get(normalize_name(nm)) if nm else None
            if canon:
                kind = classify_actor(canon)
                same_name_tag = ("동명이인 미확인" if kind == "person"
                                 else "동명 법인·조합 미확인")
                matches.setdefault(canon, []).append({
                    "source": f"DART {label}(자동매칭)",
                    "status": "auto_matched",
                    "evidence": f"{corp} {label} 인수자로 등장",
                    "url": f"https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rn}",
                    "date": date,
                    "rcept_no": rn,
                    "tags": ["자동 매칭", same_name_tag],
                    "companies": [corp] if corp else [],
                    "company_links": {corp: disclosure_url(rn)} if corp else {},
                    "kind": KIND_LABELS.get(kind, "개인"),
                })
    return matches


def merge_auto_matches(data: dict, matches: dict) -> list:
    """matches를 data에 병합. 등재 인물만, 동일 rcept_no 중복 스킵.

    반환: 새로 추가된 (인물명, 기록) 튜플 리스트 — 호출측이 레지스트리에
    기록할 대상. 변경 없으면 빈 리스트(기존 bool 사용처와 truthiness 호환).
    """
    actors = data.setdefault("actors", {})
    added = []
    for name, recs in matches.items():
        if name not in actors:
            continue  # 등재 인물만 근거 추가 (새 인물 등재 안 함)
        seen = {r.get("rcept_no") for r in actors[name] if r.get("rcept_no")}
        for rec in recs:
            if rec.get("rcept_no") and rec["rcept_no"] in seen:
                continue
            actors[name].append(rec)
            seen.add(rec.get("rcept_no"))
            added.append((name, rec))
    return added


def build_change_summary(data: dict, matches: dict) -> str:
    """status별 집계 + 이번 변경분을 평문 요약으로 반환 (사실 표기·판정 아님)."""
    counts = {"verified": 0, "maintainer_seed": 0, "auto_matched": 0}
    for recs in data.get("actors", {}).values():
        for r in recs:
            st = r.get("status", "")
            if st in counts:
                counts[st] += 1
    lines = [
        "known_actors 자동 갱신 — 변경 알림 (사실 표기 · 판정 아님)",
        "",
        f"현재 등재 근거: verified {counts['verified']} · "
        f"maintainer_seed {counts['maintainer_seed']} · auto_matched {counts['auto_matched']}",
        "",
        "이번 추가:",
    ]
    for name, recs in matches.items():
        for r in recs:
            lines.append(f"  - {name} — {r.get('evidence', '')} (접수 {r.get('rcept_no', '')})")
    lines.append("")
    lines.append("자동 매칭은 동명이인 미확인 — 원본 공시로 확인 필요. 판정 아님.")
    return "\n".join(lines)


def send_mail(subject: str, body: str) -> bool:
    """제작자 Gmail로 발송. 자격증명(env) 미설정 시 스킵(False). 예외도 False."""
    user = os.environ.get("MAIL_USER")
    pw = os.environ.get("MAIL_APP_PASSWORD")
    to = os.environ.get("MAIL_TO")
    if not (user and pw and to):
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = user
        msg["To"] = to
        msg.set_content(body)
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.starttls()
            s.login(user, pw)
            s.send_message(msg)
        return True
    except Exception:
        return False


def main():
    key = _api_key()
    if not key:
        raise SystemExit("DART_API_KEY 또는 tmp/_apikey.txt 필요")
    # 크론 실행은 캐시를 우회해 항상 최신 레지스트리로 중복 판정한다
    data = fetch_registry_from_notion() or load_known_actors()
    known_names = set(data.get("actors", {}).keys())
    matches = collect_auto_matches(key, known_names)
    added = merge_auto_matches(data, matches)
    if added:
        written = sum(1 for name, rec in added if add_registry_record(name, rec))
        summary = build_change_summary(data, matches)
        summary += (f"\n※ Notion 레지스트리 기록: {written}/{len(added)}건"
                    + ("" if written == len(added)
                       else " — NOTION_TOKEN/DB_KNOWN_ACTORS 설정 확인 필요"))
        sent = send_mail("[known_actors] 자동 갱신 변경 알림", summary)
        print(f"갱신: {len(added)}건 근거 추가, Notion 기록 {written}건"
              + (" (메일 발송)" if sent else " (메일 스킵)"))
    else:
        print("변경 없음")


if __name__ == "__main__":
    main()
