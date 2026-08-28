"""**양수(사는 것)** 결정 공시의 상대방을 읽는지 잠근다.

`_confirm_outflow_counterparties`가 보는 것은 **자금이 나가는 방향**이다.
그런데 `parse_asset_disposal_detail`의 게이트가 「처분·양도」만 담고 있어
**양수 서식을 통째로 거절**했다 — 상대방 정규식은 이미 읽을 수 있는데도
앞단에서 막혔다.

실측(2026-08-28, 시장 12건):

    양도(파는 것)  5건 → core 5건 전부 읽음
    양수(사는 것)  6건 → core **0건**        ← 돈이 나가는 쪽을 못 읽었다

게이트 확장 후 **11/12**(남은 1건은 원문에 거래상대방 블록이 아예 없다).

## 두 화면이 서로 다른 사실을 말했다

라이브: 아틀라스링크 20260810000747 「유형자산양수결정」 원문에
「6. 거래상대방 회사명(성명) 정은산업 주식회사 … 216억」이 있는데

    MCP   → 거래상대방: (미확인) · 관계: 미확인
    뷰어  → 상대: 정은산업 주식회사 (관계 미기재) — 216억

MCP는 DS005(`fetch_major_decision`)만 보고 **원문 폴백을 하지 않았고**,
그 공시에서 DART DS005는 error를 냈다. 뷰어는 DS005를 쓰지 않아 원문을 읽었다.
이번에 core에 폴백을 배선해 맞췄다.
"""
import pathlib
import re

import pytest

from dart_risk_mcp.core.dart_client import parse_asset_disposal_detail

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SERVER = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")

# 실측 원문의 특징 구간 (아틀라스링크 20260810000747)
_ACQ_DOC = (
    "주요사항보고서(유형자산양수결정) 1. 양수영업 유형자산 2. 양수가액(원) "
    "21,600,000,000 3. 양수목적 사업 확장 4. 양수예정일자 2026년 12월 31일 "
    "등기예정일 2026년 12월 31일 6. 거래상대방 회사명(성명) 정은산업 주식회사 "
    "자본금(원) 300,000,000 주요사업 기계 제조업 "
    "본점소재지(주소) 충청북도 영동군 영동읍 동정로 30, 801호 "
    "회사와의 관계 - 7. 거래대금지급 1. 지급형태: 현금"
)

_DISP_DOC = (
    "주요사항보고서(유형자산양도결정) 1. 양도재산 토지 2. 양도가액(원) "
    "5,000,000,000 6. 거래상대방 회사명(성명) 한국토지주택공사 "
    "자본금(원) 1,000,000,000 회사와의 관계 - 7. 거래대금"
)


def test_양수_서식의_상대방을_읽는다():
    got = parse_asset_disposal_detail(_ACQ_DOC)
    assert got["counterparty"] == "정은산업 주식회사"
    assert got["amount"] == 21_600_000_000, "양수가액을 읽지 못했다"


def test_양도_서식은_그대로_읽는다():
    """게이트를 넓히면서 기존 경로가 깨지면 안 된다."""
    got = parse_asset_disposal_detail(_DISP_DOC)
    assert got["counterparty"] == "한국토지주택공사"
    assert got["amount"] == 5_000_000_000


def test_게이트에_양수가_들어_있다():
    src = (_ROOT / "dart_risk_mcp" / "core" / "dart_client.py").read_text(encoding="utf-8")
    i = src.index("def parse_asset_disposal_detail(")
    body = src[i:i + 2200]
    for w in ("양수 결정", "양수결정", "자산양수"):
        assert f'"{w}"' in body, f"게이트에 {w}가 없다 — 양수 서식이 거절된다"


def test_양수_금액_표기를_읽는다():
    src = (_ROOT / "dart_risk_mcp" / "core" / "dart_client.py").read_text(encoding="utf-8")
    i = src.index("_DISPOSAL_AMOUNT_RE = re.compile(")
    body = src[i:i + 400]
    for w in ("양수금액", "양수가액", "취득금액", "취득가액"):
        assert w in body, f"{w} 표기를 금액 정규식이 모른다"


def test_관계가_미기재면_빈_값이다():
    """원문의 「회사와의 관계 -」는 관계가 「-」인 게 아니라 안 적힌 것이다."""
    got = parse_asset_disposal_detail(_ACQ_DOC)
    assert got["relation"] in ("", "-"), got["relation"]


def test_DS005가_비면_원문으로_폴백한다():
    """「(미확인)」은 상대를 모른다는 뜻이지, DS005가 실패했다는 뜻이 아니다."""
    i = _SERVER.index("def _confirm_outflow_counterparties(")
    body = _SERVER[i:i + 3200]
    assert 'if r is None or not (r.get("counterparty") or "").strip():' in body, (
        "DS005 결과가 비었을 때를 가르지 않는다"
    )
    j = body.index('if r is None or not (r.get("counterparty")')
    seg = body[j:j + 1400]
    assert "fetch_asset_disposal_detail(rcept" in seg, "원문 폴백이 없다"
    assert "classify_outflow_relation" in seg, "관계 분류를 거치지 않는다"


def test_폴백이_예외를_밖으로_던지지_않는다():
    i = _SERVER.index('if r is None or not (r.get("counterparty")')
    seg = _SERVER[i:i + 1400]
    assert re.search(r"try:\s*\n\s*_d = fetch_asset_disposal_detail", seg), (
        "원문 조회 실패가 도구 전체를 죽일 수 있다"
    )
    assert "except Exception:" in seg
