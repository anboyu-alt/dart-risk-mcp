"""자금사용 내역의 **보고서 연도별 중복**을 접는지 잠근다.

같은 조달건이 여러 연도 보고서에 되풀이 실린다. `_clear_stale_unreported`가
옛 스냅샷의 **플래그**는 이미 뗐지만 **레코드 자체는 전부 남아** 건수와
목록이 부풀려졌다.

실측(2026-08-28, 6개사 lookback 3년):

    레코드 990건 → 고유 용도 줄 235건 (**76%가 중복**)
    KB금융  499 → 146    「총 499건 조회」는 3.4배 부풀려진 수였다
    오르비텍 132 →  16
    STX     138 →  27
    두산      81 →  22

⚠ 접는 단위는 **(조달유형, 회차, 납입일, 계획용도, 계획금액)**이다 —
한 조달건 안의 용도별 줄은 서로 다른 사실이라 뭉개면 안 된다. 대표는 가장
최신 보고서 연도의 레코드다.

## 라벨 연도도 어긋나 있었다

`[2023 공모 제306회차] 납입일 2021.07.06` — `year`는 **보고서 사업연도**이지
조달 시점이 아니다. 실측: 라벨 연도 ≠ 납입 연도가 STX **96%** · 오르비텍 91% ·
KB금융 84%. 사용자가 「언제 조달했나」로 읽는 자리라 납입 연도를 쓴다.
"""
import pathlib
import re

from dart_risk_mcp.core.dart_client import _collapse_fund_snapshots

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SERVER = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")


def _rec(year, tm, pay_de, use="운영자금", amount=1000, kind="public", flags=None):
    return {"year": year, "tm": tm, "pay_de": pay_de, "plan_useprps": use,
            "plan_amount": amount, "kind": kind, "flags": flags or []}


def test_같은_줄이_연도마다_반복되면_하나로_접힌다():
    recs = [_rec("2023", "306", "2021.07.06"),
            _rec("2024", "306", "2021.07.06"),
            _rec("2025", "306", "2021.07.06")]
    out = _collapse_fund_snapshots(recs)
    assert len(out) == 1
    assert out[0]["year"] == "2025", "최신 보고서 스냅샷이 대표여야 한다"


def test_한_조달건_안의_용도별_줄은_뭉개지_않는다():
    """서로 다른 사실이다 — 접는 단위에 용도·금액이 들어가야 한다."""
    recs = [_rec("2024", "11-1", "2023.02.03", "운영자금", 330),
            _rec("2024", "11-1", "2023.02.03", "채무상환자금", 220)]
    out = _collapse_fund_snapshots(recs)
    assert len(out) == 2


def test_회차가_비어도_납입일로_갈린다():
    """회차가 「-」로 비는 서식이 실측에 있다(유티아이)."""
    recs = [_rec("2024", "", "2021.07.06"), _rec("2024", "", "2022.01.24")]
    assert len(_collapse_fund_snapshots(recs)) == 2


def test_입력_순서를_보존한다():
    recs = [_rec("2024", "A", "2021.01.01"),
            _rec("2024", "B", "2022.01.01"),
            _rec("2025", "A", "2021.01.01")]
    out = _collapse_fund_snapshots(recs)
    assert [r["tm"] for r in out] == ["A", "B"]


def test_연도가_비정상이어도_죽지_않는다():
    recs = [_rec(None, "A", "2021.01.01"), _rec("없음", "A", "2021.01.01")]
    out = _collapse_fund_snapshots(recs)
    assert len(out) == 1


def test_빈_입력은_빈_결과다():
    assert _collapse_fund_snapshots([]) == []


def test_플래그_정리_뒤에_접는다():
    """옛 스냅샷이 있어야 「나중 보고서에 집행이 기재됐다」를 판단할 수 있다."""
    src = (_ROOT / "dart_risk_mcp" / "core" / "dart_client.py").read_text(encoding="utf-8")
    i = src.index("_clear_stale_unreported(results)")
    seg = src[i:i + 400]
    assert "_collapse_fund_snapshots(results)" in seg
    assert seg.index("_clear_stale_unreported") < seg.index("_collapse_fund_snapshots")


def test_라벨_연도가_납입_연도다():
    i = _SERVER.index("def _format_fund_year_prefix(")
    body = _SERVER[i:i + 1400]
    assert "_pay_year" in body, "납입 연도를 쓰지 않는다"
    assert 'rec.get("pay_de")' in body
    assert "len(_pay_year) == 4" in body, "형태 검증 없이 쓰면 깨진 값이 라벨에 온다"
    assert 'rec.get("year", "")' in body, "납입일이 없을 때의 폴백이 사라졌다"


def test_총_건수가_접힌_목록_기준이다():
    """부풀려진 수를 「총 N건 조회」라 적으면 안 된다."""
    i = _SERVER.index("def track_fund_usage(")
    body = _SERVER[i:i + 9000]
    assert re.search(r"총 \{len\(records\)\}건 조회", body), (
        "집계가 records 기준이어야 한다 — records는 이제 접힌 목록이다"
    )
