"""비감사용역 보수 비중은 계산할 수 없다 — 경고 대신 건수를 적는다.

DART의 감사·비감사 보수 필드에는 **단위가 실려 오지 않고, 회사마다도 같은
회사의 연도 사이에서도 단위가 바뀐다**(2026-08-23 라이브 실측).

| 회사 | 감사보수 2025 | 감사보수 2023 |
|---|---|---|
| 헬릭스미스 | 298 | **298,000** |
| 제이스코홀딩스 | 280 | **200,000** |
| 나이스정보통신 | 365 | **279,000** |

셀트리온은 두 엔드포인트 사이에서 어긋난다 — 감사 `2,920`(백만원=29억) vs
비감사 `130,000`·`600,000`(원=13만·60만). 그대로 나누면 비중이 1,000배
이상 부풀려진다.

그 결과 12개사 중 **4개사**가 「비감사용역 비중 30% 초과」 경고를 받았고
셀트리온은 99~100%였다. 전부 단위가 어긋나 나온 값이다.

v0.8.0이 **절대 금액**을 같은 이유로 뺐는데 비율은 그 금액에서 나온다.
판정 불가면 표기하지 않는다는 관례대로 비율을 버리고, 단위와 무관한
사실(계약 건수)만 남긴다.
"""
from unittest.mock import patch

import dart_risk_mcp.core.dart_client as dc
import dart_risk_mcp.server as srv


class _Resp:
    def __init__(self, rows):
        self._rows = rows

    def json(self):
        return {"status": "000", "list": self._rows}


def _history(audit_rows, nonaudit_rows, opinion_rows=None):
    """엔드포인트별 응답을 주입해 fetch_audit_opinion_history를 돌린다.

    이 함수는 `_retry`를 연도×엔드포인트로 직접 부른다(래퍼가 따로 없다).
    처음에 있지도 않은 `_fetch_audit_raw`를 패치했다가 전부 실패했다.
    """
    def fake(method, url, **kw):
        if "NonAdtServc" in url:
            return _Resp(nonaudit_rows)
        if "adtServcCnclsSttus" in url:
            return _Resp(audit_rows)
        return _Resp(opinion_rows or [])

    dc._audit_history_cache.clear()
    with patch.object(dc, "_retry", side_effect=fake):
        return dc.fetch_audit_opinion_history("00000001", "k", 5)


CELLTRION_AUDIT = [{"bsns_year": "제35기\n(당기)", "stlm_dt": "2025-12-31",
                    "mendng": "-", "adt_cntrct_dtls_mendng": "2,920",
                    "real_exc_dtls_mendng": "2,920"}]
CELLTRION_NONAUDIT = [{"cntrct_cncls_de": "2025.03",
                       "servc_cn": "ESG 보고서 컨설팅 용역",
                       "servc_mendng": "130,000\n600,000\n185,000"}]


class TestNoRatioWarning:
    def test_단위가_어긋난_실측값에도_경고가_없다(self):
        h = _history(CELLTRION_AUDIT, CELLTRION_NONAUDIT)
        assert "independence_warnings" not in h  # 2026-08-27 키 자체를 제거

    def test_계약_건수를_사실로_남긴다(self):
        h = _history(CELLTRION_AUDIT, CELLTRION_NONAUDIT)
        assert h["non_audit_contracts"] == {2025: 1}

    def test_내용이_없는_행은_세지_않는다(self):
        """'-'만 있는 행은 '계약 없음' 표기다."""
        rows = [{"cntrct_cncls_de": "2025.03", "servc_cn": "-",
                 "servc_mendng": "-"},
                {"cntrct_cncls_de": "2025.05", "servc_cn": "세무자문",
                 "servc_mendng": "43"}]
        assert _history([], rows)["non_audit_contracts"] == {2025: 1}


class TestRender:
    def _out(self, contracts, warnings=()):
        data = {"opinions": [{"year": 2025, "opinion": "적정",
                              "auditor": "A회계법인", "tenure_years": 1}],
                "auditor_changes": [],
                "non_audit_contracts": contracts}
        with patch.object(srv, "_DART_API_KEY", "k"), \
             patch.object(srv, "resolve_corp",
                          return_value=("테스트", {"corp_code": "00000001",
                                                 "stock_code": "000001"})), \
             patch.object(srv, "fetch_audit_opinion_history", return_value=data), \
             patch.object(srv, "fetch_loss_streak", return_value={}):
            return srv.get_audit_opinion_history("테스트")

    def test_건수를_표기한다(self):
        out = self._out({2025: 3, 2024: 1})
        assert "비감사용역 계약 (참고)" in out
        assert "- 2025: 3건" in out and "- 2024: 1건" in out

    def test_단위를_모른다는_사실을_밝힌다(self):
        assert "단위를 함께 제공하지 않아" in self._out({2025: 1})

    def test_계약이_없으면_섹션이_없다(self):
        assert "비감사용역 계약" not in self._out({})

    def test_옛_경고_문구는_더_이상_나오지_않는다(self):
        """경고 리스트가 (하위 호환으로) 채워져 있어도 렌더하지 않는다."""
        out = self._out({2025: 1}, warnings=["2025 비감사용역 비중 99%"])
        assert "독립성 훼손 우려" not in out
        assert "비중 99%" not in out
