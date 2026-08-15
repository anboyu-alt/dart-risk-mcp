# 신호 한정층 잔여 도구 배선 설계 — `check_disclosure_risk` · `search_market_disclosures`

작성일: 2026-08-16
대상: `dart_risk_mcp/server.py`, `dart_risk_mcp/core/dart_client.py`
선행: [2026-08-14 신호 한정층 설계](2026-08-14-signal-qualification-design.md) (PR #163 머지)

---

## 1. 배경

PR #163이 `core/qualifiers.py`에 한정층을 추가하고 `analyze_company_risk`·`build_event_timeline`·
공개 뷰어에 배선했다. **`check_disclosure_risk`와 `search_market_disclosures`에는 배선하지
않았다**(#163 설계 §12 비범위). 그 결과 두 도구는 여전히 제목 키워드 매칭만으로 판정한다.

### 1.1 실측 — `check_disclosure_risk`는 반대 방향으로 두 번 깨져 있다

```
$ check_disclosure_risk(report_name='주식등의대량보유상황보고서(일반)')
🎯 **최대주주변경**
최대주주가 바뀌는 공시입니다. 회사 지배구조의 핵심 사건으로…
```

제출인이 회사가 아닌 지분 보고서인데 최대주주변경으로 표기된다 — #163이 없애려던 그 오탐이다.

```
$ check_disclosure_risk(rcept_no='20260731000779')
공시: 접수번호 20260731000779              ← 자리표시자
이 공시에서 의심 신호가 탐지되지 않았습니다.    ← 항상 무신호
━━ 원문 요약 (첫 500자) ━━
주식등의 대량보유상황보고서(일반) …          ← 제목이 바로 아래 찍힌다
```

함수 132줄에 `report_nm`이 **0회** 등장한다. 접수번호로 부르면 실제 제목을 얻지 않고
`f"접수번호 {rcept_no}"`를 `match_signals`에 넘기므로 **어떤 신호도 매칭될 수 없다**.

### 1.2 `search_market_disclosures`

`list.json` 원본 행을 그대로 순회하므로 `flr_nm`·`corp_name`이 이미 손에 있다. 한정층을
붙이면 **R1~R5 전부** 적용 가능하다 — 회사 리포트와 동일한 판정 품질.

현재 `all_risk` 7일 스캔은 전체 3,721건 중 543건을 반환한다. `max_results` 기본 50칸을
절차·사후 보고가 잠식하고 있을 가능성이 높다(실측은 구현 후 §6).

---

## 2. 목표와 비목표

### 목표

1. 두 도구가 `analyze_company_risk`와 같은 판정에 도달한다.
2. `check_disclosure_risk`의 접수번호 경로가 실제 제목을 알게 되어 신호 매칭이 살아난다.
3. 실패 시 **현재 동작으로 조용히 퇴화**한다 — 지금보다 나빠지지 않는다.

### 비목표

- `_AMENDMENT_RE`·`match_signals`·`SIGNAL_TYPES`·`taxonomy.py` 수정 (#163과 동일)
- `core/qualifiers.py`의 규칙 변경 — 그대로 쓴다
- `docs/tool/se/app.js` 반영
- 날짜 불일치 0.7% 건의 해결 (§4.3 알려진 한계)

---

## 3. 설계 착수 전 정정된 전제 (실측 2026-08-16)

브레인스토밍 중 제시했던 전제 두 개가 **실측으로 틀린 것이 확인**됐다. 설계는 정정된
사실 위에 세운다.

### 3.1 "추가 API 호출 없음" — 거짓

`resolve_corp_code_from_rcept_no`는 `pblntf_ty="B"`(주요사항보고)로 좁혀 조회한다.
지분공시(D)·거래소공시(H)는 애초에 검색 범위 밖이다.

```
resolve_corp_code_from_rcept_no('20260731000779')  → ''   (대량보유보고, 못 찾음)
```

필터를 풀면 하루치가 커진다. 20260731 실측:

| pblntf_ty | 건수 | 페이지 |
|---|---:|---:|
| (없음) | 1,159 | 12 |
| B 주요사항 | 54 | 1 |
| D 지분 | 217 | 3 |

### 3.2 "접수번호 앞 8자리 = 접수일" — 대체로 참, 예외 존재

20260803 **전수 610건 중 4건(0.7%)** 이 불일치했다.

```
20260731000816 → rcept_dt=20260803  본느  주요사항보고서(전환사채권발행결정)
20260731000813 → rcept_dt=20260803  본느  주요사항보고서(전환사채권발행결정)
20260731000812 → rcept_dt=20260803  본느  주요사항보고서(유상증자결정)
20260731000814 → rcept_dt=20260803  제이월드라이팅  감사보고서 (2025.12)
```

**기존 `resolve_corp_code_from_rcept_no`도 이 0.7%에서 구조적으로 실패한다** — 신규 설계만의
문제가 아니라 이미 배포된 코드의 잠복 결함이다. 이번 범위에서는 고치지 않고 기록만 한다.

> 표본 주의: 처음에 3페이지씩 900건을 봤을 때는 불일치 0건이었다. 알려진 반례가 7페이지에
> 있었기 때문이다. 위 0.7%는 **하루치 전수**를 훑어 다시 잰 값이다.

### 3.3 원문에서 제목 추출 — 불가

`fetch_document_text`의 첫 줄을 제목으로 쓰는 우회로를 검토했으나, 여러 공시 유형(펀드
증권신고서·투자설명서 등)에서 빈 문자열을 반환해 채택하지 않았다.

---

## 4. `check_disclosure_risk` 설계

### 4.1 행 조회 — 신규 순수 조회 함수

`dart_client.py`에 추가한다.

```python
def resolve_disclosure_row_from_rcept_no(
    rcept_no: str, api_key: str, max_pages: int = 12
) -> "dict | None":
    """접수번호 → list.json 행 전체. 실패 시 None."""
```

- `pblntf_ty`를 **보내지 않는다** — 유형 무관 조회 (§3.1).
- `rcept_no[:8]`을 `bgn_de`/`end_de`로 쓴다.
- `total_page`까지, `max_pages`(12) 상한으로 페이징. 매칭 즉시 종료.
- 비정상 `status`·네트워크 오류는 즉시 `None`.
- 전용 캐시 `_rcept_row_cache`(10분 TTL, 최대 50건) — 기존 `_rcept_corp_cache`와 분리한다.
  두 캐시는 값의 타입이 다르고(`str` vs `dict`) 조회 범위도 다르므로 공유하면
  한쪽 미스가 다른 쪽을 오염시킨다.

**기존 `resolve_corp_code_from_rcept_no`는 시그니처·동작·캐시를 그대로 둔다.** 감싸지도
않는다 — 조회 범위(`pblntf_ty="B"`)가 달라 통합하면 DS005 경로의 호출 예산이 4배가 된다.
두 함수는 목적이 다른 별개 조회다.

### 4.2 배선

```
rcept_no 있음 → resolve_disclosure_row_from_rcept_no
                 ├─ 성공: title = row["report_nm"], filing = row
                 │        → match_signals(title) + qualify_signals(sigs, parsed, filing)
                 │        → R1~R5 전부 적용
                 └─ 실패: 현재 동작 그대로 (자리표시자 title, filing=None)

report_name만  → title = report_name, filing = None
                 → R1 건너뜀, R1b~R5 적용
```

`filing=None`은 `qualify_signals`의 기존 계약이다 — 새 분기를 만들지 않는다.

### 4.3 알려진 한계

`rcept_dt`가 `rcept_no[:8]`과 다른 0.7% 건은 행을 찾지 못해 현재 동작으로 퇴화한다.
사용자에게는 지금과 같은 출력이므로 **회귀가 아니다**. 출력에 실패 사실을 별도 표기하지
않는다 — 자리표시자 제목이 이미 그 상태를 드러낸다.

### 4.4 출력

단건 도구이므로 #163의 "두 층" 절 구분은 과하다. **한 건의 판정과 사유만** 보인다.

```
📋 **공시 리스크 분석**
공시: 주식등의대량보유상황보고서(일반)
제출인: 삼성물산

⚪ **절차·사후 보고**
지분 보유·변동 신고서입니다 (회사의 사건 공시가 아님)
→ 제목에 [최대주주변경] 신호가 매칭되지만, 회사가 낸 사건 공시가 아닙니다.
```

- 관찰 신호면 기존 `🎯` 블록을 **그대로** 쓴다(라벨은 `qualify_signals`가 보정한 값).
- `제출인:` 줄은 행 조회에 성공했을 때만 표기한다.
- `note`가 있으면 `※` 줄로 덧붙인다 — `analyze_company_risk`와 동일 관례.

---

## 5. `search_market_disclosures` 설계

### 5.1 배선 — 필터 루프 한 곳

```python
for d in raw:
    report_nm = d.get("report_nm", "")
    sigs = match_signals(report_nm)
    if not sigs:
        continue
    parsed = parse_report_name(report_nm)
    qual = qualify_signals(sigs, parsed, d)          # d가 곧 list.json 행
    obs = [q for q in qual if q.tier == TIER_OBSERVED]
    if not obs:
        procedural_count += 1
        continue
    if target_keys and not any(q.key in target_keys for q in obs):
        continue
    filtered.append((d, obs))
```

**preset 필터는 `observed`에만 건다.** 강등된 신호가 preset을 통과시키면 제외의 의미가 없다.

`filtered`의 두 번째 원소가 `list[dict]`(원본 신호)에서 `list[Qualified]`로 바뀐다. 렌더가
`s["key"]`·`s["label"]`로 접근하므로 `q.key`·`q.label`로 함께 고친다.

### 5.2 출력

헤더 한 줄만 바뀐다.

```
이전:  전체 3721건 중 신호 일치 543건 (표시 50건)
이후:  전체 3721건 중 관찰 신호 209건 (표시 50건) · 절차·사후 보고 334건 제외
```

숫자는 형식 예시다. 실제 비율은 §6에서 실측한다.

절차 건은 목록에 표시하지 않는다 — 스캔 도구의 목적이 "볼 것을 좁히기"이고, `max_results`
50칸이 정작 볼 것으로 채워지는 게 이 변경의 핵심이다. 다만 **건수를 헤더에 밝혀 숨기지
않는다**.

### 5.3 라벨 보정

`🔖 [제3자배정유상증자]`가 제목에 근거 없으면 `🔖 [유상증자(배정방식 미상)]`로 바뀐다.
`qualify_signals`가 이미 하는 일이라 별도 작업이 없다.

---

## 6. 검증

### 6.1 단위 테스트 (`tests/test_qualification_wiring.py` 확장)

```
check_disclosure_risk(report_name='주식등의대량보유상황보고서(일반)')
    → 절차·사후 보고, 사유에 "지분"

check_disclosure_risk(report_name='주요사항보고서(전환사채권발행결정)')
    → 관찰 신호 유지                                    ← 과잉 강등 방지

check_disclosure_risk(report_name='조회공시요구(풍문또는보도)(감사의견비적정설)')
    → 관찰 신호 유지 (filing 없어 R1 미적용)              ← 과잉 강등 방지

시장 스캔 필터 루프 (합성 행 입력, 네트워크 없음)
    대량보유보고(제출인 다름) 3 + CB발행 2
        → filtered 2건, procedural_count 3
    강등된 신호만 preset 대상인 행
        → preset 통과하지 않음                          ← preset 누수 방지
```

시장 스캔 필터는 네트워크를 타므로 **순수 필터 부분을 함수로 분리해** 합성 행 리스트로
테스트한다. 분리 자체가 테스트 가능성을 위한 것이며, 렌더는 건드리지 않는다.

### 6.2 골든

`market_*.txt` 13개 preset 전부 재생성 대상. **재생성 후 preset별 diff를 대조해 보고한다** —
어떤 preset이 얼마나 줄었는지가 이 변경의 실측 근거다.

`shareholder_change`(대량보유보고 다수)·`inquiry`(해명 공시 다수)가 크게 줄 것으로 **예상**
하지만, 예상은 예상으로만 적고 실측으로 확인한다.

### 6.3 라이브 확인

```
check_disclosure_risk(rcept_no='20260731000779')   대량보유(D) — 3페이지째 발견 실측
check_disclosure_risk(rcept_no='20260731901330')   거래소 담보제공(H) — 2페이지째 발견 실측
check_disclosure_risk(rcept_no='20260731000816')   날짜 불일치 건 — 퇴화 확인(회귀 아님)
```

---

## 7. 오류 처리

| 상황 | 동작 |
|---|---|
| 행 조회 실패 | 현재 동작으로 퇴화 — 자리표시자 제목, `filing=None` |
| `flr_nm` 없음 | R1 건너뛰고 R1b~R5 |
| `qualify_signals` 예외 | 발생하지 않음 — 판단 불가 시 `observed`가 계약 |
| 시장 스캔에서 행에 `corp_name` 없음 | R1 건너뜀 (`filing` 키 누락 허용이 기존 계약) |

두 도구 모두 **실패 시 기존 동작으로 수렴**한다. 새 코드가 죽어도 도구가 죽지 않는다.

---

## 8. 이번 범위 밖

- `rcept_dt` 불일치 0.7% 건의 해결 (§3.2·§4.3)
- `resolve_corp_code_from_rcept_no`의 같은 잠복 결함 수정
- `docs/tool/se/app.js` 한정층 반영
- 뷰어(`docs/tool/index.html`)는 이미 #163에서 배선 완료 — 변경 없음
