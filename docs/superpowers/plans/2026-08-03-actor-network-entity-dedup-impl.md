# 행위자 연결망 동일 실체 중복 노드 해소 — 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 같은 법인의 표기 변형('(주)에이프로젠'·'(주)에이프로젠케이아이씨')이 회사 노드와 분리 표시되는 결함을 해소하고, 진짜 동명 별개 법인은 화면에서 구분 표기한다.

**Architecture:** discover 측 self-heal 산출물(`actor_corp_ids`)을 그래프 빌더가 1순위로 소비해 fold 충돌과 무관하게 병합. 옛 상호는 백필 창 확대(2015~)로 소급 해소. 동명 이법인은 병합하지 않고 시장 배지·사실 주석으로 구분(판정 없음 원칙).

**Tech Stack:** Python 3.11 표준 라이브러리만(외부 의존 금지), 자체 완결형 HTML/JS 템플릿, pytest.

**설계 근거:** `docs/superpowers/plans/2026-08-03-actor-network-entity-dedup-plan.md`

## Global Constraints

- 외부 라이브러리 추가 금지 (`requests`·`mcp` 외 불가)
- 점수·등급·판정 표기 금지 (v0.8.5 원칙) — 새 문구는 사실 표기만
- 출력 network.html·sightings 데이터(실명 포함)는 public 레포에 커밋 금지 — `tmp/`·scratchpad에만
- 문서·커밋 메시지는 한국어

---

### Task 1: build_graph가 `actor_corp_ids`를 1순위로 소비

**Files:**
- Modify: `scripts/build_network_html.py:82-94` (Phase B — fold2cc 구성 직후)
- Test: `tests/test_build_network_html.py`

**Interfaces:**
- Consumes: sightings dict의 `actor_corp_ids` 필드 `{corp_code: 정본 행위자 키}` (discover_actors.reconcile_corp_renames가 생성, 2026-07-23~)
- Produces: `build_graph` 동작 변경 — 명부 해석된 법인 행위자는 fold 충돌(동명 회사)이 있어도 회사 노드(`c:<cc>`)로 병합

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_build_network_html.py` 말미에 추가:

```python
def _dup_name_sightings():
    """동명 회사 2곳(corp_code 상이) + 명부 해석된 법인 행위자 — 에이프로젠 축소판.

    fold('알파')가 {201, 202} 2개 corp_code에 걸려 fold2cc로는 병합 불가.
    actor_corp_ids가 '(주)알파'→201 해석을 제공하면 병합돼야 한다.
    """
    return {
        "sightings": {
            "(주)알파": [
                {"corp": "베타", "corp_code": "101", "corp_cls": "Y",
                 "rcept_no": "20260101000001", "date": "2026-01", "kind": "corp"},
                {"corp": "감마", "corp_code": "102", "corp_cls": "K",
                 "rcept_no": "20260201000002", "date": "2026-02", "kind": "corp"},
            ],
            "조합1호": [
                {"corp": "알파", "corp_code": "201", "corp_cls": "Y",
                 "rcept_no": "20260301000003", "date": "2026-03", "kind": "fund"},
                {"corp": "베타", "corp_code": "101", "corp_cls": "Y",
                 "rcept_no": "20260301000004", "date": "2026-03", "kind": "fund"},
            ],
            "조합2호": [
                {"corp": "알파", "corp_code": "202", "corp_cls": "E",
                 "rcept_no": "20260401000005", "date": "2026-04", "kind": "fund"},
                {"corp": "감마", "corp_code": "102", "corp_cls": "K",
                 "rcept_no": "20260401000006", "date": "2026-04", "kind": "fund"},
            ],
        },
        "actor_corp_ids": {"201": "(주)알파"},
    }


def test_actor_corp_ids_merges_despite_fold_collision():
    """actor_corp_ids 해석이 있으면 fold 충돌(동명 회사 2곳)에도 병합된다."""
    g = build_graph(_dup_name_sightings(), min_companies=2)
    ids = {n["id"] for n in g["nodes"]}
    assert "a:(주)알파" not in ids          # 별도 행위자 노드가 사라짐
    merged = next(n for n in g["nodes"] if n["id"] == "c:201")
    assert merged["dual"] is True            # 회사(조합1호 투자 유치) + 투자자(베타·감마)
    assert merged["out_deg"] == 2
    assert "(주)알파" in merged.get("aliases", [])   # 원표기 보존
    assert "c:202" in ids                    # 동명 별개 법인 노드는 그대로 유지


def test_without_actor_corp_ids_fold_collision_stays_split():
    """actor_corp_ids가 없으면 기존 모호 가드 유지 — 병합하지 않는다(회귀 고정)."""
    data = _dup_name_sightings()
    del data["actor_corp_ids"]
    g = build_graph(data, min_companies=2)
    assert "a:(주)알파" in {n["id"] for n in g["nodes"]}


def test_actor_corp_ids_unknown_corp_ignored():
    """해석된 corp_code가 그래프에 회사로 실존하지 않으면 무시 — 라벨이 코드
    숫자로 남는 병합을 만들지 않는다."""
    data = _dup_name_sightings()
    data["actor_corp_ids"] = {"999": "(주)알파"}
    g = build_graph(data, min_companies=2)
    assert "a:(주)알파" in {n["id"] for n in g["nodes"]}
    assert "c:999" not in {n["id"] for n in g["nodes"]}
```

- [ ] **Step 2: 실패 확인** — `python -m pytest tests/test_build_network_html.py -v -k actor_corp` → 3건 FAIL (병합 미구현)
- [ ] **Step 3: 최소 구현** — `build_graph`의 fold2cc 생성(90행) 직후에 역맵 추가, `canon_actor_id` 수정:

```python
    # actor_corp_ids(디스커버 self-heal, reconcile_corp_renames) 역맵 —
    # 정본 행위자 키 → corp_code. 명부 해석이 끝난 법인 키는 fold 충돌
    # (동명 회사)과 무관하게 병합한다. 회사 노드로 실존하는 corp_code만
    # 채택 — 아니면 병합해도 라벨이 코드 숫자로 남는다. 같은 키가 복수
    # corp_code의 정본이면(비정상 데이터) 모호로 보고 제외.
    actor_cc: dict = {}
    _seen_keys: set = set()
    for cc, k in (sightings.get("actor_corp_ids") or {}).items():
        if cc not in company_label:
            continue
        if k in _seen_keys:
            actor_cc.pop(k, None)
            continue
        _seen_keys.add(k)
        actor_cc[k] = cc

    def canon_actor_id(nm: str) -> str:
        cc = actor_cc.get(nm) or fold2cc.get(fold_name(nm))
        return ("c:" + cc) if cc else ("a:" + nm)
```

- [ ] **Step 4: 통과 확인** — `python -m pytest tests/test_build_network_html.py -v` 전체 PASS (기존 테스트 포함)
- [ ] **Step 5: 커밋** — `git add scripts/build_network_html.py tests/test_build_network_html.py && git commit` (`feat(network): actor_corp_ids 1순위 병합 — fold 충돌에도 동일 법인 노드 단일화`)

---

### Task 2: 검색 리스트 시장 배지 + 동명 별개 법인 사실 주석 (템플릿)

**Files:**
- Modify: `scripts/network_template.html` — `renderSearchResults`(~1384행 row.innerHTML), `openDetail` meta 블록(~1215행), 전역 초기화부(nodes 정의 이후)

**Interfaces:**
- Consumes: 노드 필드 `n.mkt`(빌더가 이미 부여), `mtag(mkt)` 헬퍼(1092행 기존)
- Produces: UI 변경만 — 파이썬 API 불변

- [ ] **Step 1: 동명 카운트 맵 추가** — `mtag` 함수 정의 바로 아래에 삽입:

```js
// 동명 별개 법인 감지 — 같은 라벨의 노드 수. corp_code가 달라 병합되지 않은
// 실존 동명 실체를 상세에서 구분 안내한다(사실 표기 — 합병·계열 판정 아님).
const labelCount = {};
nodes.forEach(n => { labelCount[n.label] = (labelCount[n.label] || 0) + 1; });
```

- [ ] **Step 2: 검색 행에 시장 배지 병기** — `renderSearchResults`의 `row.innerHTML` 3줄을 다음으로 교체 (회사·이중역할 노드만 배지, 행위자는 기존 그대로):

```js
    row.innerHTML = `<span class="${dotCls}"${dotStyle}></span>` +
      `<span class="cname">${esc(n.label)}</span>` +
      ((n.type === "company" || n.dual) && n.mkt ? mtag(n.mkt) : "") +
      `<span class="qr-kind">${kindKo}</span>`;
```

- [ ] **Step 3: 상세 패널 동명 주석** — `openDetail`의 aliases 표시(`⚑ 다른 이름`) 직후에 추가:

```js
  if ((labelCount[n.label] || 0) > 1)
    meta.innerHTML += `<span class="aka">⚠ 동명 별개 법인 ${labelCount[n.label] - 1}건 — ` +
      `이름이 같아도 corp_code가 다른 별도 실체입니다</span>`;
```

- [ ] **Step 4: 재생성 스모크** — `SIGHTINGS_PATH=C:/Users/anboy/vibecoding/dart-risk-mcp/tmp/sightings.json python scripts/build_network_html.py --out <scratchpad>/network_check.html` 성공 + 출력 HTML에 `동명 별개 법인`·`labelCount` 문자열 존재 확인 (`grep -c`)
- [ ] **Step 5: 커밋** — `git add scripts/network_template.html && git commit` (`feat(network): 검색 리스트 시장 배지 + 동명 별개 법인 사실 주석`)

---

### Task 3: `_corp_name_index` 동명 해석 정책 명시화 (계약 고정)

**Files:**
- Modify: `scripts/discover_actors.py:572-586` (`_corp_name_index` docstring)
- Test: `tests/test_discover_actors.py`

**Interfaces:**
- Consumes: `dart_client._merge_corp_entry(cache, mdates, name, code, stock, mdate)` (기존, v1.10.1)
- Produces: 동작 변경 없음 — 암묵 정책의 docstring 명문화 + 회귀 고정 테스트

- [ ] **Step 1: 계약 테스트 작성** — `tests/test_discover_actors.py`에 추가:

```python
def test_corp_name_index_same_name_prefers_listed(monkeypatch):
    """동명 상장+비상장 법인이 명부에 공존하면 _corp_cache의 상장 우선 병합
    (_merge_corp_entry)을 이어받아 상장사 corp_code 단독으로 해석된다 —
    에이프로젠(00152385 상장 vs 00549059 비상장) 실측 사례의 계약화.
    이 덕에 reconcile_corp_renames가 '(주)에이프로젠'류 행위자 키를
    모호 없이 상장사로 귀속한다(비상장 동명 법인이 실제 행위자일 가능성은
    잔존 한계 — 설계 문서 Task 4 리스크 참고)."""
    from dart_risk_mcp.core import dart_client as dc
    from dart_risk_mcp.core.known_actors import fold_name
    import scripts.discover_actors as da
    cache, mdates = {}, {}
    # 비상장이 먼저 등장 + modify_date도 더 최신이지만 상장이 이긴다
    dc._merge_corp_entry(cache, mdates, "에이프로젠", "00549059", "", "20260101")
    dc._merge_corp_entry(cache, mdates, "에이프로젠", "00152385", "007460", "20230101")
    assert cache["에이프로젠"]["corp_code"] == "00152385"
    monkeypatch.setattr(dc, "_load_corp_codes", lambda key: None)
    monkeypatch.setattr(dc, "_corp_cache", cache)
    idx = da._corp_name_index("dummy-key")
    assert idx[fold_name("에이프로젠")] == {"00152385"}
```

- [ ] **Step 2: 실행 확인** — `python -m pytest tests/test_discover_actors.py -v -k prefers_listed` → PASS면 계약이 이미 성립(고정 완료), FAIL이면 `_merge_corp_entry` 회귀이므로 중단·보고
- [ ] **Step 3: docstring 보강** — `_corp_name_index` docstring에 1문단 추가:

```
    동명 법인(같은 corp_name, 다른 corp_code)은 _corp_cache가 이름 키 dict라
    _merge_corp_entry의 '상장 우선' 정책으로 한쪽만 남는다 — 즉 이 인덱스의
    동명 해석은 암묵이 아닌 그 정책의 의도된 계승이다(에이프로젠 00152385
    상장 vs 00549059 비상장 실측). 비상장 동명 법인이 실제 행위자인 경우의
    오귀속 가능성은 알려진 한계로, 완전한 해소는 공시 원문의 추가 식별자
    (주소·대표자)가 필요해 비범위.
```

- [ ] **Step 4: 전체 테스트** — `python -m pytest tests/test_discover_actors.py -v` PASS
- [ ] **Step 5: 커밋** — (`docs(actors): _corp_name_index 동명 해석의 상장 우선 정책 명문화 + 계약 테스트`)

---

### Task 4: 운영 — 옛 상호 백필 창 확대 + 최신 데이터 재생성·검증 (오케스트레이터 직접)

private 데이터(실명)·API 키를 다루므로 서브에이전트가 아닌 메인 세션에서 수행.

- [ ] **Step 1**: `gh repo clone anboyu-alt/dart-risk-mcp-sightings <scratchpad>/sightings-repo` (접근 확인 완료 — 2026-08-02 갱신 리포)
- [ ] **Step 2**: 최신 sightings로 현재 상태 베이스라인 — `(주)에이프로젠`·`(주)에이프로젠케이아이씨` alias/actor_corp_ids 존재 여부 기록
- [ ] **Step 3**: `SIGHTINGS_PATH=<clone>/sightings.json python scripts/backfill_renames.py --start 2015-01-01` (DART_API_KEY는 tmp/_apikey.txt 자동 로드, 장시간 — 백그라운드 실행)
- [ ] **Step 4**: 검증 — `corp_renames`에 00152385(에이프로젠케이아이씨 표기) 포함 여부, `aliases['(주)에이프로젠케이아이씨']` 정본 귀속 여부 확인
- [ ] **Step 5**: `SIGHTINGS_PATH=<clone>/sightings.json python scripts/build_network_html.py --out C:/Users/anboy/vibecoding/dart-risk-mcp/tmp/network.html` 재생성 (details.json 동반 갱신)
- [ ] **Step 6**: 종단 검증 — build_graph 결과에서 '에이프로젠' 검색 수렴 확인: `a:(주)에이프로젠`·`a:(주)에이프로젠케이아이씨` 노드 부재, `c:00152385` dual+별칭 포함, `c:00549059` 비상장 유지. 결과를 사용자 보고에 수치로 포함
- [ ] **Step 7**: sightings-repo 변경분 커밋·push (`chore: 상호변경안내 백필 창 확대(2015~) — 옛 상호 소급 별칭`)

---

### Task 5: 문서 갱신 + PR

- [ ] **Step 1**: `CLAUDE.md` 연결망 항목(`build_network_html.py` 소개 문장)에 병합 우선순위 1줄 추가: "노드 병합 우선순위는 actor_corp_ids(명부 해석) > fold2cc(비모호 fold) > 미병합이며, 동명 별개 법인은 병합하지 않고 검색 배지·상세 주석으로 구분한다(v1.11.0)."
- [ ] **Step 2**: 설계 문서(`2026-08-03-actor-network-entity-dedup-plan.md`) 상태를 "구현 완료(PR #)"로 갱신, Task 0/2 실측 결과 부록 추가
- [ ] **Step 3**: `python -m pytest tests/ -x -q` 전체 회귀 확인
- [ ] **Step 4**: 커밋 + PR 생성 (base master). PR 본문에 회귀 영향 분석 명시(메모리 지침): 하위 호환(actor_corp_ids 없는 옛 sightings → 기존 동작 그대로 — Task 1 회귀 테스트로 고정), 템플릿 변경은 표시 전용, 테스트 통과 수 기재
