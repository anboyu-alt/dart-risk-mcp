# dart-risk-mcp

개인 작업용. DART 공시를 흐름으로 읽어 불공정거래 신호를 사실로 표기하는 MCP 서버.

## 하는 일

공시를 한 건씩 조회하는 대신 흐름과 연결로 읽는다. 공시 제목·원문·구조화 데이터에서
신호(CB·BW 발행, 최대주주 변경, 감사의견, 자금 유출 등)를 뽑고, 여러 신호가 겹치는
패턴과 그 뒤의 행위자(누가 돈을 댔나)를 사실로 적는다. 점수·등급은 매기지 않고
투자 판단도 하지 않는다.

- **회사 단위** — `analyze_company_risk`(신호·복합 패턴·CB 인수자 종합) · `build_event_timeline`(시간순 흐름) · `check_disclosure_anomaly`(정정·감사·조회공시 등 공시 구조 지표)
- **공시 한 건** — `check_disclosure_risk` · `get_major_decision`(양수도·합병의 상대방·규모·외부평가) · `get_mezzanine_terms`(CB·BW·EB 발행 조건) · `check_board_conflict`(특수관계 거래를 결의한 이사의 겸직)
- **자금·자본** — `track_capital_structure`(증자·감자·메자닌·희석) · `track_fund_usage`(조달 자금의 계획과 집행) · `track_debt_balance`(채무증권 잔액·만기) · `get_affiliate_investments`(타법인 출자)
- **사람** — `find_actor_overlap`(여러 회사의 임원 겸직·공통 인수자) · `track_insider_trading`(최대주주·임원 지분 변동) · `get_shareholder_info` · `get_executive_compensation` · `manage_watchlist` · `lookup_known_actor`
- **재무·감사** — `scan_financial_anomaly` · `track_turnover_trend` · `get_financial_summary` · `get_financial_statements_full` · `compare_financials` · `get_audit_opinion_history` · `get_audit_opinion_text` · `list_report_revisions` · `get_unlisted_financials`(비상장사 감사보고서 원문)
- **시장** — `search_market_disclosures`(시장 전체 공시를 신호 유형별로 스캔) · `track_market_reaction`(공시 전후 시세·거래량·시장경보)
- **원문** — `list_disclosures_by_stock`(공시 목록·접수번호) · `get_disclosure_document` · `list_disclosure_sections` · `view_disclosure` · `search_notes_in_report`(주석 본문 검색)
- **참고** — `get_company_info` · `find_risk_precedents`(신호 유형의 뜻과 금감원 적발 사례)

## 돌리기

```bash
pip install -e .
python -m dart_risk_mcp
```

```json
{
  "mcpServers": {
    "dart-risk": {
      "command": "python",
      "args": ["-m", "dart_risk_mcp"],
      "env": { "DART_API_KEY": "..." }
    }
  }
}
```

- `DART_API_KEY` 필수
- `KRX_API_KEY` · `KIS_APP_KEY` + `KIS_APP_SECRET` 선택 — 시세 대조용(KRX 먼저, 빈 날은 KIS)

## 메모

- 설계·실측 근거는 전부 `CLAUDE.md`
- 보류한 판단은 `docs/DEFERRED-DECISIONS.md`
- 뷰어 소스는 `docs/tool/`
- 테스트는 키 없이: `env -u DART_API_KEY python -m pytest tests/ -q`
- 골든 재생성: `python scripts/regen_goldens.py`
- 릴리스 순서: `CLAUDE.md` 「릴리스 정책」

MIT. 일부 로직은 kreports-dart-mcp(Apache 2.0)에서 이식 — `THIRD_PARTY_NOTICES.md`.
