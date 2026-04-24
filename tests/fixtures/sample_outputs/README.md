# sample_outputs — 골드 파일 회귀 테스트 기준선

**수집 일자:** 2026-04-24
**기준선 버전:** v0.7.4
**용도:** `tests/test_golden_output_hygiene.py`가 이 폴더의 모든 `.txt`를 스캔해 내부 flag 코드·카탈로그 영문 메타·영문 약어가 사용자 출력에 노출되지 않는지 기계적으로 검증한다.

## 파일 구성 (13개)

| 파일 | 생성 도구 | 입력 |
|---|---|---|
| `셀트리온_analyze.txt` · `제이스코홀딩스_analyze.txt` · `두산에너빌리티_analyze.txt` | `analyze_company_risk` | lookback_days=180 |
| `셀트리온_timeline.txt` · `제이스코홀딩스_timeline.txt` · `두산에너빌리티_timeline.txt` | `build_event_timeline` | lookback_days=365 |
| `셀트리온_scan_fs.txt` · `제이스코홀딩스_scan_fs.txt` · `두산에너빌리티_scan_fs.txt` | `scan_financial_anomaly` | year="", report_type="annual" |
| `셀트리온_list.txt` | `list_disclosures_by_stock` | stock_code=068270, lookback_days=90 |
| `셀트리온_disclosure_<rcept_no>.txt` | `check_disclosure_risk` | 셀트리온_list.txt 첫 접수번호 |
| `precedents_CB_3PCA_SHAREHOLDER.txt` | `find_risk_precedents` | signal_types=["CB_BW","3PCA","SHAREHOLDER"] |
| `actor_overlap.txt` | `find_actor_overlap` | 3개 기업 동시 |

## 재수집 절차

렌더러를 의미 있게 건드렸다면 이 폴더를 갱신해야 한다:

```bash
set DART_API_KEY=...
python tmp/v072_review/regen_fixtures.py
```

스크립트는 `tests/fixtures/sample_outputs/`에 직접 덮어쓴다. 재수집 후:

```bash
python -m pytest tests/test_golden_output_hygiene.py -v
git diff tests/fixtures/sample_outputs/
```

diff를 사람이 눈으로 확인해 의도한 변화인지 검증한 뒤 커밋.

## 수집 회사 선정 근거

- **셀트리온 (068270)** — 대형·안정 기준선, "깨끗한" 출력 회귀 감지용.
- **제이스코홀딩스 (033320)** — CB/BW 공시 다수, 반복 prose 억제 검증용.
- **두산에너빌리티 (034020)** — 중간 규모·중간 위험, 과도 경고 톤 회귀 감지용.
