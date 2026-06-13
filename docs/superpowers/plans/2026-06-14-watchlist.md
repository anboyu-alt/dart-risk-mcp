# 워치리스트 (인물↔회사군 영속 매핑) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 감시 대상 인물↔회사군 매핑을 영속 저장하고, `manage_watchlist` 도구와 `find_actor_overlap` 연동으로 저장된 세력을 바로 재조회한다.

**Architecture:** 순수 파일 I/O 모듈 `core/watchlist.py`(JSON 영속)를 신설하고, MCP 도구 `manage_watchlist`(list/show/add/remove)와 `find_actor_overlap`의 `watchlist` 파라미터로 연동한다. 실시간 알림·자동 스캔은 비범위, 저장+수동조회까지만.

**Tech Stack:** Python 3.11+, 표준 라이브러리만(`json`, `pathlib`, `datetime`), `unittest`+`pytest`. 외부 라이브러리 추가 없음.

---

## File Structure

- `dart_risk_mcp/core/watchlist.py` — 순수 파일 I/O (신규)
- `dart_risk_mcp/core/__init__.py` — export 추가
- `dart_risk_mcp/server.py` — `manage_watchlist` 도구 신규 + `find_actor_overlap` watchlist 연동
- `tests/test_watchlist.py` — watchlist.py 단위 테스트 (신규)
- `tests/test_manage_watchlist.py` — manage_watchlist 도구 테스트 (신규)
- `tests/test_find_actor_overlap.py` — watchlist 연동 테스트 추가 (기존)
- `CLAUDE.md` — 도구 목록·함수표·저장구조·디렉토리 갱신

---

## Task 1: `core/watchlist.py` — 영속 저장 모듈

**Files:**
- Create: `dart_risk_mcp/core/watchlist.py`
- Test: `tests/test_watchlist.py` (신규)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_watchlist.py`:

```python
import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestWatchlist(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._path = str(Path(self._tmp.name) / "watchlist.json")
        self._env = patch.dict("os.environ", {"DART_WATCHLIST_PATH": self._path})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def test_load_missing_file_returns_empty(self):
        from dart_risk_mcp.core.watchlist import load_watchlist
        self.assertEqual(load_watchlist(), {"version": 1, "persons": {}})

    def test_add_then_load_round_trip(self):
        from dart_risk_mcp.core.watchlist import add_person, load_watchlist
        add_person("신승수", ["CG인바이츠", "티쓰리"], note="겸직")
        data = load_watchlist()
        self.assertIn("신승수", data["persons"])
        self.assertEqual(data["persons"]["신승수"]["companies"], ["CG인바이츠", "티쓰리"])
        self.assertEqual(data["persons"]["신승수"]["note"], "겸직")
        self.assertIn("updated", data["persons"]["신승수"])

    def test_add_merges_companies_union_preserving_order(self):
        from dart_risk_mcp.core.watchlist import add_person, get_person_companies
        add_person("신승수", ["CG인바이츠", "티쓰리"])
        add_person("신승수", ["티쓰리", "헬스커넥트"])  # 티쓰리 중복
        self.assertEqual(get_person_companies("신승수"),
                         ["CG인바이츠", "티쓰리", "헬스커넥트"])

    def test_remove_person(self):
        from dart_risk_mcp.core.watchlist import add_person, remove_person, get_person_companies
        add_person("신승수", ["CG인바이츠"])
        self.assertTrue(remove_person("신승수"))
        self.assertFalse(remove_person("신승수"))  # 두 번째는 없음
        self.assertEqual(get_person_companies("신승수"), [])

    def test_get_companies_unknown_returns_empty(self):
        from dart_risk_mcp.core.watchlist import get_person_companies
        self.assertEqual(get_person_companies("없는사람"), [])

    def test_load_corrupt_json_returns_empty(self):
        from dart_risk_mcp.core.watchlist import load_watchlist
        Path(self._path).write_text("{ not valid json", encoding="utf-8")
        self.assertEqual(load_watchlist(), {"version": 1, "persons": {}})

    def test_list_persons_sorted_with_counts(self):
        from dart_risk_mcp.core.watchlist import add_person, list_persons
        add_person("오종원", ["인트로메딕"])
        add_person("신승수", ["CG인바이츠", "티쓰리"])
        # 가나다순 정렬: "신승수" < "오종원"
        self.assertEqual(list_persons(), [("신승수", 2), ("오종원", 1)])


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_watchlist.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'dart_risk_mcp.core.watchlist'`

- [ ] **Step 3: 구현**

`dart_risk_mcp/core/watchlist.py` (신규):

```python
"""인물↔회사군 워치리스트 영속 저장 (순수 파일 I/O, requests 무관)."""
import json
import os
from datetime import datetime
from pathlib import Path

_DEFAULT_PATH = Path.home() / ".config" / "dart-risk-mcp" / "watchlist.json"
_EMPTY = {"version": 1, "persons": {}}


def _watchlist_path() -> Path:
    override = os.environ.get("DART_WATCHLIST_PATH")
    return Path(override) if override else _DEFAULT_PATH


def load_watchlist() -> dict:
    """파일을 읽어 dict 반환. 없거나 손상 시 빈 구조(예외 비전파)."""
    try:
        with open(_watchlist_path(), encoding="utf-8") as f:
            data = json.load(f)
        if not isinstance(data, dict) or not isinstance(data.get("persons"), dict):
            return {"version": 1, "persons": {}}
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError):
        return {"version": 1, "persons": {}}


def save_watchlist(data: dict) -> None:
    path = _watchlist_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)


def add_person(person: str, companies: list[str], note: str = "") -> dict:
    """인물 추가/갱신. companies는 기존과 합집합 병합(순서 보존). 갱신 엔트리 반환."""
    data = load_watchlist()
    persons = data.setdefault("persons", {})
    existing = persons.get(person, {})
    old = existing.get("companies", [])
    merged = list(dict.fromkeys(old + [c for c in companies if c]))
    entry = {
        "companies": merged,
        "note": note if note else existing.get("note", ""),
        "updated": datetime.now().strftime("%Y-%m-%d"),
    }
    persons[person] = entry
    save_watchlist(data)
    return entry


def remove_person(person: str) -> bool:
    data = load_watchlist()
    persons = data.get("persons", {})
    if person in persons:
        del persons[person]
        save_watchlist(data)
        return True
    return False


def get_person_companies(person: str) -> list[str]:
    data = load_watchlist()
    return list(data.get("persons", {}).get(person, {}).get("companies", []))


def list_persons() -> list[tuple[str, int]]:
    data = load_watchlist()
    return sorted(
        (name, len(e.get("companies", [])))
        for name, e in data.get("persons", {}).items()
    )
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_watchlist.py -q`
Expected: PASS (7 passed)

- [ ] **Step 5: 커밋**

```bash
git add dart_risk_mcp/core/watchlist.py tests/test_watchlist.py
git commit -m "feat(watchlist): add persistent person-to-companies store"
```

---

## Task 2: `core/__init__.py` export

**Files:**
- Modify: `dart_risk_mcp/core/__init__.py`

- [ ] **Step 1: export 추가**

`dart_risk_mcp/core/__init__.py` 끝부분(import 블록들 뒤, `__all__` 앞)에 추가:

```python
from .watchlist import (
    load_watchlist,
    save_watchlist,
    add_person,
    remove_person,
    get_person_companies,
    list_persons,
)
```

그리고 `__all__` 리스트에 추가:

```python
    "load_watchlist",
    "save_watchlist",
    "add_person",
    "remove_person",
    "get_person_companies",
    "list_persons",
```

- [ ] **Step 2: import 검증**

Run: `python -c "from dart_risk_mcp.core import add_person, get_person_companies, list_persons; print('OK')"`
Expected: `OK`

- [ ] **Step 3: 커밋**

```bash
git add dart_risk_mcp/core/__init__.py
git commit -m "chore(core): export watchlist functions"
```

---

## Task 3: `manage_watchlist` MCP 도구

**Files:**
- Modify: `dart_risk_mcp/server.py` (import 블록 + 새 도구, `find_actor_overlap` 데코레이터 `@mcp.tool()`(server.py:1038) 바로 앞에 삽입)
- Test: `tests/test_manage_watchlist.py` (신규)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_manage_watchlist.py`:

```python
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestManageWatchlist(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._env = patch.dict(
            "os.environ",
            {"DART_WATCHLIST_PATH": str(Path(self._tmp.name) / "wl.json")},
        )
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def test_add_show_list_remove_flow(self):
        from dart_risk_mcp.server import manage_watchlist

        add = manage_watchlist("add", "신승수", ["CG인바이츠", "티쓰리"], "겸직")
        self.assertIn("신승수", add)
        self.assertIn("CG인바이츠", add)

        listed = manage_watchlist("list")
        self.assertIn("신승수", listed)
        self.assertIn("2개사", listed)

        shown = manage_watchlist("show", "신승수")
        self.assertIn("티쓰리", shown)
        self.assertIn("겸직", shown)

        removed = manage_watchlist("remove", "신승수")
        self.assertIn("삭제", removed)
        self.assertIn("비어 있", manage_watchlist("list"))

    def test_invalid_action(self):
        from dart_risk_mcp.server import manage_watchlist
        self.assertIn("입력 오류", manage_watchlist("frobnicate"))

    def test_add_requires_person_and_companies(self):
        from dart_risk_mcp.server import manage_watchlist
        self.assertIn("입력 오류", manage_watchlist("add", "", ["x"]))
        self.assertIn("입력 오류", manage_watchlist("add", "신승수", []))

    def test_show_unknown_person(self):
        from dart_risk_mcp.server import manage_watchlist
        self.assertIn("없습니다", manage_watchlist("show", "유령"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_manage_watchlist.py -q`
Expected: FAIL — `ImportError: cannot import name 'manage_watchlist'`

- [ ] **Step 3: 구현**

(3a) `server.py`의 `from .core import (...)` 블록에 watchlist 함수 추가(알파벳/기존 순서에 맞게 한 줄씩):

```python
    add_person,
    get_person_companies,
    list_persons,
    remove_person,
```

(3b) `find_actor_overlap`의 `@mcp.tool()` 데코레이터(server.py:1038) **바로 앞**에 새 도구 삽입:

```python
@mcp.tool()
def manage_watchlist(
    action: str,
    person: str = "",
    companies: list[str] | None = None,
    note: str = "",
) -> str:
    """감시 대상 인물↔회사군 워치리스트를 관리한다 (list / show / add / remove).

    DART는 인물명 역검색이 불가능해 회사 목록을 직접 입력해야 한다. 자주 보는
    인물의 연관 회사군을 저장해두면 find_actor_overlap(watchlist=인물명)으로 바로
    재조회할 수 있다. 회사군은 사용자가 직접 채운다(예: find_actor_overlap의 임원
    겸직 결과를 add).

    Args:
        action: "list" | "show" | "add" | "remove"
        person: 인물명 (show/add/remove에 필요)
        companies: 회사명 목록 (add에 필요, 기존과 합집합 병합)
        note: 메모 (add 시 선택)
    """
    companies = list(companies or [])
    act = (action or "").strip().lower()

    if act == "list":
        rows = list_persons()
        if not rows:
            return ("워치리스트가 비어 있습니다. "
                    "manage_watchlist(action='add', person='홍길동', "
                    "companies=['회사1','회사2'])로 추가하세요.")
        lines = ["📋 워치리스트 등록 인물:"]
        for name, cnt in rows:
            lines.append(f"  • {name} — {cnt}개사")
        return "\n".join(lines)

    if act == "show":
        if not person:
            return "입력 오류: show에는 person이 필요합니다."
        comps = get_person_companies(person)
        if not comps:
            return f"'{person}'은(는) 워치리스트에 없습니다."
        note_txt = load_watchlist().get("persons", {}).get(person, {}).get("note", "")
        lines = [f"👤 {person} — {len(comps)}개사:"]
        for c in comps:
            lines.append(f"  • {c}")
        if note_txt:
            lines.append(f"메모: {note_txt}")
        lines.append(f"→ find_actor_overlap(watchlist='{person}') 으로 분석할 수 있습니다.")
        return "\n".join(lines)

    if act == "add":
        if not person or not companies:
            return "입력 오류: add에는 person과 companies(1개 이상)가 필요합니다."
        entry = add_person(person, companies, note)
        return (f"✅ '{person}' 갱신 — 총 {len(entry['companies'])}개사: "
                f"{', '.join(entry['companies'])}")

    if act == "remove":
        if not person:
            return "입력 오류: remove에는 person이 필요합니다."
        ok = remove_person(person)
        return (f"🗑 '{person}' 삭제됨." if ok
                else f"'{person}'은(는) 워치리스트에 없습니다.")

    return "입력 오류: action은 list / show / add / remove 중 하나여야 합니다."
```

(3c) `load_watchlist`도 (3a) import 블록에 포함되어야 한다(show에서 사용). 추가:

```python
    load_watchlist,
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_manage_watchlist.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: 도구 등록 확인**

Run: `python -c "import dart_risk_mcp.server as s; print(len(s.mcp._tool_manager.list_tools()), 'manage_watchlist' in [t.name for t in s.mcp._tool_manager.list_tools()])"`
Expected: `24 True`

- [ ] **Step 6: 커밋**

```bash
git add dart_risk_mcp/server.py tests/test_manage_watchlist.py
git commit -m "feat(server): add manage_watchlist tool (list/show/add/remove)"
```

---

## Task 4: `find_actor_overlap` watchlist 연동

**Files:**
- Modify: `dart_risk_mcp/server.py` (`find_actor_overlap` 시그니처 + 초입 로직)
- Test: `tests/test_find_actor_overlap.py` (기존, 테스트 추가)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_find_actor_overlap.py`의 `TestFindActorOverlapMerging` 클래스에 추가:

```python
    def test_watchlist_loads_saved_companies(self):
        # watchlist 이름을 주면 저장된 회사군이 분석 대상이 된다
        import tempfile
        from pathlib import Path
        from dart_risk_mcp.server import find_actor_overlap
        from dart_risk_mcp.core.watchlist import add_person

        seen_corps = []

        def _resolve(query, api_key):
            seen_corps.append(query)
            return (query, {"corp_code": query.lower(), "stock_code": "000000"})

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {
                "DART_WATCHLIST_PATH": str(Path(tmp) / "wl.json"),
                "DART_API_KEY": "test_key",
            }):
                add_person("신승수", ["회사가", "회사나"])
                with patch("dart_risk_mcp.server.resolve_corp", side_effect=_resolve), \
                     patch("dart_risk_mcp.server.fetch_company_disclosures", return_value=[]), \
                     patch("dart_risk_mcp.server.fetch_executive_roster", return_value={}):
                    find_actor_overlap(watchlist="신승수")

        self.assertIn("회사가", seen_corps)
        self.assertIn("회사나", seen_corps)

    def test_watchlist_unknown_name_message(self):
        import tempfile
        from pathlib import Path
        from dart_risk_mcp.server import find_actor_overlap

        with tempfile.TemporaryDirectory() as tmp:
            with patch.dict("os.environ", {
                "DART_WATCHLIST_PATH": str(Path(tmp) / "wl.json"),
                "DART_API_KEY": "test_key",
            }):
                result = find_actor_overlap(["회사가", "회사나"], watchlist="유령")

        # 미등록 워치리스트는 안내하되 company_names로 계속 진행
        self.assertIn("유령", result)
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_find_actor_overlap.py -q`
Expected: FAIL — `test_watchlist_*` 가 `TypeError: unexpected keyword argument 'watchlist'`

- [ ] **Step 3: 구현 — 시그니처 + 초입 로직**

(3a) `find_actor_overlap` 시그니처를 변경:

```python
def find_actor_overlap(
    company_names: list[str] | None = None,
    lookback_years: int = 1,
    watchlist: str = "",
) -> str:
```

(3b) docstring `Args:` 에 한 줄 추가:

```python
        watchlist: 저장된 워치리스트 인물명. 지정 시 해당 회사군을 company_names와
            합집합으로 분석한다 (manage_watchlist로 관리).
```

(3c) 함수 본문 맨 앞(기존 `if not isinstance(company_names, list) ...` 검증 **앞**)에 삽입:

```python
    names = list(company_names or [])
    watchlist_note = ""
    if watchlist:
        wl_companies = get_person_companies(watchlist)
        if wl_companies:
            names = list(dict.fromkeys(names + wl_companies))
            watchlist_note = (f"ℹ️ 워치리스트 '{watchlist}'에서 "
                              f"{len(wl_companies)}개사를 불러왔습니다.")
        else:
            watchlist_note = (f"ℹ️ 워치리스트 '{watchlist}'를 찾지 못했습니다. "
                              "manage_watchlist(action='list')로 등록 인물을 확인하세요.")
    company_names = names
```

(3d) 기존 검증 라인은 그대로 두되, 검증 실패 시 watchlist 안내를 덧붙인다. 기존:

```python
    if not isinstance(company_names, list) or not (2 <= len(company_names) <= 5):
        return "입력 오류: 2개 이상 5개 이하 기업명(또는 종목코드) 리스트를 전달하세요."
```

를:

```python
    if not isinstance(company_names, list) or not (2 <= len(company_names) <= 5):
        base = "입력 오류: 2개 이상 5개 이하 기업명(또는 종목코드) 리스트를 전달하세요."
        return f"{base}\n{watchlist_note}" if watchlist_note else base
```

(3e) watchlist 안내를 정상 출력에도 노출: 요약 블록 직후에 삽입한다. 기존 `lines.append("")`(🎯 요약 블록과 본문 사이, `if failed:` 직전) 위치에서, `failed` 안내 블록 **앞**에 다음을 추가:

```python
    if watchlist_note:
        lines.append(watchlist_note)
        lines.append("")
```

(이 삽입 지점은 server.py에서 `if failed:` 로 시작하는 블록 바로 위다.)

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_find_actor_overlap.py -q`
Expected: PASS (11 passed — 기존 9 + 신규 2)

- [ ] **Step 5: 전체 스위트 + hygiene 회귀 확인**

Run: `python -m pytest tests/ -q`
Expected: 신규 회귀 0. 기존 골드 `actor_overlap.txt`는 watchlist 미사용이라 출력 불변. (사전 존재 실패 `test_audit_opinion_history.py::TestCheckDisclosureAnomalyAuditBonus` 2건은 변동 없음)

- [ ] **Step 6: 커밋**

```bash
git add dart_risk_mcp/server.py tests/test_find_actor_overlap.py
git commit -m "feat(find_actor_overlap): load company set from watchlist param"
```

---

## Task 5: 라이브 검증 + CLAUDE.md 문서

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 라이브 검증 (add → watchlist 조회)**

API 키는 메인 워크트리 `tmp/_apikey.txt`. 임시 워치리스트 경로로 add 후 조회:

```bash
cd <worktree>
TMPWL=$(mktemp -u)
PYTHONIOENCODING=utf-8 DART_WATCHLIST_PATH="$TMPWL" \
DART_API_KEY="$(cat /c/Users/anboy/vibecoding/dart-risk-mcp/tmp/_apikey.txt | tr -d '[:space:]')" \
python -c "
from dart_risk_mcp.server import manage_watchlist, find_actor_overlap
print(manage_watchlist('add', '신승수', ['이엠앤아이','제이케이시냅스','CG인바이츠','헬스커넥트','티쓰리'], '코스닥 다수 등기임원 겸직'))
print('---')
print(find_actor_overlap(watchlist='신승수', lookback_years=3))
"
rm -f "$TMPWL"
```

Expected: add 출력에 "✅ '신승수' 갱신 — 총 5개사"; find_actor_overlap 출력에 "워치리스트 '신승수'에서 5개사를 불러왔습니다" + 신승수 겸직 공통 행위자 라인.

- [ ] **Step 2: CLAUDE.md 갱신**

1. **MCP 도구 개수**: "23개" → "24개" (헤더/문장)
2. **새 도구 항목** 추가(도구 #24): `manage_watchlist(action, person, companies, note)` — list/show/add/remove, 인물↔회사군 영속 매핑. 저장+수동조회까지만(실시간 알림 비범위)
3. **도구 #5 `find_actor_overlap`**: 시그니처에 `watchlist=""` 추가, "저장된 워치리스트 인물명으로 회사군 자동 로드(합집합)" 한 줄
4. **디렉토리 구조**: `core/watchlist.py` 추가(인물↔회사군 영속 저장)
5. **핵심 내부 함수 표** 또는 별도 절: `core/watchlist.py`의 add_person/remove_person/get_person_companies/list_persons/load_watchlist/save_watchlist
6. **캐시 구조 표**: `watchlist.json` 행 추가 — 저장 위치 `~/.config/dart-risk-mcp/watchlist.json`(또는 `DART_WATCHLIST_PATH`), TTL "영속(비휘발)"

- [ ] **Step 3: 커밋**

```bash
git add CLAUDE.md
git commit -m "docs: document manage_watchlist tool and watchlist.json store"
```

---

## 검증 체크리스트 (완료 전)

- [ ] `test_watchlist.py` 7개 PASS
- [ ] `test_manage_watchlist.py` 4개 PASS
- [ ] `find_actor_overlap` 11개 PASS (기존 9 + 신규 2)
- [ ] 전체 스위트: 신규 회귀 0 (사전 존재 env 실패 2건 외)
- [ ] hygiene 9/9 PASS, 기존 `actor_overlap.txt` 골드 불변
- [ ] 도구 24개, `manage_watchlist` 등록 확인
- [ ] 라이브: add → find_actor_overlap(watchlist=...) 회사군 로드 + 겸직 탐지
- [ ] CLAUDE.md 6곳 갱신
```
