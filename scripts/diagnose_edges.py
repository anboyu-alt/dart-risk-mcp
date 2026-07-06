"""이탈 엣지가 실제로 그래프에 생성되는지 진단(점선이 안 보이는 원인 규명).

sightings에는 지분감소 'out' 이벤트가 있는데도 화면에 점선이 없다면,
그 이탈이 (a) 최소 2사 필터에 걸려 노드/엣지가 안 만들어지거나,
(b) 상태 계산이 어긋난 것이다. build_graph를 실제 sightings로 돌려
링크 상태(active/exited)를 세고 예시를 출력한다. DART 조회 없음(파일만).

사용: SIGHTINGS_PATH=_sightings/sightings.json python scripts/diagnose_edges.py
"""
import json
import os
from collections import Counter
from pathlib import Path

from scripts.build_network_html import build_graph
from dart_risk_mcp.core.known_actors import classify_actor

_DEFAULT = Path(__file__).resolve().parents[1] / "tmp" / "sightings.json"


def main():
    path = Path(os.environ.get("SIGHTINGS_PATH") or _DEFAULT)
    sdata = json.loads(path.read_text(encoding="utf-8"))
    s = sdata.get("sightings", {})

    # 원자료: 'out' 이벤트 보유 (행위자, 회사) 쌍
    raw_out_pairs = set()
    raw_out_actors = set()
    for nm, recs in s.items():
        for r in recs:
            if r.get("event") == "out":
                raw_out_pairs.add((nm, r.get("corp_code")))
                raw_out_actors.add(nm)
    print(f"[EDGE] sightings 내 'out' 이벤트: (행위자,회사) {len(raw_out_pairs)}쌍 · "
          f"행위자 {len(raw_out_actors)}명")

    # out 보유 행위자별 진입 회사 수(=그래프 노드 자격, 최소 2사)
    multi = 0
    for nm in raw_out_actors:
        in_ccs = {r.get("corp_code") for r in s[nm]
                  if r.get("event") != "out" and r.get("corp_code")}
        if len(in_ccs) >= 2:
            multi += 1
    print(f"[EDGE] 그 중 진입 회사 2곳+ (그래프에 노드로 등장 가능): {multi}명")

    for mc in (2, 1):
        g = build_graph(sdata, min_companies=mc)
        cnt = Counter(l.get("status") for l in g["links"])
        exited = [l for l in g["links"] if l.get("status") == "exited"]
        print(f"\n[EDGE] build_graph(min_companies={mc}) → "
              f"노드 {len(g['nodes'])} · 링크 {len(g['links'])} · 상태 {dict(cnt)}")
        for l in exited[:12]:
            src = next((n['label'] for n in g['nodes'] if n['id'] == l['source']), l['source'])
            tgt = next((n['label'] for n in g['nodes'] if n['id'] == l['target']), l['target'])
            print(f"        이탈엣지: {src} → {tgt}  (t_in {l.get('t_in')} · t_out {l.get('t_out')})")

    print("\n[해석] min=2에서 exited>0 → 점선 데이터는 있음(렌더/새로고침 문제). "
          "min=2 exited=0 이지만 min=1 exited>0 → 이탈 행위자가 단일 회사라 필터에 걸림.")
    print("[DONE]")


if __name__ == "__main__":
    main()
