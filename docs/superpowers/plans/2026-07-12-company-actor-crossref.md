# 회사→인물 레지스트리 역방향 대조 섹션 구현 계획

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `analyze_company_risk`·`build_event_timeline` 리포트 말미에, 조회한 회사가 `관련기업`으로 태깅된 공개기록 레지스트리 행위자를 자동 표면화하는 섹션을 추가한다.

**Architecture:** `core/known_actors.py`에 회사명 역방향 조회 함수(`lookup_actors_by_company`), `server.py`에 공용 렌더 헬퍼(`_registry_company_section`)를 추가하고 두 도구의 리턴 직전에 섹션을 append한다. 매칭 0건·레지스트리 미설정 시 섹션 무출력.

**Tech Stack:** Python 3.11+, 표준 라이브러리만 (신규 의존성 없음). 테스트는 unittest + pytest 러너.

**Spec:** `docs/superpowers/specs/2026-07-12-company-actor-crossref-design.md`

## Global Constraints

- 외부 라이브러리 추가 금지 (`requests`, `mcp` 외 불가)
- 점수·등급·판정 표기 금지 (v0.8.5 원칙) — 사실 표기 + status별 면책만
- sightings 데이터 사용 금지 — 데이터 원천은 Notion 레지스트리(24h 캐시)뿐
- 예외를 도구 레벨로 전파하지 않음 (레지스트리 실패 = 빈 결과)
- 출력 문구는 한국어, 기존 "📎 공개기록 참고 (사실 표기 — 판정 아님)" 포맷 유지
- 커밋 메시지 끝: `Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>`

---

### Task 1: `lookup_actors_by_company` (core)

**Files:**
- Modify: `dart_risk_mcp/core/known_actors.py` (파일 끝, `lookup_actor` 뒤)
- Modify: `dart_risk_mcp/core/__init__.py:55` (import), `:143-144` 근처 (`__all__`)
- Test: `tests/test_known_actors.py` (기존 파일에 테스트 추가)

**Interfaces:**
- Consumes: `load_known_actors()`, `normalize_name(name)` (기존, 같은 모듈)
- Produces: `lookup_actors_by_company(company_name: str) -> list[tuple[str, dict]]` — `(인물명, 기록dict)` 리스트, 인물명 오름차순. Task 2가 사용.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_known_actors.py`의 `TestKnownActors` 클래스에 추가 (기존 `setUp`이 `DART_KNOWN_ACTORS_PATH`를 임시 파일로 patch하므로 그대로 활용):

```python
    def test_lookup_by_company_matches(self):
        from dart_risk_mcp.core.known_actors import lookup_actors_by_company
        self._write({"version": 1, "actors": {
            "신승수": [
                {"source": "DART 임원현황", "evidence": "CG인바이츠 등기임원",
                 "date": "2024", "status": "verified",
                 "companies": ["CG인바이츠", "이엠앤아이"]},
                {"source": "CB 인수", "evidence": "티쓰리 CB",
                 "date": "2023", "status": "verified", "companies": ["티쓰리"]},
            ],
            "이호영": [
                {"source": "DART 임원현황", "evidence": "이엠앤아이 등기임원",
                 "date": "2024", "status": "auto_matched",
                 "companies": ["이엠앤아이"]},
            ],
        }})
        hits = lookup_actors_by_company("이엠앤아이")
        # 인물명 오름차순, 해당 회사가 태깅된 기록만
        self.assertEqual([(n, r["source"]) for n, r in hits],
                         [("신승수", "DART 임원현황"), ("이호영", "DART 임원현황")])

    def test_lookup_by_company_normalized_match(self):
        from dart_risk_mcp.core.known_actors import lookup_actors_by_company
        self._write({"version": 1, "actors": {
            "LIU HUAN": [{"source": "자동 발굴", "evidence": "e",
                          "companies": ["ABC Holdings"]}],
        }})
        self.assertEqual(len(lookup_actors_by_company("abc  holdings")), 1)

    def test_lookup_by_company_no_match_or_blank(self):
        from dart_risk_mcp.core.known_actors import lookup_actors_by_company
        self._write({"version": 1, "actors": {
            "신승수": [{"source": "X", "evidence": "y", "companies": ["티쓰리"]}],
            "구기록": [{"source": "X", "evidence": "y"}],  # companies 필드 없는 구 기록
        }})
        self.assertEqual(lookup_actors_by_company("없는회사"), [])
        self.assertEqual(lookup_actors_by_company(""), [])
        self.assertEqual(lookup_actors_by_company("   "), [])

    def test_lookup_by_company_empty_registry(self):
        from dart_risk_mcp.core.known_actors import lookup_actors_by_company
        self._write({"version": 1, "actors": {}})
        self.assertEqual(lookup_actors_by_company("티쓰리"), [])
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_known_actors.py -v -k lookup_by_company`
Expected: 4건 FAIL/ERROR — `ImportError: cannot import name 'lookup_actors_by_company'`

- [ ] **Step 3: 구현** — `dart_risk_mcp/core/known_actors.py` 파일 끝(`lookup_actor` 함수 뒤)에 추가:

```python
def lookup_actors_by_company(company_name: str) -> list[tuple[str, dict]]:
    """회사명 역방향 조회 → [(인물명, 기록)] (없으면 []).

    각 기록의 companies(레지스트리 '관련기업' 태그)와 정규화 비교한다.
    반환은 인물명 오름차순 — 렌더 결정성(테스트 안정성) 보장.
    """
    if not company_name or not company_name.strip():
        return []
    want = normalize_name(company_name)
    actors = load_known_actors().get("actors", {})
    hits: list[tuple[str, dict]] = []
    for name in sorted(actors.keys()):
        for rec in actors[name]:
            comps = rec.get("companies") or []
            if any(normalize_name(c) == want for c in comps):
                hits.append((name, rec))
    return hits
```

`dart_risk_mcp/core/__init__.py` 55행을 다음으로 교체:

```python
from .known_actors import load_known_actors, lookup_actor, lookup_actors_by_company
```

`__all__`의 `"lookup_actor",` 항목(144행 근처) 바로 아래에 추가:

```python
    "lookup_actors_by_company",
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_known_actors.py -v`
Expected: 전체 PASS (기존 테스트 포함)

- [ ] **Step 5: 커밋**

```bash
git add dart_risk_mcp/core/known_actors.py dart_risk_mcp/core/__init__.py tests/test_known_actors.py
git commit -m "feat(core): 레지스트리 회사명 역방향 조회 lookup_actors_by_company 추가

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 2: `_registry_company_section` 렌더 헬퍼 (server)

**Files:**
- Modify: `dart_risk_mcp/server.py` — (a) core import 목록의 `lookup_actor,` 다음 줄에 `lookup_actors_by_company,` 추가 (55행 근처), (b) `# ── 도구 1` 섹션 주석 직전(모듈 레벨)에 헬퍼 함수 추가
- Test: `tests/test_registry_company_section.py` (신규)

**Interfaces:**
- Consumes: `lookup_actors_by_company(company_name)` (Task 1), `lookup_actor(name)` (기존)
- Produces: `_registry_company_section(corp_name: str) -> list[str]` — 섹션 라인 리스트, 매칭 0건이면 `[]`. Task 3이 사용.

- [ ] **Step 1: 실패하는 테스트 작성** — `tests/test_registry_company_section.py` 신규 생성:

```python
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestRegistryCompanySection(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._path = str(Path(self._tmp.name) / "ka.json")
        self._env = patch.dict("os.environ", {"DART_KNOWN_ACTORS_PATH": self._path})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def _write(self, data):
        Path(self._path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_empty_when_no_match(self):
        from dart_risk_mcp.server import _registry_company_section
        self._write({"version": 1, "actors": {}})
        self.assertEqual(_registry_company_section("티쓰리"), [])

    def test_renders_matched_records_only(self):
        from dart_risk_mcp.server import _registry_company_section
        self._write({"version": 1, "actors": {
            "신승수": [
                {"source": "DART 임원현황", "evidence": "CG인바이츠 등기임원",
                 "date": "2024", "status": "verified",
                 "companies": ["CG인바이츠", "이엠앤아이"]},
                {"source": "CB 인수", "evidence": "티쓰리 CB",
                 "date": "2023", "status": "verified", "companies": ["티쓰리"]},
            ],
        }})
        lines = _registry_company_section("이엠앤아이")
        text = "\n".join(lines)
        self.assertIn("공개기록 참고", text)
        self.assertIn("사실 표기 — 판정 아님", text)
        self.assertIn("신승수 — DART 임원현황(2024)", text)
        self.assertNotIn("티쓰리 CB", text)  # 다른 회사 기록은 미표시
        # 전체 기록 수(2) > 표시(1) → 드릴다운 안내
        self.assertIn('lookup_known_actor("신승수")', text)
        self.assertIn("전체 기록 2건", text)
        # 공통 면책
        self.assertIn("동명이인 가능성", text)

    def test_status_warnings(self):
        from dart_risk_mcp.server import _registry_company_section
        self._write({"version": 1, "actors": {
            "이호영": [{"source": "자동 발굴", "evidence": "e", "date": "2025",
                       "status": "auto_matched", "companies": ["티쓰리"]}],
            "김모니": [{"source": "제작자 등록", "evidence": "e2", "date": "2025",
                       "status": "maintainer_seed", "companies": ["티쓰리"]}],
        }})
        text = "\n".join(_registry_company_section("티쓰리"))
        self.assertIn("[자동 매칭 · 동명이인 미확인] 이호영", text)
        self.assertIn("동일인 여부 미확인", text)
        self.assertIn("제작자 모니터링 등록", text)

    def test_no_drilldown_hint_when_all_shown(self):
        from dart_risk_mcp.server import _registry_company_section
        self._write({"version": 1, "actors": {
            "신승수": [{"source": "X", "evidence": "y", "status": "verified",
                       "companies": ["티쓰리"]}],
        }})
        text = "\n".join(_registry_company_section("티쓰리"))
        self.assertNotIn("lookup_known_actor", text)


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_registry_company_section.py -v`
Expected: FAIL/ERROR — `ImportError: cannot import name '_registry_company_section'`

- [ ] **Step 3: 구현** — `dart_risk_mcp/server.py`:

(a) core import 목록에서 `lookup_actor,` 줄 바로 다음에 추가:

```python
    lookup_actors_by_company,
```

(b) `# ── 도구 1` 섹션 주석 직전에 모듈 레벨 함수 추가:

```python
def _registry_company_section(corp_name: str) -> list[str]:
    """회사→인물 레지스트리 역방향 대조 섹션 (매칭 없으면 []).

    사실 표기 전용 — 판정·점수 없음(v0.8.5). 해당 회사가 태깅된 기록만
    표시하고, 그 인물의 나머지 기록은 lookup_known_actor 안내로 위임한다.
    """
    hits = lookup_actors_by_company(corp_name)
    if not hits:
        return []
    lines = [
        "📎 공개기록 참고 (사실 표기 — 판정 아님): "
        "이 회사에 등장 기록이 있는 등재 행위자",
    ]
    has_auto = has_seed = False
    shown_counts: dict[str, int] = {}
    for nm, r in hits:
        st = r.get("status", "")
        has_auto = has_auto or st == "auto_matched"
        has_seed = has_seed or st == "maintainer_seed"
        prefix = "[자동 매칭 · 동명이인 미확인] " if st == "auto_matched" else ""
        src = r.get("source", "")
        date = r.get("date", "")
        tag = f"{src}({date})" if date else src
        lines.append(f"  • {prefix}{nm} — {tag}: {r.get('evidence', '')}")
        shown_counts[nm] = shown_counts.get(nm, 0) + 1
    for nm, n_shown in shown_counts.items():
        total = len(lookup_actor(nm))
        if total > n_shown:
            lines.append(
                f"    ({nm} 레지스트리 전체 기록 {total}건 — "
                f'자세히: lookup_known_actor("{nm}"))'
            )
    if has_auto:
        lines.append("  ⚠ 일부는 시장 공시 자동 매칭 (동일인 여부 미확인)")
    if has_seed:
        lines.append("  ⚠ 일부는 제작자 모니터링 등록 (공시 자동매칭 아님, 혐의·확정 아님)")
    lines.append("  ⚠ 원본 공시로 사실 확인 권장 · 동명이인 가능성 있음")
    return lines
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_registry_company_section.py -v`
Expected: 4건 PASS

- [ ] **Step 5: 커밋**

```bash
git add dart_risk_mcp/server.py tests/test_registry_company_section.py
git commit -m "feat(server): 회사 기준 레지스트리 대조 섹션 렌더 헬퍼 추가

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 3: 두 도구에 섹션 연결

**Files:**
- Modify: `dart_risk_mcp/server.py:647-651` (analyze_company_risk 리턴 직전 — 카탈로그 블록 뒤)
- Modify: `dart_risk_mcp/server.py:1098` (build_event_timeline 최종 면책 라인 직전)
- Test: 기존 스위트 + 골드 hygiene (신규 테스트 없음 — 렌더 로직은 Task 2에서 검증 완료, 여기는 배선만)

**Interfaces:**
- Consumes: `_registry_company_section(corp_name)` (Task 2). 두 도구 모두 지역변수 `corp_name`(resolve_corp 반환값) 보유.
- Produces: 없음 (최종 배선)

- [ ] **Step 1: analyze_company_risk 수정** — 현재 코드(647행 근처):

```python
    catalog = load_catalog_excerpt(tax_ids_all)
    if catalog:
        lines += ["", catalog]

    return _append_size_footer("\n".join(lines), lookback_years)
```

를 다음으로 교체:

```python
    catalog = load_catalog_excerpt(tax_ids_all)
    if catalog:
        lines += ["", catalog]

    reg_section = _registry_company_section(corp_name)
    if reg_section:
        lines += [""] + reg_section

    return _append_size_footer("\n".join(lines), lookback_years)
```

※ 주의: `return _append_size_footer(...)` + 그 위 catalog 블록 조합은 이 함수(analyze_company_risk)에만 있다. `check_disclosure_risk`(762행)·`find_risk_precedents`(845행)의 유사 블록은 `return "\n".join(lines)`라 구분된다 — 수정 대상 아님.

- [ ] **Step 2: build_event_timeline 수정** — 현재 코드(1098행 근처):

```python
    lines.append("⚠️ 이 타임라인은 공시 제목 기반 자동 분류이며, 실제 상황과 다를 수 있습니다.")
    return _append_size_footer("\n".join(lines), lookback_years)
```

를 다음으로 교체:

```python
    reg_section = _registry_company_section(corp_name)
    if reg_section:
        lines += reg_section + [""]

    lines.append("⚠️ 이 타임라인은 공시 제목 기반 자동 분류이며, 실제 상황과 다를 수 있습니다.")
    return _append_size_footer("\n".join(lines), lookback_years)
```

- [ ] **Step 3: 도구 docstring 한 줄씩 추가** — 각 도구 docstring의 Args 위 본문 끝에:

analyze_company_risk:
```
    공개기록 레지스트리(opt-in)가 설정돼 있고 이 회사가 등재 행위자의
    관련기업으로 태깅된 경우, 리포트 말미에 공개기록 참고 섹션이 추가된다.
```

build_event_timeline에도 동일 문구 추가.

- [ ] **Step 4: 전체 검증**

Run: `python -c "import dart_risk_mcp.server; print('OK')"`
Expected: `OK`

Run: `python -m pytest tests/ -q`
Expected: 전체 PASS (골드는 레지스트리 미주입 환경에서 생성됐고 미설정 시 섹션 무출력이므로 골드 무변경)

Run: `python -m pytest tests/test_golden_output_hygiene.py -v`
Expected: 전체 PASS

- [ ] **Step 5: 커밋**

```bash
git add dart_risk_mcp/server.py
git commit -m "feat: analyze_company_risk·build_event_timeline에 레지스트리 역방향 대조 섹션 연결

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```

---

### Task 4: 문서 갱신

**Files:**
- Modify: `CLAUDE.md` — 도구 1(`analyze_company_risk`)·도구 4(`build_event_timeline`) 절에 불릿 1줄씩, "핵심 내부 함수" `dart_client.py` 표 아님 → known_actors 관련 서술이 있는 도구 25(`lookup_known_actor`) 절 뒤 문맥 확인 후 함수 표에는 추가하지 않고 도구 절 불릿으로 충분 (함수 표는 dart_client.py 전용이므로)
- Modify: `README.md` — 두 도구 설명에 "공개기록 참고 섹션(레지스트리 opt-in 시)" 1줄

**Interfaces:** 없음 (문서만)

- [ ] **Step 1: CLAUDE.md 갱신** — 도구 1 절(`### 1. analyze_company_risk`) 불릿 목록 끝에:

```markdown
- 공개기록 레지스트리(opt-in) 설정 시, 이 회사가 등재 행위자의 관련기업으로 태깅돼 있으면 리포트 말미에 "📎 공개기록 참고" 섹션 자동 표면화 (`lookup_actors_by_company` 역방향 조회 — 사실 표기, 판정 없음)
```

도구 4 절(`### 4. build_event_timeline`)에도 동일 불릿 추가. 디렉토리 구조 절의 `known_actors.py` 설명에 "회사명 역방향 조회 포함" 문구 반영.

- [ ] **Step 2: README.md 갱신** — 두 도구 설명 위치를 `grep -n "analyze_company_risk\|build_event_timeline" README.md`로 찾아 각 설명에 1줄 추가:

```markdown
공개기록 레지스트리(opt-in)를 설정한 경우, 조회 회사에 등장 기록이 있는 등재 행위자가 리포트 말미에 사실 표기로 함께 안내됩니다.
```

포지셔닝 문구는 "공시 기반 불공정거래 위험 모니터링" 범위 유지 — "투자 위험" 류 표현 금지.

- [ ] **Step 3: 커밋**

```bash
git add CLAUDE.md README.md
git commit -m "docs: 레지스트리 역방향 대조 섹션 문서화

Co-Authored-By: Claude Fable 5 <noreply@anthropic.com>"
```
