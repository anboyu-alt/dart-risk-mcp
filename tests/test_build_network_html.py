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


def test_single_company_exiter_included_as_exit_only():
    """이탈이 있으면 2사 미만 행위자도 포함하되 exit_only로 표시(기본 숨김)."""
    s = {
        "sightings": {
            "조합갑": [  # 2사(A,B), B 이탈 → 코어
                {"corp": "A", "corp_code": "001", "rcept_no": "i1", "date": "2024-03",
                 "kind": "fund", "event": "in"},
                {"corp": "B", "corp_code": "002", "rcept_no": "i2", "date": "2024-06",
                 "kind": "fund", "event": "in"},
                {"corp": "B", "corp_code": "002", "rcept_no": "o1", "date": "2025-01",
                 "kind": "fund", "event": "out", "event_type": "지분감소", "pct": 3.1},
            ],
            "단발병": [  # 1사(C), C 이탈 → exit_only 로 포함
                {"corp": "C", "corp_code": "003", "rcept_no": "i3", "date": "2024-05",
                 "kind": "fund", "event": "in"},
                {"corp": "C", "corp_code": "003", "rcept_no": "o2", "date": "2025-02",
                 "kind": "fund", "event": "out", "event_type": "지분감소", "pct": 2.0},
            ],
            "평범정": [  # 2사(A,D), 이탈 없음 → 코어
                {"corp": "A", "corp_code": "001", "rcept_no": "i4", "date": "2024-04",
                 "kind": "fund", "event": "in"},
                {"corp": "D", "corp_code": "004", "rcept_no": "i5", "date": "2024-07",
                 "kind": "fund", "event": "in"},
            ],
        },
    }
    g = build_graph(s, min_companies=2)
    by_label = {n["label"]: n for n in g["nodes"] if n["type"] != "company"}
    assert by_label["단발병"]["exit_only"] is True and by_label["단발병"]["deg"] == 1
    assert by_label["조합갑"]["exit_only"] is False
    assert by_label["평범정"]["exit_only"] is False
    # 이탈 엣지는 코어(조합갑→B) + 단일회사(단발병→C) 둘 다
    exited = {(l["source"], l["target"]) for l in g["links"] if l["status"] == "exited"}
    assert ("a:조합갑", "c:002") in exited
    assert ("a:단발병", "c:003") in exited
    # 단발병만 닿는 회사 C도 exit_only(기본 숨김)
    cmap = {n["label"]: n for n in g["nodes"] if n["type"] == "company"}
    assert cmap["C"]["exit_only"] is True
    assert cmap["A"]["exit_only"] is False


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


# ── 단일 엔티티 병합 (같은 실체 = 한 노드) ──────────────────────────

def _merge_sightings():
    """엔켐(cc=100, 투자받음) + '주식회사 엔켐'(2개사 투자)이 fold 일치."""
    return {"sightings": {
        # 투자자갑: 2개사(엔켐·다른회사)에 투자 → 코어. 엔켐은 여기서 투자받음.
        "투자자갑": [
            {"corp": "엔켐", "corp_code": "100", "corp_cls": "K", "rcept_no": "r1",
             "date": "2024-01", "kind": "corp", "event": "in"},
            {"corp": "다른회사", "corp_code": "200", "corp_cls": "K", "rcept_no": "r2",
             "date": "2024-02", "kind": "corp", "event": "in"},
        ],
        # 행위자 '주식회사 엔켐'(fold == 엔켐)이 2개사에 투자 → c:100로 병합.
        "주식회사 엔켐": [
            {"corp": "타겟일", "corp_code": "300", "corp_cls": "K", "rcept_no": "r3",
             "date": "2024-03", "kind": "corp", "event": "in"},
            {"corp": "타겟이", "corp_code": "400", "corp_cls": "K", "rcept_no": "r4",
             "date": "2024-04", "kind": "corp", "event": "in"},
        ],
    }}


def test_enchem_single_entity_merge():
    g = build_graph(_merge_sightings(), min_companies=2)
    ids = {n["id"] for n in g["nodes"]}
    # 별도 행위자 노드가 사라지고 회사 코드로 단일화
    assert "a:주식회사 엔켐" not in ids
    node = {n["id"]: n for n in g["nodes"]}["c:100"]
    assert node["type"] == "company"
    assert node["dual"] is True
    assert node["label"] == "엔켐"
    assert "주식회사 엔켐" in node.get("aliases", [])
    # out(투자) 2건 + in(투자받음) 1건 이상
    assert node["out_deg"] == 2 and node["in_deg"] >= 1
    outs = [l for l in g["links"] if l["source"] == "c:100"]
    assert len(outs) == 2 and {l["target"] for l in outs} == {"c:300", "c:400"}
    ins = [l for l in g["links"] if l["target"] == "c:100"]
    assert len(ins) >= 1 and ins[0]["source"] == "a:투자자갑"


def test_self_loop_skipped():
    """병합된 노드가 자기 자신에 투자한 관계는 링크·companies에서 스킵."""
    s = _merge_sightings()
    s["sightings"]["주식회사 엔켐"].append(
        {"corp": "엔켐", "corp_code": "100", "corp_cls": "K", "rcept_no": "r5",
         "date": "2024-05", "kind": "corp", "event": "in"})
    g = build_graph(s, min_companies=2)
    assert not any(l["source"] == "c:100" and l["target"] == "c:100"
                   for l in g["links"])
    node = {n["id"]: n for n in g["nodes"]}["c:100"]
    assert all(c["name"] != "엔켐" for c in node.get("companies", []))
    assert node["out_deg"] == 2   # 자기 자신 제외 유지


def test_fold_collision_not_merged():
    """한 fold가 복수 corp_code로 접히면(모호) 자동 병합 금지 — a: 유지."""
    s = {"sightings": {
        # 서로 다른 corp_code(501·502)가 같은 fold('베이트리')로 접힘 → 충돌
        "투자자을": [
            {"corp": "베이트리", "corp_code": "501", "rcept_no": "c1", "date": "2024-01",
             "kind": "corp", "event": "in"},
            {"corp": "무관회사", "corp_code": "999", "rcept_no": "c2", "date": "2024-01",
             "kind": "corp", "event": "in"},
        ],
        "투자자병": [
            {"corp": "(주)베이트리", "corp_code": "502", "rcept_no": "c3", "date": "2024-02",
             "kind": "corp", "event": "in"},
            {"corp": "무관회사2", "corp_code": "998", "rcept_no": "c4", "date": "2024-02",
             "kind": "corp", "event": "in"},
        ],
        # fold('베이트리')로 접히는 행위자 — 충돌이라 미병합, a: 유지
        "주식회사 베이트리": [
            {"corp": "타겟삼", "corp_code": "601", "rcept_no": "c5", "date": "2024-03",
             "kind": "corp", "event": "in"},
            {"corp": "타겟사", "corp_code": "602", "rcept_no": "c6", "date": "2024-03",
             "kind": "corp", "event": "in"},
        ],
    }}
    g = build_graph(s, min_companies=2)
    ids = {n["id"] for n in g["nodes"]}
    assert "a:주식회사 베이트리" in ids                       # 충돌로 미병합
    byid = {n["id"]: n for n in g["nodes"]}
    assert byid["c:501"].get("dual") is not True
    assert byid["c:502"].get("dual") is not True
