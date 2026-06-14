# known_actors 자동 갱신 + 원격 로드 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** GitHub Actions가 매일 시장 신규 CB/유상증자 공시에서 등재 인물의 인수 근거를 자동 수집(`auto_matched`)하고, 유저는 GitHub raw 최신 데이터를 원격 로드(24h 캐시)로 즉시 받는다.

**Architecture:** `core/known_actors.py`에 원격 로드(캐시→원격→동봉 fallback)를 추가하고, `scripts/refresh_known_actors.py`가 시장 공시 인수자를 등재 인물과 매칭해 `auto_matched` 근거를 더한다. GitHub Actions cron이 매일 실행해 master에 자동 push. 자동 매칭은 동명이인 미확인이라 강한 경고를 동반하고 verified로 자동 승격하지 않는다.

**Tech Stack:** Python 3.11+, `requests`(원격 fetch·이미 의존), `unittest`+`pytest`, GitHub Actions. 외부 라이브러리 추가 없음.

---

## File Structure

- `dart_risk_mcp/core/known_actors.py` — 원격 로드 추가 (수정)
- `dart_risk_mcp/server.py` — `lookup_known_actor`·`find_actor_overlap`에 auto_matched 표기 (수정)
- `scripts/refresh_known_actors.py` — 시장 스캔 매칭 (신규)
- `.github/workflows/refresh-known-actors.yml` — cron 워크플로우 (신규)
- `tests/test_known_actors.py` — 원격 로드 테스트 추가 (기존)
- `tests/test_lookup_known_actor.py` — auto_matched 렌더 테스트 추가 (기존)
- `tests/test_refresh_known_actors.py` — 매칭/병합 로직 테스트 (신규)
- `CLAUDE.md` / `README.md` / 버전 — 문서·릴리스 (수정)

---

## Task 1: `known_actors.py` 원격 로드 (캐시 → 원격 → 동봉)

**Files:**
- Modify: `dart_risk_mcp/core/known_actors.py`
- Test: `tests/test_known_actors.py` (추가)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_known_actors.py`의 `TestKnownActors` 클래스에 추가:

```python
    def test_override_skips_remote(self):
        # DART_KNOWN_ACTORS_PATH 지정 시 원격 fetch를 호출하지 않는다
        from unittest.mock import patch as _p
        from dart_risk_mcp.core import known_actors as ka
        self._write({"version": 1, "actors": {"X": [{"source": "s", "evidence": "e"}]}})
        with _p("dart_risk_mcp.core.known_actors.requests.get") as get:
            data = ka.load_known_actors()
        get.assert_not_called()
        self.assertIn("X", data["actors"])

    def test_remote_fetch_when_no_cache(self):
        # 캐시 없음 + 원격 성공 → 원격 데이터 반환
        import tempfile
        from unittest.mock import patch as _p, MagicMock
        from pathlib import Path
        from dart_risk_mcp.core import known_actors as ka
        # override 제거(원격 경로 진입)
        self._env.stop()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cache = Path(tmp) / "remote.json"
                resp = MagicMock(); resp.status_code = 200
                resp.json.return_value = {"version": 1, "actors": {"원격인물": [{"source": "DART", "evidence": "e"}]}}
                with _p("dart_risk_mcp.core.known_actors._CACHE_FILE", cache), \
                     _p("dart_risk_mcp.core.known_actors.requests.get", return_value=resp) as get, \
                     _p.dict("os.environ", {}, clear=False):
                    import os
                    os.environ.pop("DART_KNOWN_ACTORS_PATH", None)
                    data = ka.load_known_actors()
                get.assert_called_once()
                self.assertIn("원격인물", data["actors"])
                self.assertTrue(cache.exists())  # 캐시 저장됨
        finally:
            self._env.start()

    def test_remote_failure_falls_back_to_bundled(self):
        # 원격 실패 → 동봉 데이터 fallback (예외 없음)
        import tempfile
        from unittest.mock import patch as _p
        from pathlib import Path
        from dart_risk_mcp.core import known_actors as ka
        self._env.stop()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cache = Path(tmp) / "remote.json"
                with _p("dart_risk_mcp.core.known_actors._CACHE_FILE", cache), \
                     _p("dart_risk_mcp.core.known_actors.requests.get", side_effect=Exception("net")):
                    import os
                    os.environ.pop("DART_KNOWN_ACTORS_PATH", None)
                    data = ka.load_known_actors()
                # 동봉 데이터(현재 신승수 등 포함)가 반환되며 예외 없음
                self.assertIsInstance(data.get("actors"), dict)
        finally:
            self._env.start()
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_known_actors.py -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'requests'` / `_CACHE_FILE`

- [ ] **Step 3: 구현 — `known_actors.py` 전체 교체**

```python
"""공개기록 행위자 레지스트리 (원격 로드 + 동봉 fallback, 순수 표준+requests)."""
import json
import os
import time
from importlib import resources
from pathlib import Path

import requests

_REMOTE_URL = (
    "https://raw.githubusercontent.com/anboyu-alt/dart-risk-mcp/master/"
    "dart_risk_mcp/data/known_actors.json"
)
_CACHE_FILE = Path.home() / ".cache" / "dart-risk-mcp" / "known_actors_remote.json"
_CACHE_TTL = 24 * 3600
_EMPTY = {"version": 1, "actors": {}}


def _valid(data) -> bool:
    return isinstance(data, dict) and isinstance(data.get("actors"), dict)


def _bundled() -> dict:
    try:
        text = (resources.files("dart_risk_mcp") / "data" / "known_actors.json").read_text(
            encoding="utf-8")
        data = json.loads(text)
        return data if _valid(data) else {"version": 1, "actors": {}}
    except Exception:
        return {"version": 1, "actors": {}}


def load_known_actors() -> dict:
    """레지스트리 로드. 우선순위: 환경변수 경로 > 신선한 원격 캐시 > 원격 fetch > 동봉.

    원격 실패 시 동봉 데이터로 graceful fallback(예외 비전파).
    """
    override = os.environ.get("DART_KNOWN_ACTORS_PATH")
    if override:
        try:
            with open(override, encoding="utf-8") as f:
                data = json.load(f)
            return data if _valid(data) else {"version": 1, "actors": {}}
        except Exception:
            return {"version": 1, "actors": {}}

    # 24h 신선 캐시
    try:
        if _CACHE_FILE.exists() and (time.time() - _CACHE_FILE.stat().st_mtime) < _CACHE_TTL:
            data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            if _valid(data):
                return data
    except Exception:
        pass

    # 원격 fetch
    try:
        resp = requests.get(_REMOTE_URL, timeout=5)
        if resp.status_code == 200:
            data = resp.json()
            if _valid(data):
                try:
                    _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
                    _CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
                except Exception:
                    pass
                return data
    except Exception:
        pass

    return _bundled()


def lookup_actor(name: str) -> list[dict]:
    """인물명 정확 매칭 → 기록 리스트(없으면 [])."""
    if not name or not name.strip():
        return []
    return list(load_known_actors().get("actors", {}).get(name.strip(), []))
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_known_actors.py -q`
Expected: PASS (기존 5 + 신규 3 = 8 passed)

- [ ] **Step 5: 커밋**

```bash
git add dart_risk_mcp/core/known_actors.py tests/test_known_actors.py
git commit -m "feat(known_actors): remote load from GitHub raw with 24h cache + bundled fallback"
```

---

## Task 2: `auto_matched` 렌더 (lookup + find_actor_overlap)

**Files:**
- Modify: `dart_risk_mcp/server.py`
- Test: `tests/test_lookup_known_actor.py` (추가)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_lookup_known_actor.py`의 `TestLookupKnownActor`에 추가:

```python
    def test_auto_matched_marked_with_strong_warning(self):
        import json
        from pathlib import Path
        from dart_risk_mcp.server import lookup_known_actor
        Path(self._path).write_text(json.dumps({"version": 1, "actors": {
            "이준민": [{"source": "DART CB인수(자동매칭)", "status": "auto_matched",
                       "evidence": "△△전자 CB 인수자로 등장", "url": "https://dart.fss.or.kr",
                       "date": "2026-06", "rcept_no": "20260612000123",
                       "tags": ["자동 매칭", "동명이인 미확인"]}]
        }}, ensure_ascii=False), encoding="utf-8")
        out = lookup_known_actor("이준민")
        self.assertIn("자동 매칭", out)
        self.assertIn("동명이인", out)
        self.assertIn("동일인 여부", out)   # 강한 경고 문구
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_lookup_known_actor.py::TestLookupKnownActor::test_auto_matched_marked_with_strong_warning -q`
Expected: FAIL — "동일인 여부" 미발견

- [ ] **Step 3: 구현 — `lookup_known_actor` status 분기 확장**

`server.py`의 `lookup_known_actor` 본문에서 기존 루프와 면책을 다음으로 교체:

```python
    lines = [f"📎 '{name}' 공개기록 (사실 표기 — 판정 아님):"]
    has_seed = False
    has_auto = False
    for r in records:
        src = r.get("source", "")
        ev = r.get("evidence", "")
        date = r.get("date", "")
        url = r.get("url", "")
        st = r.get("status", "")
        if st == "maintainer_seed":
            has_seed = True
        elif st == "auto_matched":
            has_auto = True
        prefix = "[자동 매칭 · 동명이인 미확인] " if st == "auto_matched" else ""
        head = f"  • {prefix}{src}"
        if date:
            head += f" ({date})"
        head += f": {ev}"
        lines.append(head)
        if url:
            lines.append(f"      출처: {url}")
    if has_auto:
        lines.append("⚠ 자동 매칭 항목은 시장 공시 이름 매칭 결과로 동일인 여부가 미확인입니다 — 원본 공시로 반드시 확인하세요.")
    if has_seed:
        lines.append("⚠ 일부 항목은 공시 자동매칭이 아닌 제작자 모니터링 등록입니다 (혐의·확정 아님).")
    lines.append("⚠ 원본 공시로 사실 확인 권장 · 동명이인 가능성 있음 · 본 기록은 판정이 아닙니다.")
    return "\n".join(lines)
```

- [ ] **Step 4: find_actor_overlap 대조에도 auto 경고 추가**

`server.py`의 `find_actor_overlap` 공개기록 대조 블록에서 seed 경고 줄 위에 추가:

```python
        if any(r.get("status") == "auto_matched" for _, recs in known_hits for r in recs):
            lines.append("  ⚠ 일부는 시장 공시 자동 매칭 (동일인 여부 미확인)")
        if any(r.get("status") == "maintainer_seed" for _, recs in known_hits for r in recs):
            lines.append("  ⚠ 일부는 제작자 모니터링 등록 (공시 자동매칭 아님, 혐의·확정 아님)")
        lines.append("  ⚠ 원본 공시로 사실 확인 권장 · 동명이인 가능성 있음")
```

(기존 seed 분기 한 줄을 위 두 분기로 교체.)

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/test_lookup_known_actor.py tests/test_find_actor_overlap.py -q`
Expected: PASS (전부)

- [ ] **Step 6: 커밋**

```bash
git add dart_risk_mcp/server.py tests/test_lookup_known_actor.py
git commit -m "feat(known_actors): render auto_matched status with strong same-name warning"
```

---

## Task 3: 시장 스캔 매칭 스크립트

**Files:**
- Create: `scripts/refresh_known_actors.py`
- Test: `tests/test_refresh_known_actors.py` (신규)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_refresh_known_actors.py`:

```python
import unittest
from unittest.mock import patch


class TestRefreshKnownActors(unittest.TestCase):
    def test_collect_matches_registered_actor(self):
        import scripts.refresh_known_actors as rk

        discs = [{"rcept_no": "R1", "report_nm": "전환사채권발행결정",
                  "corp_name": "△△전자", "corp_code": "c1", "rcept_dt": "20260612"}]

        def _match(rnm):
            return [{"key": "CB_BW"}] if "전환사채" in rnm else []

        with patch.object(rk, "fetch_market_disclosures", return_value=discs), \
             patch.object(rk, "match_signals", side_effect=_match), \
             patch.object(rk, "is_amendment_disclosure", return_value=False), \
             patch.object(rk, "extract_cb_investors", return_value=[{"name": "이준민"}]), \
             patch.object(rk, "extract_rights_offering_investors", return_value=[]):
            matches = rk.collect_auto_matches("key", {"이준민"}, window_days=2, max_pages=1)

        self.assertIn("이준민", matches)
        self.assertEqual(matches["이준민"][0]["status"], "auto_matched")
        self.assertEqual(matches["이준민"][0]["rcept_no"], "R1")

    def test_collect_ignores_unregistered(self):
        import scripts.refresh_known_actors as rk
        discs = [{"rcept_no": "R1", "report_nm": "전환사채권발행결정",
                  "corp_name": "X", "corp_code": "c", "rcept_dt": "20260612"}]
        with patch.object(rk, "fetch_market_disclosures", return_value=discs), \
             patch.object(rk, "match_signals", return_value=[{"key": "CB_BW"}]), \
             patch.object(rk, "is_amendment_disclosure", return_value=False), \
             patch.object(rk, "extract_cb_investors", return_value=[{"name": "낯선사람"}]), \
             patch.object(rk, "extract_rights_offering_investors", return_value=[]):
            matches = rk.collect_auto_matches("key", {"이준민"}, window_days=2, max_pages=1)
        self.assertEqual(matches, {})

    def test_merge_skips_duplicate_rcept(self):
        import scripts.refresh_known_actors as rk
        data = {"version": 1, "actors": {"이준민": [
            {"source": "x", "status": "auto_matched", "rcept_no": "R1"}]}}
        matches = {"이준민": [{"source": "y", "status": "auto_matched", "rcept_no": "R1"},
                            {"source": "z", "status": "auto_matched", "rcept_no": "R2"}]}
        changed = rk.merge_auto_matches(data, matches)
        self.assertTrue(changed)
        rcepts = {r["rcept_no"] for r in data["actors"]["이준민"]}
        self.assertEqual(rcepts, {"R1", "R2"})  # R1 중복 스킵, R2 추가

    def test_merge_ignores_unregistered_name(self):
        import scripts.refresh_known_actors as rk
        data = {"version": 1, "actors": {}}
        changed = rk.merge_auto_matches(data, {"낯선사람": [{"rcept_no": "R1"}]})
        self.assertFalse(changed)
        self.assertEqual(data["actors"], {})


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_refresh_known_actors.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.refresh_known_actors'` (또는 함수 부재)

- [ ] **Step 3: 구현**

`scripts/refresh_known_actors.py`:

```python
"""known_actors 자동 갱신 — 시장 신규 CB/유상증자 공시에서 등재 인물의 인수 근거 수집.

GitHub Actions cron이 매일 실행. 등재 인물만 대상이며, 자동 매칭은 status=auto_matched
(동명이인 미확인)로 추가하고 verified로 승격하지 않는다.

사용: python scripts/refresh_known_actors.py
API 키: 환경변수 DART_API_KEY 또는 tmp/_apikey.txt.
"""
import json
import os
from datetime import datetime, timedelta
from pathlib import Path

from dart_risk_mcp.core.dart_client import (
    fetch_market_disclosures, extract_cb_investors,
)
from dart_risk_mcp.core.investor_extractor import extract_rights_offering_investors
from dart_risk_mcp.core.signals import match_signals, is_amendment_disclosure

WINDOW_DAYS = 2
MAX_PAGES = 5
DATA_PATH = Path(__file__).resolve().parents[1] / "dart_risk_mcp" / "data" / "known_actors.json"


def _api_key() -> str:
    key = os.environ.get("DART_API_KEY")
    if key:
        return key.strip()
    p = Path(__file__).resolve().parents[1] / "tmp" / "_apikey.txt"
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def collect_auto_matches(api_key, known_names, window_days=WINDOW_DAYS, max_pages=MAX_PAGES):
    """최근 window_days CB/유상증자 공시에서 known_names와 매칭되는 인수자 근거 수집.

    반환: {인물명: [auto_matched record, ...]}
    """
    end = datetime.now()
    start = end - timedelta(days=max(1, window_days))
    discs = fetch_market_disclosures(
        api_key, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"),
        pblntf_ty="B", max_pages=max_pages) or []
    matches = {}
    for d in discs:
        rn = d.get("rcept_no", "")
        rnm = d.get("report_nm", "")
        corp = d.get("corp_name", "")
        cc = d.get("corp_code", "")
        if not rn or is_amendment_disclosure(rnm):
            continue
        keys = {s["key"] for s in (match_signals(rnm) or [])}
        invs = []
        if keys & {"CB_BW", "EB"}:
            invs += [("CB인수", i) for i in (extract_cb_investors(rn, api_key, cc) or [])]
        if keys & {"3PCA", "RIGHTS_UNDER"}:
            invs += [("유상증자", i) for i in (extract_rights_offering_investors(rn, api_key, cc) or [])]
        rdt = (d.get("rcept_dt", "") or "")
        date = f"{rdt[:4]}-{rdt[4:6]}" if len(rdt) >= 6 else ""
        for label, inv in invs:
            nm = (inv.get("name") or "").strip()
            if nm in known_names:
                matches.setdefault(nm, []).append({
                    "source": f"DART {label}(자동매칭)",
                    "status": "auto_matched",
                    "evidence": f"{corp} {label} 인수자로 등장",
                    "url": "https://dart.fss.or.kr",
                    "date": date,
                    "rcept_no": rn,
                    "tags": ["자동 매칭", "동명이인 미확인"],
                })
    return matches


def merge_auto_matches(data: dict, matches: dict) -> bool:
    """matches를 data에 병합. 등재 인물만, 동일 rcept_no 중복 스킵. 변경 여부 반환."""
    actors = data.setdefault("actors", {})
    changed = False
    for name, recs in matches.items():
        if name not in actors:
            continue  # 등재 인물만 근거 추가 (새 인물 등재 안 함)
        seen = {r.get("rcept_no") for r in actors[name] if r.get("rcept_no")}
        for rec in recs:
            if rec.get("rcept_no") and rec["rcept_no"] in seen:
                continue
            actors[name].append(rec)
            seen.add(rec.get("rcept_no"))
            changed = True
    return changed


def main():
    key = _api_key()
    if not key:
        raise SystemExit("DART_API_KEY 또는 tmp/_apikey.txt 필요")
    data = json.loads(DATA_PATH.read_text(encoding="utf-8"))
    known_names = set(data.get("actors", {}).keys())
    matches = collect_auto_matches(key, known_names)
    changed = merge_auto_matches(data, matches)
    if changed:
        DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"갱신: {sum(len(v) for v in matches.values())}건 근거 추가")
    else:
        print("변경 없음")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_refresh_known_actors.py -q`
Expected: PASS (4 passed)

`scripts/__init__.py`가 없어 import 실패하면 빈 파일 생성: `touch scripts/__init__.py` (이미 `scripts/regen_goldens.py`가 패키지 외부 실행되므로, 테스트 import를 위해 `scripts/__init__.py` 필요 시 생성).

- [ ] **Step 5: 커밋**

```bash
git add scripts/refresh_known_actors.py tests/test_refresh_known_actors.py
git commit -m "feat(scripts): market-scan auto-refresh for known_actors (auto_matched)"
```

---

## Task 4: GitHub Actions cron 워크플로우

**Files:**
- Create: `.github/workflows/refresh-known-actors.yml`

- [ ] **Step 1: 워크플로우 작성**

`.github/workflows/refresh-known-actors.yml`:

```yaml
name: Refresh known_actors

on:
  schedule:
    - cron: "0 19 * * *"   # UTC 19:00 = 한국 04:00
  workflow_dispatch: {}

permissions:
  contents: write

jobs:
  refresh:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.11"
      - name: Install package
        run: pip install -e .
      - name: Refresh known_actors
        env:
          DART_API_KEY: ${{ secrets.DART_API_KEY }}
        run: python scripts/refresh_known_actors.py
      - name: Commit if changed
        run: |
          if ! git diff --quiet dart_risk_mcp/data/known_actors.json; then
            git config user.name "github-actions[bot]"
            git config user.email "github-actions[bot]@users.noreply.github.com"
            git add dart_risk_mcp/data/known_actors.json
            git commit -m "chore(known_actors): auto-refresh evidence [skip ci]"
            git push
          else
            echo "변경 없음"
          fi
```

- [ ] **Step 2: YAML 문법 검증**

Run: `python -c "import yaml,sys; yaml.safe_load(open('.github/workflows/refresh-known-actors.yml',encoding='utf-8')); print('YAML OK')"`
Expected: `YAML OK` (yaml 미설치면 `pip install pyyaml` 후 재시도; 검증만 하고 의존성엔 추가 안 함)

- [ ] **Step 3: 커밋**

```bash
git add .github/workflows/refresh-known-actors.yml
git commit -m "ci: daily cron to auto-refresh known_actors evidence"
```

---

## Task 5: 라이브 실행 검증 + 문서 + 릴리스(v1.3.0)

**Files:**
- Modify: `CLAUDE.md`, `README.md`, `pyproject.toml`, `dart_risk_mcp/__init__.py`, `CHANGELOG.md`

- [ ] **Step 1: 라이브 스크립트 1회 실행(동작 확인)**

Run:
```bash
PYTHONPATH="$(pwd)" PYTHONIOENCODING=utf-8 DART_API_KEY="$(cat /c/Users/anboy/vibecoding/dart-risk-mcp/tmp/_apikey.txt | tr -d '[:space:]')" python scripts/refresh_known_actors.py
```
Expected: "변경 없음" 또는 "N건 근거 추가" 정상 종료(매칭 0건이어도 정상). 만약 근거가 추가되면 `data/known_actors.json` 변경 — 육안 검증 후 유지/되돌림 결정.

- [ ] **Step 2: 버전 1.2.1 → 1.3.0**

- `pyproject.toml`: `version = "1.2.1"` → `"1.3.0"`
- `dart_risk_mcp/__init__.py`: `__version__ = "1.2.1"` → `"1.3.0"`
- `README.md`: `**버전:** v1.2.1` → `v1.3.0`

- [ ] **Step 3: CHANGELOG v1.3.0 엔트리**

`CHANGELOG.md`의 `## [Unreleased]` 다음에 삽입:

```markdown
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
```

- [ ] **Step 4: CLAUDE.md 갱신**

1. `core/known_actors.py` 설명에 원격 로드(GitHub raw 24h 캐시 + 동봉 fallback) 추가
2. 디렉토리/스크립트에 `scripts/refresh_known_actors.py`, `.github/workflows/refresh-known-actors.yml`
3. 도구 #25 `lookup_known_actor`·등재 기준 절에 `status` 3단계 + "auto_matched는 동명이인 미확인, verified 아님" 명시
4. 캐시 구조 표에 `known_actors_remote.json`(원격 캐시, 24h) 행 추가
5. 운영 안내: `DART_API_KEY` repo Secret 등록

- [ ] **Step 5: 전체 스위트 + hygiene**

Run: `python -m pytest tests/ -q`
Expected: 신규 회귀 0. (사전 존재 env 실패 2건 외)

- [ ] **Step 6: 커밋**

```bash
git add CLAUDE.md README.md pyproject.toml dart_risk_mcp/__init__.py CHANGELOG.md dart_risk_mcp/data/known_actors.json
git commit -m "release: v1.3.0 — known_actors auto-refresh + remote load"
```

---

## 검증 체크리스트 (완료 전)

- [ ] `test_known_actors.py` 원격 로드 3개 PASS (override 우선·원격 성공·실패 fallback)
- [ ] `test_lookup_known_actor.py` auto_matched 경고 PASS
- [ ] `test_refresh_known_actors.py` 4개 PASS (매칭·미등재 무시·중복 스킵·미등재 병합 차단)
- [ ] 전체 스위트: 신규 회귀 0 (사전 존재 env 실패 2건 외)
- [ ] 라이브: refresh 스크립트 정상 종료
- [ ] YAML 문법 OK
- [ ] 버전 1.3.0 일치, CHANGELOG·README·CLAUDE.md 갱신
- [ ] 자동 매칭은 verified로 자동 승격 안 함(코드·문서 확인)
```
