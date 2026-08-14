# 신호 한정층(qualification layer) 설계

작성일: 2026-08-14
대상: `dart_risk_mcp/core/`, `docs/tool/index.html`(리스크뷰어 일반판), `scripts/export_tool_data.py`

---

## 1. 배경 — 무엇이 문제인가

현재 공시 분류는 3단이며 전부 제목 문자열 처리다.

```
report_nm ─▶ ① 정정 필터(AMEND_RE) ─▶ ② match_signals(키워드 183개 부분일치) ─▶ ③ category = max(taxonomy 첫자리)
```

`match_signals`는 `kw in report_nm` 하나뿐이라 **부정·방향·주체·수식어를 표현할 수단이 구조적으로 없다.**
그 결과 정상 공시가 위험 신호로 잡힌다.

### 1.1 실측 (골든 픽스처 기준, 2026-08-14)

| 회사 | 발화 신호 | 오탐 내역 |
|---|---|---|
| 삼성전자 | 8건 | 자사주 결과보고서 3 · 대량보유보고 3 · 자사주 결정 2 — **8건 전부** |
| 셀트리온 | 32건 | 대량보유보고 14 · 자사주 결과보고서 5 · 해명(미확정) 2 · 종속회사 유상증자 1 |
| 두산 | 10건 | 해명(미확정) 4 · 대량보유보고 4 · 자사주 결과보고서 1 |

대표적 오분류 문구:

```
주식등의대량보유상황보고서(일반)
  → "최대주주가 바뀌는 공시입니다"     (제출인은 국민연금·블랙록 등 제3자)

유상증자결정(종속회사의주요경영사항)
  → 셀트리온 헤드라인 "가장 무게 있는 신호는 제3자배정유상증자"

풍문또는보도에대한해명(미확정)
  → "거래소가 이상 징후를 감지해…"     (실제로는 회사의 부인 답변)
```

### 1.2 오탐의 4개 축

| 축 | 못 가르는 것 |
|---|---|
| ① 주체 | 회사가 낸 공시 vs 제3자가 회사에 대해 낸 보고 |
| ② 국면 | 결정 / 결과보고 / 정정 / 철회·해제 / 해명 |
| ③ 성격 | 유상증자의 배정방식, 사채의 발행/취득, 담보의 상대 |
| ④ 양면성 | 자사주 등 정상 기업활동으로도 빈발하는 유형 |

①②③은 추가 네트워크 호출 없이 갈린다(§3). ④는 헤드라인 규칙으로 다룬다(§5).

### 1.3 미사용 데이터

`/api/list.json` 응답의 `flr_nm`(공시 제출인명)과 `rm`(비고)은 **코드베이스 어디에서도 사용되지 않는다**
(`grep -rn "flr_nm" dart_risk_mcp/ docs/tool/` → 0건). ①을 기계적으로 가르는 데 직접 쓸 수 있다.

> ⚠️ **미검증 가정.** `flr_nm` 존재는 DART API 스펙 문서 기준이며 실응답으로 확인하지 않았다.
> 구현 1단계에서 라이브 응답으로 검증하고, 부재 시 R1을 끄고 R1b(제목 기반)만 적용한다(§3.1).

---

## 2. 목표와 비목표

### 목표

1. 정상적으로 공시되는 내용이 위험 신호로 표시되는 것을 막는다.
2. 실제 문제 기업의 신호는 보존한다 — 아틀라스링크 `capital_backflow` 서사, 제이스코 CB 반복, STX 회생절차.
3. 강등 판단의 **이유를 사실 문장으로 남긴다**. 무판정 원칙(v0.8.5) 유지 — 점수·등급 없음.
4. core 단일 소스를 유지한다. MCP와 뷰어가 같은 답을 낸다.

### 비목표

- `match_signals`·`SIGNAL_TYPES`·`taxonomy.py` 수정 — 이번 범위 밖.
- 신호 재배정(예: `CB_BW` → `CB_BUYBACK`). 사실 주석만 붙인다(§4.3).
- 스캔 시점의 자동 원문 확인. 사용자가 펼 때만(§6).
- 심도 원문 분석. 향후 회원 기능으로 이연.

---

## 3. 아키텍처

새 파일 **`dart_risk_mcp/core/qualifiers.py`** — 순수 함수만, 네트워크 호출 없음.

```
                  ┌──────────── core/qualifiers.py ────────────┐
report_nm ───────▶│ parse_report_name(nm) → ParsedName          │
                  │   {tags, body, subtitles, tail}             │
list.json         │                    ↓                        │
 {flr_nm, rm,     │ qualify_signals(signals, parsed, filing)    │
  corp_name} ────▶│   → [Qualified{key,label,tier,reason,note}] │
                  └────────────────────┬───────────────────────┘
signals.py                             │
 match_signals() ──────────────────────┘
                                       ▼
              export_tool_data.py ──▶ signals-data.json (규칙 데이터)
                                       ▼
        server.py (MCP)  ◀─────────────┴─────────────▶  docs/tool/index.html (JS 이식)
```

### 3.1 계약

| 함수 | 입력 | 출력 | 부작용 |
|---|---|---|---|
| `parse_report_name(report_nm: str)` | 제목 1개 | `ParsedName` | 없음 |
| `qualify_signals(signals, parsed, filing)` | `match_signals` 결과 + `ParsedName` + `filing` dict | `list[Qualified]` | 없음 |

```python
@dataclass(frozen=True)
class ParsedName:
    tags: tuple[str, ...]        # 대괄호 접두 태그, 예: ("첨부정정",)
    body: str                    # 괄호·태그 제거한 본체 (공백 정규화)
    subtitles: tuple[str, ...]   # 괄호 내용, 공백 제거 후
    tail: str                    # body의 마지막 어미 토큰

@dataclass(frozen=True)
class Qualified:
    key: str
    label: str                   # 보정된 표시 라벨 (§4)
    tier: str                    # "observed" | "procedural"
    reason: str                  # tier가 procedural일 때 강등 사유(사실 문장)
    note: str                    # 사실 주석 (방향 불일치 등), 없으면 ""
```

- **신호를 제거하지 않는다.** `tier`만 붙는다. 정보 손실 없음, 규칙 되돌리기 쉬움.
- `filing`은 list.json 원소를 그대로 넘긴다(`flr_nm`, `rm`, `corp_name`). 키가 없어도 동작해야 한다.

### 3.2 tier의 의미

| tier | 정의 | 집계 참여 |
|---|---|---|
| `observed` | 회사가 낸, 해당 사건 자체의 공시 | 카테고리 집계 · 헤드라인 · `CROSS_SIGNAL_PATTERNS` 매칭 **포함** |
| `procedural` | 제3자 제출 / 사후 보고 / 철회·해제 / 해명 / 정정 | 전부 **제외**. 접힌 목록에만 표시 |

`procedural`이 패턴 매칭에서 빠지는 것이 중요하다 — 대량보유보고가 `SHAREHOLDER`(3.1)로 잡히면서
`capital_backflow`·`zombie_ma` 같은 패턴의 전제 조건을 가짜로 충족시켜 왔다.

---

## 4. 규칙

### 4.1 강등 규칙 R1~R5

모든 비교는 **공백 제거 후** 수행한다(`자회사의 주요경영사항` / `종속회사의주요경영사항` 두 표기가 실존).

#### R1 — 제출인이 회사가 아니면 `procedural`

```
filing.flr_nm 과 filing.corp_name 을 _fold_corp_name 으로 정규화해 비교.
불일치 → tier="procedural"
reason = "회사가 낸 공시가 아닙니다 (제출인: {flr_nm})"
```

`_fold_corp_name`(dart_client.py 기존 함수)을 재사용해 `㈜`·`(주)`·`주식회사` 표기차를 흡수한다.

#### R1b — `flr_nm` 부재 시 제목 기반 예비

본체가 아래로 **시작**하면 `procedural`:

```
주식등의대량보유상황보고서
임원ㆍ주요주주특정증권등소유상황보고서
최대주주등소유주식변동신고서
```

reason = `"제3자가 회사에 대해 제출한 보고서입니다"`

R1이 동작하면 R1b는 건너뛴다. 둘 다 적용 시 R1의 reason이 더 구체적이므로 우선한다.

#### R2 — 사후·해제 국면이면 `procedural`

`ParsedName.tail`이 아래 중 하나:

```
결과보고서 · 해제ㆍ취소등 · 해제 · 취소 · 철회 · 해지 · 중단
```

reason = `"이미 실행된 건의 결과 보고입니다"` (결과보고서) /
`"체결이 아니라 {tail}입니다"` (나머지)

**마지막 어미만 본다.** `자기주식취득신탁계약해지결정`은 `해지`를 포함하지만 `결정`으로 끝나므로
`observed`를 유지한다 — 새로 내린 결정이 맞다. 이것이 부분일치와의 결정적 차이다.

#### R3 — 자회사 사안이면 `procedural`

`subtitles` 중 하나가 `종속회사의주요경영사항` / `자회사의주요경영사항` / `관계회사의주요경영사항`,
또는 body가 `특수관계인의`로 시작할 때.

reason = `"이 회사가 아니라 자회사·특수관계인 사안입니다"`

#### R4 — 해명·미확정이면 `procedural`

`tail == "해명"` 또는 `"미확정" in subtitles`.

reason = `"회사가 미확정으로 답한 해명 공시입니다"`

거래소가 요구한 조회공시(`조회공시요구(풍문또는보도)`)는 `tail`이 `요구`라 걸리지 않는다 —
`observed`로 남는다. 제이스코 `조회공시요구(풍문또는보도) (감사의견 비적정설)`가 유지되는 것을 확인했다.

#### R5 — 정정·후속 꼬리표면 `procedural`

`tags` 중 하나가 아래이거나 `정정`으로 끝날 때:

```
기재정정 · 첨부정정 · 첨부추가 · 정정 · 발행조건확정 · 연장결정
```

reason = `"기존 공시의 정정·후속 보고입니다 ({tag})"`

동시에 **기존 `_AMENDMENT_RE`의 오탐을 고친다.** 현재 `^\[(?:기재정정|첨부추가|정정)`은
`[정정명령부과]증권신고서`를 정정공시로 오판해 신호를 통째로 삭제한다. 정정명령 부과는
규제기관의 조치이므로 `observed`로 남아야 한다.

- `_AMENDMENT_RE` 자체는 건드리지 않는다(비목표).
- R5의 태그 목록은 **완전 일치 또는 `정정`으로 끝남**으로 판정하므로 `정정명령부과`는 걸리지 않는다.
- `match_signals`는 `_AMENDMENT_RE`로 이미 `[정정명령부과]`를 빈 리스트로 만들어버린다.
  따라서 **호출부에서 오탐인 경우에만** 접두를 벗겨 재매칭한다(§7.1).

`qualifiers.py`에 판정 헬퍼를 둔다:

```python
def is_false_amendment(parsed: ParsedName) -> bool:
    """_AMENDMENT_RE에는 걸리지만 실제 정정공시가 아닌 경우."""
    return bool(parsed.tags) and not any(_is_amendment_tag(t) for t in parsed.tags)
```

`_is_amendment_tag`는 R5와 **같은 목록**을 쓴다. 진짜 정정공시(`[기재정정]` 등)는
지금처럼 신호가 발생하지 않고 기존 `amendRate` 집계에만 잡힌다 — **동작이 바뀌지 않는다.**
`[정정명령부과]`처럼 목록에 없는 태그만 복구된다.

#### 규칙 우선순위

R1 → R1b → R5 → R2 → R3 → R4 순으로 평가하고 **첫 매칭에서 멈춘다.**
R5를 앞에 두는 이유: 정정본은 내용과 무관하게 정정이므로 다른 사유보다 먼저 확정된다.

### 4.2 라벨 보정

제목이 확정해주지 못하는 수식어는 라벨에서 뺀다.

| 조건 | 원래 라벨 | 보정 라벨 |
|---|---|---|
| `3PCA` 매칭인데 body/subtitles에 `제3자배정`이 없음 | 제3자배정유상증자 | **유상증자(배정방식 미상)** |

`제3자배정`이 명시된 경우(`증권발행결과(자율공시) (제3자배정 유상증자)`)는 원래 라벨을 유지한다.

보정 라벨 문자열은 `signals-data.json`으로 내보내 뷰어·MCP가 공유한다.

### 4.3 사실 주석 (`note`)

tier를 바꾸지 않고 사실만 덧붙인다.

| 조건 | note |
|---|---|
| `CB_BW` 매칭인데 tail이 `취득`·`매도`로 끝남 | `"발행이 아니라 사채 취득·매도 건입니다"` |

제이스코 `전환사채(해외전환사채포함)발행후만기전사채취득`, `주요사항보고서(자기전환사채매도결정)`가 해당한다.
신호 재배정은 하지 않는다(비목표).

---

## 5. 양면적 신호와 헤드라인

### 5.1 `AMBIGUOUS_SIGNAL_KEYS`

`signals.py`에 상수로 정의하고 export한다. **새로운 판단을 만들지 않는다** — 코드가 이미
양면성을 서술하고 있는 신호만 담는다.

| 키 | 근거 (기존 코드 원문) |
|---|---|
| `TREASURY` | explain.py: "주주 환원으로 긍정적일 수도 있지만…" |
| `TREASURY_TRUST` | 위와 동일 계열 |
| `EQUITY_SPLIT` | 정상 유동성 조치 |
| `FUND_OUTFLOW` | explain.py: "대기업의 일상적 계열 지원과 이 신호…" / CLAUDE.md 참고 강도 |
| `ACQ_REVIEW` | explain.py: "정상적인 사업 인수도…" / CLAUDE.md 참고 강도 |

### 5.2 헤드라인 선정

```
후보 = observed 신호 중 AMBIGUOUS_SIGNAL_KEYS 를 뺀 것
후보가 있으면 → 기존과 동일하게 배열 순서(내부 우선순위) 첫 항목
후보가 비면   → 헤드라인 없이 중립 표기
                "이 기간 관찰된 유형: {라벨} {n}건"
```

규칙은 이 한 줄이 전부다. ambiguous 신호를 후보로 되돌리는 별도 조건은 두지 않는다 —
non-ambiguous 신호가 하나라도 있으면 그것이 헤드라인이 되고, 없으면 중립 표기이므로
ambiguous가 헤드라인이 되어야 할 경우가 존재하지 않는다.

동작 예:

| 회사 | observed 구성 | 헤드라인 |
|---|---|---|
| 삼성전자 | `TREASURY` 2건 (전부 ambiguous) | 없음 → "관찰된 유형: 자사주 취득·처분 2건" |
| 셀트리온 | `TREASURY` 9 + `MGMT_DISPUTE` 1 | `MGMT_DISPUTE`(경영권분쟁소송) |
| 제이스코 | `CB_BW` 등 다수 | 기존과 동일 |

ambiguous 신호는 헤드라인만 못 될 뿐 **목록·카테고리 집계·패턴 매칭에는 정상 참여한다.**

---

## 6. 화면 사양 (뷰어)

### 6.1 두 층 구조

```
관찰 신호 21건 · 절차·사후 보고 15건        ← 항상 둘 다 표기

[관찰 신호]  기존 렌더 그대로 (카테고리 색·caution 배지·타임라인)

[절차·사후 보고 15건]  기본 접힘, 한 번 클릭으로 펼침
   └ 요약 줄 (§6.2)
   └ 개별 행 + 강등 이유
```

- `procedural`은 `catCount`·`typeCount`·`detectedTypes`·`heaviest`·`crisisEvents`·패턴 매칭에서 제외한다.
- 타임라인 SVG·카테고리 분포 막대도 `observed`만 그린다.

### 6.2 대량보유보고 묶음 요약 — 임계값 없음

R1/R1b로 강등된 대량보유보고를 한 줄로 접고 **분모를 함께 적는다.**

```
대량보유상황보고 15건 — 전체 공시 61건 중 (2026-01~07)
```

임계값을 두지 않는 이유는 실측이다:

```
아틀라스링크  15건 / 전체 61건   (경영권분쟁 진행 중)
셀트리온      14건 / 전체 222건  (정상)
```

건수가 거의 같아 count 임계는 셀트리온을 다시 오탐으로 만든다. 우리가 "몰렸다"를 판정하지 않고
분모를 제시해 사용자가 읽게 한다 — 무판정 원칙과 정합한다.

### 6.3 관찰 신호 0건

```
이 기간 공시에서는 관찰 신호가 없습니다.
공시 외 지표(재무·감사의견·연속적자)는 아래 블록에서 확인하세요.
```

헬릭스미스처럼 유일 신호가 강등되는 경우 0건이 "안전"으로 오독되지 않게 한다.

### 6.4 좁은 T2 — 사용자가 펼 때만

라벨이 `유상증자(배정방식 미상)`인 행에 `[원문 확인 ▾]` 버튼을 단다.

```
클릭 → fetchDisclosureText(rcept)  ← 기존 함수·기존 sessionStorage 캐시 재사용
     → 본문에서 배정 방식 문자열 탐색
     → 발견: 라벨 "유상증자 — 제3자배정 확인됨", 근거 문구 표시
       미발견: "원문에서 배정 방식을 확인하지 못했습니다" (라벨 유지)
```

- 스캔 시점 추가 호출 **0건**.
- 이미 열람한 공시는 캐시 히트로 네트워크 호출 없음.
- 실패해도 이 버튼만 조용히 실패한다 — 기존 렌더 무영향.

---

## 7. 통합 지점

### 7.1 core 호출부

`server.py`의 `analyze_company_risk`·`build_event_timeline`이 신호를 만드는 지점에서:

```python
parsed = parse_report_name(report_nm)
sigs = match_signals(report_nm)
if not sigs and is_amendment_disclosure(report_nm):
    # [정정명령부과] 같은 오탐 복구 — 접두 제거 후 재매칭
    sigs = match_signals(strip_amendment_prefix(report_nm))
qualified = qualify_signals(sigs, parsed, filing)
observed = [q for q in qualified if q.tier == "observed"]
```

집계·헤드라인·패턴 매칭은 `observed`만 사용한다.

### 7.2 export

`export_tool_data.py`에 추가 내보내기:

```json
{
  "qualifier_rules": {
    "third_party_titles": [...],
    "phase_tails": [...],
    "subsidiary_subtitles": [...],
    "amendment_tags": [...],
    "label_overrides": {"3PCA": {"missing_marker": "제3자배정", "label": "유상증자(배정방식 미상)"}},
    "direction_notes": {"CB_BW": {"tails": ["취득", "매도"], "note": "..."}}
  },
  "ambiguous_signal_keys": ["TREASURY", "TREASURY_TRUST", "EQUITY_SPLIT", "FUND_OUTFLOW", "ACQ_REVIEW"]
}
```

**규칙 데이터는 JSON으로 내보내고 로직만 JS로 이식한다.** 문자열 목록의 이중 관리를 막는다.
기존 `match_affiliate_row`/`summarize_affiliate_stake` 이식 선례와 동일한 패턴이다.

`docs/tool/se/`(SE 뷰어)는 이번 범위 밖이다 — `signals-data.json`에 필드가 추가되어도
읽지 않으면 무영향이다.

---

## 8. 오류 처리

| 상황 | 동작 |
|---|---|
| `filing`에 `flr_nm` 없음 | R1 건너뛰고 R1b 적용 |
| `filing` 자체가 없음(제목만 아는 경로) | R1·R1b 건너뛰고 R2~R5만 적용 |
| `report_nm`이 빈 문자열 | `ParsedName` 빈 값, 모든 규칙 미적용, 원본 신호 그대로 `observed` |
| 원문 확인(§6.4) 실패 | 버튼만 실패 메시지, 라벨·tier 유지 |

`qualify_signals`는 **예외를 던지지 않는다.** 판단 불가하면 `observed`(기존 동작)로 남긴다 —
실패 시 기존 동작으로 수렴하는 방향이 안전하다.

---

## 9. 테스트 전략

### 9.1 단위 테스트 (`tests/test_qualifiers.py`)

순수 함수라 골든 없이 검증 가능하다. 실측 제목을 그대로 케이스로 쓴다.

```
파서:
  [첨부정정]유상증자결정(종속회사의주요경영사항)
    → tags=("첨부정정",) body="유상증자결정" subtitles=("종속회사의주요경영사항",) tail="결정"
  최대주주변경을수반하는주식담보제공계약해제ㆍ취소등  → tail="해제ㆍ취소등"
  자기주식취득신탁계약해지결정                        → tail="결정"   ← 회귀 방지 핵심

규칙:
  R1  제출인 국민연금공단 ≠ 삼성전자                  → procedural
  R1b 주식등의대량보유상황보고서(일반), flr_nm 없음    → procedural
  R2  자기주식취득결과보고서                          → procedural
  R2  자기주식취득신탁계약해지결정                    → observed   ← 과잉 강등 방지
  R3  유상증자결정(종속회사의주요경영사항)             → procedural
  R4  풍문또는보도에대한해명(미확정)                  → procedural
  R4  조회공시요구(풍문또는보도)(감사의견 비적정설)    → observed   ← 과잉 강등 방지
  R5  [첨부정정]주요사항보고서(유상증자결정)           → procedural
  R5  [정정명령부과]증권신고서                        → observed   ← 기존 버그 수정

보존(문제 기업 신호가 살아있는지):
  최대주주변경 / 최대주주변경을수반하는주식양수도계약체결 / 금전대여결정 /
  타인에대한채무보증결정(자율공시) / 주요사항보고서(유형자산양수결정) /
  주요사항보고서(전환사채권발행결정) / 회생절차개시결정 /
  자본잠식50%이상또는매출액50억원미만사실발생        → 전부 observed
```

### 9.2 회귀 기대값 (골든 기준)

구현 후 아래 수치가 나와야 한다. 어긋나면 규칙이 과하거나 부족하다.

| 회사 | 현재 신호 | 기대 `observed` | 기대 `procedural` |
|---|---|---|---|
| 아틀라스링크 | 36 | 21 | 15 |
| 제이스코홀딩스 | 26 | 19 | 7 |
| STX | 6 | 5 | 1 |
| 삼성전자 | 8 | 2 → 헤드라인 없음(전부 ambiguous) | 6 |
| 셀트리온 | 32 | 10 → 헤드라인 `경영권분쟁소송` | 22 |
| 두산 | 10 | 1 → 헤드라인 없음(전부 ambiguous) | 9 |
| 헬릭스미스 | 1 | 0 → §6.3 안내 문구 | 1 |

산출 근거 스크립트: `tmp/_an/rules.py`, `tmp/_an/check2.py`(프로토타입, 구현 시 폐기).

### 9.3 기존 테스트

- `tests/test_golden_output_hygiene.py` 9종은 그대로 통과해야 한다(점수·등급·이모지 회귀 방지).
- `tests/test_export_tool_data.py`에 신규 필드 검증 추가.
- 골든 재생성(`scripts/regen_goldens.py`)은 **기대값이 실제로 바뀌는 변경**이므로 정당하다.
  재생성 후 diff가 위 9.2 표와 일치하는지 확인한다.

---

## 10. 구현 순서

1. **`flr_nm` 라이브 검증** — list.json 실응답에 존재하는지 확인. 결과에 따라 R1 적용 여부 확정.
2. `core/qualifiers.py` 작성 + `tests/test_qualifiers.py` (TDD).
3. `signals.py`에 `AMBIGUOUS_SIGNAL_KEYS` 추가.
4. `export_tool_data.py`에 규칙 데이터·ambiguous 키 내보내기 + 테스트.
5. `server.py` 배선 — `analyze_company_risk`·`build_event_timeline`.
6. 골든 재생성 + 9.2 표 대조.
7. 뷰어 JS 이식 — 파서·한정자·두 층 렌더·헤드라인 규칙·묶음 요약·0건 안내.
8. 좁은 T2(§6.4) 배선.
9. 프로덕션 배포 후 실제 화면 확인 — 파일 내용이 맞다는 것과 화면이 동작한다는 것은 다르다.

---

## 11. 위험과 완화

| 위험 | 완화 |
|---|---|
| 규칙이 진짜 신호를 강등 | `procedural`은 삭제가 아니라 접힘. 이유가 표시되어 오판이 눈에 보인다. 9.1의 "과잉 강등 방지" 케이스가 기계적으로 막는다 |
| 0건이 "안전"으로 오독 | §6.3 안내 문구 + 상단에 항상 두 카운트 병기 |
| `flr_nm` 부재 | R1b로 대체. 대량보유보고 계열은 제목만으로도 확실히 잡힌다 |
| MCP·뷰어 드리프트 | 규칙 데이터를 JSON export로 단일화. 로직만 이식 |
| DART 제목 표기 변형 | 공백 제거 후 비교. `ㆍ`(U+318D) 포함 표기는 실측 케이스로 테스트에 고정 |

---

## 12. 이번 범위 밖 (후속)

- 신호 재배정(`CB_BW` → `CB_BUYBACK`) — 사실 주석까지만.
- 결정→결과→정정을 하나의 사건으로 묶는 이벤트 그룹핑.
- 심도 원문 분석(모든 신호의 상대방·금액 확인) — 회원 기능으로 이연.
- `docs/tool/se/` 반영.
- ④ 양면성 축의 근본 해결(자사주 규모·신탁 여부 확인) — 헤드라인 제외까지만.
