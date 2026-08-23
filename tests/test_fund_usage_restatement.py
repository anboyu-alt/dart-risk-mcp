"""FUND_UNREPORTED 재정산 — 같은 조달건의 옛 스냅샷을 경고하지 않는다.

`_detect_fund_anomaly`는 레코드 하나만 보고 판정한다. 그런데 자금사용내역은
**같은 조달건이 여러 연도 보고서에 반복해서 실린다** — 납입 직후 보고서는
아직 집행이 없어 real=0이고, 나중 보고서에 집행이 채워진다. 레코드 단위
판정이 그 옛 스냅샷까지 전부 "미보고"로 세면, 전액 집행한 회사에 경고가
무더기로 뜬다.

라이브 실측(2026-08-23, lookback 3년, 도구 출력 기준):

| 회사 | 수정 전 | 수정 후 | 성격 |
|---|---|---|---|
| 유티아이 | 25건 | **0건** | 조달건 4개 최신 보고에 88.5억·7억·161.5억·23억 집행 기재 |
| 링크드 | 4건 | **0건** | 조달건 전부 최신 보고에 집행 기재 |
| HLB | 5건 | **3건** | 남은 3건은 「사용기간 미도래」 — 진짜 미집행 |
| 오르비텍 | 13건 | **13건** | 5개 조달건 최신 보고가 「미사용」 — 대조군 |

오르비텍이 그대로인 것이 핵심이다. 진짜 미보고를 지우면 이 도구의 목적
자체가 무너진다.
"""
import dart_risk_mcp.core.dart_client as dc


def _rec(kind, tm, pay_de, year, real, plan=1_000_000_000, flags=None):
    return {
        "kind": kind, "tm": tm, "pay_de": pay_de, "year": year,
        "plan_amount": plan, "real_dtls_amount": real,
        "real_dtls_cn": "시설자금" if real else "",
        "dffrnc_resn": "",
        "flags": ["FUND_UNREPORTED"] if flags is None else list(flags),
    }


def _flagged(recs):
    return sum(1 for r in recs if "FUND_UNREPORTED" in r["flags"])


class TestClearStaleUnreported:
    def test_최신_보고에_집행이_있으면_옛_스냅샷을_떼어낸다(self):
        recs = [
            _rec("private", "1", "2024.05.22", 2024, 0),
            _rec("private", "1", "2024.05.22", 2025, 0),
            _rec("private", "1", "2024.05.22", 2026, 38_000_000_000, flags=[]),
        ]
        assert dc._clear_stale_unreported(recs) == 2
        assert _flagged(recs) == 0

    def test_최신_보고도_미집행이면_그대로_둔다(self):
        """오르비텍 「미사용」 — 이걸 지우면 도구의 목적이 무너진다."""
        recs = [
            _rec("private", "10회차", "2025.12.08", 2025, 0),
            _rec("private", "10회차", "2025.12.08", 2026, 0),
        ]
        assert dc._clear_stale_unreported(recs) == 0
        assert _flagged(recs) == 2

    def test_최신_보고_자체의_경고는_남긴다(self):
        """최신 보고에 집행이 있으면 그 레코드엔 애초에 플래그가 없다.
        혹시 있더라도 최신 것은 건드리지 않는다 — 판정 근거가 그 레코드다."""
        latest = _rec("private", "1", "2024.05.22", 2026, 5_000_000_000)
        recs = [_rec("private", "1", "2024.05.22", 2024, 0), latest]
        dc._clear_stale_unreported(recs)
        assert "FUND_UNREPORTED" in latest["flags"]

    def test_다른_조달건은_서로_영향을_주지_않는다(self):
        recs = [
            _rec("private", "1", "2024.05.22", 2024, 0),
            _rec("private", "1", "2024.05.22", 2026, 38_000_000_000, flags=[]),
            _rec("private", "2", "2025.12.08", 2025, 0),
            _rec("private", "2", "2025.12.08", 2026, 0),
        ]
        dc._clear_stale_unreported(recs)
        assert _flagged(recs) == 2, "회차 2는 미집행이라 남아야 한다"

    def test_공모와_사모를_섞지_않는다(self):
        """납입일·회차가 같아도 공모/사모는 별개 조달건이다."""
        recs = [
            _rec("public", "-", "2024.05.31", 2024, 0),
            _rec("private", "-", "2024.05.31", 2026, 9_000_000_000, flags=[]),
        ]
        assert dc._clear_stale_unreported(recs) == 0
        assert _flagged(recs) == 1

    def test_회차가_비어도_납입일로_묶는다(self):
        """유티아이 실측 — 회차가 "-"로 비는 서식이 있다."""
        recs = [
            _rec("private", "-", "2024.07.04", 2024, 0),
            _rec("private", "-", "2024.07.04", 2025, 0),
            _rec("private", "-", "2024.07.04", 2026, 2_000_000_000, flags=[]),
        ]
        assert dc._clear_stale_unreported(recs) == 2

    def test_보고가_하나뿐이면_건드리지_않는다(self):
        recs = [_rec("private", "12회차", "2026.04.10", 2026, 0)]
        assert dc._clear_stale_unreported(recs) == 0
        assert _flagged(recs) == 1

    def test_용도변경은_떼지_않는다(self):
        """FUND_DIVERSION은 나중 보고에 집행이 기재돼도 사라지는 사실이 아니다."""
        recs = [
            _rec("private", "1", "2024.05.22", 2024, 0,
                 flags=["FUND_UNREPORTED", "FUND_DIVERSION"]),
            _rec("private", "1", "2024.05.22", 2026, 5_000_000_000, flags=[]),
        ]
        dc._clear_stale_unreported(recs)
        assert recs[0]["flags"] == ["FUND_DIVERSION"]

    def test_빈_입력에서_죽지_않는다(self):
        assert dc._clear_stale_unreported([]) == 0
