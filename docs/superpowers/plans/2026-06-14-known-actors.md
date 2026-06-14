# 공개기록 행위자 레지스트리 (known_actors) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 출처가 명확한 공개기록(임원 겸직·CB/유상증자 인수)으로 특정 인물의 상장사 등장 이력을 동봉 데이터로 제공하고, `find_actor_overlap`이 탐지한 인물을 자동 대조해 사실을 표면화한다.

**Architecture:** 패키지 동봉 JSON(`data/known_actors.json`)을 순수 모듈(`core/known_actors.py`)이 로드/조회하고, 신규 도구 `lookup_known_actor`와 `find_actor_overlap` 연동이 소비한다. 근거는 부트스트랩 스크립트가 DART에서 집계해 채운다. 판정 없음·출처 필수·면책 동반.

**Tech Stack:** Python 3.11+, 표준 라이브러리만(`json`, `importlib.resources`), `unittest`+`pytest`. 외부 라이브러리 추가 없음.

---

## File Structure

- `dart_risk_mcp/data/known_actors.json` — 동봉 데이터 (신규, 초기엔 빈 구조)
- `dart_risk_mcp/core/known_actors.py` — 로드/조회 (신규)
- `dart_risk_mcp/core/__init__.py` — export 추가
- `dart_risk_mcp/server.py` — `lookup_known_actor` 도구 신규 + `find_actor_overlap` 대조 연동
- `scripts/build_known_actors.py` — 근거 집계 부트스트랩 (신규)
- `tests/test_known_actors.py` — 모듈 단위 (신규)
- `tests/test_lookup_known_actor.py` — 도구 (신규)
- `tests/test_find_actor_overlap.py` — 대조 연동 테스트 추가 (기존)
- `CLAUDE.md` / `README.md` — 문서 갱신

---

## Task 1: `core/known_actors.py` + 동봉 데이터 골격

**Files:**
- Create: `dart_risk_mcp/data/known_actors.json`
- Create: `dart_risk_mcp/core/known_actors.py`
- Test: `tests/test_known_actors.py`

- [ ] **Step 1: 빈 동봉 데이터 생성**

`dart_risk_mcp/data/known_actors.json`:

```json
{
  "version": 1,
  "updated": "2026-06-14",
  "actors": {}
}
```

- [ ] **Step 2: 실패 테스트 작성**

`tests/test_known_actors.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestKnownActors(unittest.TestCase):
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

    def test_lookup_returns_records(self):
        from dart_risk_mcp.core.known_actors import lookup_actor
        self._write({"version": 1, "actors": {
            "신승수": [{"source": "DART 임원현황", "evidence": "CG인바이츠 등기임원",
                       "url": "https://dart.fss.or.kr", "date": "2024", "tags": ["겸직"]}]
        }})
        recs = lookup_actor("신승수")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["source"], "DART 임원현황")

    def test_lookup_unknown_returns_empty(self):
        from dart_risk_mcp.core.known_actors import lookup_actor
        self._write({"version": 1, "actors": {}})
        self.assertEqual(lookup_actor("유령"), [])

    def test_lookup_strips_and_handles_blank(self):
        from dart_risk_mcp.core.known_actors import lookup_actor
        self._write({"version": 1, "actors": {"신승수": [{"source": "X", "evidence": "y"}]}})
        self.assertEqual(len(lookup_actor("  신승수  ")), 1)
        self.assertEqual(lookup_actor(""), [])

    def test_load_missing_file_returns_empty(self):
        from dart_risk_mcp.core.known_actors import load_known_actors
        # 파일 미생성 상태
        self.assertEqual(load_known_actors(), {"version": 1, "actors": {}})

    def test_load_corrupt_returns_empty(self):
        from dart_risk_mcp.core.known_actors import load_known_actors
        Path(self._path).write_text("{ broken", encoding="utf-8")
        self.assertEqual(load_known_actors(), {"version": 1, "actors": {}})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 3: 실패 확인**

Run: `python -m pytest tests/test_known_actors.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'dart_risk_mcp.core.known_actors'`

- [ ] **Step 4: 구현**

`dart_risk_mcp/core/known_actors.py`:

```python
"""공개기록 행위자 레지스트리 (동봉 데이터 로드/조회, 순수 표준 라이브러리)."""
import json
import os
from importlib import resources


def load_known_actors() -> dict:
    """동봉 known_actors.json 로드. 환경변수 DART_KNOWN_ACTORS_PATH로 오버라이드.

    파일 부재/손상 시 빈 구조 반환(예외 비전파).
    """
    override = os.environ.get("DART_KNOWN_ACTORS_PATH")
    try:
        if override:
            with open(override, encoding="utf-8") as f:
                data = json.load(f)
        else:
            text = (resources.files("dart_risk_mcp") / "data" / "known_actors.json").read_text(
                encoding="utf-8")
            data = json.loads(text)
        if not isinstance(data, dict) or not isinstance(data.get("actors"), dict):
            return {"version": 1, "actors": {}}
        return data
    except (FileNotFoundError, json.JSONDecodeError, OSError, ValueError, ModuleNotFoundError):
        return {"version": 1, "actors": {}}


def lookup_actor(name: str) -> list[dict]:
    """인물명 정확 매칭 → 기록 리스트(없으면 [])."""
    if not name or not name.strip():
        return []
    return list(load_known_actors().get("actors", {}).get(name.strip(), []))
```

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/test_known_actors.py -q`
Expected: PASS (5 passed)

- [ ] **Step 6: 커밋**

```bash
git add dart_risk_mcp/data/known_actors.json dart_risk_mcp/core/known_actors.py tests/test_known_actors.py
git commit -m "feat(known_actors): add public-record actor registry module + bundled data"
```

---

## Task 2: 패키지 데이터 포함 검증 + export

**Files:**
- Modify: `dart_risk_mcp/core/__init__.py`
- Verify: `pyproject.toml` (이미 `packages=["dart_risk_mcp"]`)

- [ ] **Step 1: export 추가**

`dart_risk_mcp/core/__init__.py`의 watchlist import 블록 아래에 추가:

```python
from .known_actors import load_known_actors, lookup_actor
```

그리고 `__all__`에 추가:

```python
    "load_known_actors",
    "lookup_actor",
```

- [ ] **Step 2: import 검증**

Run: `python -c "from dart_risk_mcp.core import lookup_actor; print('OK')"`
Expected: `OK`

- [ ] **Step 3: 빌드 산출물에 데이터 포함 확인**

Run: `python -m build 2>&1 | tail -2 && python -c "import zipfile,glob; w=glob.glob('dist/*.whl')[-1]; print([n for n in zipfile.ZipFile(w).namelist() if 'known_actors.json' in n])"`
Expected: `['dart_risk_mcp/data/known_actors.json']` (비어 있으면 pyproject.toml `[tool.hatch.build.targets.wheel]`에 `force-include` 또는 `artifacts = ["dart_risk_mcp/data/*.json"]` 추가 후 재빌드)

- [ ] **Step 4: 빌드 산출물 정리 + 커밋**

```bash
rm -rf dist/ build/
git add dart_risk_mcp/core/__init__.py pyproject.toml
git commit -m "chore(core): export known_actors functions, ensure data bundling"
```

---

## Task 3: `lookup_known_actor` 도구

**Files:**
- Modify: `dart_risk_mcp/server.py` (import + 새 도구, `manage_watchlist` `@mcp.tool()` 앞에 삽입)
- Test: `tests/test_lookup_known_actor.py` (신규)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_lookup_known_actor.py`:

```python
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestLookupKnownActor(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._path = str(Path(self._tmp.name) / "ka.json")
        Path(self._path).write_text(json.dumps({"version": 1, "actors": {
            "신승수": [{"source": "DART 임원현황", "evidence": "CG인바이츠 등기임원",
                       "url": "https://dart.fss.or.kr", "date": "2024", "tags": ["겸직"]}]
        }}, ensure_ascii=False), encoding="utf-8")
        self._env = patch.dict("os.environ", {"DART_KNOWN_ACTORS_PATH": self._path})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def test_known_person_renders_evidence_and_disclaimer(self):
        from dart_risk_mcp.server import lookup_known_actor
        out = lookup_known_actor("신승수")
        self.assertIn("CG인바이츠", out)
        self.assertIn("DART 임원현황", out)
        self.assertIn("판정", out)          # 면책 문구
        self.assertIn("동명이인", out)

    def test_unknown_person(self):
        from dart_risk_mcp.server import lookup_known_actor
        self.assertIn("없습니다", lookup_known_actor("유령"))


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_lookup_known_actor.py -q`
Expected: FAIL — `ImportError: cannot import name 'lookup_known_actor'`

- [ ] **Step 3: 구현**

(3a) `server.py`의 `from .core import (...)` 블록에 `lookup_actor` 추가(기존 watchlist 함수들 근처):

```python
    lookup_actor,
```

(3b) `manage_watchlist`의 `@mcp.tool()` 데코레이터 **바로 앞**에 새 도구 삽입:

```python
@mcp.tool()
def lookup_known_actor(name: str) -> str:
    """인물명으로 공개기록 레지스트리를 조회한다 (사실 표기 — 판정 아님).

    출처가 명확한 공개기록(DART 임원현황·CB/유상증자 인수 등)에 그 인물이 어느
    상장사에 등장했는지를 사실로만 반환한다. 위험 판정·점수·등급은 부여하지 않으며,
    동명이인 가능성과 원본 확인 필요를 함께 고지한다.

    Args:
        name: 조회할 인물명
    """
    records = lookup_actor(name)
    if not records:
        return (f"'{name}'에 대한 공개기록이 레지스트리에 없습니다. "
                "(등재는 공개 출처가 확인된 경우에만 이뤄집니다.)")
    lines = [f"📎 '{name}' 공개기록 (사실 표기 — 판정 아님):"]
    for r in records:
        src = r.get("source", "")
        ev = r.get("evidence", "")
        date = r.get("date", "")
        url = r.get("url", "")
        head = f"  • {src}"
        if date:
            head += f" ({date})"
        head += f": {ev}"
        lines.append(head)
        if url:
            lines.append(f"      출처: {url}")
    lines.append("⚠ 원본 공시로 사실 확인 권장 · 동명이인 가능성 있음 · 본 기록은 판정이 아닙니다.")
    return "\n".join(lines)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_lookup_known_actor.py -q`
Expected: PASS (2 passed)

- [ ] **Step 5: 도구 등록 확인**

Run: `python -c "import dart_risk_mcp.server as s; ts=[t.name for t in s.mcp._tool_manager.list_tools()]; print(len(ts), 'lookup_known_actor' in ts)"`
Expected: `25 True`

- [ ] **Step 6: 커밋**

```bash
git add dart_risk_mcp/server.py tests/test_lookup_known_actor.py
git commit -m "feat(server): add lookup_known_actor tool"
```

---

## Task 4: `find_actor_overlap` 공개기록 대조 연동

**Files:**
- Modify: `dart_risk_mcp/server.py` (`find_actor_overlap` 면책 문구 앞에 대조 섹션)
- Test: `tests/test_find_actor_overlap.py` (기존, 테스트 추가)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_find_actor_overlap.py`의 `TestFindActorOverlapMerging` 클래스에 추가:

```python
    def test_known_actor_cross_reference_appended(self):
        # 탐지된 임원이 공개기록 레지스트리에 있으면 참고 섹션이 붙는다
        import json, tempfile
        from pathlib import Path
        from dart_risk_mcp.server import find_actor_overlap

        def _resolve(query, api_key):
            return (query, {"corp_code": query.lower(), "stock_code": "000000"})

        def _roster(corp_code, api_key, lookback_years):
            if corp_code in ("a", "b"):
                return {"신승수": {"2024"}}
            return {}

        with tempfile.TemporaryDirectory() as tmp:
            ka = Path(tmp) / "ka.json"
            ka.write_text(json.dumps({"version": 1, "actors": {
                "신승수": [{"source": "DART 임원현황", "evidence": "CG인바이츠 등기임원",
                           "url": "https://dart.fss.or.kr", "date": "2024"}]
            }}, ensure_ascii=False), encoding="utf-8")
            with patch.dict("os.environ", {
                "DART_KNOWN_ACTORS_PATH": str(ka), "DART_API_KEY": "test_key",
            }):
                with patch("dart_risk_mcp.server.resolve_corp", side_effect=_resolve), \
                     patch("dart_risk_mcp.server.fetch_company_disclosures", return_value=[]), \
                     patch("dart_risk_mcp.server.fetch_executive_roster", side_effect=_roster):
                    result = find_actor_overlap(["a", "b"])

        self.assertIn("공개기록 참고", result)
        self.assertIn("신승수", result)
        self.assertIn("동명이인", result)

    def test_no_known_actor_no_section(self):
        # 레지스트리에 없으면 참고 섹션이 붙지 않는다
        import tempfile
        from pathlib import Path
        from dart_risk_mcp.server import find_actor_overlap

        def _resolve(query, api_key):
            return (query, {"corp_code": query.lower(), "stock_code": "000000"})

        with tempfile.TemporaryDirectory() as tmp:
            ka = Path(tmp) / "ka.json"
            ka.write_text('{"version":1,"actors":{}}', encoding="utf-8")
            with patch.dict("os.environ", {
                "DART_KNOWN_ACTORS_PATH": str(ka), "DART_API_KEY": "test_key",
            }):
                with patch("dart_risk_mcp.server.resolve_corp", side_effect=_resolve), \
                     patch("dart_risk_mcp.server.fetch_company_disclosures", return_value=[]), \
                     patch("dart_risk_mcp.server.fetch_executive_roster", return_value={}):
                    result = find_actor_overlap(["a", "b"])

        self.assertNotIn("공개기록 참고", result)
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_find_actor_overlap.py -q`
Expected: FAIL — `test_known_actor_cross_reference_appended` 가 "공개기록 참고" 미발견으로 실패

- [ ] **Step 3: 구현**

(3a) `find_actor_overlap`이 `lookup_actor`를 쓰도록 — 이미 Task 3 (3a)에서 server.py에 `lookup_actor`가 import됨.

(3b) `find_actor_overlap` 본문에서 **맨 끝 면책 문구 `lines.append("⚠️ 이 결과는 DART 공개 API ...")` 바로 앞**에 대조 섹션 삽입:

```python
    # 공개기록 대조 (사실 표면화 — 판정 아님)
    known_hits = []
    for nm in sorted(actor_map.keys()):
        recs = lookup_actor(nm)
        if recs:
            known_hits.append((nm, recs))
    if known_hits:
        lines.append("📎 공개기록 참고 (사실 표기 — 판정 아님):")
        for nm, recs in known_hits:
            for r in recs:
                src = r.get("source", "")
                date = r.get("date", "")
                ev = r.get("evidence", "")
                tag = f"{src}({date})" if date else src
                lines.append(f"  • {nm} — {tag}: {ev}")
        lines.append("  ⚠ 원본 공시로 사실 확인 권장 · 동명이인 가능성 있음")
        lines.append("")
```

(`actor_map`은 함수 내 이미 존재하는 dict — 탐지된 모든 인수자·임원 이름이 키다.)

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_find_actor_overlap.py -q`
Expected: PASS (13 passed — 기존 11 + 신규 2)

- [ ] **Step 5: 전체 스위트 + hygiene**

Run: `python -m pytest tests/ -q`
Expected: 신규 회귀 0. 기존 골드 `actor_overlap.txt`는 신승수군 라이브 골드인데, 시드가 빈 상태(Task 5 전)면 참고 섹션 미출현이라 골드 불변. (사전 존재 env 실패 2건 외)

- [ ] **Step 6: 커밋**

```bash
git add dart_risk_mcp/server.py tests/test_find_actor_overlap.py
git commit -m "feat(find_actor_overlap): cross-reference detected actors against known_actors"
```

---

## Task 5: 부트스트랩 스크립트 + 라이브 시드 생성

**Files:**
- Create: `scripts/build_known_actors.py`
- Modify: `dart_risk_mcp/data/known_actors.json` (라이브 집계 결과로 채움)

- [ ] **Step 1: 스크립트 작성**

`scripts/build_known_actors.py`:

```python
"""공개기록 행위자 레지스트리 부트스트랩.

인물명 + 후보 회사군을 받아, 그 인물이 등기임원 / CB·유상증자 인수자로 등장하는
회사·연도를 DART에서 집계해 dart_risk_mcp/data/known_actors.json 엔트리를 생성한다.
사람은 회사 단서만 주고, 근거(회사·연도·출처)는 코드가 채운다.

사용: python scripts/build_known_actors.py
API 키: tmp/_apikey.txt 또는 환경변수 DART_API_KEY.
"""
import json
import os
from pathlib import Path

from dart_risk_mcp.core.dart_client import (
    resolve_corp, fetch_executive_roster, fetch_company_disclosures,
)
from dart_risk_mcp.core.signals import match_signals, is_amendment_disclosure
from dart_risk_mcp.core.cb_extractor import extract_cb_investors
from dart_risk_mcp.core.investor_extractor import extract_rights_offering_investors

# 회사 단서가 있는 인물만 (CASSANDRA knowledge-base 기반, 회사명은 DART resolve 대상)
SEED = {
    "신승수": ["이엠앤아이", "제이케이시냅스", "CG인바이츠", "헬스커넥트", "티쓰리"],
    "오종원": ["인트로메딕"],
    "김준범": ["씨그널엔터테인먼트그룹"],
}
LOOKBACK_YEARS = 3
DATA_PATH = Path(__file__).resolve().parents[1] / "dart_risk_mcp" / "data" / "known_actors.json"


def _api_key() -> str:
    key = os.environ.get("DART_API_KEY")
    if key:
        return key.strip()
    p = Path(__file__).resolve().parents[1] / "tmp" / "_apikey.txt"
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def collect(person: str, companies: list[str], api_key: str) -> list[dict]:
    exec_hits = {}   # company -> set(years)
    inv_hits = {}    # company -> set(source labels)
    for q in companies:
        r = resolve_corp(q, api_key)
        if not r:
            continue
        name, info = r
        cc = info["corp_code"]
        # 임원 차원
        roster = fetch_executive_roster(cc, api_key, LOOKBACK_YEARS) or {}
        if person in roster:
            exec_hits.setdefault(name, set()).update(roster[person])
        # 투자자 차원 (최근 lookback*365일 CB/유상증자 인수자)
        discs = fetch_company_disclosures(cc, api_key, LOOKBACK_YEARS * 365) or []
        for d in discs:
            rn, rnm = d.get("rcept_no", ""), d.get("report_nm", "")
            if not rn or is_amendment_disclosure(rnm):
                continue
            keys = {s["key"] for s in (match_signals(rnm) or [])}
            invs = []
            if keys & {"CB_BW", "EB"}:
                invs += [("CB인수", i) for i in (extract_cb_investors(rn, api_key, cc) or [])]
            if keys & {"3PCA", "RIGHTS_UNDER"}:
                invs += [("유상증자", i) for i in (extract_rights_offering_investors(rn, api_key, cc) or [])]
            for label, inv in invs:
                if (inv.get("name") or "").strip() == person:
                    inv_hits.setdefault(name, set()).add(label)

    records = []
    if exec_hits:
        comps = sorted(exec_hits.keys())
        yrs = sorted({y for s in exec_hits.values() for y in s})
        records.append({
            "source": "DART 임원현황",
            "evidence": f"{'·'.join(comps)} 등기임원 ({yrs[0]}–{yrs[-1]})" if len(yrs) > 1
                        else f"{'·'.join(comps)} 등기임원 ({yrs[0]})",
            "url": "https://dart.fss.or.kr",
            "date": f"{yrs[0]}-{yrs[-1]}" if len(yrs) > 1 else yrs[0],
            "tags": ["다수 상장사 등기임원 겸직"] if len(comps) >= 2 else ["상장사 등기임원"],
        })
    for company, labels in sorted(inv_hits.items()):
        records.append({
            "source": f"DART {'·'.join(sorted(labels))}",
            "evidence": f"{company} {'·'.join(sorted(labels))} 인수자 등장",
            "url": "https://dart.fss.or.kr",
            "date": "",
            "tags": ["상장사 자금조달 인수자"],
        })
    return records


def main():
    key = _api_key()
    if not key:
        raise SystemExit("DART_API_KEY 또는 tmp/_apikey.txt 필요")
    data = {"version": 1, "updated": "2026-06-14", "actors": {}}
    for person, companies in SEED.items():
        recs = collect(person, companies, key)
        if recs:
            data["actors"][person] = recs
            print(f"  {person}: {len(recs)}건 근거 집계")
        else:
            print(f"  {person}: 근거 없음(스킵)")
    DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
    print(f"저장: {DATA_PATH}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: 라이브 시드 생성 실행**

Run:
```bash
PYTHONIOENCODING=utf-8 DART_API_KEY="$(cat /c/Users/anboy/vibecoding/dart-risk-mcp/tmp/_apikey.txt | tr -d '[:space:]')" python scripts/build_known_actors.py
```
Expected: 각 인물별 "N건 근거 집계" 출력, `data/known_actors.json`에 신승수 등 임원/투자자 근거가 채워짐. 최소 신승수 임원 근거가 들어가야 함(앞선 라이브 검증과 일치).

- [ ] **Step 3: 생성 데이터 육안 검증**

`dart_risk_mcp/data/known_actors.json`을 열어 (1) 판정/단정 표현 없음, (2) 모든 엔트리에 source·url 존재, (3) evidence가 회사·연도 사실인지 확인. 이상하면 SEED 회사군을 조정해 재실행.

- [ ] **Step 4: 시드 반영 후 회귀 확인**

Run: `python -m pytest tests/ -q`
Expected: 통과. 단 `find_actor_overlap` 신승수군 골드(`actor_overlap.txt`)는 이제 참고 섹션이 추가되므로 **골드 재생성 필요**:

```bash
PYTHONIOENCODING=utf-8 DART_API_KEY="$(cat /c/Users/anboy/vibecoding/dart-risk-mcp/tmp/_apikey.txt | tr -d '[:space:]')" \
python -c "from dart_risk_mcp.server import find_actor_overlap; open('tests/fixtures/sample_outputs/actor_overlap.txt','w',encoding='utf-8').write(find_actor_overlap(['이엠앤아이','제이케이시냅스','CG인바이츠','헬스커넥트','티쓰리'], lookback_years=3))"
python -m pytest tests/test_golden_output_hygiene.py -q
```
Expected: hygiene 9/9 PASS (📎⚠ 가 severity 등급 이모지로 오탐되지 않는지 확인 — 오탐 시 hygiene 허용 목록 점검).

- [ ] **Step 5: 커밋**

```bash
git add scripts/build_known_actors.py dart_risk_mcp/data/known_actors.json tests/fixtures/sample_outputs/actor_overlap.txt
git commit -m "feat(scripts): bootstrap known_actors from DART evidence; seed 신승수 등"
```

---

## Task 6: 문서 (CLAUDE.md / README) + 등재 기준·면책

**Files:**
- Modify: `CLAUDE.md`, `README.md`

- [ ] **Step 1: CLAUDE.md 갱신**

1. 도구 개수 24 → **25**, 도구 #25 `lookup_known_actor(name)` 항목 추가
2. 도구 #5 `find_actor_overlap`에 "탐지 인물을 공개기록(known_actors)과 대조해 참고 표기" 1줄
3. 디렉토리 구조에 `core/known_actors.py`, `data/known_actors.json`, `scripts/build_known_actors.py`
4. 핵심 내부 함수/모듈에 `core/known_actors.py`(load_known_actors/lookup_actor)
5. **등재 기준** 절 신설: 공개 출처 필수 · 판정/점수 없음 · 면책 동반 · 부트스트랩으로 DART 근거 집계 · 이의제기는 GitHub Issues

- [ ] **Step 2: README.md 갱신**

1. 도구 수 24 → **25**
2. 행위자 그룹 설명에 `lookup_known_actor` + 공개기록 대조 추가
3. "이 도구가 하지 않는 것"에 한 줄: 공개기록 레지스트리는 **사실·출처만 제공하며 위험 판정이 아님**, 동명이인 가능성 고지, 등재 이의는 Issues

- [ ] **Step 3: 커밋**

```bash
git add CLAUDE.md README.md
git commit -m "docs: document lookup_known_actor + known_actors registry policy"
```

---

## 검증 체크리스트 (완료 전)

- [ ] `test_known_actors.py` 5개 PASS
- [ ] `test_lookup_known_actor.py` 2개 PASS
- [ ] `find_actor_overlap` 13개 PASS (기존 11 + 신규 2)
- [ ] 전체 스위트: 신규 회귀 0 (사전 존재 env 실패 2건 외)
- [ ] 빌드 산출물(whl)에 `data/known_actors.json` 포함 확인
- [ ] 도구 25개, `lookup_known_actor` 등록
- [ ] 라이브: 부트스트랩으로 신승수 등 실제 근거 집계, 데이터 판정 표현 없음
- [ ] hygiene 9/9, 골드 `actor_overlap.txt` 참고 섹션 반영 후에도 점수·등급·이모지 회귀 없음
- [ ] CLAUDE.md / README 등재 기준·면책 명시
```
