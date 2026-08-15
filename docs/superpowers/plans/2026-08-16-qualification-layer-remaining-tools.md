# 한정층 잔여 도구 배선 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `check_disclosure_risk`와 `search_market_disclosures`가 `analyze_company_risk`와 같은 신호 한정 판정에 도달하게 한다.

**Architecture:** PR #163이 만든 `core/qualifiers.py`를 그대로 쓴다 — 규칙은 하나도 바꾸지 않는다. `check_disclosure_risk`는 접수번호로 실제 `list.json` 행을 복원해 제목·제출인을 얻고, `search_market_disclosures`는 이미 손에 든 행을 `qualify_signals`에 넘긴다. 두 도구 모두 실패 시 현재 동작으로 조용히 퇴화한다.

**Tech Stack:** Python 3.11+ (표준 라이브러리 + `requests`), pytest + `unittest.mock`

**Spec:** [docs/superpowers/specs/2026-08-16-qualification-layer-remaining-tools-design.md](../specs/2026-08-16-qualification-layer-remaining-tools-design.md)

## Global Constraints

- **외부 라이브러리 추가 금지.** `requests`와 `mcp` 외 의존성을 추가하지 않는다.
- **점수·등급 없음 (v0.8.5).** 기업 위험도를 정량화하거나 등급("매우위험", "고위험" 등)으로 부여하는 어떤 표기도 사용자 출력에 노출되면 안 된다.
- **`_AMENDMENT_RE`·`match_signals`·`SIGNAL_TYPES`·`taxonomy.py`·`core/qualifiers.py`는 수정하지 않는다.** 한정 규칙은 그대로 쓰고 배선만 한다.
- **`resolve_corp_code_from_rcept_no`는 시그니처·동작·캐시를 그대로 둔다.** 조회 범위가 달라(`pblntf_ty="B"`) 신규 함수와 통합하면 DS005 경로의 호출 예산이 1페이지에서 12페이지로 늘어난다.
- **실패 시 기존 동작으로 수렴한다.** 새 코드가 죽어도 도구가 죽지 않는다.
- 오류 처리: API 호출 실패 시 빈 값 반환, 예외를 도구 레벨로 전파하지 않는다.
- 커밋 메시지는 한국어, 말미에 `Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>`.

---

## File Structure

| 파일 | 책임 | 상태 |
|---|---|---|
| `dart_risk_mcp/core/dart_client.py` | `resolve_disclosure_row_from_rcept_no` + 전용 캐시 추가 | 수정 |
| `dart_risk_mcp/server.py` | 두 도구 배선 + 시장 스캔 필터 함수 분리 | 수정 |
| `tests/test_resolve_disclosure_row.py` | 신규 조회 함수 단위 테스트 | **생성** |
| `tests/test_qualification_wiring.py` | 두 도구 배선 테스트 추가 | 수정 |
| `tests/fixtures/sample_outputs/market_*.txt` | 13개 preset 골든 재생성 | 재생성 |
| `CLAUDE.md` | 도구 설명·감사표 갱신 | 수정 |

---

## Task 1: `resolve_disclosure_row_from_rcept_no`

접수번호로 `list.json` 행 전체를 복원한다. `check_disclosure_risk`가 실제 제목과 제출인을 알게 하는 것이 목적이다.

**Files:**
- Modify: `dart_risk_mcp/core/dart_client.py`
- Create: `tests/test_resolve_disclosure_row.py`

**Interfaces:**
- Consumes: 기존 `_retry`, `_cache_get`, `_cache_set`, `_log_dart_status`, `DART_BASE`
- Produces:
  - `resolve_disclosure_row_from_rcept_no(rcept_no: str, api_key: str, max_pages: int = 12) -> "dict | None"`
  - 모듈 상수 `_rcept_row_cache: dict`, `_RCEPT_ROW_CACHE_TTL: int`, `_RCEPT_ROW_CACHE_MAX: int`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_resolve_disclosure_row.py`:

```python
# -*- coding: utf-8 -*-
"""resolve_disclosure_row_from_rcept_no 단위 테스트.

배경: check_disclosure_risk가 rcept_no로 불릴 때 title을 f"접수번호 {rcept_no}"
자리표시자로 만들어 match_signals에 넘겨, 어떤 신호도 매칭될 수 없었다
(함수 132줄에 report_nm이 0회 등장). 실제 행을 복원해 제목·제출인을 얻는다.

기존 resolve_corp_code_from_rcept_no와 별개 함수인 이유: 그쪽은
pblntf_ty="B"(주요사항보고)로 좁혀 조회해 지분공시(D)·거래소공시(H)를
찾지 못한다(실측: 대량보유보고 20260731000779 → ""). 통합하면 DS005 경로의
호출 예산이 1페이지에서 12페이지로 늘어난다.
"""
import unittest
from unittest.mock import patch, MagicMock

from dart_risk_mcp.core import dart_client


def _list_resp(status="000", lst=None, total_page=1):
    resp = MagicMock()
    lst = lst or []
    resp.json.return_value = {
        "status": status,
        "message": "정상" if status == "000" else "필수값 누락",
        "list": lst,
        "total_page": total_page,
        "total_count": len(lst),
    }
    return resp


_ROW = {
    "rcept_no": "20260731000779",
    "corp_code": "00126380",
    "corp_name": "삼성전자",
    "stock_code": "005930",
    "corp_cls": "Y",
    "report_nm": "주식등의대량보유상황보고서(일반)",
    "flr_nm": "삼성물산",
    "rcept_dt": "20260731",
    "rm": "",
}


class TestResolveDisclosureRow(unittest.TestCase):
    def setUp(self):
        dart_client._rcept_row_cache.clear()

    def test_invalid_rcept_no_returns_none(self):
        self.assertIsNone(
            dart_client.resolve_disclosure_row_from_rcept_no("123", "key")
        )

    def test_no_api_key_returns_none(self):
        self.assertIsNone(
            dart_client.resolve_disclosure_row_from_rcept_no("20260731000779", "")
        )

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_found_on_first_page_returns_full_row(self, mock_retry):
        mock_retry.return_value = _list_resp(lst=[
            {"rcept_no": "20260731000111", "corp_name": "다른회사"},
            _ROW,
        ])
        row = dart_client.resolve_disclosure_row_from_rcept_no(
            "20260731000779", "key"
        )
        self.assertIsNotNone(row)
        self.assertEqual(row["report_nm"], "주식등의대량보유상황보고서(일반)")
        self.assertEqual(row["flr_nm"], "삼성물산")
        self.assertEqual(row["corp_name"], "삼성전자")

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_does_not_send_pblntf_ty(self, mock_retry):
        """유형 필터를 보내면 지분공시(D)·거래소공시(H)를 못 찾는다."""
        mock_retry.return_value = _list_resp(lst=[_ROW])
        dart_client.resolve_disclosure_row_from_rcept_no("20260731000779", "key")
        params = mock_retry.call_args.kwargs["params"]
        self.assertNotIn("pblntf_ty", params)
        self.assertEqual(params["bgn_de"], "20260731")
        self.assertEqual(params["end_de"], "20260731")

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_found_on_later_page(self, mock_retry):
        mock_retry.side_effect = [
            _list_resp(lst=[{"rcept_no": "20260731000001"}], total_page=3),
            _list_resp(lst=[{"rcept_no": "20260731000002"}], total_page=3),
            _list_resp(lst=[_ROW], total_page=3),
        ]
        row = dart_client.resolve_disclosure_row_from_rcept_no(
            "20260731000779", "key"
        )
        self.assertIsNotNone(row)
        self.assertEqual(mock_retry.call_count, 3)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_stops_at_total_page(self, mock_retry):
        mock_retry.return_value = _list_resp(
            lst=[{"rcept_no": "20260731000001"}], total_page=2
        )
        row = dart_client.resolve_disclosure_row_from_rcept_no(
            "20260731000779", "key"
        )
        self.assertIsNone(row)
        self.assertEqual(mock_retry.call_count, 2)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_respects_max_pages(self, mock_retry):
        mock_retry.return_value = _list_resp(
            lst=[{"rcept_no": "20260731000001"}], total_page=99
        )
        row = dart_client.resolve_disclosure_row_from_rcept_no(
            "20260731000779", "key", max_pages=4
        )
        self.assertIsNone(row)
        self.assertEqual(mock_retry.call_count, 4)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_bad_status_stops_immediately(self, mock_retry):
        mock_retry.return_value = _list_resp(status="100", total_page=9)
        row = dart_client.resolve_disclosure_row_from_rcept_no(
            "20260731000779", "key"
        )
        self.assertIsNone(row)
        self.assertEqual(mock_retry.call_count, 1)

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_network_error_returns_none(self, mock_retry):
        mock_retry.side_effect = RuntimeError("boom")
        self.assertIsNone(
            dart_client.resolve_disclosure_row_from_rcept_no(
                "20260731000779", "key"
            )
        )

    @patch("dart_risk_mcp.core.dart_client._retry")
    def test_second_call_hits_cache(self, mock_retry):
        mock_retry.return_value = _list_resp(lst=[_ROW])
        dart_client.resolve_disclosure_row_from_rcept_no("20260731000779", "key")
        dart_client.resolve_disclosure_row_from_rcept_no("20260731000779", "key")
        self.assertEqual(mock_retry.call_count, 1)

    def test_row_cache_is_separate_from_corp_cache(self):
        """값 타입이 dict vs str이고 조회 범위도 달라 공유하면 오염된다."""
        self.assertIsNot(
            dart_client._rcept_row_cache, dart_client._rcept_corp_cache
        )


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run (PowerShell): `python -m pytest tests/test_resolve_disclosure_row.py -v`
Expected: FAIL — `AttributeError: module 'dart_risk_mcp.core.dart_client' has no attribute '_rcept_row_cache'`

- [ ] **Step 3: 최소 구현**

`dart_client.py`에서 `_rcept_corp_cache` 정의 근처에 캐시를 추가한다:

```python
# rcept_no → list.json 행 전체 캐시. _rcept_corp_cache와 분리한다 —
# 값 타입이 dict vs str이고, 이쪽은 pblntf_ty 필터 없이 조회하므로
# 조회 범위 자체가 다르다. 공유하면 한쪽 미스가 다른 쪽을 오염시킨다.
_rcept_row_cache: dict = {}
_RCEPT_ROW_CACHE_TTL = 600
_RCEPT_ROW_CACHE_MAX = 50
```

`resolve_corp_code_from_rcept_no` **바로 아래**에 함수를 추가한다(기존 함수는 건드리지 않는다):

```python
def resolve_disclosure_row_from_rcept_no(
    rcept_no: str, api_key: str, max_pages: int = 12
) -> "dict | None":
    """접수번호 → list.json 행 전체. 실패 시 None.

    check_disclosure_risk가 rcept_no만 아는 경로에서 실제 report_nm·flr_nm·
    corp_name을 얻어 신호 매칭과 한정층(R1~R5)을 적용하기 위한 조회다.

    resolve_corp_code_from_rcept_no와 별개 함수인 이유:
      - 그쪽은 pblntf_ty="B"(주요사항보고)로 좁혀 조회한다. 지분공시(D)·
        거래소공시(H)는 검색 범위 밖이다(실측 2026-08-16: 대량보유보고
        20260731000779 → "").
      - 필터를 풀면 하루치가 커진다(20260731 실측: 전체 1,159건 12페이지 vs
        B 54건 1페이지). 통합하면 DS005 경로의 호출 예산이 12배가 된다.

    알려진 한계: rcept_no 앞 8자리가 접수일과 다른 공시가 있다(20260803 전수
    610건 중 4건, 0.7% — 본느 20260731000816의 rcept_dt는 20260803). 그런
    건은 찾지 못하고 None을 반환하며, 호출부는 기존 동작으로 퇴화한다.
    """
    if (
        not api_key
        or not isinstance(rcept_no, str)
        or len(rcept_no) != 14
        or not rcept_no.isdigit()
    ):
        return None

    cached = _cache_get(_rcept_row_cache, rcept_no, _RCEPT_ROW_CACHE_TTL)
    if cached is not None:
        return cached

    rcpt_date = rcept_no[:8]
    page_no = 1
    total_page = 1
    while page_no <= max_pages:
        params = {
            "crtfc_key": api_key,
            "bgn_de": rcpt_date,
            "end_de": rcpt_date,
            "page_no": page_no,
            "page_count": 100,
        }
        try:
            data = _retry("GET", f"{DART_BASE}/list.json", params=params).json()
        except Exception:
            return None
        if data.get("status") != "000":
            _log_dart_status(data.get("status", "?"), f"rcept→row {rcept_no}")
            return None
        for row in data.get("list", []) or []:
            if row.get("rcept_no") == rcept_no:
                _cache_set(
                    _rcept_row_cache, rcept_no, row, _RCEPT_ROW_CACHE_MAX
                )
                return row
        try:
            total_page = int(data.get("total_page", 1) or 1)
        except (TypeError, ValueError):
            total_page = 1
        if page_no >= total_page:
            return None
        page_no += 1
    return None
```

`core/__init__.py`의 `from .dart_client import (...)` 블록과 `__all__`에 `resolve_disclosure_row_from_rcept_no`를 추가한다.

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_resolve_disclosure_row.py -v`
Expected: PASS (11 passed)

Run: `python -m pytest tests/test_resolve_corp_from_rcept.py -q`
Expected: 기존 테스트 전부 통과 — 기존 함수를 건드리지 않았음을 확인

- [ ] **Step 5: 라이브 확인 (PowerShell)**

```powershell
python -c "
import os,sys; sys.path.insert(0,'.')
from dart_risk_mcp.core.dart_client import resolve_disclosure_row_from_rcept_no as f
k=os.environ['DART_API_KEY']
for rc,label in [('20260731000779','대량보유(D)'),('20260731901330','거래소(H)'),('20260731000816','날짜불일치')]:
    r=f(rc,k)
    print('%-12s %s' % (label, (r['report_nm'].strip()[:34]+' | flr='+str(r.get('flr_nm'))) if r else 'None (퇴화)'))
"
```

Expected:
```
대량보유(D)     주식등의대량보유상황보고서(일반) | flr=삼성물산
거래소(H)      타인에대한담보제공결정 | flr=피플바이오
날짜불일치      None (퇴화)
```

세 번째가 `None`인 것이 정상이다 — 스펙 §4.3의 알려진 한계다.

- [ ] **Step 6: 커밋**

```bash
git add dart_risk_mcp/core/dart_client.py dart_risk_mcp/core/__init__.py tests/test_resolve_disclosure_row.py
git commit -m "feat(dart_client): 접수번호로 list.json 행 전체를 복원하는 조회 추가

check_disclosure_risk가 rcept_no만 아는 경로에서 실제 report_nm·flr_nm을
얻어 한정층 R1~R5를 적용할 수 있게 한다.

기존 resolve_corp_code_from_rcept_no는 그대로 둔다 — pblntf_ty=B로 좁혀
조회해 지분공시·거래소공시를 못 찾지만(실측), 통합하면 DS005 경로의
호출 예산이 12배가 된다. 목적이 다른 별개 조회다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 2: `check_disclosure_risk` 배선

**Files:**
- Modify: `dart_risk_mcp/server.py:1258-1292` (`check_disclosure_risk` 진입부와 신호 렌더)
- Modify: `tests/test_qualification_wiring.py`

**Interfaces:**
- Consumes: `resolve_disclosure_row_from_rcept_no` (Task 1), 기존 `parse_report_name`·`qualify_signals`·`TIER_OBSERVED` (PR #163에서 이미 `server.py`가 import 중)
- Produces: 없음 (도구 출력만 변경)

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_qualification_wiring.py` 하단에 추가:

```python
class TestCheckDisclosureRiskQualification(unittest.TestCase):
    """check_disclosure_risk 배선 — 제목만 주는 경로는 R1b~R5만 적용된다."""

    def test_ownership_report_is_demoted(self):
        from dart_risk_mcp.server import check_disclosure_risk
        out = check_disclosure_risk(report_name="주식등의대량보유상황보고서(일반)")
        self.assertIn("절차·사후 보고", out)
        self.assertIn("지분", out)
        self.assertNotIn("🎯", out)

    def test_cb_issuance_stays_observed(self):
        """과잉 강등 방지 — 회사가 낸 실제 결정은 관찰 신호로 남는다."""
        from dart_risk_mcp.server import check_disclosure_risk
        out = check_disclosure_risk(
            report_name="주요사항보고서(전환사채권발행결정)"
        )
        self.assertIn("🎯", out)
        self.assertNotIn("절차·사후 보고", out)

    def test_exchange_inquiry_stays_observed_without_filing(self):
        """filing이 없으면 R1은 적용되지 않는다 — 거래소 조회공시가 남아야 한다."""
        from dart_risk_mcp.server import check_disclosure_risk
        out = check_disclosure_risk(
            report_name="조회공시요구(풍문또는보도)(감사의견비적정설)"
        )
        self.assertIn("🎯", out)

    def test_result_report_is_demoted(self):
        from dart_risk_mcp.server import check_disclosure_risk
        out = check_disclosure_risk(report_name="자기주식취득결과보고서")
        self.assertIn("절차·사후 보고", out)

    def test_label_softened_when_allocation_absent(self):
        from dart_risk_mcp.server import check_disclosure_risk
        out = check_disclosure_risk(report_name="주요사항보고서(유상증자결정)")
        self.assertIn("배정방식 미상", out)


class TestCheckDisclosureRiskRcertPath(unittest.TestCase):
    """rcept_no 경로 — 행 복원 성공/실패 양쪽."""

    _ROW = {
        "rcept_no": "20260731000779",
        "corp_code": "00126380",
        "corp_name": "삼성전자",
        "report_nm": "주식등의대량보유상황보고서(일반)",
        "flr_nm": "삼성물산",
        "rcept_dt": "20260731",
    }

    @patch("dart_risk_mcp.server._DART_API_KEY", "testkey")
    @patch("dart_risk_mcp.server.fetch_document_text", return_value="")
    @patch("dart_risk_mcp.server.resolve_corp_code_from_rcept_no", return_value="")
    @patch("dart_risk_mcp.server.resolve_disclosure_row_from_rcept_no")
    def test_row_found_uses_real_title_and_filer(self, mock_row, _cc, _doc):
        from dart_risk_mcp.server import check_disclosure_risk
        mock_row.return_value = dict(self._ROW)
        out = check_disclosure_risk(rcept_no="20260731000779")
        self.assertIn("주식등의대량보유상황보고서(일반)", out)
        self.assertIn("삼성물산", out)
        self.assertNotIn("공시: 접수번호", out)
        self.assertIn("절차·사후 보고", out)

    @patch("dart_risk_mcp.server._DART_API_KEY", "testkey")
    @patch("dart_risk_mcp.server.fetch_document_text", return_value="")
    @patch("dart_risk_mcp.server.resolve_corp_code_from_rcept_no", return_value="")
    @patch("dart_risk_mcp.server.resolve_disclosure_row_from_rcept_no")
    def test_row_missing_degrades_to_current_behaviour(self, mock_row, _cc, _doc):
        """행 복원 실패는 회귀가 아니다 — 지금과 같은 출력이어야 한다."""
        from dart_risk_mcp.server import check_disclosure_risk
        mock_row.return_value = None
        out = check_disclosure_risk(rcept_no="20260731000816")
        self.assertIn("공시: 접수번호 20260731000816", out)
        self.assertNotIn("제출인:", out)
```

파일 상단에 `from unittest.mock import patch`가 없으면 추가한다.

> **네트워크 차단이 필수다.** `check_disclosure_risk`는 `rcept_no`와 API 키가 있으면
> `server.py:1331`에서 `resolve_corp_code_from_rcept_no`를, `server.py:1365-1366`에서
> `fetch_document_text`(원문 500자 미리보기)를 호출한다. `_DART_API_KEY`만 패치하고
> 이 둘을 놔두면 단위 테스트가 가짜 키로 실제 DART를 때린다 — 느리고 불안정하다.
> 위 데코레이터 순서(아래에서 위로 인자에 대응)를 그대로 쓴다.

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_qualification_wiring.py -v -k "CheckDisclosure"`
Expected: FAIL — `AssertionError: '절차·사후 보고' not found`

- [ ] **Step 3: 최소 구현**

`server.py` 상단 import에 추가(이미 있으면 생략):

```python
from .core.dart_client import resolve_disclosure_row_from_rcept_no
```

`check_disclosure_risk`의 1268-1272행을 아래로 교체한다:

```python
    # rcept_no만 아는 경로에서도 실제 제목·제출인을 복원한다. 실패하면
    # 기존 동작(자리표시자 제목, 무신호)으로 조용히 퇴화한다 — 회귀가 아니다.
    filing: "dict | None" = None
    if rcept_no and not report_name and _DART_API_KEY:
        filing = resolve_disclosure_row_from_rcept_no(rcept_no, _DART_API_KEY)

    if filing and filing.get("report_nm"):
        title = filing["report_nm"].strip()
    else:
        title = report_name or f"접수번호 {rcept_no}"

    parsed = parse_report_name(title)
    is_amendment = is_amendment_disclosure(title)
    matched = match_signals(title)
    qualified = qualify_signals(matched, parsed, filing)

    lines = ["📋 **공시 리스크 분석**", f"공시: {title}"]
    if filing and filing.get("flr_nm"):
        lines.append(f"제출인: {filing['flr_nm']}")
    lines.append("")
```

1283-1292행의 신호 렌더 루프를 아래로 교체한다:

```python
        for sig, q in zip(matched, qualified):
            from .core.signals import SIGNAL_KEY_TO_TAXONOMY

            tax_ids = SIGNAL_KEY_TO_TAXONOMY.get(sig["key"], [])
            prose = signal_to_prose(sig["key"])
            amendment_note = " (정정공시 — 원공시의 번복/수정이므로 관찰 대상에서 제외됩니다.)" if is_amendment else ""
            if q.tier == TIER_OBSERVED:
                lines.append(f"🎯 **{q.label}**{amendment_note}")
                if prose:
                    lines.append(prose)
                if q.note:
                    lines.append(f"※ {q.note}")
                lines.append("")
            else:
                # 단건 도구라 #163의 두 층 절 구분은 과하다 — 한 건의 판정과
                # 사유만 보인다.
                lines.append("⚪ **절차·사후 보고**")
                lines.append(q.reason)
                lines.append(
                    f"→ 제목에 [{q.label}] 신호가 매칭되지만, "
                    "회사가 낸 사건 공시가 아닙니다."
                )
                if q.note:
                    lines.append(f"※ {q.note}")
                lines.append("")
                continue
```

`continue`로 인해 아래 타임라인 블록은 `procedural`일 때 건너뛴다. 타임라인 블록의 기존 조건 `if tax_ids and not is_amendment:`는 그대로 둔다.

> **`server.py:1326`의 `resolve_decision_type(report_name)`은 건드리지 않는다.**
> 이 줄은 `title`이 아니라 원본 인자 `report_name`을 쓴다. 접수번호로만 부르면
> `report_name`이 빈 문자열이라 DS005 섹션이 발화하지 않는데, 이제 실제 제목을
> 알게 됐으니 `title`로 바꾸면 그 섹션이 살아날 여지가 있다. 하지만 그것은 DS005
> 조회 경로의 동작 변경이라 이번 스펙의 범위가 아니다(스펙 §2 비목표: 배선만 한다).
> 구현자는 이 줄을 그대로 두고, 보고서에 "확인했고 의도적으로 두었다"고 적는다.

1314행의 CB 인수자 조건을 아래로 바꿔 강등된 CB 공시가 인수자 추출을 유발하지 않게 한다:

```python
    if (
        rcept_no
        and any(
            q.key == "CB_BW" and q.tier == TIER_OBSERVED for q in qualified
        )
        and not is_amendment
    ):
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_qualification_wiring.py -v -k "CheckDisclosure"`
Expected: PASS (7 passed)

Run: `python -m pytest tests/ -q --tb=line`
Expected: 기존 대비 실패 0건. 정확한 건수를 보고한다.

- [ ] **Step 5: 라이브 확인 (PowerShell)**

```powershell
python -c "
import sys; sys.path.insert(0,'.')
from dart_risk_mcp.server import check_disclosure_risk
for kw in [dict(rcept_no='20260731000779'), dict(rcept_no='20260731901330'), dict(report_name='주요사항보고서(전환사채권발행결정)')]:
    out = check_disclosure_risk(**kw)
    print('---', kw)
    for l in out.splitlines()[:6]:
        if l.strip(): print('   ' + l.strip()[:84])
"
```

첫 번째는 실제 제목·제출인이 나오고 `⚪ 절차·사후 보고`, 세 번째는 `🎯`가 나와야 한다.

- [ ] **Step 6: 커밋**

```bash
git add dart_risk_mcp/server.py tests/test_qualification_wiring.py
git commit -m "feat(server): check_disclosure_risk에 한정층 배선

접수번호 경로가 실제 제목·제출인을 복원해 신호 매칭이 살아나고 R1~R5가
적용된다. 제목만 주는 경로는 R1b~R5. 행 복원 실패 시 기존 동작으로 퇴화.

단건 도구라 두 층 절 구분 없이 한 건의 판정과 사유만 표기한다.
강등된 CB 공시는 인수자 추출을 유발하지 않는다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 3: `search_market_disclosures` 배선

**Files:**
- Modify: `dart_risk_mcp/server.py:2865-2906` (필터 루프·커버리지 문구·렌더)
- Modify: `tests/test_qualification_wiring.py`

**Interfaces:**
- Consumes: 기존 `parse_report_name`·`qualify_signals`·`TIER_OBSERVED`
- Produces:
  - `_filter_market_rows(raw: list[dict], target_keys: set) -> tuple[list, int]`
    반환은 `(filtered, procedural_count)`이며 `filtered`의 원소는 `(row_dict, list[Qualified])`

- [ ] **Step 1: 실패하는 테스트 작성**

`tests/test_qualification_wiring.py` 하단에 추가:

```python
class TestMarketScanFilter(unittest.TestCase):
    """시장 스캔 필터 — 네트워크 없이 합성 행으로 검증한다."""

    @staticmethod
    def _row(nm, flr, corp="테스트회사", rc="20260731000001"):
        return {
            "rcept_no": rc, "corp_name": corp, "report_nm": nm,
            "flr_nm": flr, "rcept_dt": "20260731", "corp_code": "00000001",
        }

    def test_third_party_rows_are_counted_not_listed(self):
        from dart_risk_mcp.server import _filter_market_rows
        raw = [
            self._row("주식등의대량보유상황보고서(일반)", "국민연금공단", rc="1" * 14),
            self._row("주식등의대량보유상황보고서(일반)", "국민연금공단", rc="2" * 14),
            self._row("주식등의대량보유상황보고서(일반)", "국민연금공단", rc="3" * 14),
            self._row("주요사항보고서(전환사채권발행결정)", "테스트회사", rc="4" * 14),
            self._row("주요사항보고서(전환사채권발행결정)", "테스트회사", rc="5" * 14),
        ]
        filtered, procedural = _filter_market_rows(raw, set())
        self.assertEqual(len(filtered), 2)
        self.assertEqual(procedural, 3)

    def test_preset_filter_applies_to_observed_only(self):
        """강등된 신호가 preset을 통과시키면 제외의 의미가 없다."""
        from dart_risk_mcp.server import _filter_market_rows
        raw = [
            self._row("주식등의대량보유상황보고서(일반)", "국민연금공단"),
        ]
        filtered, procedural = _filter_market_rows(raw, {"SHAREHOLDER"})
        self.assertEqual(len(filtered), 0)
        self.assertEqual(procedural, 1)

    def test_observed_row_passes_matching_preset(self):
        from dart_risk_mcp.server import _filter_market_rows
        raw = [self._row("주요사항보고서(전환사채권발행결정)", "테스트회사")]
        filtered, procedural = _filter_market_rows(raw, {"CB_BW"})
        self.assertEqual(len(filtered), 1)
        self.assertEqual(procedural, 0)

    def test_no_signal_row_counts_as_neither(self):
        from dart_risk_mcp.server import _filter_market_rows
        raw = [self._row("사업보고서 (2025.12)", "테스트회사")]
        filtered, procedural = _filter_market_rows(raw, set())
        self.assertEqual(len(filtered), 0)
        self.assertEqual(procedural, 0)

    def test_filtered_elements_carry_qualified_objects(self):
        from dart_risk_mcp.server import _filter_market_rows
        raw = [self._row("주요사항보고서(유상증자결정)", "테스트회사")]
        filtered, _ = _filter_market_rows(raw, set())
        self.assertEqual(len(filtered), 1)
        _row, quals = filtered[0]
        self.assertEqual(quals[0].label, "유상증자(배정방식 미상)")
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_qualification_wiring.py -v -k "MarketScan"`
Expected: FAIL — `ImportError: cannot import name '_filter_market_rows'`

- [ ] **Step 3: 최소 구현**

`server.py`의 `search_market_disclosures` **바로 위**에 함수를 추가한다:

```python
def _filter_market_rows(
    raw: list[dict], target_keys: set
) -> "tuple[list[tuple[dict, list]], int]":
    """시장 스캔 행을 한정해 관찰 신호만 남긴다.

    (filtered, procedural_count)를 반환한다. filtered의 원소는
    (list.json 행, list[Qualified])이며 Qualified는 observed만 담는다.

    네트워크를 타지 않는 순수 함수로 분리해 합성 행으로 테스트할 수 있게 했다.
    preset 필터를 observed에만 거는 것이 핵심이다 — 강등된 신호가 preset을
    통과시키면 제외의 의미가 없다.
    """
    filtered: list[tuple[dict, list]] = []
    procedural_count = 0
    for d in raw:
        report_nm = d.get("report_nm", "")
        sigs = match_signals(report_nm)
        if not sigs:
            continue
        parsed = parse_report_name(report_nm)
        qual = qualify_signals(sigs, parsed, d)
        obs = [q for q in qual if q.tier == TIER_OBSERVED]
        if not obs:
            procedural_count += 1
            continue
        if target_keys and not any(q.key in target_keys for q in obs):
            continue
        filtered.append((d, obs))
    return filtered, procedural_count
```

`search_market_disclosures`의 2867-2875행(필터 루프)을 아래로 교체한다:

```python
    filtered, procedural_count = _filter_market_rows(raw, target_keys)
```

2881행 커버리지 문구를 교체한다:

```python
    coverage = (
        f"전체 {len(raw)}건 중 관찰 신호 {len(filtered)}건 "
        f"(표시 {len(shown)}건)"
    )
    if procedural_count:
        coverage += f" · 절차·사후 보고 {procedural_count}건 제외"
```

2903행의 라벨 조립을 `Qualified` 속성 접근으로 바꾼다:

```python
        sig_labels = ", ".join(q.label for q in sigs)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_qualification_wiring.py -v -k "MarketScan"`
Expected: PASS (5 passed)

Run: `python -m pytest tests/ -q --tb=line`
Expected: 실패 0건. 정확한 건수를 보고한다.

- [ ] **Step 5: 라이브 확인 (PowerShell)**

```powershell
python -c "
import sys; sys.path.insert(0,'.')
from dart_risk_mcp.server import search_market_disclosures
out = search_market_disclosures('all_risk', 7, 5)
print(out.splitlines()[1])
"
```

`전체 N건 중 관찰 신호 M건 (표시 5건) · 절차·사후 보고 K건 제외` 형식이 나와야 한다.
**실제 M·K 값을 보고한다** — 이 변경의 효과를 재는 수치다.

- [ ] **Step 6: 커밋**

```bash
git add dart_risk_mcp/server.py tests/test_qualification_wiring.py
git commit -m "feat(server): search_market_disclosures에 한정층 배선

필터 루프를 _filter_market_rows 순수 함수로 분리해 합성 행으로 테스트
가능하게 하고, preset 필터를 observed에만 건다 — 강등된 신호가 preset을
통과시키면 제외의 의미가 없다.

절차·사후 보고는 목록에서 빼되 헤더에 건수를 밝혀 숨기지 않는다.
max_results 칸이 정작 볼 것으로 채워지는 게 이 변경의 목적이다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## Task 4: 골든 재생성 + preset 대조 + 문서

**Files:**
- Regenerate: `tests/fixtures/sample_outputs/market_*.txt` (13개)
- Modify: `CLAUDE.md`

**Interfaces:**
- Consumes: Task 2~3의 배선
- Produces: 없음

- [ ] **Step 1: preset별 변화 측정 (재생성 전)**

재생성 전에 현재 골든의 건수를 기록해 둔다.

```powershell
Get-ChildItem tests/fixtures/sample_outputs/market_*.txt | ForEach-Object {
  $l = (Get-Content $_.FullName -TotalCount 2 -Encoding utf8)[1]
  "{0,-34} {1}" -f $_.Name, $l
}
```

출력을 보고서에 그대로 붙인다.

- [ ] **Step 2: 재생성**

```powershell
python scripts/regen_goldens.py --tools market
```

- [ ] **Step 3: preset별 대조**

```powershell
Get-ChildItem tests/fixtures/sample_outputs/market_*.txt | ForEach-Object {
  $l = (Get-Content $_.FullName -TotalCount 2 -Encoding utf8)[1]
  "{0,-34} {1}" -f $_.Name, $l
}
```

Step 1의 표와 나란히 놓아 **preset별로 관찰 신호가 몇 건 줄고 절차가 몇 건 제외됐는지** 보고한다.

`shareholder_change`(대량보유보고 다수)와 `inquiry`(해명 공시 다수)가 크게 줄 것으로 **예상**하지만, 예상은 예상으로 적고 실측값을 그대로 쓴다. 예상과 다르면 다른 대로 보고한다.

- [ ] **Step 4: hygiene + 전체 스위트**

```powershell
python -m pytest tests/test_golden_output_hygiene.py -q
python -m pytest tests/ -q --tb=line
```

Expected: hygiene 9 passed, 전체 실패 0건.

- [ ] **Step 5: CLAUDE.md 갱신**

- 도구 카탈로그의 `check_disclosure_risk`(2번) 항목에 접수번호 경로가 실제 제목·제출인을 복원한다는 점과 한정층 적용을 한 줄씩 추가
- 도구 카탈로그의 `search_market_disclosures`(14번) 항목에 절차·사후 보고 제외와 헤더 건수 표기를 추가
- "제목 수준 vs 내용 확인 감사표"의 한정층 행에 두 도구가 이제 포함된다는 사실 반영
- `dart_client.py` 핵심 함수 표에 `resolve_disclosure_row_from_rcept_no` 추가 (기존 `resolve_corp_code_from_rcept_no` 행 아래)
- 캐시 구조 표에 `_rcept_row_cache`(최대 50건, 10분) 추가

기존 톤·구조를 유지하고 재구성하지 않는다.

- [ ] **Step 6: 커밋**

```bash
git add tests/fixtures/sample_outputs/ CLAUDE.md
git commit -m "test: 시장 스캔 골든 재생성 + 문서 갱신

13개 preset 재생성. preset별 관찰/절차 건수 변화는 PR 본문에 실측 표로 첨부.
CLAUDE.md에 두 도구의 한정층 적용, resolve_disclosure_row_from_rcept_no,
_rcept_row_cache를 반영했다.

Co-Authored-By: Claude Opus 5 <noreply@anthropic.com>"
```

---

## 검증 로그

Task 1 Step 5, Task 3 Step 5, Task 4 Step 3의 실측값을 여기에 기록한다.

```
(구현 중 채운다 — 라이브 조회 결과, 시장 스캔 관찰/절차 건수, preset별 대조표)
```
