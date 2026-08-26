"""매출채권 계정 별칭이 실제 표기를 덮는지 잠근다.

재무 축 감사 중 Beneish 변수의 **산출 성공률**을 재다 찾았다(2026-08-25).

    DSRI  27/35 (77%)   없음: 기아 · CJ제일제당 · 진원생명과학 · STX · 이오플로우 …

`_pick_account`는 **정확 일치**다. 별칭이 `["매출채권", "매출채권및기타채권"]`
둘뿐이라 표기가 다르면 무조건 실패하고, 그러면 **`AR_SURGE` 플래그와 DSRI가
조용히 사라진다** — 그 회사에서는 영원히 뜨지 않는다. 실패했다는 표시도 없다.

39개사 재무제표 전수에서 별칭에 없던 표기:

    유동매출채권             2곳   (CJ제일제당 · STX)
    매출채권 및 기타유동채권   3곳   (진원생명과학 등)
    단기 매출채권            1곳   (기아 — **공백 있음**)

⚠ 「장기매출채권」(5곳)·「비유동매출채권」(2곳)·「장기매출채권및기타채권」(2곳)은
**넣지 않았다** — 매출채권/매출은 유동 채권을 보는 지표이고, 비유동을 섞으면
회전율 해석이 뒤집힌다.

수정 후 **DSRI 27/35 → 33/35 (94%)**. 회복된 값은 전부 상식 범위였다
(기아 3.1% · CJ제일제당 10.7% · STX 7.6% · 셀트리온 43.0%) — 장기채권을
잘못 집지 않았다는 확인이다.
"""
import pathlib

import pytest

from dart_risk_mcp.core.dart_client import _FS_ALIASES, _pick_account

_ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("acc", [
    "매출채권", "매출채권및기타채권",
    "유동매출채권", "매출채권 및 기타유동채권", "단기 매출채권",
])
def test_실제_표기를_집는다(acc):
    assert _pick_account({acc: 100}, _FS_ALIASES["매출채권"]) == 100


@pytest.mark.parametrize("acc", [
    "장기매출채권", "비유동매출채권", "장기매출채권및기타채권",
])
def test_비유동_채권은_집지_않는다(acc):
    """유동 비율 지표에 비유동을 섞으면 회전율 해석이 뒤집힌다."""
    assert _pick_account({acc: 100}, _FS_ALIASES["매출채권"]) is None


def test_유동이_비유동보다_우선한다():
    """둘 다 있는 회사(기아·STX)에서 유동 쪽을 집어야 한다."""
    fs = {"장기매출채권": 900, "단기 매출채권": 100}
    assert _pick_account(fs, _FS_ALIASES["매출채권"]) == 100


def test_정확_일치_방식이_유지된다():
    """부분 일치로 바꾸면 현금흐름표의 「장기대여금및수취채권의 처분」을 집는다."""
    import inspect

    from dart_risk_mcp.core.dart_client import _pick_account as fn

    src = inspect.getsource(fn)
    assert "fs.get(n)" in src, "정확 일치가 아니면 CF 항목을 집을 수 있다"


def test_AR_SURGE가_이_별칭에_달려_있다():
    """이 수정의 파급 — 별칭이 실패하면 플래그 자체가 사라진다."""
    from dart_risk_mcp.core.dart_client import detect_financial_anomaly

    cur = {"매출액": 1000, "유동매출채권": 300}
    pri = {"매출액": 1000, "유동매출채권": 100}
    flags, _ = detect_financial_anomaly(cur, pri)
    assert "AR_SURGE" in flags


def test_별칭이_없으면_플래그도_없다():
    """옛 상태 재현 — 표기가 다르면 조용히 사라졌다."""
    from dart_risk_mcp.core.dart_client import detect_financial_anomaly

    cur = {"매출액": 1000, "장기매출채권": 300}
    pri = {"매출액": 1000, "장기매출채권": 100}
    flags, _ = detect_financial_anomaly(cur, pri)
    assert "AR_SURGE" not in flags
