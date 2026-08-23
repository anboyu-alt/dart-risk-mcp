"""회사분할결정의 상대방(분할신설회사)이 항상 공란이던 문제.

`_normalize_decision`의 이름 폴백 체인은 3종뿐이었다. 2026-08-04 감사가
`dvcmp_cmpnm`을 "가이드에 없는 죽은 필드"로 제거했는데, 이름이 비슷한
**다른 필드**가 실제 응답에 있다는 것을 그때 못 찾았다.

라이브 실측(2026-08-23, 53일 시장 전수에서 DS005 8종 표본):

| 유형 | 체인 적중 | 원본 *cmpnm 필드 |
|---|---|---|
| merger | 7/7 | mgptncmp_cmpnm, nmgcmp_cmpnm |
| stock_acq | 7/7 | dlptn_cmpnm, iscmp_cmpnm |
| stock_div | 4/4 | dlptn_cmpnm, iscmp_cmpnm |
| stock_exchange | 2/2 | extr_tgcmp_cmpnm, atextr_cpcmpnm |
| tangible_acq | 6/6 | dlptn_cmpnm |
| tangible_div | 7/7 | dlptn_cmpnm |
| business_acq | 1/1 | dlptn_cmpnm |
| **demerger** | **0/3** | atdv_excmp_cmpnm, **dvfcmp_cmpnm** |

`demerger`만 놓치고 있었다. 존속회사(`atdv_excmp_cmpnm`)는 공시 회사 자신
이므로 상대방이 아니고, 분할신설회사(`dvfcmp_cmpnm`)가 맞는 값이다.

라이브: 현대홈쇼핑 20260805000212 → '(주)현대홈쇼핑지주(가칭) …'

⚠ `relation_text`는 여전히 빈다 — 분할 응답에 관계 필드가 없고
(`dvfcmp_rlst_atn`은 상장 여부다) 이건 데이터의 한계다.
"""
import pytest

from dart_risk_mcp.core.dart_client import _normalize_decision

_URL = "https://opendart.fss.or.kr/api/cmpDvDecsn.json"


class TestDemergerCounterparty:
    def test_분할신설회사를_상대방으로_읽는다(self):
        raw = {
            "atdv_excmp_cmpnm": "(주)현대홈쇼핑\nHYUNDAI HOME SHOPPING",
            "dvfcmp_cmpnm": "(주)현대홈쇼핑지주(가칭)\nHYUNDAI HOME SHOPPING HOLDINGS",
            "dvfcmp_rlst_atn": "아니오",
        }
        got = _normalize_decision(raw, "demerger", _URL)
        assert got["counterparty"].startswith("(주)현대홈쇼핑지주(가칭)")
        assert "현대홈쇼핑 HYUNDAI" not in got["counterparty"], (
            "존속회사는 공시 회사 자신이라 상대방이 아니다")

    def test_원문_개행을_한_줄로_편다(self):
        raw = {"dvfcmp_cmpnm": "(주)가나\nGANA Co.,Ltd"}
        assert _normalize_decision(raw, "demerger", _URL)["counterparty"] == \
            "(주)가나 GANA Co.,Ltd"

    def test_관계는_비워_둔다(self):
        """분할 응답에 관계 필드가 없다 — 데이터의 한계지 파서 결함이 아니다."""
        raw = {"dvfcmp_cmpnm": "(주)가나", "dvfcmp_rlst_atn": "아니오"}
        assert _normalize_decision(raw, "demerger", _URL)["relation_text"] == ""


class TestChainOrderUnchanged:
    """체인 끝에 붙였으므로 기존 7종의 해석이 바뀌지 않는다."""

    @pytest.mark.parametrize("field,dtype", [
        ("dlptn_cmpnm", "stock_acq"),
        ("mgptncmp_cmpnm", "merger"),
        ("extr_tgcmp_cmpnm", "stock_exchange"),
    ])
    def test_앞선_필드가_우선한다(self, field, dtype):
        raw = {field: "정답회사", "dvfcmp_cmpnm": "분할신설회사"}
        assert _normalize_decision(raw, dtype, _URL)["counterparty"] == "정답회사"

    def test_이름_필드가_없으면_빈_문자열(self):
        got = _normalize_decision({"bddd": "2026년 08월 05일"}, "demerger", _URL)
        assert got["counterparty"] == ""
