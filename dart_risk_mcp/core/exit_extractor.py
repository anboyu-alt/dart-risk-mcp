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


def extract_holding_exits(major_records: list, tracked_norm: set) -> list:
    """대량보유(majorstock) 이력에서 추적 행위자의 보유비율 감소(=이탈) 추출.

    DART가 보유비율 증감(stkrt_irds)을 직접 신고하므로 그 값이 음수면 처분(이탈).
    증감 결측 시엔 보유비율(stkrt) 시계열의 감소로 폴백 판정한다.

    Args:
        major_records: fetch_major_holdings 결과(한 회사 대량보유 전체 이력).
        tracked_norm: 추적 대상 정규화 이름 집합.

    Returns:
        [{"name","norm","date":"YYYY-MM","pct":감소후 비율,"prev_pct","delta",
          "rcept_no","event":"out","event_type":"지분감소"}] — 시간순 감소 이벤트.
    """
    # 보고자별 (date8, 보유비율 stkrt, 증감 stkrt_irds, rcept_no, 원표기)
    series: dict = {}
    for rec in major_records or []:
        nm = (rec.get("repror") or "").strip()
        if not nm:
            continue
        norm = normalize_name(nm)
        if norm not in tracked_norm:
            continue
        d8 = "".join(ch for ch in str(rec.get("rcept_dt") or "") if ch.isdigit())[:8]
        if len(d8) < 8:
            continue
        series.setdefault(norm, []).append(
            (d8, _ratio(rec.get("stkrt")), _ratio(rec.get("stkrt_irds")),
             rec.get("rcept_no", ""), nm))

    events = []
    for norm, rows in series.items():
        rows.sort(key=lambda r: r[0])
        prev = None
        for d8, rt, ird, rcept, nm in rows:
            # 증감(ird) 음수 = 처분. 증감 결측이면 보유비율 하락으로 폴백.
            decreased = (ird is not None and ird < 0) or \
                        (ird is None and prev is not None and rt is not None and rt < prev - 1e-9)
            if decreased:
                events.append({
                    "name": nm, "norm": norm,
                    "date": f"{d8[:4]}-{d8[4:6]}",
                    "pct": rt, "prev_pct": prev,
                    "delta": ird, "rcept_no": rcept,
                    "event": "out", "event_type": "지분감소",
                })
            if rt is not None:
                prev = rt
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
