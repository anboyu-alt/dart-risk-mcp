"""build_network_html — 시장구분(corp_cls) 매핑·회사 노드 태깅 검증."""
from scripts.build_network_html import build_graph, market_of


def test_market_of_maps_corp_cls():
    assert market_of("Y") == ("KOSPI", "kospi")
    assert market_of("K") == ("KOSDAQ", "kosdaq")
    assert market_of("N") == ("KONEX", "konex")
    assert market_of("E") == ("비상장", "unlisted")
    # 소문자·공백·미상·빈값은 비상장 폴백
    assert market_of("k") == ("KOSDAQ", "kosdaq")
    assert market_of("") == ("비상장", "unlisted")
    assert market_of(None) == ("비상장", "unlisted")
    assert market_of("Z") == ("비상장", "unlisted")


def _sightings():
    return {"sightings": {
        "홍길동": [
            {"corp": "에이스", "corp_code": "001", "corp_cls": "Y",
             "rcept_no": "20260501000001", "date": "2026-05", "kind": "person"},
            {"corp": "베타", "corp_code": "002", "corp_cls": "K",
             "rcept_no": "20260601000002", "date": "2026-06", "kind": "person"},
        ],
        "가나조합제1호": [
            {"corp": "베타", "corp_code": "002", "corp_cls": "K",
             "rcept_no": "20260601000003", "date": "2026-06", "kind": "fund"},
            # corp_cls 누락 레코드 — 같은 corp_code(003)의 다른 레코드가 값 보유
            {"corp": "감마", "corp_code": "003",
             "rcept_no": "20260615000004", "date": "2026-06", "kind": "fund"},
            {"corp": "감마", "corp_code": "003", "corp_cls": "E",
             "rcept_no": "20260615000005", "date": "2026-06", "kind": "fund"},
        ],
    }}


def test_company_nodes_get_market():
    g = build_graph(_sightings(), min_companies=2)
    comp = {n["label"]: n for n in g["nodes"] if n["type"] == "company"}
    assert comp["에이스"]["mkt"] == "kospi"
    assert comp["베타"]["mkt"] == "kosdaq"
    # 값이 있는 레코드에서 채워짐 (누락 레코드가 있어도)
    assert comp["감마"]["mkt"] == "unlisted"
    assert comp["감마"]["market"] == "비상장"


def test_actor_company_links_carry_market():
    g = build_graph(_sightings(), min_companies=2)
    actor = next(n for n in g["nodes"] if n["label"] == "홍길동")
    mkts = {c["name"]: c["mkt"] for c in actor["companies"]}
    assert mkts == {"에이스": "kospi", "베타": "kosdaq"}
    # 공시 링크는 살아있는 뷰어 URL
    assert all(c["url"].startswith("https://dart.fss.or.kr/dsaf001/main.do?rcpNo=")
               for c in actor["companies"])


def _temporal_sightings():
    return {
        "company_events": {"003": [
            {"date": "2025-02", "rcept_no": "conv1", "event_type": "전환청구"}]},
        "sightings": {
            "홍길동": [
                {"corp": "에이스", "corp_code": "001", "corp_cls": "Y",
                 "rcept_no": "i1", "date": "2024-03", "kind": "person", "event": "in"},
                {"corp": "베타", "corp_code": "002", "corp_cls": "K",
                 "rcept_no": "i2", "date": "2024-06", "kind": "person", "event": "in"},
                {"corp": "베타", "corp_code": "002", "corp_cls": "K",
                 "rcept_no": "o1", "date": "2025-01", "kind": "person",
                 "event": "out", "event_type": "지분감소", "pct": 3.2},
            ],
            "가나조합제1호": [
                {"corp": "베타", "corp_code": "002", "corp_cls": "K",
                 "rcept_no": "i3", "date": "2024-06", "kind": "fund", "event": "in"},
                {"corp": "감마", "corp_code": "003", "corp_cls": "E",
                 "rcept_no": "i4", "date": "2024-08", "kind": "fund", "event": "in"},
            ],
        },
    }


def test_edge_intervals_and_status():
    g = build_graph(_temporal_sightings(), min_companies=2)
    edges = {(l["source"], l["target"]): l for l in g["links"]}
    beta = edges[("a:홍길동", "c:002")]
    assert beta["t_in"] == "2024-06" and beta["t_out"] == "2025-01"
    assert beta["status"] == "exited"
    ace = edges[("a:홍길동", "c:001")]
    assert ace["t_in"] == "2024-03" and ace["t_out"] == "" and ace["status"] == "active"
    # 스크러버용 시점 범위 — 진입·이탈·전환청구 월 모두 포함
    assert g["span"] == {"min": "2024-03", "max": "2025-02"}


def test_company_timeline_events_and_conversion():
    g = build_graph(_temporal_sightings(), min_companies=2)
    hong = next(n for n in g["nodes"] if n["label"] == "홍길동")
    beta = next(c for c in hong["companies"] if c["name"] == "베타")
    dirs = [(e["dir"], e["date"]) for e in beta["events"]]
    assert dirs == [("in", "2024-06"), ("out", "2025-01")]
    assert beta["events"][1]["type"] == "지분감소" and beta["events"][1]["pct"] == 3.2
    # 전환청구는 회사기준 이벤트로 감마 타임라인에 병합
    gana = next(n for n in g["nodes"] if n["label"] == "가나조합제1호")
    gamma = next(c for c in gana["companies"] if c["name"] == "감마")
    conv = [e for e in gamma["events"] if e.get("company_level")]
    assert conv and "전환청구" in conv[0]["type"]
