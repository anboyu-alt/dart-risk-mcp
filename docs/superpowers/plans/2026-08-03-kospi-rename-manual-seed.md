# KOSPI 개명 소급 경로 — 수동 시드 + corp-aliases 보조 인덱스

- 날짜: 2026-08-03
- 상태: **구현 완료** (종단 라이브 검증 포함, 아래 §5)
- 선행 문서: `2026-08-03-actor-network-entity-dedup-plan.md` 부록 B
  (브랜치 `claude/actor-network-duplicate-entities-d0687a`) — "KOSPI 개명 공백"
  잔존 한계를 후속 과제로 분리한 지점에서 이 계획이 시작한다.

## 1. 문제

행위자 연결망의 옛 상호 소급 병합(`corp_renames`, `backfill_renames.py`)은
'상호변경안내' 공시를 소스로 쓰는데, 이 공시는 사실상 코스닥 전용이다
(2026-08-03 실측: corp_renames 610사 중 K 354 vs **Y 2**). 유가증권(KOSPI)
상장사의 개명은 정기주총 정관변경으로 처리되고 '상호변경안내'가 없어 자동
백필이 원리적으로 못 잡는다 — 실례: 에이프로젠KIC → 에이프로젠(00152385).
그래서 `(주)에이프로젠케이아이씨` 행위자 키(2018~19 레코드 3건)가 연결망에서
현재 회사 노드와 병합되지 않고 잔존했다.

## 2. 접근 선택 (3후보 실측 평가)

| 후보 | 채택 | 근거 |
|---|---|---|
| (1) 주총 결과/소집공고 원문 regex 추출 백필 | **기각** | 실측 — 에이프로젠 2020 정기주총결과(20200323801307) 원문 1,810자 전체에 '상호'라는 단어 자체가 없다("제2호 의안: 정관 일부 변경의 건 - 원안대로 승인"뿐). 소집공고(20200306000345)도 앞 20,000자에 상호변경 안건 문구 없음. 새 상호가 원문에 없는 사례가 존재하므로 regex 백필은 원리적으로 불완전하고, 정관변경 안건의 다수(사업목적 추가 등)는 개명이 아니라 오탐원 |
| (2) 근거 rcept_no 동반 수동 시드 | **채택 (주 경로)** | 얇고 검증 가능. 종단 검증 성공(§5) |
| (3) 공개 corp-aliases.json을 legacy_index 보조 소스로 | **채택 (자동 보완)** | 명부 diff는 시장 무관 — 과거 개명은 못 잡지만 주간 diff 도입 이후 개명은 KOSPI 포함 자동 커버. 종단 실행에서 실제로 KOSPI 3건(한국조선해양→에이치디한국조선해양, 예스코홀딩스→㈜INVENI, 한국콜마홀딩스→콜마홀딩스)을 소급 병합했다(§5) |

## 3. 설계

### 3-1. 근거(evidence)의 의미 — "옛 사명 명의 제출 공시"

DART `list.json`의 `corp_name`은 **항상 현재명으로 정규화**되어 과거 명의가
남지 않는다(실측). 옛 사명의 1차 근거는 공시 **원문 헤더**다 — 예:
20200306000345 소집공고 원문 "회 사 명 : (주)에이프로젠케이아이씨".
따라서 수동 시드의 event rcept_no는 "그 corp_code가 옛 사명 명의로
제출했거나 개명 사실을 담은 공시"로 정의하고, 검증도 이 의미로 한다:

1. **연결(치명)**: rcept_no 접수일의 해당 corp_code 공시 목록에 그 rcept_no가
   실재하는가 — 다른 회사의 공시를 근거로 붙이는 것을 기계적으로 차단.
2. **표기(경고)**: 원문(앞 20,000자)에 시드의 옛 사명이 fold 수렴 기준으로
   등장하는가. fold_name의 라틴 음차 변환 덕에 '에이프로젠 KIC'(원문 표기)와
   '에이프로젠케이아이씨'(시드 표기)가 같은 fold로 수렴한다(실측 확인).

### 3-2. 구성 요소

- `scripts/discover_actors.py`
  - `load_manual_renames(path)` — 시드 로드 + 스키마 강제. **rcept_no(14자리)
    없는 event를 가진 entry는 통째로 거부**(출처 없는 데이터 등재 금지 기조).
    유효 entry는 살아남고 오류만 기록.
  - `apply_manual_renames(sdata, seed_path)` — `merge_renames` 재사용
    (rcept_no dedup, idempotent). daily cron(main)이 sightings.json 옆
    `manual_renames.json`을 자동 반영 — 운영자는 private repo에 시드만 커밋.
  - `_alias_name_index()` — 공개 corp-aliases.json → {fold(옛 사명):
    set(corp_code)}. 로드 실패 시 빈 dict(graceful).
  - `_combined_legacy_index(data)` — corp_renames ∪ corp-aliases 합집합.
    같은 옛 사명이 두 corp_code를 가리키면 합집합으로 남겨 reconcile의 모호
    가드(len==1)가 해석을 거부하게 한다(보수적).
  - main()의 reconcile 호출이 `_legacy_name_index` → `_combined_legacy_index`.
- `scripts/backfill_renames.py` — main()의 reconcile도 combined 인덱스 사용.
- `scripts/merge_manual_renames.py` (신규 CLI) — "지금 즉시 + 검증하며" 경로.
  §3-1의 2단계 DART 대조 검증(이미 병합된 rcept_no는 건너뜀 — 호출 예산),
  `--dry-run`/`--no-verify`/`--seed`.
- `.github/workflows/merge-manual-renames.yml` — 수동 dispatch, private
  sightings repo 체크아웃 + 검증·병합 + 커밋(backfill-renames.yml과 동형).

### 3-3. 시드 파일 위치·형식

위치: private sightings repo(`dart-risk-mcp-sightings`)의 sightings.json 옆
`manual_renames.json`. 법인 개명은 공개 사실이지만(공개 corp-aliases.json과
동일 성격) 운영 경로를 sightings와 한 곳으로 모은다. 형식:

```json
{
  "version": 1,
  "renames": {
    "00152385": {
      "names": ["(주)에이프로젠케이아이씨", "에이프로젠KIC"],
      "events": [
        {
          "date": "2020-03",
          "rcept_no": "20200306000345",
          "before": ["(주)에이프로젠케이아이씨"],
          "after": "에이프로젠",
          "src": "manual",
          "note": "주주총회소집공고를 (주)에이프로젠케이아이씨 명의로 제출(00152385) — KOSPI 개명은 '상호변경안내' 공시가 없어 수동 시드. 2022-11 이후 공시는 (주)에이프로젠 명의"
        }
      ]
    }
  }
}
```

위 내용이 그대로 **첫 시드**다(운영자가 private repo에 커밋 →
`merge-manual-renames.yml` 수동 실행 또는 다음 daily cron이 자동 반영).

## 4. 사실 확인 기록 (미실측 값 배제)

- 브리프의 중간 단계 "에이프로젠 MED(2020-03)"는 시드에서 **제외**했다 —
  2020-08·2021-03 공시 원문 헤더가 여전히 "에이프로젠 KIC" 명의였고(실측),
  "에이프로젠 MED" 명의 제출 공시를 확인하지 못했다. 2022-11 공시부터
  "(주)에이프로젠" 명의(실측). MED 표기 행위자 키도 sightings에 없어 병합
  실익이 없다. 근거 없는 값은 등재하지 않는다.
- 20200323801307(정기주총결과)이 아니라 20200306000345(소집공고)를 근거로
  택한 이유: 후자가 원문 헤더에 옛 사명 전체 표기("(주)에이프로젠케이아이씨")를
  담아 표기 검증까지 통과한다. 전자는 "에이프로젠 KIC" 단축 표기만 있다
  (fold 수렴으로 이쪽도 통과하지만 전체 표기 쪽이 근거로 더 강함).

## 5. 종단 라이브 검증 (2026-08-03)

로컬 sightings 스냅샷 사본(16,153 키·36,240 레코드) + 위 시드 +
실 DART 검증으로 `merge_manual_renames.py` 실행:

- 검증: 치명 0·경고 0 (rcept 20200306000345 ↔ 00152385 연결 + 원문 표기 확인)
- `(주)에이프로젠케이아이씨` → `(주)에이프로젠` 병합. 정본 키 레코드 28→31건
  (2018-05·2019-04·2019-07 케이아이씨 시절 3건 합류), `actor_corp_ids
  ["00152385"] = "(주)에이프로젠"` 확립 → dedup 계획 Task 1(actor_corp_ids
  1순위 소비)이 머지되면 연결망에서 회사 노드로 접힌다.
- corp-aliases 보조 인덱스 효과(옵션 3): 추가 5건 소급 병합 —
  (주)리노스→(주)폴라리스에이아이, 에이아이비트→폭스브레인(코스닥 2건) +
  **한국조선해양→에이치디한국조선해양, 예스코홀딩스→㈜INVENI,
  한국콜마홀딩스→콜마홀딩스(유가증권 3건)**. KOSPI 커버가 실제로 성립.
- 레코드 총량 36,240건 보존(무손실), 전체 테스트 2,161개 + hygiene 9/9 통과.

## 6. 비범위

- 과거 KOSPI 개명의 전수 발굴(주총 공시 일괄 파싱): §2-(1) 기각 사유 그대로.
  발견되는 케이스마다 수동 시드로 등재한다(연결망에서 미병합 잔존이 보이는
  키가 발굴 트리거).
- 합병 계보 병합(00549059→00152385류)·그룹 클러스터링: dedup 계획의 비범위
  결정 유지.
