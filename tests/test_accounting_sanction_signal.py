"""회계처리기준 위반 제재를 `DISCLOSURE_VIOL`(4.3)이 잡는지 고정한다.

## 무엇이 문제였나

증권선물위원회가 회계처리기준 위반을 확정해 **검찰에 고발한** 공시가 통째로
무신호였다. 1년 전수(271,141건 · 절단일 0, 정정 제외 228,492건)에서
**12건 / 12개사**.

    회계처리기준위반행위로인한증권선물위원회의검찰고발등   4
    회계처리기준위반에따른검찰고발등조치                 3
    회계처리기준위반에따른임원의해임권고조치              3
    회계처리기준위반행위로인한검찰기소                   1
    투자판단관련주요경영사항 (…검찰 기소 관련 진행사항)     1   ← 공백형이라 미포착

## 왜 `4.3`인가 — v1.12.3의 판단을 뒤집는다

v1.12.3은 「4.3은 **공시** 의무 위반이라 맞는 taxonomy가 없다」고 보고 넣지
않았다. 그러나 **이 레포 자신의 금감원 카탈로그가 4.3에 130건**(277건 중
**47%, 최다**)을 매핑하고 있고 그 사례가 바로 이것이다.

    "㈜국보가 … 회계처리기준을 위반해 금융위원회가 과징금 부과 등을 의결"
    제재: 과징금 5,420만원 · 과태료 3,600만원 · 감사인지정 2년

적발 기법에 「소액공모**공시서류**에 회계기준 위반 재무제표 사용(**거짓기재**)」이
있다 — 재무제표는 공시이고, 틀린 재무제표를 낸 것은 공시 의무 위반이다.

## 함정 — 공백형을 넣으면 안 된다

실제로 `"회계처리기준 위반"`(공백)을 한 번 넣었다가 되돌렸다. 그러면 **5건에
두 번째 신호**가 붙는다.

    조회공시요구(풍문또는보도)(회계처리기준 위반)          3   이미 INQUIRY
    기타시장안내(…상장적격성 실질심사 절차 미진행 안내)     2   이미 DELISTING_RISK

한 제목이 신호 둘을 켜서 패턴 임계를 혼자 채우는 것이 **한탑 실사고**(v1.12.1)의
구조 그대로다. 붙여쓴 형태만 넣으면 그 5건은 원래 신호만 유지한다.

## 감사 결과 (같은 전수)

    부분 문자열 충돌   0
    한정층             11건 100% observed (강등 0)
    패턴 영향          11개 전부 +0 · 카드를 받는 회사 252곳 불변
    4.3을 처음 얻는 회사  10곳

## 넣지 않은 것 — 벌금·과징금(공정위 담합)

「벌금등의부과」 25건은 접수일 **10일**에 몰려 있고 같은 날 업계가 함께 낸다.

    20260423  6건  무림페이퍼 / 해성산업 / 무림P&P / 한국제지 / 한솔홀딩스 / 한솔제지
    20260520  5건  삼양홀딩스 / 삼양사 / 사조동아원 / 대한제분 / 한탑
    20260212  3건  삼양홀딩스 / 삼양사 / 대한제당

개별 회사의 위험 신호가 아니라 **산업 담합 사건**이고, 자본시장 불공정거래도
아니라 이 도구의 포지셔닝과 다르다. 위험 목록 12번에 근거를 남겼다.
"""
import pathlib

import pytest

from dart_risk_mcp.core.qualifiers import parse_report_name, qualify_signals
from dart_risk_mcp.core.signals import (
    SIGNAL_KEY_TO_TAXONOMY, SIGNAL_TYPES, match_signals,
)

_ROOT = pathlib.Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("title", [
    # 1년 전수의 실측 제목 그대로
    "회계처리기준위반행위로인한증권선물위원회의검찰고발등",
    "회계처리기준위반에따른검찰고발등조치",
    "회계처리기준위반에따른임원의해임권고조치",
    "회계처리기준위반행위로인한검찰기소",
])
def test_회계기준_위반_제재가_잡힌다(title):
    keys = [m["key"] for m in match_signals(title)]
    assert "DISCLOSURE_VIOL" in keys, f"무신호로 돌아갔다: {title}"


def test_taxonomy_4_3으로_간다():
    """카탈로그가 4.3에 130건(최다)을 매핑한 그 유형이다."""
    assert "4.3" in SIGNAL_KEY_TO_TAXONOMY["DISCLOSURE_VIOL"]


@pytest.mark.parametrize("title", [
    "회계처리기준위반행위로인한증권선물위원회의검찰고발등",
    "회계처리기준위반에따른임원의해임권고조치",
])
def test_강등되지_않는다(title):
    q = qualify_signals(match_signals(title), parse_report_name(title))
    assert q and all(i.tier == "observed" for i in q), \
        f"강등됐다: {[(i.tier, i.reason) for i in q]}"


@pytest.mark.parametrize("title,expect", [
    # ⚠ 이미 다른 신호가 잡는 것 — **두 번째 신호가 붙으면 안 된다**
    ("조회공시요구(풍문또는보도)              (회계처리기준 위반)", "INQUIRY"),
    ("기타시장안내              (회계처리기준 위반행위 관련 상장적격성 실질심사 "
     "절차 미진행 안내)", "DELISTING_RISK"),
])
def test_이미_잡히던_것에_신호가_겹치지_않는다(title, expect):
    """공백형을 넣으면 여기서 걸린다 — 한탑 실사고(v1.12.1)의 구조다."""
    keys = sorted(m["key"] for m in match_signals(title))
    assert keys == [expect], (
        f"신호가 겹쳤다: {keys}\n"
        "「회계처리기준 위반」(공백)을 키워드에 넣지 않았는지 확인하라 — "
        "한 제목이 신호 둘을 켜면 패턴 임계를 혼자 채운다.")


def test_공백형은_키워드에_없다():
    kws = next(s["keywords"] for s in SIGNAL_TYPES if s["key"] == "DISCLOSURE_VIOL")
    assert "회계처리기준위반" in kws
    assert "회계처리기준 위반" not in kws, (
        "공백형이 들어왔다 — 위 테스트의 5건에 두 번째 신호가 붙는다")
    assert "회계처리기준" not in kws, "단독형은 더 넓다"


@pytest.mark.parametrize("title", [
    # ⚠ 공정위 담합 과징금 — **일부러 넣지 않았다**
    "벌금등의부과",
    "벌금등의부과(자회사의 주요경영사항)",
])
def test_벌금등의부과는_넣지_않았다(title):
    """넣으려면 「산업 담합을 개별 회사 위험 신호로 볼 것인가」를 먼저 정해야
    한다 — 위험 목록 12번과 이 테스트를 함께 갱신하라."""
    assert not match_signals(title), (
        f"신호가 붙기 시작했다: {title} → "
        f"{[m['key'] for m in match_signals(title)]}\n"
        "같은 날 업계가 함께 내는 공정위 담합 공시다(제지 6사·제분 5사·제당 3사 실측).")


def test_위험_목록에_판단_근거가_남아_있다():
    doc = (_ROOT / "docs" / "DEFERRED-DECISIONS.md").read_text(encoding="utf-8")
    assert "## 12." in doc
    assert "담합" in doc, "「벌금은 산업 담합이라 넣지 않았다」는 판단이 사라졌다"
    assert "130건" in doc or "47%" in doc, (
        "「카탈로그가 4.3에 최다 매핑한다」는 근거가 사라졌다")
