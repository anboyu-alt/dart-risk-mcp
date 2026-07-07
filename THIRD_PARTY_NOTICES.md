# Third-Party Notices

본 프로젝트(dart-risk-mcp, MIT License)는 아래 제3자 프로젝트의 코드·데이터를
이식·수정해 포함하고 있습니다.

---

## kreports-dart-mcp

- 저장소: https://github.com/capitalparser/kreports-dart-mcp
- 라이선스: Apache License 2.0 (http://www.apache.org/licenses/LICENSE-2.0)
- Copyright: capitalparser (kreports-dart-mcp contributors)

### 이식·수정된 구성 요소

| 본 프로젝트 위치 | 원본 파일 | 수정 내용 |
|---|---|---|
| `dart_risk_mcp/core/sector_policy.py` | `kreports/processor/sector_policy_map.py` | 업종별 회계정책 맵 이식, 표기 라벨 정리 |
| `dart_risk_mcp/core/notes.py` | `kreports/processor/note_parser.py` (NOTE_KEYWORDS) | 주석 카테고리 키워드 이식, 제목 태깅용으로 범용 키워드 제거·80자 게이트 추가 |
| `dart_risk_mcp/core/dart_client.py` 의 `_AUDITOR_ALIASES`/`_normalize_auditor` | `kreports/processor/audit_parser.py` | 감사인명 별칭 사전 이식 |
| `dart_risk_mcp/core/dart_client.py` 의 `_FS_ALIASES` 확장분 | `kreports/processor/account_map.py` | 계정과목 별칭 이식·확장 |
| `dart_risk_mcp/core/dart_client.py` 의 `compute_beneish_variables` | `kreports/judge/beneish.py` | 개별 변수 6종만 이식, M-Score 합산·임계 판정 제거, DEPI·TATA 제외, LVGI 총부채/총자산 기준으로 변형 |
| `dart_risk_mcp/core/dart_client.py` 의 발생액 비율·연결/별도 괴리·영업/순이익 괴리·전기 재작성·연속 적자 | `kreports/judge/flags.py`, `kreports/analysis/api.py` | 개념 이식, 로컬 DB 없이 DART API 직접 호출로 재구현, 임계값 라이브 재검증 후 재설계 |
| `dart_risk_mcp/core/dart_client.py` 의 `extract_rd_values`/`extract_rd_ratio_from_report`, `scan_note_titles` | `kreports/analysis/business_insights.py`, `kreports/processor/report_section_parser.py` | R&D 비율 regex·TITLE 스캔 방식 이식, 간격 제한·인접 소수점 규칙 등 정밀도 보강 |

위 구성 요소는 Apache License 2.0 조건에 따라 사용되며, 원본의 저작권 및
라이선스 고지는 본 문서와 각 파일 상단 주석으로 유지됩니다. 전체 라이선스
전문은 위 링크 또는 원본 저장소의 LICENSE 파일을 참조하세요.
