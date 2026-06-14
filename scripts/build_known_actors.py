"""공개기록 행위자 레지스트리 부트스트랩.

인물명 + 후보 회사군을 받아, 그 인물이 등기임원 / CB·유상증자 인수자로 등장하는
회사·연도를 DART에서 집계해 dart_risk_mcp/data/known_actors.json 엔트리를 생성한다.
사람은 회사 단서만 주고, 근거(회사·연도·출처)는 코드가 채운다.

사용: python scripts/build_known_actors.py
API 키: tmp/_apikey.txt 또는 환경변수 DART_API_KEY.
"""
import json
import os
from pathlib import Path

from dart_risk_mcp.core.dart_client import (
    resolve_corp, fetch_executive_roster, fetch_company_disclosures,
)
from dart_risk_mcp.core.signals import match_signals, is_amendment_disclosure
from dart_risk_mcp.core.cb_extractor import extract_cb_investors
from dart_risk_mcp.core.investor_extractor import extract_rights_offering_investors

# 회사 단서가 있는 인물만 (CASSANDRA knowledge-base 기반, 회사명은 DART resolve 대상)
SEED = {
    "신승수": ["이엠앤아이", "제이케이시냅스", "CG인바이츠", "헬스커넥트", "티쓰리"],
    "오종원": ["인트로메딕"],
    "김준범": ["씨그널엔터테인먼트그룹"],
}
LOOKBACK_YEARS = 3
DATA_PATH = Path(__file__).resolve().parents[1] / "dart_risk_mcp" / "data" / "known_actors.json"


def _api_key() -> str:
    key = os.environ.get("DART_API_KEY")
    if key:
        return key.strip()
    p = Path(__file__).resolve().parents[1] / "tmp" / "_apikey.txt"
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def collect(person: str, companies: list[str], api_key: str) -> list[dict]:
    exec_hits = {}   # company -> set(years)
    inv_hits = {}    # company -> set(source labels)
    for q in companies:
        r = resolve_corp(q, api_key)
        if not r:
            continue
        name, info = r
        cc = info["corp_code"]
        # 임원 차원
        roster = fetch_executive_roster(cc, api_key, LOOKBACK_YEARS) or {}
        if person in roster:
            exec_hits.setdefault(name, set()).update(roster[person])
        # 투자자 차원 (최근 lookback*365일 CB/유상증자 인수자)
        discs = fetch_company_disclosures(cc, api_key, LOOKBACK_YEARS * 365) or []
        for d in discs:
            rn, rnm = d.get("rcept_no", ""), d.get("report_nm", "")
            if not rn or is_amendment_disclosure(rnm):
                continue
            keys = {s["key"] for s in (match_signals(rnm) or [])}
            invs = []
            if keys & {"CB_BW", "EB"}:
                invs += [("CB인수", i) for i in (extract_cb_investors(rn, api_key, cc) or [])]
            if keys & {"3PCA", "RIGHTS_UNDER"}:
                invs += [("유상증자", i) for i in (extract_rights_offering_investors(rn, api_key, cc) or [])]
            for label, inv in invs:
                if (inv.get("name") or "").strip() == person:
                    inv_hits.setdefault(name, set()).add(label)

    records = []
    if exec_hits:
        comps = sorted(exec_hits.keys())
        yrs = sorted({y for s in exec_hits.values() for y in s})
        records.append({
            "source": "DART 임원현황",
            "evidence": f"{'·'.join(comps)} 등기임원 ({yrs[0]}–{yrs[-1]})" if len(yrs) > 1
                        else f"{'·'.join(comps)} 등기임원 ({yrs[0]})",
            "url": "https://dart.fss.or.kr",
            "date": f"{yrs[0]}-{yrs[-1]}" if len(yrs) > 1 else yrs[0],
            "tags": ["다수 상장사 등기임원 겸직"] if len(comps) >= 2 else ["상장사 등기임원"],
        })
    for company, labels in sorted(inv_hits.items()):
        records.append({
            "source": f"DART {'·'.join(sorted(labels))}",
            "evidence": f"{company} {'·'.join(sorted(labels))} 인수자 등장",
            "url": "https://dart.fss.or.kr",
            "date": "",
            "tags": ["상장사 자금조달 인수자"],
        })
    return records


def main():
    key = _api_key()
    if not key:
        raise SystemExit("DART_API_KEY 또는 tmp/_apikey.txt 필요")
    data = {"version": 1, "updated": "2026-06-14", "actors": {}}
    for person, companies in SEED.items():
        recs = collect(person, companies, key)
        if recs:
            data["actors"][person] = recs
            print(f"  {person}: {len(recs)}건 근거 집계")
        else:
            print(f"  {person}: 근거 없음(스킵)")
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {DATA_PATH}")


if __name__ == "__main__":
    main()
