"""행위자 이탈(exit) 신호 추출 — 관계의 '빠져나가는 시점'을 기록.

우리가 추적하는 연결은 한시적이다: 진입 시점(자금조달 공시 인수자 등장)과
이탈 시점(지분 처분)이 있다. 이탈은 삭제하지 않고 '닫힌 관계'로 보존한다.

이탈 소스
  1. 5% 대량보유 감소 (elestock) — 보고자(repror)가 추적 행위자와 일치하고
     보유비율(stkqy_rt)이 이전 대비 감소한 보고. 개별 귀속이 깨끗하다.
  2. 전환청구권행사 — 회사가 보고하므로 개별 행위자 귀속이 불확실 →
     '회사 단위' 이벤트로만 표기(어느 CB 인수자인지 단정하지 않는다).

판정 아님 — 사실(공시 기록) 표기다.
"""
from dart_risk_mcp.core.known_actors import normalize_name


def _ratio(v):
    """'12.34' / '12.34%' / '1,234' → float. 결측·파싱실패 None."""
    if v in (None, "", "-"):
        return None
    try:
        return float(str(v).replace(",", "").replace("%", "").strip())
    except (ValueError, AttributeError):
        return None


def _yyyymm(rcept_dt: str) -> str:
    d = "".join(ch for ch in str(rcept_dt or "") if ch.isdigit())
    return f"{d[:4]}-{d[4:6]}" if len(d) >= 6 else ""


def extract_holding_exits(elestock_records: list, tracked_norm: set) -> list:
    """elestock 이력에서 추적 행위자의 보유비율 감소(=이탈) 이벤트 추출.

    Args:
        elestock_records: fetch_bulk_holdings 결과(한 회사 전체 이력).
        tracked_norm: 추적 대상 정규화 이름 집합.

    Returns:
        [{"name": 보고자 원표기, "norm": 정규화, "date": "YYYY-MM",
          "pct": 감소 후 비율, "prev_pct": 이전 비율, "rcept_no": 접수번호,
          "event": "out", "event_type": "지분감소"}] — 보고자별 시간순 감소 이벤트.
    """
    # 보고자별 (date8, ratio, rcept_no) 시계열
    series: dict = {}
    for rec in elestock_records or []:
        nm = (rec.get("repror") or "").strip()
        if not nm:
            continue
        norm = normalize_name(nm)
        if norm not in tracked_norm:
            continue
        ratio = _ratio(rec.get("stkqy_rt"))
        d8 = "".join(ch for ch in str(rec.get("rcept_dt") or "") if ch.isdigit())[:8]
        if ratio is None or len(d8) < 8:
            continue
        series.setdefault(norm, []).append((d8, ratio, rec.get("rcept_no", ""), nm))

    events = []
    for norm, rows in series.items():
        rows.sort(key=lambda r: r[0])
        prev = None
        for d8, ratio, rcept, nm in rows:
            if prev is not None and ratio < prev - 1e-9:   # 감소 = 이탈 이벤트
                events.append({
                    "name": nm, "norm": norm,
                    "date": f"{d8[:4]}-{d8[4:6]}",
                    "pct": ratio, "prev_pct": prev, "rcept_no": rcept,
                    "event": "out", "event_type": "지분감소",
                })
            prev = ratio
    return events


_CONVERSION_KEYWORD = "전환청구권행사"


def scan_conversion_events(disclosures: list, corp_codes: set) -> list:
    """공시 목록에서 '전환청구권행사'(회사 단위 이벤트) 추출.

    개별 행위자 귀속은 하지 않는다 — 해당 회사의 CB 인수 행위자 전반에
    영향을 줄 수 있는 회사 단위 이벤트로만 표기.

    Returns:
        [{"corp_code","corp","date":"YYYY-MM","rcept_no",
          "event":"out","event_type":"전환청구"}]
    """
    out = []
    for d in disclosures or []:
        cc = d.get("corp_code")
        if cc not in corp_codes:
            continue
        if _CONVERSION_KEYWORD not in (d.get("report_nm") or ""):
            continue
        rn = d.get("rcept_no", "")
        if not rn:
            continue
        out.append({
            "corp_code": cc, "corp": d.get("corp_name", ""),
            "date": _yyyymm(d.get("rcept_dt")), "rcept_no": rn,
            "event": "out", "event_type": "전환청구",
        })
    return out
