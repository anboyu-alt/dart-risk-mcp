"""매입채무 계정 별칭이 실제 표기를 덮는지 잠근다.

Phase 1(회전율 지표 신설, 2026-08-28)에서 38개사 fnlttSinglAcntAll 전수 실측으로
찾은 유동 재무상태표 표기 7종을 반영했다 — `test_receivable_alias_coverage.py`와
같은 이유·같은 형식이다: `_pick_account`는 **정확 일치**라 표기가 별칭에
없으면 그 회사에서 매입채무회전율·CCC가 조용히 사라진다.

    매입채무               22곳
    매입채무및기타채무       14곳
    매입채무 및 기타유동채무  2곳
    매입채무 및 기타지급채무  1곳 (이마트)
    유동매입채무            1곳 (오리온)
    단기매입채무            1곳 (제이스코홀딩스)
    매입채무 및 기타채무     1곳 (KR모터스)

⚠ 「장기매입채무및기타채무」(4곳)는 넣지 않는다 — 매출채권 별칭과 같은 원칙:
회전율은 유동 채무를 보는 지표이고 비유동을 섞으면 해석이 뒤집힌다.

⚠ 현금흐름표 항목(「매입채무의 증가(감소)」·「매입채무의 감소」·「매입채무 및
기타채무의 증가(감소)」)도 넣지 않는다 — 잔액이 아니라 흐름(증감액)이라
`_fs_response_to_periods`가 account_nm만 보고 섞으면 회전율이 무의미해진다.
"""
import pytest

from dart_risk_mcp.core.dart_client import _FS_ALIASES, _pick_account


@pytest.mark.parametrize("acc", [
    "매입채무",
    "매입채무및기타채무",
    "매입채무 및 기타유동채무",
    "매입채무 및 기타지급채무",
    "유동매입채무",
    "단기매입채무",
    "매입채무 및 기타채무",
])
def test_실측_표기를_모두_집는다(acc):
    assert _pick_account({acc: 100}, _FS_ALIASES["매입채무"]) == 100


def test_비유동_매입채무는_집지_않는다():
    """유동 비율 지표에 비유동을 섞으면 회전율 해석이 뒤집힌다."""
    assert _pick_account({"장기매입채무및기타채무": 100}, _FS_ALIASES["매입채무"]) is None


@pytest.mark.parametrize("acc", [
    "매입채무의 증가(감소)",
    "매입채무의 감소",
    "매입채무 및 기타채무의 증가(감소)",
])
def test_현금흐름표_항목은_집지_않는다(acc):
    """잔액이 아니라 흐름(증감액)이다 — 섞이면 회전율이 무의미해진다."""
    assert _pick_account({acc: 100}, _FS_ALIASES["매입채무"]) is None


def test_매입채무가_가장_좁은_표기로_맨_앞에_있다():
    """둘 다 있는 경우 가장 좁은 순수 "매입채무"를 우선 집는다."""
    fs = {"매입채무및기타채무": 900, "매입채무": 100}
    assert _pick_account(fs, _FS_ALIASES["매입채무"]) == 100


def test_정확_일치_방식이_유지된다():
    """부분 일치로 바꾸면 현금흐름표 항목이 부분 문자열로 걸릴 수 있다."""
    import inspect

    from dart_risk_mcp.core.dart_client import _pick_account as fn

    src = inspect.getsource(fn)
    assert "fs.get(n)" in src, "정확 일치가 아니면 CF 항목을 집을 수 있다"
