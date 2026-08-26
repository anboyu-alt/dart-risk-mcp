"""재무 스캔 리포트가 **당기/전기 방향**과 **검사 범위**를 정확히 말하는지 잠근다.

재무 축 감사에서 `scan_financial_anomaly` 출력을 끝까지 읽어 찾았다
(셀트리온 2025, 2026-08-25).

## ① 한 리포트에서 당기/전기 순서가 반대였다

    | 지표 | **당기** | **전기** | 변화 |      ← 표: 당기 먼저
    | 매출채권/매출 | 43.0% | 34.2% | +8.9%p |

    **전년 대비 추세**
    - 순이익률  11.78% → 24.78%  (전년 대비 +110.4%)   ← 추세: 전기 먼저

표를 먼저 읽은 눈에는 「11.78% → 24.78%」이 당기→전기로 보여 **순이익률이
떨어졌다**고 읽힌다. 실제로는 그 해에 **두 배가 됐다**. 방향이 뒤집혀 읽히는
것은 이 세션에서 반복해 고쳐 온 결함과 같은 종류다.

순서를 바꾸지 않고 **라벨을 붙였다** — `전기 11.78% → 당기 24.78%`.
(순서를 표에 맞추면 「전년 대비 +110.4%」의 부호와 어긋난다.)

## ② 「네 지표 모두 정상 범위입니다」

플래그는 **9종**으로 늘었는데(AR_SURGE · INVENTORY_SURGE · CASH_GAP ·
CAPITAL_IMPAIRMENT · CFS_OFS_REVERSAL · LOAN_ADVANCE_SURGE · RESTATEMENT ·
OPNET_POS_NEG · OPNET_NEG_POS) 문구는 v0.8.x 시절의 「네」에 멈춰 있어
**검사 범위를 실제보다 좁게** 말했다. 개수를 박으면 또 낡으므로 세지 않는다.
"""
import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SRC = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
_CLIENT = (_ROOT / "dart_risk_mcp" / "core" / "dart_client.py").read_text(encoding="utf-8")
_GOLD = _ROOT / "tests" / "fixtures" / "sample_outputs"


def test_추세_줄이_방향을_말한다():
    assert '전기 {pv:.2f}{unit} → 당기 {cv:.2f}{unit}' in _SRC
    assert '{pv:.2f}{unit} → {cv:.2f}{unit}  ({trend})' not in _SRC


def test_표는_당기_먼저다():
    """추세와 순서가 다르다는 사실 자체를 고정한다 — 그래서 라벨이 필요하다."""
    assert "| 지표 | 당기 | 전기 | 변화 |" in _SRC


def test_개수를_박은_문구가_없다():
    assert "네 지표 모두 정상 범위입니다" not in _SRC
    assert "위 지표에서는 이상이 감지되지 않았습니다" in _SRC


def test_플래그가_넷보다_많다():
    """이 수정의 전제 — 넷이면 옛 문구가 맞았을 것이다."""
    i = _CLIENT.index("def detect_financial_anomaly")
    j = _CLIENT.index("\ndef ", i + 10)
    flags = set(re.findall(r'flags\.append\("([A-Z_]+)"\)', _CLIENT[i:j]))
    assert len(flags) >= 6, flags
    # scan이 추가로 붙이는 것들
    assert "RESTATEMENT" in _SRC
    assert "OPNET_POS_NEG" in _SRC and "OPNET_NEG_POS" in _SRC


@pytest.mark.parametrize("phrase", ["네 지표 모두 정상 범위입니다"])
def test_골드에_옛_문구가_없다(phrase):
    hits = sorted(p.name for p in _GOLD.glob("*_scan_fs.txt")
                  if phrase in p.read_text(encoding="utf-8"))
    assert not hits, (
        f"골드 {len(hits)}개에 옛 문구가 남아 있다 — "
        f"`python scripts/regen_goldens.py --tools scan_fs`로 재생성하세요: {hits[:4]}"
    )


def test_골드에_방향_라벨이_있다():
    """렌더만 고치고 골드가 낡으면 hygiene이 옛 출력을 훑는다(#301)."""
    hits = [p.name for p in _GOLD.glob("*_scan_fs.txt")
            if "전기 " in p.read_text(encoding="utf-8")
            and "→ 당기 " in p.read_text(encoding="utf-8")]
    assert hits, "방향 라벨이 담긴 재무 골드가 하나도 없다"
