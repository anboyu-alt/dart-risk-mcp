# Changelog

[Keep a Changelog](https://keepachangelog.com/ko/1.1.0/) 형식 준수. 버전은 [SemVer](https://semver.org/lang/ko/).

## Stability / Deprecation Policy (v1.0 GA부터 발효)

본 정책은 v1.0.0 GA에서 발효합니다. 마이너 릴리스(1.x)는 사용자에게 노출되는 모든 표면을 stable contract로 간주하며, 다음 규칙을 따릅니다.

### Stable contract 표면

1. **MCP 도구 시그니처** — 25개 도구의 함수명·파라미터명·기본값·반환 타입.
2. **사용자 출력 형식** — 첫 줄 패턴, 핵심 헤더, 한국어 표기 원칙(점수·등급·이모지·내부 flag·영문 약어 노출 금지). `tests/test_golden_output_hygiene.py` 9종 검증으로 기계적으로 보장.
3. **신호 키 카탈로그** — `SIGNAL_TYPES[*].key`, `SIGNAL_KEY_TO_TAXONOMY` 매핑, taxonomy ID(N.M) 체계.
4. **CLI 인터페이스** — `python -m dart_risk_mcp` 진입점·환경변수 `DART_API_KEY`·`scripts/regen_goldens.py` 인자.

### 변경 분류 + 최소 절차

| 변경 유형 | SemVer 영향 | 절차 |
|----------|:-:|------|
| 도구 시그니처 변경(파라미터 추가·이름 변경·기본값 변경) | minor | 최소 **1 minor 버전 동안 별칭(alias) 유지** + CHANGELOG `### Deprecated` 섹션 표기. 별칭 제거는 다음 minor에서. |
| 도구 제거 | major | CHANGELOG `### Removed` + 직전 minor에서 `### Deprecated` 1회 이상 공지 선행. |
| 사용자 출력 형식 변경(첫 줄·핵심 헤더·표기 원칙) | **major 또는 minor + 명시 공지** | hygiene 9종 회귀가 깨지는 변경은 stable output contract 위반. 의도적 변경 시 CHANGELOG `### Output Contract Change` 섹션으로 명시 + 골드 파일 일괄 갱신. |
| 신호 키 추가(`SIGNAL_TYPES`에 새 key) | minor | contract 변경 아님(추가 정보). CHANGELOG `### Added`. |
| 신호 키 제거 또는 라벨 변경 | minor | CHANGELOG `### Removed` 또는 `### Changed` + 직전 minor에서 `### Deprecated` 공지 권장. |
| MCP 도구 신규 추가 | minor | CHANGELOG `### Added`. **단, 도구 인플레이션 회피 — 흡수 우선**(v0.9.0 `analyze_company_risk` 부실 후속 흡수 사례 참고). |
| 내부 헬퍼·렌더러·캐시 구조 변경 | patch / minor | 출력 형식이 깨지지 않으면 contract 영향 없음. hygiene PASS 시 자유. |

### 비범위는 영구 비범위

[README.md](README.md) "이 도구가 하지 않는 것" 7개 항목은 v1.0 이후 어떤 마이너 릴리스에서도 도입하지 않습니다. 우회 PR은 거절됩니다.

---

## [1.18.3] — 2026-08-23

> ⚠ #206(1.18.1)·#207(1.18.2) 뒤에 머지되는 것을 전제로 번호를 매겼다.

**뷰어의 원문 확인 이식이 절반이었다.**

v1.14.0에서 자산 처분(5.3)은 독립 블록이 됐지만, **금전대여·채무보증·담보제공(5.7)은 여전히 `loadCapitalBackflowGate` 안에만** 있었다. 그래서 경영권 변경 공시가 없어 `capital_backflow` 패턴이 성립하지 않는 회사에서는 "누구에게 나갔나"가 통째로 사라졌다 — core가 v1.13.4에서 이미 고친 문제(확인된 상대방은 패턴 주장이 아니라 사실이므로 게이트와 무관하게 낸다)가 뷰어에 절반만 반영돼 있었다.

### Fixed

- `loadAssetTransferCore`가 `ASSET_TRANSFER`와 `FUND_OUTFLOW`를 함께 후보로 삼고, **제목으로 파서를 가른다** — 자산 처분은 `parseAssetDisposalDetail`(「처분금액/양도가액」), 금전대여·담보는 `parseOutflowDetail`(「대여금액/담보설정금액」). 원문 서식이 다르다.
- 패널 라벨을 「OUTFLOW — 자금유출·자산이전 상대방 확인」으로.
- 관계 원문과 분류 라벨이 같을 때 `(종속회사 — 종속회사)`로 중복 표기되던 것을 하나로 접었다.

브라우저 확인: 금전대여(종속회사)·자산양도(계열회사) 두 계열이 한 블록에 날짜순으로 렌더된다.

---

## [1.18.2] — 2026-08-23

> ⚠ 이 항목은 #206(1.18.1) 뒤에 머지되는 것을 전제로 번호를 매겼다.

**기업별 다년 조회도 절단되고 있었다.** 시장 스캔(#206)과 같은 종류인데 다른 층이다.

`_resolve_lookback`을 쓰는 도구는 창에 비례해 상한을 올렸지만(years×10), 그 함수를 안 쓰는 세 경로가 기본값 10페이지(1,000건)를 쓰고 있었다. 로그에 이렇게 남았다.

```
공시목록 1000건 초과 기업 (corp_code=00126380, total=3547) — 일부 누락
```

삼성전자 5년 공시 3,547건 중 1,000건만 보고 결과를 냈다는 뜻이다.

### Fixed

`find_actor_overlap` · `track_capital_structure` · `get_audit_opinion_history`의 공시 조회 상한을 창에 비례하게(years×10) 맞췄다. 라이브: 삼성전자 5년 `track_capital_structure` 52.6초 · **절단 경고 없음**.

### 왜 완전 제거는 안 하나

1년 코퍼스(법인 45,426개) 기준 분포가 극단적으로 치우쳐 있다.

| | 건/년 | 5년 추정 |
|---|---:|---:|
| p50 | 1 | 5건 |
| p90 | 8 | 40건 |
| p99 | 77 | 385건 |
| 최다 | 4,143 | 20,715건(208페이지) |

years×10 상한을 넘는 법인은 **0.05%**이고 대부분 펀드 공시를 쏟아내는 자산운용사다. 상위 0.05%를 위해 모든 조회를 208페이지로 늘리는 것은 대기 예산에 맞지 않는다. 남는 절단은 기존대로 로그 경고로 남는다.
## [1.18.1] — 2026-08-23

**시장 스캔이 조용히 절단되고 있었다.** v1.10.2가 고쳤다는 그 문제가 다른 층에 남아 있었다.

### Measured

1년 코퍼스(270,882건 · 244영업일)로 재니 상한이 분포를 못 덮었다.

| 상한 | 초과 |
|---|---|
| 2일 묶음 1,000건 | **122개 중 112개 (92%)** |
| 1일 재분할 1,500건 | 244일 중 45일 (18%) |

하루 분포는 중앙값 774 · p90 2,224 · **최대 6,006**건이다. 즉 1일 상한이 p90보다 낮았다.

### Fixed

- **하루 청크 직행.** 2일 묶음의 92%가 상한에 닿아 거의 항상 재분할됐으므로, 2일 청크는 헛조회를 한 번 더 하는 것일 뿐이었다.
- **하루 상한 15 → 70페이지**(1,500 → 7,000건). 244영업일 전부를 덮는다.

라이브 검증(30일 창): 전체 **19,524건** 스캔 · **절단 0** · 독립 수집한 1년 코퍼스의 같은 구간과 **정확히 일치**. 시간도 218.9초 → **168.7초**로 줄었다 — 절단을 고쳤는데 빨라졌다(헛조회가 사라져서).

### Added — 시점 지정

`from_date`/`to_date`. `analyze_company_risk`와 같은 계약(표기 3종 허용, 형식 오류는 ❌ 안내, 90일 초과 구간은 거절).

### Added — 대기 예산 분기

창이 10일을 넘으면 **바로 실행하지 않는다**. 예상 소요와 좁히는 법을 먼저 안내하고 `confirm_long=True`를 받아 실행한다.

```
⏳ **최근 30일 스캔은 약 3분 0초 걸립니다**
그대로 진행하려면:
  search_market_disclosures("all_risk", days=30, confirm_long=True)
더 빨리 보려면 구간을 좁히세요:
  search_market_disclosures("all_risk", days=10)  — 약 60초
  search_market_disclosures("all_risk", from_date="2026-03-01", to_date="2026-03-31")
```

11분을 기다리게 해놓고 결과가 절단돼 있는 것보다, 무엇을 기다리는지 먼저 아는 편이 낫다. 경계 10일은 실측(7일 17.7초 · 14일 107.5초) 사이에서 여유를 둔 값이다.

### Unchanged

- 7일 기본 조회는 시간·결과 모두 불변(시장 골든 diff 0 — 7일 창은 원래 절단되지 않았다).
- 점수·등급 없음(v0.8.5). hygiene 9/9 PASS.
## [1.18.0] — 2026-08-23

**넓게 볼 땐 얕게, 좁게 볼 땐 깊게.** 그리고 최근이 아닌 **임의 시점**을 조회할 수 있게 했다.

### 왜

창이 1년이든 5년이든 원문 확인은 최근 3건으로 고정이었다. 5년을 조회해도 3년 전 사건은 제목만 보였다 — 깊이가 창을 따라가지 않으니 넓은 조회는 "많이 보는데 얕게 보는" 상태였다.

그리고 조회는 늘 오늘이 끝점이었다. "2024년 상반기에 무슨 일이 있었나"를 물을 수 없었다.

### Added — 탐색 깊이 분리

창이 400일을 넘으면 **지도 모드**가 된다.

| | 싣는 것 |
|---|---|
| 좁은 창(≤400일) | 신호 · 패턴 · 타임라인 · **원문 사실 블록** |
| 넓은 창(>400일) | 신호 · 패턴 · 타임라인 |

지도에는 「🔎 더 깊게 보려면」 안내가 붙어, **관찰된 최근 신호의 달**을 `from_date` 예시로 제시한다. 사용자는 지도에서 구간을 고른 뒤 그 구간을 깊게 본다.

⚠ **패턴 게이트**(`capital_backflow`·`fund_diversion_chain`)의 원문 확인은 얕은 모드에서도 유지한다 — 그건 표시용 사실이 아니라 패턴을 띄울지의 판정 입력이라, 빼면 지도에서 패턴 자체가 사라진다.

### Added — 시점 지정 조회

`analyze_company_risk` · `build_event_timeline` · `list_disclosures_by_stock`에 `from_date`/`to_date`.

- `"2024-01-01"` · `"20240101"` · `"2024.01.01"` 모두 허용(`normalize_date8`)
- 주면 `lookback_years`를 무시한다
- 시작일만 주면 오늘까지, 종료일만 주면 **그날 기준 1년**
- 형식 오류·역순 구간은 조용히 무시하지 않고 `❌` 안내로 반환한다

하부 `fetch_company_disclosures`가 `bgn_de`/`end_de`를 받도록 확장됐다. 옛 호출자는 그대로 "오늘 기준 N일 전부터"로 동작한다.

### 라이브 확인 (제이스코홀딩스)

| 호출 | 시간 | 원문 블록 | 안내 |
|---|---:|---|---|
| 1년(기본) | 32.9초 | 있음 | — |
| 5년 | 20.1초 | **없음** | 있음 |
| `from_date="2025-01-01", to_date="2025-12-31"` | **8.2초** | 있음 | — |
| `from_date="2025-13-99"` | — | ❌ 형식 안내 | — |

구간을 좁히면 1년 기본 조회보다도 빠르다.

### Unchanged

- 나머지 도구는 연도 단위 API를 쓰거나(재무·감사·지분) 성격이 달라 시점 지정 대상이 아니다.
- 점수·등급 없음(v0.8.5). hygiene 9/9 PASS.

---

## [1.17.1] — 2026-08-22

**동시성을 4 → 2로 낮췄다.** 속도가 아니라 **대기 예산**으로 정한다는 기준이 정해졌다 — 이 도구의 허용 대기는 1분이다.

순차로도 27초라 예산 안이므로 병렬화는 애초에 필수가 아니었다. 반면 동시 요청은 DART 분당 스로틀(status 020) 조건을 만들고, 그건 이 레포가 SE-4h에서 이미 겪은 사고 유형이다. **예산에 여유가 있는데 외부 API 부하를 늘릴 이유가 없다.**

| 동시성 | 무거운 날(46p) | 순간 부하 |
|---|---:|---|
| 순차 | 27초 | 가장 낮음 |
| **2 (현재)** | **13.8초** | 절반 |
| 4 (v1.17.0) | 8.0초 | — |

셋 다 예산 안이라 가장 부하가 낮은 쪽 중 실용적인 값을 골랐다. 최악(전 페이지 순회, 못 찾는 경우)도 라이브 21.9초로 예산의 3분의 1이다.

스로틀 방어(`_ROW_TRANSIENT_STATUSES`)는 그대로 둔다 — 동시 2도 버스트이긴 하다.

`tests/test_rcept_row_lookup.py::TestConcurrencyBudget`이 이 판단을 고정한다. 동시성을 다시 올리려면 대기 예산부터 확인하게 된다.

---

## [1.17.0] — 2026-08-22

**접수번호만으로 조회할 때, "신호가 없다"와 "확인하지 못했다"가 같은 화면으로 보였다.**

`check_disclosure_risk(rcept_no=...)`는 list.json을 훑어 제목·제출인을 복원한다. 그 조회가 실패하면 자리표시자 제목으로 퇴화하며 "이 공시에서 의심 신호가 탐지되지 않았습니다"를 냈다 — 실패 이유를 구분하지 않았기 때문이다.

### Measured

1년 코퍼스(270,882건·244영업일)로 하루 공시량 분포를 재니 옛 상한이 얼마나 좁았는지 드러났다.

| 하루 공시량 | |
|---|---|
| 중앙값 | 774건 |
| p90 | 2,224건 |
| p99 | 4,600건 |
| 최대 | 6,006건 (3/31 사업보고서 마감) |

| 상한 | 커버 영업일 |
|---|---|
| 1,200건(12p) — 옛 값 | 188/244일 (**77.0%**) |
| 5,000건(50p) — 새 값 | 242/244일 (99.2%) |

**영업일의 23%에서 실패**하고 있었고, 하필 공시가 몰리는 결산·감사 시즌에 집중됐다.

### Fixed

- **상한 12 → 50페이지.** 대부분의 날은 비용이 늘지 않는다 — 중앙값 774건(8페이지)이라 `total_page`로 자연 종료하기 때문이다. 비용이 느는 것은 지금 실패하던 23%뿐이다.
- **실패 이유를 구분한다.** `resolve_disclosure_row_with_status`가 `ROW_FOUND`/`ROW_NOT_FOUND`/`ROW_SCAN_LIMIT`/`ROW_ERROR`를 함께 돌려준다. 도구는 각각 다른 안내를 낸다 — 상한 초과·오류일 때는 "**신호가 없다는 뜻이 아닙니다**"를 명시하고 제목 동반 재호출을 안내한다.
- **DART `status=013`(데이터 없음, 휴장일 등)을 오류가 아니라 부재로 분류.** 옛 경로는 "일시적일 수 있으니 재시도하세요"라고 잘못 안내했을 것이다.

### Performance

페이지 2부터 **동시 4개 배치**로 받는다. 무거운 날 46페이지를 순차로 돌면 API 응답만 0.6초×46 ≈ 27초라 도구 호출로 쓸 수 없었다.

| | 라이브 실측 |
|---|---|
| 무거운 날(46p) | 26.5초 → **8.0초** |
| 보통 날 | 1.4초 |
| 캐시 재조회 | 0.000초 |

list.json은 **접수번호 순이 아니라**(20260331 실측: page 1에 …000015와 …604216이 함께 온다) 전수를 훑어야 해 위치를 추정해 건너뛸 수 없다. `page_count`도 100이 상한이다(200·500을 줘도 100만 온다 — 실측).

동시성 4는 코퍼스 수집기가 0.1초 간격(초당 10회)으로 장시간 돌려 온 부하와 비슷한 수준으로 잡았다.

### Guarded

버스트는 **DART 분당 스로틀(status 020) 조건을 만든다**. DART는 이 실패를 HTTP 상태가 아니라 바디의 `status` 필드로 알려 `_retry`(예외와 429/5xx만 재시도)가 절대 잡지 못한다. 같은 종류의 사고가 이미 기록돼 있다 — fnlttSinglIndx 12콜 버스트에서 한 호출이 020으로 죽어 그 해가 통째로 빠진 채 '추이'가 그려졌다(SE-4h). 여기서도 `_ROW_TRANSIENT_STATUSES`(020·800)로 3회까지 재시도한다(1s→2s). 013(데이터 없음)·900(키 오류)은 재시도해도 같은 답이라 즉시 반환한다.

라이브 버스트 4연속(약 140회 호출)에서는 020이 관측되지 않았다 — 방어는 관측되지 않은 위험에 대한 것이며, 걸렸을 때 조회가 통째로 죽지 않게 한다.

### Changed

- 부재·상한 도달도 센티널로 캐시한다(재조회가 50회를 다시 쓰지 않도록). 네트워크 오류·비정상 status는 일시적일 수 있어 캐시하지 않는다.
- `resolve_disclosure_row_from_rcept_no`는 하위 호환 래퍼로 남는다(행만 반환).

### Unchanged

- 남은 0.8%(2일 — 6,000건 넘는 날)는 상한을 더 올리는 대신 `ROW_SCAN_LIMIT`으로 정직하게 표기한다.
- 접수번호 앞 8자리가 접수일과 다른 공시(실측 0.7%)는 여전히 찾지 못한다 — 이제 `ROW_NOT_FOUND`로 구분된다.

---

## [1.16.0] — 2026-08-22

**감사인이 의견을 거절한 회사에 감사의견 신호가 붙지 않고 있었다.** 1년 코퍼스(#200)로 계절 표현을 판정할 수 있게 되면서 확인한 것이다.

### Fixed

- **`AUDIT` 어순 오류.** 키워드는 "부적정의견"인데 DART 실제 표기는 「반기검토(감사)**의견부적정**등사실확인…」(1년 47건)이다. 이 47건은 제목의 '자본잠식' 덕에 `INSOLVENCY`로만 잡히고 감사의견 신호는 붙지 않았다. **15건 → 62건.** 라이브: 한국유니온제약 20260814900829. 골든에서 제이스코홀딩스의 `audit_insider_dump` 패턴이 함께 표면화됐다.
- **띄어쓰기 때문에 새던 48건.** taxonomy 4.3이 명시한 "filed late"인데 붙여쓴 "제출지연"만 있어 8건만 잡았다 — 실제 표기는 「제출 지연」 42 · 「제출지연」 8 · 「지연 제출」 5. 「주권매매거래정지(사업보고서 **미제출**)」도 무신호였다(상장폐지 사유의 직접 신호).
- **해설 4종이 실제 발화와 어긋났다.** 그중 둘은 **서로 뒤바뀌어** 있었다 — `INSOLVENCY`가 "회생·파산 절차"를, `GOING_CONCERN`이 "계속기업 가정 불확실성"을 설명했는데, 실제로는 전자가 자본잠식·부도, 후자가 회생·파산절차를 잡는다. `AUDIT`은 제거된 "감사인 교체"를, `DISCLOSURE_VIOL`은 제거된 "공시 철회·발행 철회"를 설명하고 있었다.
- **테스트가 실제와 다른 입력으로 통과했다.** `test_disclosure_viol_keyword.py`의 "실제 관측 제목" 픽스처 3개가 **공백을 지운 형태**여서(「주권매매거래정지(사업보고서미제출)」 vs 실제 「주권매매거래정지              (사업보고서 미제출)」), 키워드가 실전 1년 0건인 것을 못 잡았다.

### Removed

1년 전수 270,882건에서 0건인 **dead keyword 15종**. 공백 변형까지 정규식으로 재확인했다(`감사인\s*(교체|변경|지정)`·`감사범위`·`계속기업` 모두 0건).

| 신호 | 제거 |
|---|---|
| `AUDIT` | 한정의견 · 부적정의견 · 계속기업불확실성 · 감사범위제한 · 감사인교체 |
| `GOING_CONCERN` | 계속기업가정불확실 · 계속기업불확실 |
| `INSOLVENCY` | 어음부도 · 의도적부도 |
| `DISCLOSURE_VIOL` | 공시의무위반 · 공시누락 · 중요정보누락 · 발행철회 · 공시철회 · 보고서미제출 |

**제거로 잃는 제목은 0건**(코퍼스 전수 확인, `TestNoLoss`가 고정).

⚠ `"공시의무"`가 0건인 게 아니다 — 185건 있는데 전부 「수시공시의무관련사항(공정공시)」라는 정상 공시이고, 붙여쓴 "공시의무위반"이 0건이다.

### Added

`"의견부적정"` · `"제출 지연"` · `"지연 제출"` · `"보고서 미제출"`. 넷 다 1년 전수에서 오탐 0.

⚠ `"지연"` 단독은 쓸 수 없다 — 펀드명 「글로벌클린에너**지연**금증권자투자신탁」이 걸린다(1년 5건). `WATCH_ISSUE`가 `"미달"`을 못 쓰는 것과 같은 함정이다.

### Unchanged

- 점수·등급 없음(v0.8.5). hygiene 9/9 PASS.
- `"파산절차"`는 단독기여 0이지만 남겼다(7건 전부 「회생절차및파산절차」 형태) — 0건이 아니라 중복이고, 단독 표기가 나오면 잡아야 한다.
- 「감사의견 거절 관련 상장폐지 절차 **미진행**」 17건은 의도적으로 추가하지 않았다 — 사유가 해소됐다는 안내라 감사의견 신호로 올리면 뜻이 뒤집힌다.

### Known limits

`GOING_CONCERN`의 라벨("계속기업불확실")과 실제 발화 경로(회생·파산절차)의 거리는 그대로다. '계속기업'은 DART 제목에 아예 쓰이지 않지만(1년 0건) 회생절차 개시신청이 계속기업 의문의 후속 단계라 taxonomy 8.4에는 맞는다. 라벨 변경은 사용자 노출 문자열이라 별도 판단.

---

## [1.15.0] — 2026-08-22

**severity가 겸직하던 두 질문을 분리했다.** v1.14.0은 뷰어 배지 뒤집힘을 예외 목록으로 우회했는데, 진짜 원인은 taxonomy severity가 "얼마나 심각한가"와 "점수를 매기느냐"에 동시에 답하도록 쓰여 온 것이었다(OBSERVATION = base_score 0 = 사실 표기 전용).

그 겸직 때문에 배지가 **두 방향으로** 깨졌다.

- 무점수로 설계된 신호가 낮은 우선순위로 내려앉았다 — 「상장폐지 결정·정리매매 개시」가 '참고'.
- 반대로 severity가 HIGH라는 이유만으로 양면적 신호에 배지가 붙었다 — `RELATED_PARTY`·`ASSET_TRANSFER`는 `AMBIGUOUS_SIGNAL_KEYS`에 들어 헤드라인 승격이 막혀 있는데 배지는 '주의'로 나갔다(자기모순).

### Added

- `core/signals.py`에 `observation_priority(key)` → `first` / `watch` / `context`. 기준은 **"그 공시 한 건만 보고 무엇을 알 수 있는가"**다.
  - `first` — 회사의 존속·상장 자격·회계 신뢰성이 걸린 사실. 다른 신호가 없어도 그 자체로 읽을 값이 있다(퇴출 절차·부실 진입·감사의견·횡령).
  - `watch` — 지배구조·자본·자금 흐름의 사건. 방향이 한쪽이고 조합·시계열로 의미가 커진다. **명시하지 않은 신호의 기본값**이라 새 신호가 조용히 first로 승격되지 않는다.
  - `context` — 제목만으로 정상/이상이 갈리지 않아 원문 확인이 필요하다(감사표의 확인 계층 보유 신호와 대체로 일치).
- `tests/test_observation_priority.py` — 축의 계약과 변별력을 고정.

### Changed

- `signals-data.json`의 `caution` 불리언 → `priority` 문자열로 **대체**(뷰어가 유일한 소비처였다).
- 뷰어 배지 3종 — 「먼저」(amber 외곽선) · 「참고」(회색, 관찰 신호가 **전부** context일 때만) · watch는 기존 `● 신호` 유지. 범례도 "위험도 등급 아님"을 명시한다.
- `export_tool_data.py`에서 severity는 배지 계산에 더 이상 관여하지 않는다. v1.14.0의 `_CAUTION_FORCE_KEYS` 우회는 제거됐다.

### Measured

90일 코퍼스(공시 48,646건 · 관찰 신호 2,913건):

| 구분 | 건수 | 비중 |
|---|---:|---:|
| 옛 배지(severity 파생) | 1,641 | 56.3% |
| 새 `first` | 379 | 13.0% |
| 새 `context`만 | 1,042 | 35.8% |

절반을 넘으면 배지가 아니라 기본값이다. `tests/test_observation_priority.py`가 `first` 비중을 5~25% 범위로 고정해, 재분류가 이 성질을 깨면 실패한다.

### Unchanged

- **점수는 여전히 매기지 않는다**(v0.8.5). 이 값으로 집계·정렬·가산하지 않으며, severity·base_score 원값 미노출도 그대로다.
- MCP 도구 출력은 전혀 바뀌지 않았다 — 이 축은 뷰어 표시 계층 전용이다.
- `AMBIGUOUS_SIGNAL_KEYS`(헤드라인 차단) 7종 그대로. `context`와 **합치지 않았다** — 겹치지만 같은 개념이 아니고, 합치면 헤드라인 정책이 조용히 바뀐다(7종 → 17종). 예컨대 `DIVIDEND_DRAIN`은 이미 판정을 거친 파생 플래그라 헤드라인이 될 수 있지만, 제목 하나로 정상/이상이 갈리지 않으므로 관찰 순서로는 context다. 대신 `AMBIGUOUS ⊆ context` 포함 관계를 불변식으로 둔다.

---

## [1.14.0] — 2026-08-22

**제목만으로는 판단할 수 없는 신호들에 원문 확인 계층을 붙이고, 그 결과를 MCP 리포트와 공개 뷰어 양쪽에 사실로 표기.** v1.13.4~v1.14.0에서 되살린 세 신호(`ASSET_TRANSFER`·`RELATED_PARTY`·`EARNINGS_SHOCK`)는 taxonomy가 요구하는 조건(공정가 괴리·가격 괴리·손익 방향)이 제목에 아예 없어, 신호만 띄우면 이용자가 판단할 근거가 없었다.

### Added

- `_related_party_detail_block` — 「특수관계인 자금거래 확인」. 상대방·관계·금액·**이자율**·자기자본대비. 실측 이자율 편차 4.6%~8.95%.
- `_earnings_shock_block` — 「손익구조 급변 내역」. 계정별 증감비율·**흑자적자전환여부**. 제목만으로는 증가인지 감소인지 알 수 없다.
- 공개 뷰어(`docs/tool/index.html`)에 위 두 블록 + 「자산 처분·양도 상대방 확인」 이식. 세 파서(`parseRelatedPartyDetail`·`parseEarningsShockDetail`·`parseAssetDisposalDetail`)를 JS로 옮기고 라이브 8건으로 core와 값 일치 확인.
- `tests/test_viewer_detail_parser_parity.py` — core↔뷰어 파서 동등성을 실측 원문 픽스처로 고정.

### Fixed

- **뷰어 '주의' 배지가 상장폐지·관리종목에 안 붙던 문제.** 배지는 taxonomy severity에서 파생됐는데, 이 레포에서 severity는 '심각도'가 아니라 사실상 '점수를 매기느냐'로 쓰여 왔다(OBSERVATION = 무점수). 그래서 「상장폐지 결정·정리매매 개시」가 '참고'로, 「조회공시 요구」가 '주의'로 떴다. 90일 코퍼스 관찰 신호 2,913건 중 **295건(10.1%)** 영향. taxonomy는 건드리지 않고 배지 파생 규칙에만 승격 목록(`_CAUTION_FORCE_KEYS`)을 뒀다 — MCP 출력·점수·무판정 원칙 불변.
- **뷰어 `classifyOutflowRelation`에 core의 2026-08-04 수정이 누락돼 있던 문제.** 부정 표기("특수관계 없음"·"최대주주 아님")를 부분 문자열 매칭이 계열로 읽어 CRITICAL 패턴이 오발화할 수 있었다. 관계 미추출을 external로 떨어뜨리던 것도 unknown으로 정정.
- **제목에 정정 표시가 없는데 원문이 정정신고인 공시**(포커스에이아이 20260821900279 실측). 정정 원문은 「정정전 정정후」가 나란히 오고 정정사유가 서술문이라, 표 서식 정규식이 문장을 삼켜 상대방 자리에 쓰레기가 들어가고 금액도 **정정전** 값을 잡았다. `_is_amended_document`로 세 파서 모두 읽지 않는다.
- **「(단위 : 억원)」 서식의 금액이 실제의 1억분의 1로 표기되던 문제**(삼성전자 20260730000505 출자 2,970억원 → "2970"). 백만원만 환산하고 억원을 놓쳤다.
- 관계 값이 종료 앵커를 못 만나 표를 삼킬 때 40자로 잘린 문자열("계열회사 처분금액 (원) 264,300,0…")이 화면에 남던 것 — 금액 자릿수가 섞이면 관계 미기재로 버린다.

### Changed

- 버전 표기를 1.12.0 → 1.14.0으로 정렬(패키지·확장·뷰어 메타 4곳). v1.13.x 변경이 릴리스 번호에 반영되지 않아 뷰어 하단 표기가 실제보다 낮았다.

### Known limits

- 뷰어 이식은 세 파서와 표시 블록까지다. `capital_backflow` 패턴 카드 경로(5.7)는 기존 구조를 그대로 두었다.
- `tests/fixtures/corpus/signal_titles_90d.json`은 세 신호 추가 **이전** 스냅샷이라 코퍼스 불변식이 이들을 검사하지 못한다(재수집 필요).
- 적자전환 라이브 사례 미발굴 — 표집 창의 손익구조 공시가 1건뿐이었고 그것이 흑자 증가였다.

---

## [1.12.0] — 2026-08-16

**공시 제목 키워드 매칭 위에 표시 계층(신호 한정층)을 얹어, 정상적으로 공시되는 내용이 위험 신호로 표기되던 문제를 해소.** `match_signals`는 `kw in report_nm` 부분일치가 전부라 부정·방향·주체·수식어를 표현할 수단이 구조적으로 없었다. 실측(골든 픽스처): 삼성전자 1년치 발화 신호 8건 전부, 셀트리온 32건 중 22건, 두산 10건 중 9건이 오탐.

키워드 54종·183개와 `SIGNAL_TYPES`·`taxonomy.py`·`_AMENDMENT_RE`는 **수정하지 않았다.** 잡는 범위는 그대로 두고 잡은 뒤에 나눈다.

### Output Contract Change

Stability Policy의 "사용자 출력 형식 변경(첫 줄·핵심 헤더·표기 원칙)"에 해당한다. 도구 시그니처·파라미터·반환 타입은 하나도 바뀌지 않았고 도구 제거도 없다. 골드 파일은 일괄 갱신했으며 hygiene 9종은 PASS를 유지한다.

- **`build_event_timeline` 첫 줄** — 관찰 신호가 0건일 때 `📋 **{회사명}** ({종목코드})` → `⏳ **이벤트 타임라인: {회사명}** ({종목코드})`. 정상 경로와 형식을 통일했다. 한정층 도입으로 공시 신호가 전부 강등되는 회사(헬릭스미스 실측)에서 이 경로가 처음 발화하며 출력 계약이 깨진 것을 발견해 수정.
- **`analyze_company_risk`** — `━━ 절차·사후 보고 (N건) ━━` 절 신설(강등 사유를 사실 문장으로 동반). 헤드라인 문장 `가장 무게 있는 신호는 'X'입니다`는 후보가 전부 양면적 신호면 `이 기간 관찰된 유형: …`로 대체된다.
- **`check_disclosure_risk`** — `제출인: {이름}` 줄 신설(접수번호로 행이 복원됐을 때만). 강등 판정 시 `🎯` 대신 `⚪ **절차·사후 보고**` + 사유.
- **`search_market_disclosures`** — 커버리지 문구가 `전체 N건 중 신호 일치 M건` → `전체 N건 중 관찰 신호 M건 (표시 K건) · 절차·사후 보고 P건 제외`.
- **`3PCA` 표시 라벨** — 제목에 `제3자배정` 마커가 없으면 `제3자배정유상증자` → `유상증자(배정방식 미상)`. 신호 키(`3PCA`)와 taxonomy ID(2.4)는 불변이므로 신호 키 카탈로그 contract는 영향 없음.

### Added

- `core/qualifiers.py` — 제목 구조 파서(`parse_report_name`)와 신호 한정(`qualify_signals`). 순수 함수, 네트워크 호출 없음. 신호를 삭제하지 않고 `tier`(`observed`/`procedural`)와 강등 사유만 붙인다.
  - R1 제출인 ≠ 회사 · R1b 지분 보유·변동 신고서(대량보유·임원소유·최대주주등소유주식변동) · R2 사후·해제 국면(어미가 `결과보고서`·`해제`·`취소`·`철회`·`해지`·`중단`) · R3 자회사·특수관계인 사안 · R4 해명·미확정 · R5 정정·후속 꼬리표.
  - **마지막 어미만 본다** — `자기주식취득신탁계약해지결정`은 `해지`를 포함해도 `결정`으로 끝나므로 관찰 신호로 남는다. 부분일치와의 결정적 차이.
  - 거래소 제출 공시는 R1에서 제외한다. 실측(`pblntf_ty=I`, 6,341행): `코스닥시장본부` 389 · `유가증권시장본부` 71 · **`코넥스시장` 13(본부 접미 없음)**. 이 예외가 없으면 `조회공시요구`·`불성실공시법인지정`이 집계·헤드라인·패턴 매칭에서 소실되고 타임라인 탈출기가 비어버린다.
- `signals.AMBIGUOUS_SIGNAL_KEYS` — `TREASURY`·`TREASURY_TRUST`·`FUND_OUTFLOW`·`ACQ_REVIEW`. 정상 기업활동으로도 빈발해 단독으로는 헤드라인이 되지 못한다. 목록·집계·패턴 매칭에는 정상 참여. 근거는 새로 만들지 않고 `explain.py`가 이미 쓰고 있는 양면성 서술만 사용했다.
- `core.resolve_disclosure_row_from_rcept_no` — 접수번호로 `list.json` 행 전체를 복원. `check_disclosure_risk`가 접수번호만 아는 경로에서 실제 제목·제출인을 얻어 R1~R5를 적용한다. 전용 캐시 `_rcept_row_cache`(10분, 50건).
- `signals-data.json`에 `qualifier_rules`·`ambiguous_signal_keys` 내보내기 — 규칙 문자열의 이중 관리를 막고 뷰어는 로직만 이식한다.
- 공개 뷰어(`docs/tool/index.html`) — 관찰/절차 두 층 렌더, 대량보유보고 묶음 요약(임계 없이 분모 병기), 관찰 0건 안내, 배정방식 미상 행의 **펼칠 때만** 원문 확인(스캔 시점 추가 호출 0건).

### Changed

- `analyze_company_risk`·`build_event_timeline`·`check_disclosure_risk`·`search_market_disclosures` 4개 도구가 모두 한정층을 통과한다. `procedural`은 카테고리 집계·헤드라인·`detect_capital_churn`·`capital_backflow` 게이트·`CROSS_SIGNAL_PATTERNS` 매칭에서 제외된다.
- `search_market_disclosures`의 preset 필터가 `observed` 신호에만 적용된다 — 강등된 신호가 preset을 통과시키면 제외의 의미가 없다. 절차 건수도 preset 범위로 집계한다.
- 시장 스캔 실측 효과(7일, 5,820건): `shareholder_change` 240 → **13**(−94.6%), `all_risk` 527 → 240, `inquiry` 38 → 18, `treasury` 48 → 35, `fund_outflow` 62 → 53.

### Fixed

- `check_disclosure_risk`가 접수번호로 불릴 때 제목을 `f"접수번호 {rcept_no}"` 자리표시자로 만들어 **어떤 신호도 매칭될 수 없던** 문제. 함수 132줄에 `report_nm`이 0회 등장했다.
- 같은 공시가 호출 형태에 따라 다른 판정을 받던 비대칭 — `rcept_no`와 `report_name`을 함께 넘기면 `filing=None`이 돼 R1이 발화하지 못했다.
- 강등 사유 문장이 R2~R5에서 사실과 달랐던 문제(`이미 실행된 건의 결과 보고입니다` 바로 아래에서 `회사가 낸 사건 공시가 아닙니다`로 스스로를 반박).
- 완전히 강등된 공시에도 카탈로그 발췌가 출력돼 강등을 시각적으로 되돌리던 문제.
- `scripts/regen_goldens.py`의 DS005 후보 선별 — `분할결정` 키워드가 `주식분할결정`(액면분할)에 부분일치, `[첨부정정]` 정정본 미필터, 무마커 재제출 미검증으로 골드가 에러 문자열이 되던 3종.
- `scripts/regen_goldens.py`가 `find_actor_overlap`·`compare_financials`에 회사 10개를 전부 넘겨(두 도구 모두 최대 5개) 골드가 "입력 오류"만 담고 있던 문제.
- `track_fund_usage` 출력에 내부 flag 코드가 `(DIVIDEND_DRAIN)`으로 노출되던 문제.
- 단위 테스트 9건이 실제 DART API를 호출하던 문제 — 스위트의 네트워크 의존 0.

### Known limitations

- `resolve_disclosure_row_from_rcept_no`는 하루치를 12페이지(1,200행)까지만 훑는다. 20260731 실측이 1,159행(상한의 96%)이라 더 몰리는 날엔 `None`을 반환하며, "존재하지 않음"과 구분되지 않는다. 호출부는 기존 동작으로 퇴화한다.
- 접수번호 앞 8자리가 접수일과 다른 공시가 존재한다(20260803 전수 610건 중 4건, 0.7%). 그런 건은 행을 찾지 못한다. 기존 `resolve_corp_code_from_rcept_no`도 같은 전제 위에 있다.
- SE 뷰어(`docs/tool/se/app.js`)에는 한정층이 적용되지 않았다 — 같은 회사에 대해 공개 뷰어와 SE가 다른 헤드라인을 보일 수 있다.

---

## [1.11.0] — 2026-08-04

> 이 항목은 릴리스 당시 CHANGELOG에 기록되지 않아 [GitHub 릴리스 노트](https://github.com/anboyu-alt/dart-risk-mcp/releases/tag/v1.11.0)에서 소급 정리했다. 원문이 더 상세하다.

### Added

- 연결망 실체 병합(#159) — 행위자↔회사 이분 그래프의 노드 병합 우선순위(`actor_corp_ids` > 비모호 fold > 미병합). 동명 별개 법인은 병합하지 않고 시장 배지·사실 주석으로 구분.
- KOSPI 개명 소급 경로(#160) — '상호변경안내'가 사실상 코스닥 전용인 한계를 수동 시드(`manual_renames.json`, DART 대조 검증 필수) + 공개 `corp-aliases` 보조 인덱스로 보완.

### Fixed

- 미존재 기업명 입력 시 9개 도구가 TypeError로 크래시하던 문제(`resolve_corp` None 가드).
- `resolve_decision_type`이 한글 가운뎃점 `ㆍ`(U+318D)를 제거하지 않아 `주식교환ㆍ이전결정`(stock_exchange)이 영구 리졸브 실패하던 버그 — 최근 1년 실사례 77건, 코오롱인더 건으로 종단 검증.
- `capital_backflow`(CRITICAL) 오발화 — "특수관계 없음" 등 부정 표기가 affiliated로 오분류되던 것을 external 우선 분류로 수정.
- 참고 강도(OBSERVATION) 신호에 근거 없는 "위기 도달 N개월" 문장이 렌더되던 폴백 제거.
- `view_disclosure` 숫자 엔티티 크래시·섹션 id off-by-N 수정.

---

## [1.10.3] — 2026-08-02

> 이 항목도 소급 정리했다. [GitHub 릴리스 노트](https://github.com/anboyu-alt/dart-risk-mcp/releases/tag/v1.10.3) 참고.

**v1.10.2 사용자는 이 버전으로 업데이트해야 한다** — v1.10.2는 설치 시점에 따라 서버가 뜨지 않을 수 있다. 기능 변경은 없다.

### Fixed

- `mcp<2.0.0` 상한 추가 — 의존성에 상한이 없어 설치 환경이 mcp 2.0.0을 끌어오면 2.0이 제거한 `mcp.server.fastmcp` 때문에 서버가 import 단계에서 죽었다(Claude Desktop "Server disconnected"). 로컬에는 mcp 1.x가 이미 있어 테스트로 드러나지 않던 유형.
- 가드 테스트 3종 — 의존성 상한 존재 / `server.py` import 경로 유지 / 확장 의존성 핀 == 패키지 버전.

---

## [1.10.2] — 2026-08-02

**금감원 2019-12-19 무자본 M&A 합동점검 반영.** 조달자금 유용 경로(비상장주식 취득 55%·관계회사 대여/선급금 29%)를 패턴·플래그로 도구화.

### Added

- 복합 패턴 `fund_diversion_chain`(조달-유용 체인, HIGH) — CB/BW 발행(1.1) + 타법인주식·영업 양수(5.8) 조합. 정상 신사업 M&A와 구분되지 않는 관찰 포인트라 CRITICAL이 아닌 HIGH로 설계.
- `scan_financial_anomaly` 이상 플래그 8→9종: `LOAN_ADVANCE_SURGE`(재무상태표 대여금·선급금 합계가 전기 대비 2배↑·10억원↑) + "대여금·선급금 (계정 노출 시)" 사실 표기 블록. `core.extract_loan_advance()`가 fnlttSinglAcntAll rows에서 BS(잔액)/CF(증감)를 구분 추출 — CF 전용 노출은 사실 표기만 하고 판정하지 않는다. 라이브: 두산에너빌리티(BS 3계정)·헬릭스미스·두산(CF 전용) 노출 확인, 플래그 임계 충족 사례는 미발굴.

### Changed

- `capital_backflow` field_evidence에서 아틀라스링크 실명 인용을 제거하고 금감원 합동점검 인용(24사 위법행위 적발, 대여·선급금 유용 3,799억)으로 교체 — 특정 기업 낙인 문제 해소, 패턴 자체(신호 조합·CRITICAL)는 변경 없음.
- taxonomy 5.7(Cash Outflow to Acquirer Side) description·red_flags에 동 합동점검 출처 서술 보강.

## [1.6.0] — 2026-07-07

**kreports 이식 시리즈.** [capitalparser/kreports-dart-mcp](https://github.com/capitalparser/kreports-dart-mcp)(Apache 2.0)의 회계 이상 탐지 로직을 본 도구의 원칙(점수·등급 없음, 로컬 DB 없음, 외부 라이브러리 없음)에 맞게 재설계해 이식했다. 이식 항목·수정 내용은 [THIRD_PARTY_NOTICES.md](THIRD_PARTY_NOTICES.md) 참조.

### Added

- **`get_affiliate_investments` 신규 도구 (26번째)** — 타법인 출자현황(`otrCprInvstmntSttus`). 피출자 법인·출자목적·기말지분율·장부가액·피투자사 재무를 사실 나열, SPC·자회사망 추적 축. 라이브: 삼성전자 137건·제이스코 2건 (#41)
- `scan_financial_anomaly` 이상 플래그 4→8종: `CFS_OFS_REVERSAL`(별도>연결 순이익 역전, 셀트리온 라이브 매칭 -58.3%), `RESTATEMENT`(전기 수치 재작성 — 연도 간 보고값 대조, 셀트리온·두산 라이브 매칭), `OPNET_POS_NEG`/`OPNET_NEG_POS`(영업↔순이익 부호 괴리) (#40, #44)
- `scan_financial_anomaly` 사실 표기 블록 4종: 발생액 비율, Beneish 개별 변수 6종(M-Score 합산 미제공 — 점수 금지 원칙), 연구개발비/매출액 비중 3개년(사업보고서 원문 추출, 5/6사 라이브), 업종별 유의 회계정책(KSIC 정적 맵) (#39, #40, #43, #45)
- `get_audit_opinion_history`: 감사인명 별칭 정규화("삼정KPMG"→"삼정회계법인", 13법인 — 교체·재직연수 오탐 방지) + 연속 적자 연수 블록(헬릭스미스 5년 라이브 매칭) (#39, #45)
- `list_disclosure_sections`: 재무제표 주석 카테고리 감지 10종(계속기업·특수관계자·우발부채 등) — 섹션 태그 + 원문 `<TITLE>` 스캔 보완 경로(`scan_note_titles`) (#42)
- 행위자 자동 발굴을 개인 → **개인·조합·법인 3분류**로 확대. `core.known_actors.classify_actor()`(person/fund/corp/institution/noise) 신설 — 조합(투자조합·사모 비히클)은 CB 작전 대표 창구로 개인과 동급 추적, 제도권 기관(증권사·은행·연기금 등)은 반복 등장이 정상이라 수집 제외. 레지스트리에 `구분`(select: 개인/조합/법인) 속성 추가, 법인·조합 등재에는 "동명 법인·조합 미확인" 태그.

### Changed

- `_FS_ALIASES` 계정 별칭 대폭 확장(매출 11종·당기순이익 7종 등) — 기업별 계정명 이질성 흡수 (#39)
- 감사인 교체·재직연수 비교가 정규화된 표준명 기준으로 변경 (#39)

### Docs

- README: 재무제표 기반 이상 플래그 절 신설, 라이브 검증 매트릭스 7행 추가, 제3자 코드 고지 (#46)
- LICENSE(MIT, anboyu-alt)·THIRD_PARTY_NOTICES.md(Apache 2.0 고지) 신설 (#46)
- 테스트 317 → 396 (+79), 골든 매트릭스 14개 도구로 확장

## [1.5.0] — 2026-07-03

**known_actors 레지스트리 데이터 비공개 이전.** 레지스트리 원본이 배포물·public 레포에서 제작자의 비공개 Notion DB로 이동한다. 인물 데이터는 opt-in 접근으로만 제공되며, 도구 기능(레지스트리 대조·`lookup_known_actor`)은 그대로 유지된다.

### Added

- `load_known_actors()` Notion 소스 opt-in — `NOTION_TOKEN` + `DB_KNOWN_ACTORS` env 설정 시 비공개 Notion DB에서 레지스트리를 조회(24h 캐시). 미설정 시 동봉 데이터(빈 스켈레톤)로 graceful fallback.
- 코어 `fetch_registry_from_notion()`·`add_registry_record()` — 레지스트리 Notion I/O.
- `scripts/setup_known_actors_db.py` + `setup-known-actors-db.yml`(workflow_dispatch) — 레지스트리 DB 1회성 생성·기존 데이터 시딩.

### Changed

- 일일 자동 발굴·갱신 크론이 등재·근거를 public JSON 커밋 대신 비공개 Notion DB에 기록. env 미설정 시 기록을 스킵하고 메일 통지만 수행.
- 동봉 `known_actors.json`이 빈 스켈레톤으로 교체 — 배포물에 인물 데이터를 싣지 않는다.
- 레지스트리 로드 우선순위: `DART_KNOWN_ACTORS_PATH` > Notion(캐시) > 동봉.

### Removed

- `load_known_actors()`의 GitHub raw master 원격 fetch — 릴리스 게이트 없이 전체 사용자의 레지스트리 데이터가 바뀌던 경로 제거. 데이터 접근은 Notion opt-in으로 일원화.
- 동봉 레지스트리의 개인 데이터(maintainer_seed 등) — 공개 배포 부적합 판단.

## [1.4.0] — 2026-06-21

**조회 기간 다년 확장.** 4개 도구가 `lookback_years`(1~5)를 받아 과거 위기 사이클을 한 번에 추적한다.

### Added

- `analyze_company_risk`·`build_event_timeline`·`list_disclosures_by_stock`·`check_disclosure_anomaly`에 `lookback_years: int = 1`(1~5) 파라미터 추가. 내부에서 `days = years*365`로 환산.
- 코어 `fetch_company_disclosures(..., max_pages=10)` 파라미터 — 1000건 페이지네이션 상한을 호출자가 상향 가능. 위 4개 도구는 `max_pages = years*10`(5년 → 최대 5000건) 전달로 다년 누락 방지.
- 다년(>1년) 조회 시 결과 하단에 `📊 예상 출력 규모: 약 N자 / ~M토큰 (대략적 추정)` 푸터(문자 수 휴리스틱, 외부 의존성 없음).
- 골든 재생성 워크플로우 `.github/workflows/regen-goldens.yml`(`workflow_dispatch`, 재생성 범위 `tools` 입력, 기본 `list`).

### Deprecated

- 위 4개 도구의 `lookback_days` 파라미터 — `lookback_years`로 대체. 안정성 정책(도구 시그니처 변경 = 최소 1 minor 별칭 유지)에 따라 **deprecated 별칭으로 유지**(호출 시 `DeprecationWarning`): 일 단위(1~365) 구버전 동작을 보존하며, 다음 minor(1.5.0)에서 제거 예정.

### Changed

- `analyze_company_risk`·`list_disclosures_by_stock` 기본 조회 윈도우가 90일 → 1년(365일)으로 확대(`lookback_years=1` 기본값). `years==1` 출력 라벨("최근 365일")은 기존 골든과 동일(패리티 유지).
- (test) `test_golden_output_hygiene.py`의 내부코드 괄호 검사를 verbatim passthrough 골든(`*_list.txt`·`*_doc_*`)에서 제외. 해당 골든은 DART 공시 제목·원문을 그대로 옮긴 것으로, 원문의 실제 규제기관 약어(FDA·EMA 등)는 내부코드 누출이 아니다(false-positive). 나머지 8종 hygiene 검사는 전 골든에 유지.

### Fixed

- `check_disclosure_anomaly` docstring의 stale "0~100 스코어" 표기를 v0.8.5 사실 표기로 정정.

## [1.3.0] — 2026-06-14

**known_actors 자동 갱신 + 원격 로드.** 등재 인물의 인수 근거를 매일 자동 수집하고, 유저는 갱신된 데이터를 즉시 받는다.

### Added

- `core/known_actors.py` 원격 로드 — GitHub raw 최신 `known_actors.json`을 24h 캐시로 로드, 네트워크 실패 시 동봉 fallback. 중앙 서버 없음(정적 파일).
- `scripts/refresh_known_actors.py` — 최근 2일 시장 CB/유상증자 공시에서 등재 인물의 인수자 근거를 자동 매칭. `status: auto_matched`(동명이인 미확인). 새 인물 등재 안 함.
- `.github/workflows/refresh-known-actors.yml` — 매일 cron 자동 실행 → master 자동 push.
- `status` 3단계: `verified` / `maintainer_seed` / `auto_matched`. 자동 매칭은 verified로 자동 승격하지 않으며 강한 동명이인 경고 동반.

### Notes

- `DART_API_KEY`는 GitHub repo Secret으로 운영자가 등록.
- 유저 MCP 도구의 시장 자동 스캔은 여전히 비범위 — 운영 큐레이션은 GitHub Actions 전용.
- 점수·등급·판정 없음(v0.8.5) 유지.

## [1.2.1] — 2026-06-14

**제작자 시드 + 등재 상태 구분.** 공개기록 레지스트리에 `status` 필드를 도입해, DART 근거가 확보된 인물(`verified`)과 제작자가 모니터링 대상으로 등록한 인물(`maintainer_seed`)을 명확히 구분한다.

### Added

- `known_actors.json` `status` 필드 — `verified`(공시 자동 집계 근거) / `maintainer_seed`(제작자 등록, 공시 자동매칭 아님).
- `lookup_known_actor`·`find_actor_overlap` — `maintainer_seed` 항목에 "공시 자동매칭이 아닌 제작자 모니터링 등록 (혐의·확정 아님)" 면책을 추가 표기.
- 제작자 모니터링 시드 5명 등록(이준민·배상윤·원영식·온성준·Yoo Andy C). 향후 DART 근거 확보 시 `verified`로 승격.

### Notes

- 출력은 여전히 사실·면책만 — "세력" 단정·판정·점수 없음(v0.8.5 유지).
- 신승수는 `verified`로 표기(DART 임원현황 근거).

## [1.2.0] — 2026-06-14

**메인 메시지: 공개기록 행위자 레지스트리 — 출처 기반 사실 데이터를 동봉.** MCP 사용자는 "어떤 인물이 문제 상장사에 반복 등장하는가"에 대한 사전 지식이 없다. 출처가 확인된 공개기록(DART 임원현황·CB/유상증자 인수)에 인물이 어느 상장사에 등장했는지를 **사실·출처로만** 정리한 레지스트리를 패키지에 동봉하고, `find_actor_overlap`이 탐지한 인물을 자동 대조한다.

### Added

- `core/known_actors.py` + 동봉 데이터 `data/known_actors.json` — 공개기록 행위자 레지스트리(로드/조회).
- `lookup_known_actor(name)` 신규 도구 (25개째) — 인물명으로 공개기록 조회. 위험 판정·점수 없음, 동명이인·원본 확인 면책 동반.
- `find_actor_overlap` — 탐지된 인수자·임원을 레지스트리와 대조해 "📎 공개기록 참고(사실 표기 — 판정 아님)" 섹션 표면화.
- `scripts/build_known_actors.py` — 인물+회사단서 → DART 임원현황/인수자 근거를 자동 집계하는 부트스트랩. 사람은 회사 단서만 주고, 근거(회사·연도·출처)는 코드가 채운다.

### Notes

- MCP 도구 24개 → **25개**. 외부 라이브러리 0 추가.
- **법적 안전장치:** 판정/낙인 없음 · 출처 없으면 등재 불가 · 면책 동반 · 중앙 서버 없음(패키지 동봉, pip update로 갱신) · 등재 이의는 GitHub Issues.
- 초기 시드: 신승수(CG인바이츠·제이케이시냅스·헬스커넥트 등기임원 2023–2025)를 부트스트랩으로 라이브 집계해 출처와 함께 등재.
- 비범위(후속): 매일 cron 자동 갱신(GitHub Actions). 엔진(부트스트랩)은 이번에 완성.
- 기존 호출 하위호환, hygiene 9/9, 점수·등급 없음(v0.8.5) 유지.

## [1.1.0] — 2026-06-14

**메인 메시지: 세력 탐지 강화 — `find_actor_overlap`에 등기임원 겸직 차원 + 워치리스트.** 무자본 M&A 세력은 인수마다 새 SPC/사모조합을 만들어 조합명이 매번 달라 인수자 이름 대조로는 묶이지 않는다. 조합명은 변해도 **사람 이름은 고정점**이라는 통찰로, DART 임원현황(`exctvSttus`) 다년 합집합을 통해 겸직을 포착한다. (착안 출처: gameworkerkim/vibe-investing의 CASSANDRA AI 주식셀럽 위키)

### Added — 임원 겸직 차원 (PR #1)

- `dart_client.fetch_executive_roster(corp_code, api_key, lookback_years)` — `exctvSttus.json` 다년 수집 → `{임원명: {연도}}` 합집합.
- `find_actor_overlap`에 `lookback_years`(1~5, 기본 1) 파라미터 추가 — 365일 하드코딩 → 다년 조회. 출력 안내 문구도 정직 표기(1년=최근 365일, N년=최근 N년).
- `find_actor_overlap`이 인수자(CB/유상증자)와 등기임원 겸직을 한 화면에서 교차 비교. 출처 태그 `[CB]`/`[유상증자]`/`[임원]`. 공통 행위자 = 2개사 이상에 (돈 댄 사람 또는 등기임원으로) 등장.
- 라이브 검증: 신승수군 3개사 겸직(신용규·이호영 동행 포함) 매칭 → `find_actor_overlap` ⚠ → ✅.

### Added — 워치리스트 (PR #2)

- `core/watchlist.py` 신규 — 인물↔회사군 영속 저장(`~/.config/dart-risk-mcp/watchlist.json`, 환경변수 `DART_WATCHLIST_PATH`로 오버라이드). 파일 없음/손상 시 graceful degrade.
- `manage_watchlist(action, person, companies, note)` 신규 도구 (24개째) — `list`/`show`/`add`/`remove`. add는 회사군 합집합 병합.
- `find_actor_overlap(..., watchlist="")` — 저장된 인물의 회사군을 `company_names`와 합집합으로 자동 로드.

### Notes

- MCP 도구 23개 → **24개** (`manage_watchlist` 추가).
- 외부 라이브러리 0 추가(표준 라이브러리만). 점수·등급 없음(v0.8.5)·"저장+수동조회까지만"(실시간 알림 비범위) 원칙 유지.
- 기존 호출은 모두 하위호환 — `find_actor_overlap(company_names=...)`·골드 `actor_overlap.txt` 불변. hygiene 9/9 유지.

## [1.0.3] — 2026-04-28

**메인 메시지: 검증 정직성 — 라이브 매칭된 항목과 코드만 있는 항목을 README에 명확히 구분.** 코드 본질 변경 0(서버·도구·핵심 헬퍼 그대로). 사용자 피드백 — README에 적힌 모든 기능이 라이브 검증된 것은 아니라는 점을 정직하게 표기.

### Verified — 시장 preset 8개 추가 라이브 검증

`scripts/regen_goldens.py`의 `MARKET_PRESETS` 4개 → 12개 확장. 신규 8개(`reverse_split`·`3pca`·`shareholder_change`·`exec_change`·`audit_issue`·`asset_transfer`·`embezzle`·`inquiry`)를 라이브 호출해 골드 매트릭스에 추가. `tests/fixtures/sample_outputs/market_*.txt` 4개 → 12개. 골드 총 119 → 127.

### Documented — 라이브 검증 매트릭스 (README + CLAUDE.md)

README의 "이 도구가 하지 않는 것" 직후, CLAUDE.md의 "비범위" 직후에 "라이브 검증 매트릭스" 섹션 신설. 7개 ⚠ 항목 정직 표기:

- `TREASURY_TRUST` (v0.8.7) — 자사주 신탁, 빈도 낮음
- `INSIDER_PRE_DISCLOSURE` (v0.8.6) — 매도 ±30일 부정 공시
- `DIVIDEND_DRAIN` (v0.9.0) — 적자 시점 배당
- `DISTRESS_EVENT` (v0.9.0) — 부도/영업정지/회생/해산
- `get_major_decision` 12개 decision_type — DS005 빈도 낮음
- `find_actor_overlap` 실제 공통 인수자 매칭 — 단위 테스트만
- `CROSS_SIGNAL_PATTERNS` 9개 중 8개 — capital_churn_anomaly만 라이브 검증

⚠ 표시는 "코드와 단위 테스트는 있으나 라이브 매칭 사례 0" 의미. 사례 발굴 시 골드 추가 + ⚠ 제거 (v1.0.4 이후 점진적).

### Notes

- 도구 23개 자체는 모두 라이브 검증돼 정상 작동. ⚠는 도구 안의 특정 신호 키·패턴이 발화한 사례를 못 본 것일 뿐 도구 가용성과는 무관.
- 차기 사례 발굴 트랙 — 무자본 M&A 의심 페어, 부실/배당 회사, DS005 발생 회사를 GitHub Issues로 받아 점진적 골드 추가.
- v1.0.3 PyPI 업로드 시 사용자가 `pip install --upgrade dart-risk-mcp`로 새 docs와 동기화 가능.

## [1.0.2] — 2026-04-27

**메인 메시지: 사용자 진입 장벽 제거.** 코드 본질 변경 0(서버·도구·핵심 헬퍼 그대로). v1.0.1 PyPI 등록 후 사용자가 JSON 파일 직접 편집에서 막히는 케이스가 보고돼, 자동 셋업 스크립트 + Windows PATH 트러블슈팅 보강.

### Added

- **`dart_risk_mcp/setup.py`** — 대화형 자동 셋업. `python -m dart_risk_mcp.setup` 한 줄로 클라이언트 선택(Claude Desktop / Cursor / Windsurf) → 설정 파일 자동 탐색(macOS·Windows·Linux 분기) → 백업(`.json.bak`) 생성 → DART API 키 입력 받아 `mcpServers` 블록에 안전 merge → 저장. 기존 다른 MCP 등록·preferences는 그대로 보존. CLI 인자(`--client`, `--api-key`, `--server-name`, `--dry-run`, `--force`)도 지원해 비대화형 자동화 가능.
- **README "1단계 — 자동 셋업"** 절 신설 — 0단계 패키지 설치 직후 배치. JSON 직접 편집은 옵션으로 강등.
- **헤더 설치 라인** — `pip install dart-risk-mcp → python -m dart_risk_mcp.setup` 두 단계로 갱신.

### Changed

- **JSON·CLI 설정 형태를 `python -m dart_risk_mcp` 로 통일** — Windows user-install + PATH 미등록 케이스를 회피. entry point(`dart-risk-mcp`)는 PATH에 잡히지 않아도 동작 안 함과 무관.
- **0단계 설치 확인 명령** — `dart-risk-mcp --help` (PATH 의존) → `python -c "import dart_risk_mcp; print(dart_risk_mcp.__version__)"` (100% 동작).
- **Q&A "pip로 설치했는데 명령어가 없다"** — 1줄 → Windows user-install PATH 원인 + 해결법 2가지(python -m 사용 / PowerShell로 PATH 영구 추가) 보강.

### Notes

- v1.0.2 PyPI 업로드 시 `pip install --upgrade dart-risk-mcp` 한 줄로 누구나 자동 셋업 명령 사용 가능.
- iridescent plan v1.0.x 후속 사용자 피드백 반영 — 설치 진입 장벽 0에 가깝게 단순화.

## [1.0.1] — 2026-04-26

**메인 메시지: v1.0 GA 후속 인프라 검증 종결.** 코드 변경 0(서버·도구·핵심 헬퍼). v1.0 GA 직후 분리한 인프라 검증 4건을 모두 종결하고 결과를 docs에 기록한다.

### Verified

- **PyPI 패키지명 `dart-risk-mcp` 사용 가능** — `https://pypi.org/pypi/dart-risk-mcp/json` HTTP 404 확인. `dart-risk-mcp-kr`(백업명)도 사용 가능.
- **PyPI 정식 등록 완료 (2026-04-27)** — https://pypi.org/project/dart-risk-mcp/1.0.1/ 라이브. 설치 한 줄: `pip install dart-risk-mcp` (또는 `uvx dart-risk-mcp`). README 설치 섹션 4곳(pip 대안·JSON args 3·CLI 명령·Q&A)을 git+url 기반 → PyPI 표준 명령으로 단순화.
- **빌드 무결성** — `python -m build` → `dart_risk_mcp-1.0.0-py3-none-any.whl`(170 KB) + `dart_risk_mcp-1.0.0.tar.gz`(502 KB) 생성. `python -m twine check dist/*` PASSED.
- **`fetch_market_disclosures` `pblntf_ty` 재검증** — A·B·C·D·E·F·G·H·I·J 10개 코드 모두 정상 응답(B 190건·C 659건·D 619건 등). v1.0 검증 시 보고된 빈 응답 이슈는 재현되지 않음 — 검증 종결, 코드 변경 불필요.

### Removed (영구 비범위)

- **DS007 증권신고서(`bdRs`·`mgRs`) 통합 폐기** — 5개 대형 회사(셀트리온·두산에너빌리티·셀트리온헬스케어·삼성바이오로직스·SK하이닉스) 2024-01-01 ~ 2026-12-31 3년 윈도우 모두 0건. iridescent plan #11에서 빈도 미확인으로 보류했던 항목을 영구 비범위로 확정. README "이 도구가 하지 않는 것" + CLAUDE.md "비범위" 표에 추가.

### Notes

- v1.0 GA stable contract(도구 23개·출력 형식·신호 키·CLI) 그대로 유지.
- 이번 릴리스로 iridescent plan v1.0.1 이관 4항목 모두 종결(GitHub Release 페이지 생성 포함).

## [1.0.0] — 2026-04-26 (GA)

**메인 메시지: 출력 표준의 계약화.** 새 MCP 도구 0개. v0.7.x~v0.9.0 동안 다듬어진 한국어 출력 형식이 마이너 릴리스에서도 깨지지 않음을 기계적으로 보증한다. 도구 카탈로그 23개 그대로 유지.

### Added — 골드 다양화

- **`scripts/regen_goldens.py`** 영구 승격 — `tmp/v1_feasibility/regen_v0XX.py` 4개 임시 패턴을 단일 진입점으로 통합. 6개 카테고리 회사 × 23개 도구 매트릭스를 코드에 명시. argparse CLI(`--companies`, `--tools`, `--dry-run`, `--quiet`).
- **6개 회사 카테고리 추가** — 셀트리온(대형주·바이오), 제이스코홀딩스(중소형·위험사례), 두산에너빌리티(대형 자회사·채무), 삼성전자(대형주 표준·페이지네이션), 헬릭스미스(관리종목·부실), 두산(지주사). iridescent plan 라인 211 사용자 승인.
- **rcept 자동 추출** — `analyze_company_risk` 결과의 첫 정상 공시(정정 제외) `rcept_no`를 자동 파싱해 4개 rcept 인자 도구(check_disclosure_risk·get_disclosure_document·list_disclosure_sections·view_disclosure)에 적용.
- **DS005 자동 탐지** — 회사별 DS005 키워드(타법인주식·합병·분할·영업양수도 등) 1건 자동 탐지(미발견 시 콘텐트 경고만, 발견 시 `decision_{rcept}.txt` 생성). v1.0 시점 6 회사 모두 미발견 — v1.0.1 데이터 가용성 추가 검증으로 이월.
- **회사 무관 도구** — `find_actor_overlap`(6 회사 한 번), `compare_financials`(6 회사 한 번), `find_risk_precedents`(신호 키 조합 3종), `search_market_disclosures`(preset 4종) 매트릭스 통합.
- **골드 파일 119개** — `tests/fixtures/sample_outputs/`에 24개 → 119개로 다양화.
- **`CLAUDE.md` "자주 있는 작업"** 절에 골드 재생성 명령 1단락 추가.

### Added — Stable Output Contract (hygiene 검증 3종)

- **`test_first_line_format_per_tool`** — 23개 단축명별 첫 줄 정규식 매핑(`_FIRST_LINE_PATTERNS`). 회사명 단순 13개 + 종목코드 1개 + rcept 4개 + 회사 무관 4개 + 기존 disclosure 1개. `_short_name(fname)` 헬퍼가 파일명 → 단축명 자동 추출(rcept 8자리 suffix 제거).
- **`test_core_headers_preserved`** — 사용자가 학습한 핵심 헤더 8종(`**시계열**`, `**전년 대비 추세 (DART 재무지표 기준)**`, `**공시 원문 목차**`, `**공시 원문**`, `**공시 리스크 분석**`, `**① 정정공시 비율**`, `**③ 공시의무 위반**`, `**⑤ 조회공시 빈도**`)이 골드 전체에서 살아 있어야 한다.
- **`test_no_unknown_internal_code_parens`** — v0.8.7에서 발견한 `(CAPITAL_CHURN)` 등 내부 flag 코드 괄호 인용 회귀 차단. 정규식 `\([A-Z][A-Z_]+\)` 매칭 + `_ALLOWED_PAREN_ABBREVS` 화이트리스트(CB·BW·EB·RCPS·IR·PE·MFDS·FSC·ROE·EBITDA·OECD·IFRS 등 24종) 외 모든 영문 코드 괄호 인용을 fail.

### Changed

- **hygiene 임계 ≥10 → ≥100** — `test_fixture_set_non_empty`. v1.0 GA 119개 골드 기준 충족.
- **README.md 비범위 절 신설** — "이 도구가 하는 것"(23 도구 6 그룹 분류) + "이 도구가 하지 않는 것"(7 영구 비범위 — 점수·등급/실시간 알림/매수 추천/업종 평균/해외상장/비상장 감사/시장 일일 자동 스캔). v0.7.x~v0.9.0 마이너 변경 5개 절·11개 릴리스 요약은 본 CHANGELOG로 일임.
- **CLAUDE.md "비범위" 표 신설** — 7항목 + 사유/검증 출처 컬럼. 도구 인플레이션 회피 안내.
- **CHANGELOG에 Stability/Deprecation Policy 명문화** — Stable contract 4표면(도구 시그니처·출력 형식·신호 키·CLI) 정의 + 변경 분류 7유형별 SemVer 영향·최소 절차 표. v1.0 GA부터 발효.
- **pyproject.toml** Development Status 분류 `3 - Alpha` → `5 - Production/Stable`.

### Removed

- `tmp/v1_feasibility/regen_v0{86,87,88,90}.py` 4개 임시 스크립트 — `scripts/regen_goldens.py` 단일 진입점으로 흡수 후 삭제.

### Notes

- **신규 MCP 도구 0개** — v1.0의 메인 메시지는 "새 기능 0개, 출력 표준 계약화"였음.
- **v1.0.1 이관 항목**: (1) DS007 데이터 가용성, (2) `fetch_market_disclosures` 호출법 점검(`pblntf_ty=B`/`C` 빈 응답), (3) PyPI 패키지명 점유 확인. iridescent plan 라인 142 분리 결정.
- **회귀 검증**: hygiene 9/9 PASS · 전체 157/157 PASS(DART_API_KEY 세팅 시).

## [0.9.0] — 2026-04-26

### Added
- **`fetch_distress_events(corp_code, api_key, lookback_years=3)`** — 부실 후속 4개 엔드포인트 통합:
  - `dfOcr`(부도발생) → `subtype="default"` (df_cn·df_amt·df_bnk 요약)
  - `bsnSp`(영업정지) → `subtype="business_susp"`
  - `ctrcvsBgrq`(회생절차 개시신청) → `subtype="rehabilitation"`
  - `dsRsOcr`(해산사유 발생) → `subtype="dissolution"`
  - 각 이벤트에 `key="DISTRESS_EVENT"` + 한글 `summary` 부착. rcept_dt 폴백·부분 실패 격리·캐시(20건/600초).
- **`fetch_dividend_history(corp_code, api_key, lookback_years=3)`** — `alotMatter`(배당에 관한 사항)을 분기 4코드 × N년 호출. 각 record에 `bsns_year`/`reprt_code` 부착.
- **`detect_dividend_drain(dividend_records, current_fs)`** — 적자 시점 배당 유출(DIVIDEND_DRAIN) 패턴 검출. 당기순이익 음수 + "주당 현금배당금" 양수 동시 발생 시 flag 부여. 분기 4회 호출 노이즈 dedup.
- **신호 키 2종 신규** (점수 가산 없음, 사실 표기만 — v0.8.5 원칙):
  - `DISTRESS_EVENT` (taxonomy 8.5) — 부실 단계 진입(부도/영업정지/회생/해산)
  - `DIVIDEND_DRAIN` (taxonomy 5.6) — 적자 시점 배당 유출
- **`tests/test_distress_dividend_v090.py`** — 14개 테스트.
- **골드 파일 6개 재생성** — 3개 기업 × {`_analyze.txt`, `_fund_usage.txt`}. `_fund_usage.txt`는 신규.

### Changed
- **`analyze_company_risk` 흡수** — `fetch_distress_events` 결과를 자동 통합. 발생 시 하단에 "**부실 단계 진입 — 주요사항보고서 발생**" 경고 블록과 일자별 사건 라인 추가. 점수 가산 없음.
- **`track_fund_usage` 보강** — 출력 하단에 "**배당 이력 (alotMatter)**" 블록 신설. 분기 4회 호출 dedup, 최근 사업연도 재무로 `detect_dividend_drain` 호출 후 적자 시점 배당이면 경고 라인 추가.

### Notes
- 신규 도구 추가 없음 — 도구 23개 그대로 유지(원 plan에서 검토했던 `track_distress_progression` 단독 도구는 빈도 낮음으로 폐기, 흡수 방식 채택).
- v1.0 로드맵 검증 결론에 따른 흡수 결정.

## [0.8.8] — 2026-04-26

### Added
- **`fetch_company_indicators(corp_code, api_key, bsns_year, reprt_code="11011")`** — 단일회사 주요 재무지표(`fnlttSinglIndx`)를 4개 카테고리로 호출해 합친 flat dict 반환:
  - `M210000` 수익성 / `M220000` 안정성 / `M230000` 성장성 / `M240000` 활동성
  - `idx_val=None` 또는 숫자 변환 불가 항목은 자동 제외, 일부 cl_code 실패는 격리.
  - 인메모리 LRU 캐시(`_company_indicators_cache`, 최대 40건, TTL 600초).
- **`detect_financial_anomaly`에 `current_indx` / `prior_indx` 옵션 추가** — 기존 4개 절대 임계 판정에 더해 핵심 7종 지표(순이익률·자기자본비율·부채비율·유동비율·매출액증가율·매출채권회전율·재고자산회전율)에 대해 YoY 변동률(delta_pct)을 metric에 부착. **flagged=False 유지**(절대 임계 없음, 사실 표기만).
- **`scan_financial_anomaly` 출력에 "전년 대비 추세 (DART 재무지표 기준)" 블록 신설** — 핵심 지표를 `12.30%p → 8.10%p (전년 대비 -34.1%)` 형식으로 한국어 표기. 기존 4지표 본 표(절대 임계 기준)와 분리.
- **`tests/test_financial_indx_v088.py`** — 8개 테스트(엔드포인트 통합·무효 값 스킵·부분 실패 격리·detect 옵션 호환·YoY 계산·분모 0 처리).

### Changed
- **v1.0 로드맵 #6 재정의 반영** — 원래 plan은 "업종 평균 정규화"였으나, 검증 결과 `fnlttSinglIndx`·`fnlttCmpnyIndx` 둘 다 단일 회사 지표만 반환하고 DART API가 업종 평균을 직접 제공하지 않음을 확인. 따라서 **회사 자체 YoY 추세**로 재정의해 false-positive를 완화. 절대 임계값(AR_SURGE ≥10%p 등)은 폴백으로 유지.

### Notes
- 도구 23개 그대로 유지(신규 도구 추가 없음).
- "업종 평균 대비 +Xσ" 표기는 v1.0 이후로도 영구 비범위(외부 데이터 의존성).

## [0.8.7] — 2026-04-25

### Added
- **`fetch_treasury_decisions(corp_code, api_key, lookback_years=3)`** — 자사주 결정 4개 엔드포인트 통합 조회:
  - `tsstkAqDecsn`         → `key=TREASURY`, `decision_type=acq` (자사주 취득 결정)
  - `tsstkDpDecsn`         → `key=TREASURY`, `decision_type=disp` (자사주 처분 결정)
  - `tsstkAqTrctrCnsDecsn` → `key=TREASURY_TRUST`, `decision_type=trust_cons` (신탁계약 체결)
  - `tsstkAqTrctrCcDecsn`  → `key=TREASURY_TRUST`, `decision_type=trust_canc` (신탁계약 해지)
  - 응답 누락 시 `rcept_no[:8]`로 `rcept_dt` 폴백, 일부 엔드포인트 실패는 격리.
  - 인메모리 LRU 캐시(`_treasury_decisions_cache`, 최대 20건, TTL 600초).
- **신호 키 `TREASURY_TRUST` (taxonomy `2.8`)** — 자사주 신탁 우회 매입 경로. base_score 0, severity OBSERVATION. `NON_DILUTIVE_CAPITAL_EVENTS`에 포함.
- **`signal_to_prose("TREASURY_TRUST")`** — "자사주 신탁계약 체결 또는 해지 공시입니다…" 한국어 해설.
- **`tests/test_treasury_decisions_v087.py`** — 12개 테스트(엔드포인트 정규화·rcept_dt 폴백·부분 실패 격리·캐시·신호 등록·detect_capital_churn 12개월 카운팅).
- **골드 파일 9개 재생성** — 셀트리온/제이스코홀딩스/두산에너빌리티 × {`_capital.txt`, `_analyze.txt`, `_timeline.txt`}.

### Changed
- **`track_capital_structure` — 키워드 매칭 의존을 줄이고 결정 공시 구조화 데이터로 보강**:
  - `match_signals`로 키워드 매칭한 자본 이벤트에 더해 `fetch_treasury_decisions` 결과를 자동 머지.
  - 기존 키워드 매칭으로 잡힌 동일 `rcept_no`는 중복 방지(`_existing_rcept` set).
  - 결정 이벤트는 `report_nm`이 `"자사주 취득 결정"` 등 한글 라벨로 노출.
- **`detect_capital_churn` 12개월 윈도우 카운팅** — 입력에 결정 공시가 자동으로 포함되므로 별도 코드 변경 없이 정확도 상승. `TREASURY_TRUST`는 `NON_DILUTIVE`로 분류돼 비희석 카운트에만 합산.

### Notes
- v1.0 로드맵 검증(`tmp/v1_feasibility/REPORT.md`) 결론에 따라 무상증자(`fricDecsn`)·유무상증자(`pifricDecsn`)·감자(`crDecsn`) 결정은 본 릴리스 범위에서 **제외**. 빈도가 낮아 v1.0 이후로 이월.
- 도구 개수 23개 그대로 유지(신규 도구 추가 없음).

## [0.8.6] — 2026-04-25

### Added
- **`fetch_insider_timeline` 분기 보고 데이터 통합** — 기존 `elestock`(5% 대량보유) + `hyslrSttus`(연 단위 최대주주)에 더해 신규 두 엔드포인트를 4개 분기 코드(`11011`·`11012`·`11013`·`11014`) × N년 루프로 통합:
  - `hyslrChgSttus` (최대주주 변동현황) — 분기별 보유 변동 보고
  - `tesstkAcqsDspsSttus` (임원·주요주주 자기주식 취득·처분 현황) — 회사 자기주식 활동
  - 각 record에 `source` 라벨(`elestock`·`hyslr`·`hyslr_chg`·`exec_treasury`) 부착, `bsns_year`·`reprt_code` 보존.
- **`detect_insider_pre_disclosure(insider_records, signal_events, window_days=30)`** — 매도 이벤트(Δ<0) 직후 ±30일 내 부정 공시(AUDIT/INSOLVENCY/EMBEZZLE/INQUIRY/GOING_CONCERN/DISCLOSURE_VIOL/DEBT_RESTR) 동시 발생 패턴 탐지 함수. 점수 가산 없음, 사실 표기만(v0.8.5 원칙).
- **신호 키 `INSIDER_PRE_DISCLOSURE` (taxonomy `3.6`)** — `signals.py`/`taxonomy.py` 신규 등록. base_score 0, severity OBSERVATION.
- **`tests/test_insider_v086.py`** — 13개 테스트(엔드포인트 통합·source 라벨·분기 4코드 호출·부분 실패 격리·detect 패턴·신호 등록).
- **골드 파일 3개 신규** — `셀트리온_insider.txt`/`제이스코홀딩스_insider.txt`/`두산에너빌리티_insider.txt`.

### Changed
- **`track_insider_trading` 렌더러 — 출력 품질 보정**:
  - source별 적절한 holder/ratio/date 필드 추출 헬퍼(`_extract_row`) 추가.
  - 합산 행("계"·"합계"·"Total"·"-"·빈값) 시계열에서 제외.
  - 인접 분기 동일 비율(<0.005%p 차이) **dedup** — 분기 4회 호출 노이즈 억제.
  - `lookback_years × 365`일 **윈도우 필터** — `hyslrChgSttus`가 전체 이력을 반환해도 윈도우 외 데이터는 제외.
  - `exec_treasury`(회사 자기주식 활동)는 보고자별 시계열에서 분리. 하단 안내로 `track_capital_structure` 연동 표시(예정).
  - source 라벨에 `최대주주 변동`·`임원·주요주주 자기주식` 신규 추가.

### Notes
- v1.0 로드맵 검증(`tmp/v1_feasibility/REPORT.md`) 결론에 따라 "이벤트 단위 거래 추적" 표현은 **분기 보고 단위**로 정정. DART API는 임원 거래일 단위 시계열을 직접 제공하지 않습니다.
- `tesstkAcqsDspsSttus` 응답은 회사 자기주식 활동(취득방법별 분류)이라 v0.8.6에서는 시계열 표기에서 제외하고 v0.8.7(자사주 결정 통합)에 흡수합니다.

## [0.8.5] — 2026-04-25

### Design Principle (신규 확정)
- **점수·등급 없음 원칙 확정** — 기업의 위험도를 정량화하거나 등급을 부여하는 모든 표기를 사용자 출력에서 제거합니다. 공시 기록에서 관찰된 **사실(건수·비율·날짜·공시명)**만 서술하며, 도구 작성자는 기업에 대한 정성·정량 평가의 권위자가 아닙니다. 내부에서는 `SIGNAL_TYPES[*].score`·`taxonomy.base_score`를 신호 우선순위 랭킹 목적으로 계속 사용하지만, 출력 경계를 절대 넘지 않습니다.

### Removed
- **`analyze_company_risk`** — "🔴 **위험 등급: 매우위험** (45점)" 헤더 라인 제거. 상단 요약의 둘째 문장을 "이 도구는 공시 기록에서 관찰된 사실만 서술합니다. 기업의 위험도를 정량화하거나 등급을 부여하지 않으며, 법적 판단이나 투자 결정의 근거가 아닙니다." 로 교체. 이벤트 리스팅의 ` · N점` 꼬리표 제거.
- **`find_risk_precedents`** — "🟠 이 신호 조합의 종합 위험도는 **고위험**입니다." 마감 라인 제거.
- **`check_disclosure_anomaly`** — "종합 스코어 N/100" 상단 라인과 각 지표 헤더의 "N/25점" 꼬리표 제거. 5개 구조 지표는 건수·비율만 나열. 감사의견 가산점(`+5점`/`+3점`)도 경고 문구만 남기고 점수 표기 제거. `total_score`·`grade`·`s_amend`·`s_audit`·`s_viol`·`s_capital`·`s_inquiry` 계산 전체를 삭제.
- **`build_event_timeline`** — 위상(진입기/심화기/탈출기) 이모지(🟢/🟡/🔴) 제거. `_PHASE_EMOJI` 상수 삭제. 단계 헤더는 `**[진입기] — 20250101 이후 N건**` 형태로 간소화.
- **`_risk_level`·`_risk_emoji` 헬퍼 삭제** — 더 이상 출력 경로가 없어 제거. 등급 명칭("매우위험"/"고위험"/"위험"/"주의")과 🔴🟠🟡🔵 이모지도 함께 제거.

### Added
- **`tests/test_golden_output_hygiene.py` — 점수/등급/이모지 회귀 검증 3종 추가**:
  - `test_no_score_or_grade_labels` — `\d+/\d+점`·`\d+점\s*$`·`위험 등급`·`종합 스코어`·`종합 위험도`·등급 명칭 regex 전수 검사.
  - `test_no_severity_emoji` — 🔴🟠🟡🟢🔵 이모지 전수 검사.
  - `"점" 단독 문자`는 "시점·관점·쟁점" 같은 정상 한국어와 충돌하므로 엄격한 숫자-연접 패턴으로만 검사(false-positive 방지).

### Changed
- **상단 요약 문장 표준화** — `analyze_company_risk`·`check_disclosure_anomaly`의 요약 블록에 "이 도구는 공시 기록에서 관찰된 사실만 서술합니다. 기업의 위험도를 등급화하지 않으며, 법적 판단이나 투자 결정의 근거가 아닙니다." 포지셔닝 고지를 고정 삽입.
- **이벤트 리스팅** — `• YYYY-MM-DD · 공시명` 형식으로 통일. 정정공시는 `· 정정공시(관찰 대상 제외)` 꼬리표.

### Golden File Update
- `tests/fixtures/sample_outputs/` 15개 골드 파일 전량 재생성(2026-04-25 실 API). 점수·등급·이모지 제거 후 샘플 3개 기업 출력이 v0.8.5 기준선으로 고정됨.

### Design Principles (업데이트)
1. 내부 코드는 출력 경계를 넘지 못한다.
2. 모든 수치에는 의미를 동반한다.
3. 각 도구 출력은 맨 위 3~4줄로 독립적으로 읽힌다.
4. 단일 출력 — level/mode 파라미터 분기 없음.
5. **(신규) 기업 위험도를 정량화하거나 등급을 부여하지 않는다 — 관찰된 사실만 서술한다.**

## [0.8.0] — 2026-04-25

### Design Principle (확정)
- **단일 출력 원칙 확정** — v0.7.x 동안 모든 도구를 하나의 한국어 서술 출력로 통일했습니다. v0.8.0에서 expert/easy 모드 분기 가능성을 공식 폐기합니다. 향후 어떤 도구도 `level=`·`mode=`·`format=` 같은 분기 파라미터를 받지 않습니다. 사용자가 더 자세한 원시 데이터를 원하면 개별 도구(`get_disclosure_document`, `view_disclosure`, `list_disclosure_sections`)를 조합해 파이프라인을 구성합니다.

### Added — 탐지 정확도 업그레이드
- **`get_audit_opinion_history(company_name, lookback_years=5)`** (22번째 도구) — DART 감사의견 공시 3개 엔드포인트(`accnutAdtorNmNdAdtOpinion`·`adtServcCnclsSttus`·`accnutAdtorNonAdtServcCnclsSttus`)를 연도×엔드포인트 루프로 통합. 최근 5년(조정 가능 1~10년) 감사의견·감사인·연속 재직 연수, 감사인 교체 이력, 비감사용역 비중 30% 초과 연도 경고를 단일 한국어 출력으로 반환. 재직 연수는 과거→최신 방향으로 같은 감사인 연속 횟수를 누적.
- **`track_debt_balance(company_name, year="")`** (23번째 도구) — 채무증권 잔액 5개 엔드포인트(회사채·단기사채·기업어음·신종자본증권·조건부자본증권)를 통합 조회. 종류별 잔액 + 1년 이내 만기 도래 비중을 표시하며, 단기 만기 비중이 30%를 넘으면 차환 압박 경고.
- **`detect_debt_rollover(balance_history, capital_events)`** — 3년 이상 채무 잔액이 거의 변동 없이(YoY ≤ 10%) 유지되면서 해당 기간 CB 발행이 2건 이상이면 `CB_ROLLOVER` 플래그 발생. `track_capital_structure` 출력에 잔액 추이 블록으로 반영.

### Changed
- **`check_disclosure_anomaly` 지표 ② 보강** — 감사의견 이슈(20점) 집계 시, 최근 5년간 감사인 교체 2회 이상이면 +5점, 비감사용역 비중 30% 초과 연도가 있으면 +3점을 추가 가산. 근거 문장도 함께 노출(예: "⚠ 최근 5년간 감사인 교체 2회").
- **감사보수 절대 금액 표시 제거** — DART가 기업·연도별로 천원/백만원 단위를 혼용하여 신뢰할 수 있는 단위 정규화가 불가능. v0.8.0에서는 `audit_fee_okwon`·`non_audit_fee_okwon` 원시 값만 API 응답에 포함하고, 사용자 출력에는 비감사용역 **비중(%)**만 독립성 경고 섹션에서 제공.
- **`fetch_audit_opinion_history` 파싱 견고화** — ① 연도×엔드포인트 루프로 전환해 DART가 `bsns_year` 필터를 요구하는 문제 해결, ② `bsns_year` 응답 필드가 한글("제34기(당기)")이라 `stlm_dt`(결산일)로 연도 추출, ③ `mendng='-'` 폴백 체인(`adt_cntrct_dtls_mendng → real_exc_dtls_mendng`), ④ `servc_mendng`의 공백 없는 숫자 뭉침을 거부하는 엄격 정규식(`re.fullmatch(r"[\d,]+(?:\.\d+)?", line)`) + 건당 1조원 캡으로 파싱 오류 차단.
- **`track_capital_structure` 잔액 블록** — 시계열 위에 "최근 3년 채무증권 잔액 추이" 블록을 추가. 잔액이 거의 변하지 않으면서 CB 발행이 반복되면 `CB_ROLLOVER` 플래그와 함께 차환 의존 경고 문장.

### Added — 골드 파일
- `tests/fixtures/sample_outputs/셀트리온_audit_history.txt`, `셀트리온_debt_balance.txt` — v0.8.0 신규 도구 2개의 실 API 기준선.
- `tests/fixtures/sample_outputs/` 분석·사례 골드 파일 4종 갱신(카탈로그·감사 섹션 문구 변경 반영).

### Removed
- **Track C (비상장사 감사보고서 정량 추출) 공식 폐기** — DART 비상장사 감사보고서는 개별 건별 재무 XBRL이 없고, 구조화된 attachments도 제공되지 않아 정량 비교 가치가 낮다. 제안 단계에서 폐기하며 향후 릴리스에서도 재검토하지 않음.

### Design Principles (유지)
1. 내부 코드는 출력 경계를 넘지 못한다.
2. 모든 수치에는 의미를 동반한다.
3. 각 도구 출력은 맨 위 3~4줄로 독립적으로 읽힌다.
4. 단일 출력 — level/mode 파라미터 분기 없음.

## [0.7.5] — 2026-04-24

### Changed
- **카탈로그 MD 본문 한글화** (`dart_risk_mcp/knowledge/manipulation_catalog/*.md` 8개 파일) — 그동안 영문으로만 남아 있던 `## N.M: English Title` / `### 정의` 본문 / `### Red Flags` 섹션을 전면 한글 번역. 제목 예: `1.1: Conversion Price Adjustment Exploitation` → `1.1: 전환가액 조정 악용`, `8.1: Engineered Insolvency` → `8.1: 인위적 부실화`. `### Red Flags` 헤더는 `### 위험 신호`로 통일. 금감원 적발 사례·법조·기존 기사 인용 블록은 원래부터 한글이라 그대로 유지.
- **`_strip_taxonomy_metadata` 필터 좁히기** (`dart_risk_mcp/core/catalog.py`) — v0.7.3에서 영문 방어 목적으로 `## N.M:` 서브섹션 전체를 제거하던 regex를 `- **Severity**` / `- **Base Score**` / `- **Crisis Timeline**` 세 줄만 핀포인트로 지우도록 축소. 결과적으로 `analyze_company_risk`·`find_risk_precedents`의 카탈로그 발췌에 한글화된 제목·정의·위험 신호 섹션이 처음으로 노출된다. 내부 전용 숫자 라벨 3종은 여전히 필터링되므로 `tests/test_golden_output_hygiene.py`의 기계적 회귀 검증은 통과.

### Added
- **v0.7.5 기준 골드 파일 재생성** (`tests/fixtures/sample_outputs/` 13개) — 카탈로그 한글화가 사용자 출력에 어떻게 스며드는지 고정. `tmp/v072_review/regen_fixtures.py`로 재수집.

### Design Principles (유지)
1. 내부 코드는 출력 경계를 넘지 못한다.
2. 모든 수치에는 의미를 동반한다.
3. 각 도구 출력은 맨 위 3~4줄로 독립적으로 읽힌다.
4. 단일 출력 — level/mode 파라미터 분기 없음.

## [0.7.4] — 2026-04-24

### Changed
- **반복 prose 억제** (`analyze_company_risk`, `track_capital_structure`) — 같은 `signal_key`가 4번째부터 등장하면 `→ 한국어 해설` 라인을 생략하고 공시명·날짜·점수만 출력. 제이스코홀딩스처럼 전환사채 공시가 10건 이상 몰리는 기업에서 같은 문장이 10번 반복되던 피로감 해소. 임계값은 모듈 상단 `_PROSE_REPEAT_LIMIT = 3` 상수로 조정 가능. 영향 없는 곳: `build_event_timeline`(기존 `seen_keys` dedup으로 phase별 1회), `check_disclosure_risk`(단일 공시), `find_risk_precedents`(입력 `valid_keys` 순회).

### Added
- **골드 파일 회귀 기준선** (`tests/fixtures/sample_outputs/`) — 2026-04-24 3개 기업(셀트리온·제이스코홀딩스·두산에너빌리티) 13개 실 API 출력을 v0.7.4 기준선으로 고정. analyze×3 + timeline×3 + scan_fs×3 + list(셀트리온) + disclosure(셀트리온 첫 접수번호) + precedents(CB_BW/3PCA/SHAREHOLDER) + actor_overlap 커버. 재수집 스크립트: `tmp/v072_review/regen_fixtures.py`.
- **기계적 회귀 검증** (`tests/test_golden_output_hygiene.py`) — 골드 파일을 스캔해 ① 내부 flag 코드 10종(AR_SURGE·CAPITAL_CHURN 등), ② 카탈로그 영문 메타(`**Severity**`·`### Red Flags`·`## N.M: EnglishTitle` 헤더), ③ 영문 약어(`OCF `)가 사용자 출력에 노출되면 실패. 실 API 호출 없이 저장된 `.txt`만 검사하므로 CI에서 항상 실행 가능.

### Fixed
- **v0.7.0 시절 stale 테스트 2건 갱신** — `tests/test_v6_integration.py`와 `tests/test_find_actor_overlap.py`가 `self.assertIn("AR_SURGE"/"CAPITAL_CHURN"/"[CB, 유상증자]", out)`로 내부 코드·구(舊) 포맷 노출을 기대하던 것을 한글 라벨·현행 포맷(` · ` separator) 검증으로 갱신. 전체 81개 테스트 통과.

### Design Principles (유지)
1. 내부 코드는 출력 경계를 넘지 못한다.
2. 모든 수치에는 의미를 동반한다.
3. 각 도구 출력은 맨 위 3~4줄로 독립적으로 읽힌다.
4. 단일 출력 — level/mode 파라미터 분기 없음.

## [0.7.3] — 2026-04-24

### Changed
- **실 DART API 출력 리뷰 반영 문구 다듬기** — 3개 기업(셀트리온·제이스코홀딩스·두산에너빌리티) 13개 출력 샘플을 사람이 눈으로 읽은 뒤, 내부 코드·영문 약어·어색한 반복을 제거:
  - **카탈로그 발췌 블록 한글화** (`find_risk_precedents`, `analyze_company_risk`) — `load_catalog_excerpt`가 반환하는 MD에서 `## N.M: English Title` / `- **Severity**` / `- **Base Score**` / `- **Crisis Timeline**` / `### 정의`(영문) / `### Red Flags`(영문) 블록을 regex(`_strip_taxonomy_metadata`)로 제거. 한글로 작성된 `### 금감원·금융위 적발 사례` · `### 적발 기법 종합` · `### 인용 법조` · `### 기존 현장 기사 인용` 섹션만 남김.
  - **`scan_financial_anomaly` — "OCF" 약어 제거** — 결과 표의 `순이익 X / OCF Y` 표기를 `순이익 X / 영업현금흐름 Y`로 치환(`server.py` 포매터 1곳).
  - **`analyze_company_risk` — 🎯 리드 문장 중복 해소** — `가장 무게 있는 신호는 'X'이며, X 공시입니다. ...` 꼴로 라벨과 산문 첫 문장이 같은 말을 반복하던 현상 수정. `_compose_top_signal_sentence` 헬퍼로 prose 첫 문장이 라벨 재소개형이면 생략 후 두 번째 문장부터 이어 붙임.
  - **공시 제목 내부 공백 정리** — DART 원본이 `전환가액의조정              (제4회차)`처럼 패딩된 공시명을 리스팅에 그대로 노출하던 문제 수정. `_clean_report_name`으로 2칸 이상 공백을 1칸으로 축약, 3개 렌더 지점(analyze_company_risk 이벤트, 최근 공시, build_event_timeline)에 적용.
  - **자금조달 이벤트 라벨 한글화** — `[자금:public 회차-]` 같은 디버그풍 표기를 `[자금조달(공모)]` / `[자금조달(공모) 제4회차]` 형태로 치환. `_fund_kind_korean` + `_fund_round_korean` + `_format_fund_event_name` + `_format_fund_year_prefix` 헬퍼 신설. DART API가 빈 회차를 리터럴 `"-"`로 돌려주는 케이스도 `_EMPTY_TM_VALUES` 센티넬로 흡수해 `회차-` 잔존 제거(`track_fund_usage`·`analyze_company_risk` 자금사용 블록 양쪽).

### Design Principles (유지)
1. 내부 코드는 출력 경계를 넘지 못한다.
2. 모든 수치에는 의미를 동반한다.
3. 각 도구 출력은 맨 위 3~4줄로 독립적으로 읽힌다.
4. 단일 출력 — level/mode 파라미터 분기 없음.

## [0.7.2] — 2026-04-24

### Changed
- **v0.7.1 '쉬운 출력' 원칙을 남은 4개 도구로 확장** — 내부 flag/signal/pattern 키가 절대 사용자 출력에 노출되지 않도록 렌더러를 재작성:
  - `check_disclosure_risk` — `신호 유형: ... (CB_BW, 25점)` 형식의 내부 키/점수 노출 제거. `signal_to_prose`로 "이 공시가 왜 중요한가"를 문장으로 설명. DS005 주요결정 블록의 `플래그: DECISION_RELATED_PARTY, ...` 라인은 `flag_to_prose` 본문으로 치환("이 결정에서 주의할 점" 블록).
  - `find_risk_precedents` — `━━ 전환사채·신주인수권부사채 (CB_BW, 25점) ━━` 형식의 키/점수 노출 제거. 각 신호에 `signal_to_prose` 본문을 붙이고, 과거 위기 궤적은 "평균 약 N개월/손실 N%"로 문장화. 패턴 매칭 블록은 `pattern_to_prose`로 대체.
  - `build_event_timeline` — 맨 위 🎯 3문장 요약(분석 기간·가장 밀집된 단계·패턴 유사도) 신설. 단계(진입기/심화기/탈출기)에 한 줄 정의 머리말 추가. 각 이벤트의 첫 등장 신호 아래 `→ signal_to_prose` 한 줄 해설. 재무 징후 블록의 `**이상 플래그:** AR_SURGE, CASH_GAP` 라인을 `flag_to_prose` title+body 쌍으로 교체(`_METRIC_TO_FLAG`를 통해 지표→플래그 역추적).
  - `find_actor_overlap` — 맨 위 🎯 요약 추가(이 도구의 목적 + 오늘의 결과). "공통 행위자 없음"이 "세력이 없다"는 결론이 아님을 명시. 기업별 인수자 섹션 머리말·회사별 판정 문구를 모두 완전한 문장으로.

### Design Principles (유지)
1. 내부 코드는 출력 경계를 넘지 못한다.
2. 모든 수치에는 의미를 동반한다.
3. 각 도구 출력은 맨 위 3~4줄로 독립적으로 읽힌다.
4. 단일 출력 — level/mode 파라미터 분기 없음.

## [0.7.1] — 2026-04-23

### Changed
- **비전문가가 읽어도 막힘 없는 출력** — 6개 도구의 렌더링 레이어를 완전 재작성. 내부 flag/signal/pattern 키(`AR_SURGE`, `CB_BW`, `CAPITAL_CHURN`, `DECISION_RELATED_PARTY`, `FUND_DIVERSION` 등)가 **사용자 출력에 더 이상 노출되지 않음**. 모든 코드 문자열은 렌더 직전 한국어 서술로 치환:
  - `analyze_company_risk` — 맨 위 🎯 3문장 요약 블록 신설(규모·등급·가장 무거운 신호). `• [KEY] ...` 형식 → `• YYYY-MM-DD · 공시명 → 왜 주목할 만한지 한 문장` 형식. 복합 패턴·재무이상·주요결정·자금사용 블록 모두 prose 기반.
  - `scan_financial_anomaly` — 판정 열(`🚩 AR_SURGE`) 제거. 지표별 "이 지표가 말하는 것" 단락으로 이상 신호 해설.
  - `check_disclosure_anomaly` — 5개 구조 지표 각각에 "이 지표가 뭘 재는지 + 지금 수준의 의미" 1~2문장 추가.
  - `track_fund_usage` — `⚠FUND_DIVERSION` 토큰 제거. 계획 vs 실제 불일치를 한국어 서술로 설명.
  - `track_capital_structure` — `🚩 CAPITAL_CHURN` 제거. 상단 요약에 churn 의미 3~4문장.
  - `get_major_decision` — `탐지 플래그: DECISION_*` 제거. "주목할 이유" 블록으로 대체.
- `load_catalog_excerpt` — 각 카테고리 발췌 앞에 "이 카테고리가 뭔가요" 2문장 머리말 자동 prepend.
- `README.md` — Section 7 "결과 읽는 법" 예시를 새 출력 형식으로 교체(후속 커밋).

### Added
- **`dart_risk_mcp/core/explain.py`** 신설 — plain-language 사전 모듈. 4개 공개 API: `flag_to_prose(flag, metric) → (title, body)`, `signal_to_prose(key, report_nm) → str`, `pattern_to_prose(pattern_key) → str`, `category_prose(category) → str`. 10개 flag + 31개 signal + 9개 pattern + 8개 category 사전 임베드. 외부 의존성 없음.
- `_metric_amendments()` 내부 헬퍼 — metric dict가 있을 때 본문 말미에 "이번 분석: 전년 8.0%에서 18.2%로 +10.2%포인트 움직였습니다." 같은 맥락 수치 삽입.

### Removed
- `_v6_flag_label()` 함수(server.py) — 영어 코드로 되돌리는 역방향 추상화. `flag_to_prose`로 대체.

### Design Principles (향후 유지)
1. 내부 코드는 출력 경계를 넘지 못한다.
2. 모든 수치에는 의미를 동반한다.
3. 각 도구 출력은 맨 위 3~4줄로 독립적으로 읽힌다.
4. 단일 출력 — level/mode 파라미터 분기 없음.

## [0.7.0] — 2026-04-23

### Added
- **CB/BW/EB·유상증자 구조화 엔드포인트 래퍼 6종** — `fetch_cb_issue_decision`(`cvbdIsDecsn`), `fetch_bw_issue_decision`(`bdwtIsDecsn`), `fetch_eb_issue_decision`(`exbdIsDecsn`), `fetch_piic_decision`(`piicDecsn`), `fetch_fric_decision`(`fricDecsn`), `fetch_pifric_decision`(`pifricDecsn`). 파라미터는 DART 규격에 맞춰 `corp_code + bgn_de + end_de`.
- **DART ACODE 기반 HTML 테이블 파서** — `_extract_investor_table(name_acode, amount_acode)`. DART 표준 공시의 `<TE ACODE="X">` 컬럼 속성으로 인수자명·금액을 정확히 추출. CB는 `ISSU_NM/ISSU_AMT`, Rights는 `PART/ALL_CNT`.
- 릴리스 게이트 문서 `docs/superpowers/release_gates/2026-04-23-v0.7.0-gate.md` — G1~G4 실측 결과.
- 재무이상 임계값 재조정 근거 문서 `docs/superpowers/decisions/2026-04-23-v0.7.0-thresholds-decision.md` — 25개 샘플 분포 기반.

### Changed
- **재무이상 임계값 재조정** — V.2 샘플로 측정한 실제 분포 기반:
  - `AR_SURGE`: ≥50%p → **≥10%p** (샘플 최대값 12.4%p, 50%p는 never-flag)
  - `INVENTORY_SURGE`: ≥50%p → **≥10%p** (샘플 최대값 12.6%p, 동일 논리)
  - `CAPITAL_IMPAIRMENT`: < 50% → **< 200%** (자본 버퍼 취약 경계)
  - `CASH_GAP`: 이분법 유지
- `extract_cb_investors(rcept_no, api_key, corp_code="")` / `extract_rights_offering_investors(rcept_no, api_key, corp_code="")` — `corp_code` 인자 추가. 구조화 엔드포인트 우선 시도 후 HTML 폴백.
- `fetch_major_decision(rcept_no, corp_cls, decision_type, corp_code="")` — `corp_code` 인자 추가. DS005 12개 엔드포인트를 `corp_code+bgn_de+end_de` 조합으로 호출.
- `server.py` — `extract_cb_investors`·`extract_rights_offering_investors`·`fetch_major_decision` 호출부에 `corp_code` 전달.

### Fixed
- **DART 구조화 엔드포인트 파라미터 불일치** — v0.7.0 신규 추가된 6개 발행결정 엔드포인트가 `rcept_no` 단독으로 호출되어 DART API가 `status:100 필수값(corp_code,bgn_de,end_de)이 누락되었습니다`를 반환하던 버그. 단위 테스트는 mock으로 가려졌고 라이브 게이트에서 발견.
- **`_fetch_text`/`_fetch_rights_html_text` 20,000자 truncation 제거** — 실제 공시에서 인수자 섹션이 char 23,000+ 이후 등장하는 샘플 존재(예: 하이드로리튬 CB 23,102; 핑거 Rights 28,681). 섹션 누락 원인.
- **HTML 테이블 파싱 false positive 제거** — 이전 heuristic이 "선정경위" 프로즈 텍스트를 인수자로 오인했음. ACODE 기반 파싱으로 해결.
- **재무이상 G2 측정 버그** — 사전 측정에서 `fetch_financial_statements`(요약만)를 사용해 CF 계정이 누락되어 CASH_GAP이 계산되지 않았음. 라이브 게이트에서 `fetch_financial_statements_all`로 교정.

### Infra
- `_TE_CELL_RE` 정규식 + `_CB_NAME_ACODE`/`_CB_AMOUNT_ACODE`/`_RIGHTS_NAME_ACODE`/`_RIGHTS_AMOUNT_ACODE` 상수 `cb_extractor.py`에 집약.
- 단위 테스트 4개 신규/갱신 — `test_cb_extractor_structured.py`, `test_dart_client_capital_decisions.py`, `test_dart_client_issue_decisions.py`, `test_investor_extractor.py`. 총 77 PASS.

## [0.6.1] — 2026-04-22

### Changed
- `CAPITAL_EVENT_KEYS` 희석성(`DILUTIVE_CAPITAL_EVENTS`, 8종: 3PCA·RIGHTS_UNDER·GAMJA_MERGE·REVERSE_SPLIT·CB_BW·EB·RCPS·CB_ROLLOVER) / 비희석성(`NON_DILUTIVE_CAPITAL_EVENTS`, 3종: TREASURY·CB_BUYBACK·TREASURY_EB)으로 이원화. 하위 호환용 `CAPITAL_EVENT_KEYS` 유지.
- `detect_capital_churn` 판정 규칙 변경 — `희석성 ≥ 3건` 또는 `희석성 ≥ 2 + 비희석성 ≥ 2` 조건에서만 `CAPITAL_CHURN` 플래그 (기존: 자본 이벤트 합계 ≥ 3건). 대형주 자사주 매입 반복 시나리오의 거짓양성 제거 — 삼성전자 검증 완료.
- `CROSS_SIGNAL_PATTERNS` 2개 확장:
  - `zombie_ma` signal_sequence에 `2.7`(CAPITAL_CHURN) 추가
  - `delisting_evasion` signal_sequence에 `2.7`(CAPITAL_CHURN)·`8.2`(CAPITAL_IMPAIRMENT) 추가

### Fixed
- `analyze_company_risk`·`build_event_timeline`·`scan_financial_anomaly`의 재무이상 탐지가 v0.6.0에서 0/5였던 근본 원인 수정 — `/api/fnlttSinglAcnt.json`은 주요 10개 계정만 반환해 매출채권·재고자산·현금흐름 계정이 결측이었음. `fetch_financial_statements_all` 도입(`/api/fnlttSinglAcntAll.json`, 전체 XBRL 계정)으로 교체. `get_financial_summary`·`compare_financials`는 기존 엔드포인트 유지.

### Infra
- `detect_capital_churn` 반환 dict에 `max_dilutive_12m`·`max_non_dilutive_12m` 필드 추가.
- `docs/superpowers/decisions/2026-04-22-v0.6.1-thresholds-decision.md` — V.2 5개 샘플 실측 분포 및 임계값 재조정 연기 근거 기록.

### Deferred (v0.7.x로 이연)
- 재무이상 임계값 경험적 재조정 — V.2 5개 샘플 중 2개 상폐·나머지 분포가 현재 임계값 재조정에 불충분. 10~20개 확장 샘플 필요.

## [0.6.0] — 2026-04-22

### Added
- **신규 MCP 도구 2개** (총 19개 → 21개):
  - `track_capital_structure` — 자본 이벤트(증자·감자·자사주·CB/BW/EB/RCPS 9종)를 시간순 집계. 12개월 내 3건 이상 발생 시 `CAPITAL_CHURN` 플래그
  - `scan_financial_anomaly` — 재무제표 4개 지표 YoY 이상 탐지(`AR_SURGE`·`INVENTORY_SURGE`·`CASH_GAP`·`CAPITAL_IMPAIRMENT`)
- **신규 신호 키 5개**: `CAPITAL_CHURN`(2.7), `AR_SURGE`(6.1), `INVENTORY_SURGE`(6.1), `CASH_GAP`(6.1), `CAPITAL_IMPAIRMENT`(8.2)
- **신규 taxonomy 2.7** (Category 2 자본구조) — 자본 이벤트 과다 반복
- **신규 복합 패턴 1개**: `capital_churn_anomaly` (2.7 + 4.3)
- `detect_capital_churn`, `detect_financial_anomaly` — 순수 계산 함수. 신규 DART 엔드포인트 0개

### Changed
- `analyze_company_risk` — 자본 churn·재무이상 플래그를 signal_events에 자동 합산. 리포트에 자본 변동 타임라인·재무 이상 스캔 섹션 2개 추가
- `build_event_timeline` — 신규 5개 키 `_PHASE_MAP` 매핑 추가, 말미에 "재무 징후" 블록 렌더링

### Infra
- `CAPITAL_EVENT_KEYS` 상수 추가 (자본 이벤트 신호 9개 집합)
- 재무 응답 어댑터 `_fs_response_to_periods` 추가 (DART `fnlttSinglAcnt.json` list → 당기/전기 dict 변환)

## [0.5.0] — 2026-04-22

### Added
- **신규 MCP 도구 2개** (총 17개 → 19개):
  - `track_fund_usage` — 유상증자·CB 자금 사용 계획 vs 실제 집행 대조 (DS002 `/api/prstInvstmEntrCptalUseDtls.json`·`/otrCptalUseDtls.json`). 용도 변경(`FUND_DIVERSION`), 미보고(`FUND_UNREPORTED`) 이상 플래그 탐지
  - `get_major_decision` — 타법인주식·영업·자산 양수도, 합병·분할 등 12개 DS005 주요 결정 공시의 상대방·규모·외부평가 공시 조회. 특수관계 거래(`DECISION_RELATED_PARTY`), 자산총액 대비 과대(`DECISION_OVERSIZED`), 외부평가 미시행(`DECISION_NO_EXTVAL`) 플래그 탐지
- **신규 신호 키 5개**: `FUND_DIVERSION`(5.3/8.1), `FUND_UNREPORTED`(4.3), `DECISION_RELATED_PARTY`(4.2), `DECISION_OVERSIZED`(5.3), `DECISION_NO_EXTVAL`(4.3)
- `fetch_fund_usage`, `fetch_major_decision`, `resolve_decision_type` — DS002/DS005 엔드포인트 래퍼 + LRU+TTL 메모리 캐시 (fund_usage 20건/10분, major_decision 50건/10분)

### Changed
- `check_disclosure_risk` — 주요 결정 공시(DS005) 탐지 시 자금 흐름·상대방 섹션 자동 첨부
- `analyze_company_risk` — 자금사용내역·주요 결정 상대방 플래그를 신호 이벤트에 합산해 최종 점수·복합 패턴 판정에 반영
- `build_event_timeline` — 이벤트 튜플을 6-튜플로 확장(접수번호 포함)해 주요 결정 상대방 정보를 렌더링에 포함. 신규 5개 신호 키 단계 매핑 추가

### Infra
- `dart_client._fund_usage_cache`·`_major_decision_cache` — OrderedDict LRU + TTL 범용 캐시 헬퍼(`_cache_get`·`_cache_set`) 추가

## [0.4.0] — 2026-04-21

### Added
- **금감원·금융위 카탈로그 자동 첨부** — `analyze_company_risk`, `check_disclosure_risk`, `find_risk_precedents` 응답 끝에 탐지된 taxonomy ID가 속한 카테고리의 실제 적발 사례 MD 발췌가 자동 삽입됨
- `core/catalog.py` — taxonomy ID → 카테고리 → MD 파일 로더 (`load_catalog_excerpt`); 파일 부재 시 graceful degradation
- `knowledge/manipulation_catalog/` — 금감원·금융위 보도자료(2021~2026) 기반 8개 카테고리 MD 번들 (30건 분류, 54건 수집 후 제외)
- **신규 복합 패턴 4개** (기존 4개 → 8개):
  - `zombie_ma` — 무자본 M&A 세력의 사모CB 대량발행 + 허위 신사업 + 주가부양 후 고가매도 (타임라인 12개월)
  - `audit_insider_dump` — 감사의견거절 미공개정보 이용 임원·최대주주 매도 (타임라인 6개월)
  - `delisting_evasion` — 자본잠식 기업의 연말 가장납입성 유상증자로 상폐요건 면탈 + 횡령 (타임라인 9개월)
  - `fake_new_biz` — 2차전지·AI·우주항공 등 주업 무관 테마사업 허위 발표 후 주가급등 매도 (타임라인 6개월)

### Changed
- `SIGNAL_TYPES` 11개 신호 키워드 보강 — 금감원 실제 적발 사례에서 반복 등장하는 용어 추가
  - `CB_BW` +콜옵션, 사모전환사채 / `CB_REPAY` +자회사배당, 내부배당 / `EB` +EB배임
  - `CB_ROLLOVER` +연속차입 / `3PCA` +가장납입, 상폐요건면탈 / `SHAREHOLDER` +무자본M&A, 대량보유상황보고
  - `EMBEZZLE` +미공개정보이용, 미공개중요정보, 선행매매, 차명 / `THEME_STOCK` +정치테마주, 핀플루언서
  - `REVENUE_IRREG` +선수금, 미수금급증, 매출과대계상 / `DISCLOSURE_VIOL` +발행철회, 공시철회 / `INQUIRY` +조회공시요구, 거래량급증
- `TAXONOMY` 7개 신호의 `field_evidence`를 placeholder/미흡한 사례에서 실제 금감원 보도자료 근거로 교체 (1.2, 2.4, 4.3, 4.4, 6.1, 7.1, 8.1)

## [0.3.0] — 2026-04-20

### Added
- 시장 전체 preset 배치 스캔 (`search_market_disclosures`) — 12개 preset으로 당일~90일 위험 공시 필터
- 공시 구조 이상 스코어 (`check_disclosure_anomaly`) — 정정비율·감사이슈·공시위반·자본스트레스·조회공시 0~100 집계
- 임원 보수 현황 조회 (`get_executive_compensation`) — 5억이상·개인별·미등기·주총한도 4섹션
- 임원·대주주 지분 변동 시계열 (`track_insider_trading`) — 30일 매수/매도 클러스터 탐지
- `fetch_market_disclosures` — corp_code 없이 DART /list.json 시장 전체 호출
- `fetch_executive_compensation` — 보수 4개 엔드포인트 통합
- `fetch_insider_timeline` — elestock + hyslrSttus 연도별 시계열 통합

## [0.2.0] — 2026-04-20

### Added
- 공시 원문 섹션별/페이지 단위 조회 도구 (`list_disclosure_sections`, `view_disclosure`, `get_disclosure_document`)
- 종목코드로 공시 목록 조회 (`list_disclosures_by_stock`)
- 기업 개요 조회 (`get_company_info`)
- 재무제표 조회 — 단일/다중 비교 (`get_financial_summary`, `compare_financials`)
- 최대주주·대량보유 현황 조회 (`get_shareholder_info`)
- 이벤트 타임라인 서사 분석 (`build_event_timeline`)
- 세력 추적 — 공통 CB 인수자 탐지 (`find_actor_overlap`)
- 신호 taxonomy 확장 — 28개 → 37개 (Category 1~8 전반)
- DART API status 코드 분류 (`020/900/800` → WARNING 로그)
- ZIP 메타데이터 인코딩 `cp949` 설정 (한글 파일명 대응)

### Fixed
- `SIGNAL_KEY_TO_TAXONOMY` 매핑에만 있고 `SIGNAL_TYPES`에 키워드가 없던 9개 키의 실제 탐지 누락 (ACTIVIST, CAPITAL_RED 등)
- `match_signals`가 정정공시(`[기재정정]`)를 제외하지 않아 복합 도구에서 이중 집계되던 문제
- `fetch_company_disclosures` 500건 하드캡 상향 (→ 1000건) + 초과 시 경고 로그
- `_retry` 3회 실패 후 4xx/5xx 응답을 그대로 반환해 호출측 `.json()`이 silent 실패하던 문제
- `_REPORT_CODES`의 `"semi"` vs 외부 docstring의 `"half"` 키 불일치로 반기 보고서 요청 시 연간 보고서로 조용히 대체되던 문제
- `cb_extractor` 인수자 regex의 경계 문자 부족으로 한글 법인명이 끊기던 문제

### Changed
- 외부 라이브러리 최소화 원칙 유지 (`mcp`, `requests`만 사용)

## [0.1.0] — 초기 릴리스

### Added
- MCP 서버 기본 구조 + DART API 클라이언트
- 종합 위험 분석 (`analyze_company_risk`)
- 개별 공시 분석 (`check_disclosure_risk`)
- 신호 유형 선례 조회 (`find_risk_precedents`)
- 28개 신호 taxonomy + 4개 복합 패턴 (`founder_fade`, `debt_spiral`, `reverse_split_spiral`, `related_party_hollowing`)
- CB/BW 인수자명 추출 (`extract_cb_investors`)
- 공시 원문 단순 텍스트 조회 (`fetch_document_text`)
