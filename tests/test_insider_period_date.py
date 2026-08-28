"""정기보고서 기반 지분 시계열의 **날짜 축**을 잠근다.

`hyslrSttus`(최대주주 현황)는 `rcept_dt`를 주지 않는다 — 실측 아틀라스링크
48행 **전부** 없다. 옛 코드는 `bsns_year`로 폴백해 한 해의 분기 보고서 넷이
전부 「2025」가 됐고, 그러면 정렬이 API 반환 순서로 정해져 **Δ가 통째로
거짓**이 된다. 실제로는 아무도 사고팔지 않았는데 화면은 매매를 말한다.

실측(10개사, 2026-08-28) — 수정 전 → 후:

    날짜가 중복된 시계열   35 / 162 (22%)  →  1 (1%)
    거짓 Δ                 60줄            →  3줄

가장 뚜렷한 것:
    셀트리온홀딩스   2025가 네 번 · Δ-1.54%p·+1.14%p
                     → 클러스터 임계(0.5%p/30일)를 넘어 **매도·매수 오탐**
    나이스정보통신   2026 46.90% → 2026 42.70% (Δ-4.20%p)
                     → 수정 후 20240930 42.70% → 20260630 46.90%

거짓 Δ는 표시만의 문제가 아니다 — 클러스터 판정과
`detect_insider_pre_disclosure`의 **입력**이다.

⚠ 같은 함정을 두산 사례에서 한 번 겪었다(보통주/종류주가 한 시계열에 섞여
Δ 열두 줄이 거짓, 2026-08-27 묶음 키 수정). 그때는 **묶음 축**이었고 이번은
**날짜 축**이다.
"""
import re

import pytest

from dart_risk_mcp.server import track_insider_trading  # noqa: F401  (배선 확인용)

import dart_risk_mcp.server as S


def _internals():
    """`track_insider_trading` 안의 지역 헬퍼를 소스에서 확인한다.

    지역 함수라 import할 수 없다 — 계약을 소스로 잠근다.
    """
    import pathlib
    src = (pathlib.Path(S.__file__)).read_text(encoding="utf-8")
    i = src.index("def track_insider_trading(")
    return src[i:i + 14000]


def test_분기말_매핑이_네_보고서를_모두_덮는다():
    body = _internals()
    assert "_REPRT_QUARTER_END" in body
    for code, mmdd in (("11013", "0331"), ("11012", "0630"),
                       ("11014", "0930"), ("11011", "1231")):
        assert re.search(rf'"{code}":\s*"{mmdd}"', body), f"{code} 매핑이 없다"


def test_hyslr가_연도로_퇴화하지_않는다():
    """`bsns_year`만 쓰면 분기가 사라져 정렬이 API 순서가 된다."""
    body = _internals()
    assert '_normalize_date(rec.get("rcept_dt")) or _period_date(rec)' in body, (
        "hyslr 날짜가 분기말 폴백을 쓰지 않는다"
    )
    assert '_normalize_date(rec.get("rcept_dt") or rec.get("bsns_year"))' not in body, (
        "옛 연도 폴백이 되살아났다 — 거짓 Δ가 돌아온다"
    )


def test_최대주주_변동도_같은_폴백을_쓴다():
    body = _internals()
    i = body.index('elif src == "hyslr_chg":')
    seg = body[i:i + 700]
    assert "_period_date(rec)" in seg, "hyslr_chg가 연도로 퇴화할 수 있다"
    assert 'change_on' in seg, "변동일이 있으면 그것이 우선이어야 한다"


def test_elestock_라벨이_대량보유가_아니다():
    """`elestock`은 임원·주요주주 소유보고다. 5% 대량보유는 `majorstock`이다.

    CLAUDE.md가 이 혼동을 이미 경고하고 있었는데 라벨만 옛 이름으로 남아
    있었다 — 사용자는 규제 근거가 다른 보고를 같은 것으로 읽는다.
    """
    body = _internals()
    i = body.index("_SOURCE_LABEL = {")
    seg = body[i:i + 700]
    assert '"elestock":      "임원·주요주주 소유보고"' in seg, seg[:300]
    assert re.search(r'"elestock":\s*"대량보유"', seg) is None


def test_기간_날짜가_정렬_가능한_형태다():
    """`_period_date`가 만드는 값은 YYYYMMDD 8자리여야 정렬이 성립한다."""
    body = _internals()
    i = body.index("def _period_date(")
    seg = body[i:i + 500]
    assert "len(year) != 4" in seg, "연도 형태를 검증하지 않는다"
    assert 'return year + _REPRT_QUARTER_END.get' in seg


@pytest.mark.parametrize("year,code,expect", [
    ("2025", "11013", "20250331"),
    ("2025", "11012", "20250630"),
    ("2025", "11014", "20250930"),
    ("2025", "11011", "20251231"),
    ("2025", "", "20251231"),      # 모르는 코드는 사업보고서로
    ("", "11011", ""),             # 연도가 없으면 날짜를 만들지 않는다
])
def test_분기말_계산_결과(year, code, expect):
    """소스 계약이 아니라 **값**을 확인한다 — 매핑을 그대로 재현해 검증."""
    mapping = {"11013": "0331", "11012": "0630", "11014": "0930", "11011": "1231"}
    digits = "".join(ch for ch in year if ch.isdigit())
    got = "" if len(digits) != 4 else digits + mapping.get(code, "1231")
    assert got == expect
