"""exit_extractor — 5% 대량보유 감소·전환청구 이탈 신호 추출 검증."""
from dart_risk_mcp.core.exit_extractor import (
    extract_holding_exits,
    scan_conversion_events,
)
from dart_risk_mcp.core.known_actors import normalize_name


def _ele(repror, rt, dt, rn):
    return {"repror": repror, "stkqy_rt": rt, "rcept_dt": dt, "rcept_no": rn}


def test_holding_exit_detects_decreases():
    tracked = {normalize_name("홍길동")}
    recs = [
        _ele("홍길동", "8.0", "20240601", "r1"),
        _ele("홍길동", "6.0", "20240901", "r2"),   # 감소 → 이탈
        _ele("홍길동", "3.0", "20250101", "r3"),   # 감소 → 이탈
        _ele("김철수", "9.0", "20240601", "rX"),   # 미추적 → 제외
    ]
    evs = extract_holding_exits(recs, tracked)
    assert [e["date"] for e in evs] == ["2024-09", "2025-01"]
    assert all(e["event"] == "out" and e["event_type"] == "지분감소" for e in evs)
    assert evs[0]["pct"] == 6.0 and evs[0]["prev_pct"] == 8.0
    assert evs[1]["rcept_no"] == "r3"


def test_holding_no_exit_on_increase_or_flat():
    tracked = {normalize_name("가나조합제1호")}
    recs = [
        _ele("가나조합제1호", "5.0", "20240101", "a"),
        _ele("가나조합제1호", "7.0", "20240601", "b"),   # 증가 → 이탈 아님
        _ele("가나조합제1호", "7.0", "20240901", "c"),   # 동일 → 이탈 아님
    ]
    assert extract_holding_exits(recs, tracked) == []


def test_holding_exit_ignores_bad_rows():
    tracked = {normalize_name("홍길동")}
    recs = [
        _ele("홍길동", "", "20240601", "r1"),          # 비율 결측
        _ele("홍길동", "5.0", "2024", "r2"),           # 날짜 불완전
        _ele("", "5.0", "20240601", "r3"),             # 보고자 없음
    ]
    assert extract_holding_exits(recs, tracked) == []


def test_scan_conversion_events_filters_report_nm():
    discs = [
        {"corp_code": "001", "corp_name": "에이스", "report_nm": "전환청구권행사(제3회차)",
         "rcept_dt": "20250210", "rcept_no": "c1"},
        {"corp_code": "001", "corp_name": "에이스", "report_nm": "주요사항보고서(유상증자결정)",
         "rcept_dt": "20250101", "rcept_no": "c2"},          # 전환청구 아님
        {"corp_code": "999", "corp_name": "밖", "report_nm": "전환청구권행사",
         "rcept_dt": "20250301", "rcept_no": "c3"},          # 대상 회사 아님
    ]
    out = scan_conversion_events(discs, {"001"})
    assert len(out) == 1
    assert out[0]["corp_code"] == "001" and out[0]["date"] == "2025-02"
    assert out[0]["event"] == "out" and out[0]["event_type"] == "전환청구"
