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

from dart_risk_mcp.core.known_actors import classify_actor, disclosure_url, fold_name

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
    """sightings → {nodes, links}. min_companies 미만/비추적 행위자 제외.

    같은 실체(투자를 받은 회사 + 다른 종목에 투자한 동명 법인·개인)는 하나의
    노드로 병합한다. 엔켐처럼 '엔켐'(회사, 투자받음)과 '주식회사 엔켐'(법인,
    다른 종목 투자)이 fold_name 기준 일치하면 회사 코드(c:cc)로 단일화 —
    엣지 날조 없이 투자자 엔드포인트 라벨만 회사 코드로 바꾸고 중복 노드를
    삭제한다. 한 fold가 복수 corp_code로 접히면(모호) 병합하지 않는다.
    """
    s = sightings.get("sightings", {})
    comp_events_raw: dict = sightings.get("company_events", {})   # cc -> [{date,rcept_no,event_type}]
    # 별칭 역맵: 정본 → [별칭…] (같은 인물의 다른 표기를 상세 패널에 표시)
    alias_rev: dict = {}
    for a, c in (sightings.get("aliases") or {}).items():
        alias_rev.setdefault(c, []).append(a)
    links = []
    node_reg: dict = {}            # id -> node dict (행위자·회사 역할 필드 통합)
    company_label: dict = {}       # corp_code -> corp_name
    company_deg: dict = {}         # corp_code -> {actor_id}
    company_cls: dict = {}         # corp_code -> corp_cls (첫 비어있지 않은 값)
    months: set = set()            # 스크러버용 전체 월(YYYY-MM) 집합
    exit_only_actors: set = set()  # 이탈이 있어 포함됐지만 2사 미만인 행위자 id

    # ── Phase A: 사전 스캔 — 병합 판정 전에 전체 회사 라벨·시장구분 확보 ──
    # (병합 시점에 회사가 아직 안 채워지는 순서 의존을 제거)
    for _name, _recs in s.items():
        for r in _recs:
            cc = r.get("corp_code")
            if not cc:
                continue
            company_label.setdefault(cc, r.get("corp") or cc)
            cls = (r.get("corp_cls") or "").strip()
            if cls and not company_cls.get(cc):
                company_cls[cc] = cls

    # ── Phase B: fold→cc 맵 + 충돌 가드 ──
    _fold_ccs: dict = {}
    for cc, lab in company_label.items():
        _fold_ccs.setdefault(fold_name(lab), set()).add(cc)
    # 한 fold가 복수 corp_code면 모호 → 자동 병합 금지(맵에서 제외)
    fold2cc = {f: next(iter(ccs)) for f, ccs in _fold_ccs.items() if len(ccs) == 1}

    def canon_actor_id(nm: str) -> str:
        cc = fold2cc.get(fold_name(nm))
        return ("c:" + cc) if cc else ("a:" + nm)

    # ── Phase C: 노드 레지스트리 병합 ──
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
        # 2사 미만이어도 '이탈' 기록이 있으면 포함(기본 숨김, '이탈만' 토글로 노출).
        has_out = any(d["outs"] for d in cc_in.values())
        if len(cc_in) < min_companies and not has_out:
            continue
        aid = canon_actor_id(name)
        exit_only = len(cc_in) < min_companies
        if exit_only:
            exit_only_actors.add(aid)
        companies = []
        for cc, d in sorted(cc_in.items(), key=lambda kv: kv[1]["latest"], reverse=True):
            # self-loop 가드 — 병합된 노드가 자기 자신에 투자한 관계는 링크·목록 모두 스킵
            if aid == "c:" + cc:
                continue
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
        # 노드 레지스트리에 행위자 역할 필드 누적(병합 시 같은 id로 합쳐짐)
        reg = node_reg.setdefault(aid, {"id": aid})
        reg["actor_kind"] = kind
        reg["companies"] = companies
        reg["out_deg"] = len(companies)
        reg["sight"] = reg.get("sight", 0) + len(recs)
        reg["actor_exit_only"] = exit_only
        if not aid.startswith("c:"):
            reg["label"] = name
        # 별칭: 정본 별칭 + (병합 시) 행위자 원표기를 aliases로 보존
        al = set(reg.get("aliases", []))
        al.update(alias_rev.get(name, []))
        if aid.startswith("c:"):
            al.add(name)
        if al:
            reg["aliases"] = sorted(al)

    # 회사 역할 필드 병합(투자받은 회사 노드 = c:cc)
    for cc, actors in company_deg.items():
        label, mkt = market_of(company_cls.get(cc, ""))
        cev = [{"date": e.get("date", ""), "type": e.get("event_type", "전환청구"),
                "url": disclosure_url(e.get("rcept_no", ""))}
               for e in comp_events_raw.get(cc, [])]
        # 회사도 이탈-only 행위자에만 연결되면 exit_only(기본 숨김)
        c_exit_only = actors.issubset(exit_only_actors)
        reg = node_reg.setdefault("c:" + cc, {"id": "c:" + cc})
        reg["market"] = label
        reg["mkt"] = mkt
        reg["events"] = cev
        reg["in_deg"] = len(actors)
        reg["company_exit_only"] = c_exit_only

    # ── 파생 필드 + nodes 리스트 ──
    # 무방향 이웃 집합(distinct in∪out) — deg(반경·라벨 판정) 계산용
    neighbor_ids: dict = {}
    for l in links:
        neighbor_ids.setdefault(l["source"], set()).add(l["target"])
        neighbor_ids.setdefault(l["target"], set()).add(l["source"])
    nodes = []
    for nid, reg in node_reg.items():
        is_company = nid.startswith("c:")
        in_deg = reg.get("in_deg", 0)
        out_deg = reg.get("out_deg", 0)
        reg["in_deg"] = in_deg
        reg["out_deg"] = out_deg
        reg["type"] = "company" if is_company else reg.get("actor_kind", "corp")
        reg["dual"] = in_deg > 0 and out_deg > 0
        reg["deg"] = len(neighbor_ids.get(nid, ()))
        # exit_only 합성 — 두 역할 다 비핵심일 때만 숨김. 없는 역할은 중립(True).
        a_eo = reg.get("actor_exit_only")
        c_eo = reg.get("company_exit_only")
        reg["exit_only"] = bool((a_eo if a_eo is not None else True)
                                and (c_eo if c_eo is not None else True))
        if is_company:
            reg["label"] = company_label.get(nid[2:], nid[2:])
        else:
            reg.setdefault("label", nid[2:])
        nodes.append(reg)
    span = {"min": min(months), "max": max(months)} if months else {"min": "", "max": ""}
    return {"nodes": nodes, "links": links, "span": span}


def split_details(graph: dict) -> dict:
    """무거운 타임라인·공시 링크를 details로 분리 — 첫 로딩 경량화.

    그래프(HTML 내장)에는 검색·필터·배지에 필요한 경량 필드만 남기고,
    상세 패널용 이벤트·URL은 details.json으로 빼서 노드 클릭 시 지연 로딩.
    (전체 이벤트·URL이 페이로드의 대부분이라 메인스레드 파싱 블록의 주범)
    """
    details: dict = {}
    for n in graph["nodes"]:
        d: dict = {}
        full = n.get("companies")
        if full:
            # 무거운 이벤트·URL은 details로, 인라인엔 경량 필드(name/mkt/status)만
            d["companies"] = full
            n["companies"] = [{"name": c["name"], "mkt": c["mkt"],
                               "status": c["status"]} for c in full]
        evs = n.pop("events", None)
        if evs:
            d["events"] = evs
        # 이중역할 노드는 companies·events 둘 다 details에 저장
        if d:
            details[n["id"]] = d
    return details


def render_html(graph: dict) -> str:
    tpl = _TEMPLATE.read_text(encoding="utf-8")
    payload = json.dumps(graph, ensure_ascii=False)
    # JSON.parse("...") 임베딩 — 대형 페이로드는 JS 객체 리터럴 평가보다
    # 문자열 JSON 파싱이 훨씬 빨라 첫 화면 스크립트 블록 시간을 줄인다.
    embedded = "JSON.parse(" + json.dumps(payload, ensure_ascii=False).replace("</", "<\\/") + ")"
    return tpl.replace(_PLACEHOLDER, embedded, 1)


def main():
    ap = argparse.ArgumentParser(description="행위자 연결망 HTML 생성")
    ap.add_argument("--out", default=str(_ROOT / "tmp" / "network.html"))
    ap.add_argument("--min", type=int, default=2, help="최소 등장 회사 수")
    args = ap.parse_args()

    sightings_path = Path(os.environ.get("SIGHTINGS_PATH") or (_ROOT / "tmp" / "sightings.json"))
    sightings = json.loads(sightings_path.read_text(encoding="utf-8"))
    graph = build_graph(sightings, min_companies=args.min)

    details = split_details(graph)

    out = Path(args.out)
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(render_html(graph), encoding="utf-8")
    dpath = out.parent / "details.json"
    dpath.write_text(json.dumps(details, ensure_ascii=False), encoding="utf-8")

    actors = sum(1 for n in graph["nodes"] if n["type"] != "company")
    dual = sum(1 for n in graph["nodes"] if n.get("dual"))
    print(f"[OK] {out} ({out.stat().st_size//1024}KB) + details.json "
          f"({dpath.stat().st_size//1024}KB) · 행위자 {actors} · "
          f"회사 {len(graph['nodes']) - actors} · 이중역할 {dual} · "
          f"연결 {len(graph['links'])}")


if __name__ == "__main__":
    main()
