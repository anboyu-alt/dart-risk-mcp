"""행위자 연결망 시각화 HTML 생성.

sightings.json에서 서로 다른 문제 회사 2곳+에 반복 등장한 추적 행위자
(개인·조합·법인, classify_actor 기준)와 그 회사를 이분 그래프로 뽑아,
자체 완결형 HTML(외부 CDN 없음)로 렌더한다. 조각·제도권 기관은 제외.

각 행위자→회사 엣지는 해당 회사에서의 최신 공시 링크를 담아, 상세 패널의
회사명을 열면 원본 공시로 이동한다.

⚠️ 출력 HTML에는 실명이 담기므로 public 레포에 커밋 금지 — 개인 열람·
   비공개 배포용. 스크립트(데이터 없음)만 레포에 둔다.

사용: python scripts/build_network_html.py [--out network.html] [--min 2]
환경: SIGHTINGS_PATH (기본: tmp/sightings.json)
"""
import argparse
import json
import os
from pathlib import Path

from dart_risk_mcp.core.known_actors import classify_actor, disclosure_url

_ROOT = Path(__file__).resolve().parents[1]
_TEMPLATE = Path(__file__).resolve().parent / "network_template.html"
_TRACKED = ("person", "fund", "corp")
_PLACEHOLDER = '/*__GRAPH_DATA__*/{"nodes":[],"links":[]}/*__END__*/'

# DART corp_cls → (시장 라벨, 코드). Y=유가증권(KOSPI)·K=코스닥·N=코넥스·
# E/기타/미상=비상장. 회사 노드 시장 태깅용.
_MARKET = {"Y": ("KOSPI", "kospi"), "K": ("KOSDAQ", "kosdaq"),
           "N": ("KONEX", "konex"), "E": ("비상장", "unlisted")}


def market_of(cls: str):
    """corp_cls 코드 → (라벨, 코드). 미상·빈값은 비상장으로 폴백."""
    return _MARKET.get((cls or "").strip().upper(), ("비상장", "unlisted"))


def build_graph(sightings: dict, min_companies: int = 2) -> dict:
    """sightings → {nodes, links}. min_companies 미만/비추적 행위자 제외."""
    s = sightings.get("sightings", {})
    comp_events_raw: dict = sightings.get("company_events", {})   # cc -> [{date,rcept_no,event_type}]
    nodes, links = [], []
    company_label: dict = {}       # corp_code -> corp_name
    company_deg: dict = {}         # corp_code -> {actor_id}
    company_cls: dict = {}         # corp_code -> corp_cls (첫 비어있지 않은 값)
    months: set = set()            # 스크러버용 전체 월(YYYY-MM) 집합

    for name, recs in s.items():
        kind = classify_actor(name)
        if kind not in _TRACKED:
            continue
        # 회사별 진입(in)·이탈(out) 이벤트 집계
        by_cc: dict = {}
        for r in recs:
            cc = r.get("corp_code")
            if not cc:
                continue
            corp = r.get("corp") or cc
            d = by_cc.setdefault(cc, {"corp": corp, "ins": [], "outs": [], "latest": ""})
            d["corp"] = corp
            company_label.setdefault(cc, corp)
            cls = (r.get("corp_cls") or "").strip()
            if cls and not company_cls.get(cc):
                company_cls[cc] = cls
            rc, dt, ev = r.get("rcept_no", ""), r.get("date", ""), r.get("event", "in")
            if dt:
                months.add(dt)
            if ev == "out":
                d["outs"].append((dt, rc, r.get("event_type", "이탈"), r.get("pct")))
            else:
                d["ins"].append((dt, rc))
            if rc and rc > d["latest"]:
                d["latest"] = rc
        # 진입(in)이 있는 회사만 엣지 형성 — 이탈만 있고 진입 없는 관계는 그리지 않음
        cc_in = {cc: d for cc, d in by_cc.items() if d["ins"]}
        if len(cc_in) < min_companies:
            continue
        aid = "a:" + name
        companies = []
        for cc, d in sorted(cc_in.items(), key=lambda kv: kv[1]["latest"], reverse=True):
            _, mkt = market_of(company_cls.get(cc, ""))
            in_dates = sorted(dt for dt, _ in d["ins"] if dt)
            out_dates = sorted(dt for dt, _, _, _ in d["outs"] if dt)
            t_in = in_dates[0] if in_dates else ""
            t_out = out_dates[-1] if out_dates else ""
            status = "exited" if (t_out and (not t_in or t_out >= t_in)) else "active"
            # 이벤트 타임라인(진입·이탈) — 회사 단위 전환청구도 회사기준으로 병합
            evs = [{"date": dt, "dir": "in", "type": "인수·투자", "url": disclosure_url(rc)}
                   for dt, rc in d["ins"]]
            for dt, rc, ty, pct in d["outs"]:
                e = {"date": dt, "dir": "out", "type": ty, "url": disclosure_url(rc)}
                if pct is not None:
                    e["pct"] = pct
                evs.append(e)
            for ce in comp_events_raw.get(cc, []):
                cdt = ce.get("date", "")
                if cdt:
                    months.add(cdt)
                evs.append({"date": cdt, "dir": "out", "company_level": True,
                            "type": ce.get("event_type", "전환청구") + "·회사기준",
                            "url": disclosure_url(ce.get("rcept_no", ""))})
            evs.sort(key=lambda e: e.get("date") or "")
            companies.append({"name": d["corp"], "url": disclosure_url(d["latest"]),
                              "mkt": mkt, "t_in": t_in, "t_out": t_out,
                              "status": status, "events": evs})
            links.append({"source": aid, "target": "c:" + cc,
                          "t_in": t_in, "t_out": t_out, "status": status})
            company_deg.setdefault(cc, set()).add(aid)
        nodes.append({
            "id": aid, "label": name, "type": kind,
            "deg": len(cc_in), "sight": len(recs), "companies": companies,
        })

    for cc, actors in company_deg.items():
        label, mkt = market_of(company_cls.get(cc, ""))
        cev = [{"date": e.get("date", ""), "type": e.get("event_type", "전환청구"),
                "url": disclosure_url(e.get("rcept_no", ""))}
               for e in comp_events_raw.get(cc, [])]
        nodes.append({"id": "c:" + cc, "label": company_label.get(cc, cc),
                      "type": "company", "deg": len(actors),
                      "market": label, "mkt": mkt, "events": cev})
    span = {"min": min(months), "max": max(months)} if months else {"min": "", "max": ""}
    return {"nodes": nodes, "links": links, "span": span}


def render_html(graph: dict) -> str:
    tpl = _TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps(graph, ensure_ascii=False)
    return tpl.replace(_PLACEHOLDER, payload, 1)


def main():
    ap = argparse.ArgumentParser(description="행위자 연결망 HTML 생성")
    ap.add_argument("--out", default=str(_ROOT / "tmp" / "network.html"))
    ap.add_argument("--min", type=int, default=2, help="최소 등장 회사 수")
    args = ap.parse_args()

    sightings_path = Path(os.environ.get("SIGHTINGS_PATH") or (_ROOT / "tmp" / "sightings.json"))
    sightings = json.loads(sightings_path.read_text(encoding="utf-8"))
    graph = build_graph(sightings, min_companies=args.min)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(graph), encoding="utf-8")

    actors = sum(1 for n in graph["nodes"] if n["type"] != "company")
    print(f"[OK] {out} · 행위자 {actors} · 회사 {len(graph['nodes']) - actors} · "
          f"연결 {len(graph['links'])}")


if __name__ == "__main__":
    main()
