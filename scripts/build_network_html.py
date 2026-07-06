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


def build_graph(sightings: dict, min_companies: int = 2) -> dict:
    """sightings → {nodes, links}. min_companies 미만/비추적 행위자 제외."""
    s = sightings.get("sightings", {})
    nodes, links = [], []
    company_label: dict = {}       # corp_code -> corp_name
    company_deg: dict = {}         # corp_code -> {actor_id}

    for name, recs in s.items():
        kind = classify_actor(name)
        if kind not in _TRACKED:
            continue
        # 회사별 최신 rcept (공시 링크용)
        latest: dict = {}          # corp_code -> (rcept, corp_name)
        for r in recs:
            cc, corp, rc = r.get("corp_code"), r.get("corp"), r.get("rcept_no")
            if not cc:
                continue
            if rc and rc > (latest.get(cc, ("", ""))[0]):
                latest[cc] = (rc, corp or cc)
            company_label.setdefault(cc, corp or cc)
        if len(latest) < min_companies:
            continue
        aid = "a:" + name
        companies = []
        for cc, (rc, corp) in sorted(latest.items(), key=lambda kv: kv[1][0], reverse=True):
            companies.append({"name": corp, "url": disclosure_url(rc)})
            links.append({"source": aid, "target": "c:" + cc})
            company_deg.setdefault(cc, set()).add(aid)
        nodes.append({
            "id": aid, "label": name, "type": kind,
            "deg": len(latest), "sight": len(recs), "companies": companies,
        })

    for cc, actors in company_deg.items():
        nodes.append({"id": "c:" + cc, "label": company_label.get(cc, cc),
                      "type": "company", "deg": len(actors)})
    return {"nodes": nodes, "links": links}


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
