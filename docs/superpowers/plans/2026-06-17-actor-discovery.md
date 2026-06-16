# 문제 회사 기반 행위자 자동 발굴 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 매일 시장에서 "문제 회사"(자금조달+불안정 신호)의 인수자를 비공개 누적(sightings)하고, 서로 다른 문제 회사 2곳+에 반복 등장하는 인물을 known_actors에 auto_matched로 자동 등재한다.

**Architecture:** `scripts/discover_actors.py`가 순수 함수(`is_problem_company`·`merge_sightings`·`promote_repeat_actors`)와 수집 함수(`collect_problem_sightings`)로 구성된다. sightings는 private repo(비공개), known_actors는 public. 기존 `core` 함수와 `refresh_known_actors`의 `send_mail`을 재사용. 패키지 코드 불변(버전업 없음).

**Tech Stack:** Python 표준 + 기존 `core`(requests), `unittest`+`pytest`, GitHub Actions.

---

## File Structure

- `scripts/discover_actors.py` — 자동 발굴 (신규)
- `tests/test_discover_actors.py` — 단위 테스트 (신규)
- `.github/workflows/refresh-known-actors.yml` — private repo checkout + discover step (수정)
- `CLAUDE.md` — 자동 발굴·sightings·노출 경계 문서 (수정)

---

## Task 1: 상수 + `is_problem_company` + `company_signal_keys` + `_is_person`

**Files:**
- Create: `scripts/discover_actors.py`
- Test: `tests/test_discover_actors.py`

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_discover_actors.py`:

```python
import unittest
from unittest.mock import patch


class TestDiscoverPredicates(unittest.TestCase):
    def test_is_problem_company_requires_both(self):
        import scripts.discover_actors as da
        self.assertTrue(da.is_problem_company({"CB_BW", "SHAREHOLDER"}))
        self.assertTrue(da.is_problem_company({"3PCA", "AUDIT", "MGMT"}))
        self.assertFalse(da.is_problem_company({"CB_BW", "MGMT"}))       # 불안정 없음
        self.assertFalse(da.is_problem_company({"SHAREHOLDER", "AUDIT"})) # 자금조달 없음
        self.assertFalse(da.is_problem_company(set()))

    def test_is_person_filters_orgs(self):
        import scripts.discover_actors as da
        self.assertTrue(da._is_person("홍길동"))
        self.assertTrue(da._is_person("신승수"))
        self.assertFalse(da._is_person("르퓨쳐 코스닥벤처 일반사모투자신탁"))
        self.assertFalse(da._is_person("(주)스마트에쿼티파트너스"))
        self.assertFalse(da._is_person("아레스1호투자조합"))
        self.assertFalse(da._is_person(""))

    def test_company_signal_keys_collects(self):
        import scripts.discover_actors as da
        discs = [{"report_nm": "전환사채권발행결정"},
                 {"report_nm": "최대주주변경"},
                 {"report_nm": "[기재정정]조회공시요구"}]  # 정정은 제외

        def _match(nm):
            if "전환사채" in nm:
                return [{"key": "CB_BW"}]
            if "최대주주변경" in nm:
                return [{"key": "SHAREHOLDER"}]
            if "조회공시" in nm:
                return [{"key": "INQUIRY"}]
            return []

        with patch.object(da, "fetch_company_disclosures", return_value=discs), \
             patch.object(da, "match_signals", side_effect=_match), \
             patch.object(da, "is_amendment_disclosure", side_effect=lambda n: n.startswith("[기재정정]")):
            keys = da.company_signal_keys("cc", "key")
        self.assertEqual(keys, {"CB_BW", "SHAREHOLDER"})  # 정정 조회공시 제외


if __name__ == "__main__":
    unittest.main()
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_discover_actors.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'scripts.discover_actors'`

- [ ] **Step 3: 구현 (파일 골격)**

`scripts/discover_actors.py`:

```python
"""문제 회사 기반 행위자 자동 발굴.

매일 시장 '문제 회사'(자금조달 + 불안정 신호 동반)의 개인 인수자를 sightings로
누적(private repo, 12개월 윈도우)하고, 서로 다른 문제 회사 N=2곳+ 에 반복 등장하는
인물을 known_actors(public)에 auto_matched로 자동 등재한다. 임원·조합명은 제외.

사용: python scripts/discover_actors.py
환경: DART_API_KEY, SIGHTINGS_PATH(private repo의 sightings.json), MAIL_*(선택).
"""
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from dart_risk_mcp.core.dart_client import fetch_market_disclosures, fetch_company_disclosures
from dart_risk_mcp.core.cb_extractor import extract_cb_investors
from dart_risk_mcp.core.investor_extractor import extract_rights_offering_investors
from dart_risk_mcp.core.signals import match_signals, is_amendment_disclosure
from scripts.refresh_known_actors import send_mail, _api_key

FUNDING_KEYS = {"CB_BW", "EB", "3PCA", "RIGHTS_UNDER", "RCPS"}
INSTABILITY_KEYS = {"SHAREHOLDER", "REVERSE_SPLIT", "GAMJA_MERGE", "INQUIRY",
                    "AUDIT", "MGMT_DISPUTE", "DISCLOSURE_VIOL"}
WINDOW_DAYS = 2
MAX_PAGES = 5
WINDOW_MONTHS = 12
N_THRESHOLD = 2

KNOWN_PATH = Path(__file__).resolve().parents[1] / "dart_risk_mcp" / "data" / "known_actors.json"
_DEFAULT_SIGHTINGS = Path(__file__).resolve().parents[1] / "tmp" / "sightings.json"

# 개인명이 아닌(법인·조합) 패턴
_ORG_PAT = re.compile(
    r"조합|투자|신탁|펀드|주식회사|\(주\)|㈜|유한|법인|파트너스|캐피탈|자산운용|"
    r"벤처|컴퍼니|코프|홀딩스|그룹|Co\.|Ltd|LLC|Inc")


def company_signal_keys(corp_code: str, api_key: str, lookback_days: int = 180) -> set:
    """회사 최근 공시의 신호 키 집합(정정 제외)."""
    keys = set()
    for d in (fetch_company_disclosures(corp_code, api_key, lookback_days) or []):
        rnm = d.get("report_nm", "")
        if is_amendment_disclosure(rnm):
            continue
        for s in (match_signals(rnm) or []):
            keys.add(s["key"])
    return keys


def is_problem_company(signal_keys) -> bool:
    """자금조달 신호 AND 불안정 신호가 함께 있으면 문제 회사."""
    ks = set(signal_keys)
    return bool(ks & FUNDING_KEYS) and bool(ks & INSTABILITY_KEYS)


def _is_person(name: str) -> bool:
    """개인명 여부(법인·조합 패턴 제외)."""
    if not name or not name.strip():
        return False
    return not _ORG_PAT.search(name)
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_discover_actors.py -q`
Expected: PASS (3 passed)

- [ ] **Step 5: 커밋**

```bash
git add scripts/discover_actors.py tests/test_discover_actors.py
git commit -m "feat(discover): problem-company predicate + person filter + signal keys"
```

---

## Task 2: `collect_problem_sightings`

**Files:**
- Modify: `scripts/discover_actors.py`
- Test: `tests/test_discover_actors.py` (추가)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_discover_actors.py`에 클래스 추가:

```python
class TestCollectSightings(unittest.TestCase):
    def _patches(self, da, discs, signal_map, company_keys, cb_invs, rights_invs):
        from unittest.mock import patch
        return [
            patch.object(da, "fetch_market_disclosures", return_value=discs),
            patch.object(da, "match_signals", side_effect=lambda n: signal_map.get(n, [])),
            patch.object(da, "is_amendment_disclosure", return_value=False),
            patch.object(da, "company_signal_keys", side_effect=lambda cc, k, **kw: company_keys.get(cc, set())),
            patch.object(da, "extract_cb_investors", return_value=cb_invs),
            patch.object(da, "extract_rights_offering_investors", return_value=rights_invs),
        ]

    def test_collects_only_problem_company_persons(self):
        import scripts.discover_actors as da
        from contextlib import ExitStack
        discs = [{"rcept_no": "R1", "report_nm": "전환사채권발행결정",
                  "corp_name": "문제전자", "corp_code": "c1", "rcept_dt": "20260612"},
                 {"rcept_no": "R2", "report_nm": "전환사채권발행결정",
                  "corp_name": "정상전자", "corp_code": "c2", "rcept_dt": "20260612"}]
        signal_map = {"전환사채권발행결정": [{"key": "CB_BW"}]}
        company_keys = {"c1": {"CB_BW", "SHAREHOLDER"},   # 문제 회사
                        "c2": {"CB_BW"}}                   # 정상(불안정 없음)
        with ExitStack() as st:
            for p in self._patches(da, discs, signal_map, company_keys,
                                   [{"name": "홍길동"}, {"name": "아레스1호투자조합"}], []):
                st.enter_context(p)
            sightings = da.collect_problem_sightings("key")
        names = [s["name"] for s in sightings]
        self.assertIn("홍길동", names)              # 문제회사 개인
        self.assertNotIn("아레스1호투자조합", names)  # 조합 제외
        self.assertTrue(all(s["corp_code"] == "c1" for s in sightings))  # 정상회사 c2 제외
        self.assertEqual(sightings[0]["rcept_no"], "R1")
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_discover_actors.py::TestCollectSightings -q`
Expected: FAIL — `AttributeError: module ... has no attribute 'collect_problem_sightings'`

- [ ] **Step 3: 구현 추가**

`scripts/discover_actors.py`에 추가:

```python
def collect_problem_sightings(api_key, window_days=WINDOW_DAYS, max_pages=MAX_PAGES):
    """최근 window_days 자금조달 공시 중 문제 회사의 개인 인수자 sighting 목록."""
    end = datetime.now()
    start = end - timedelta(days=max(1, window_days))
    discs = fetch_market_disclosures(
        api_key, start.strftime("%Y%m%d"), end.strftime("%Y%m%d"),
        pblntf_ty="B", max_pages=max_pages) or []
    sightings = []
    problem_cache = {}  # corp_code -> bool
    for d in discs:
        rn = d.get("rcept_no", "")
        rnm = d.get("report_nm", "")
        corp = d.get("corp_name", "")
        cc = d.get("corp_code", "")
        if not rn or is_amendment_disclosure(rnm):
            continue
        keys = {s["key"] for s in (match_signals(rnm) or [])}
        if not (keys & FUNDING_KEYS):
            continue
        if cc not in problem_cache:
            problem_cache[cc] = is_problem_company(company_signal_keys(cc, api_key))
        if not problem_cache[cc]:
            continue
        invs = []
        if keys & {"CB_BW", "EB"}:
            invs += extract_cb_investors(rn, api_key, cc) or []
        if keys & {"3PCA", "RIGHTS_UNDER"}:
            invs += extract_rights_offering_investors(rn, api_key, cc) or []
        rdt = d.get("rcept_dt", "") or ""
        date = f"{rdt[:4]}-{rdt[4:6]}" if len(rdt) >= 6 else ""
        for inv in invs:
            nm = (inv.get("name") or "").strip()
            if not _is_person(nm):
                continue
            sightings.append({
                "name": nm, "corp": corp, "corp_code": cc,
                "date": date, "rcept_no": rn,
                "signals": sorted(keys & (FUNDING_KEYS | INSTABILITY_KEYS)),
            })
    return sightings
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_discover_actors.py -q`
Expected: PASS (4 passed)

- [ ] **Step 5: 커밋**

```bash
git add scripts/discover_actors.py tests/test_discover_actors.py
git commit -m "feat(discover): collect problem-company person investor sightings"
```

---

## Task 3: `merge_sightings` + `promote_repeat_actors`

**Files:**
- Modify: `scripts/discover_actors.py`
- Test: `tests/test_discover_actors.py` (추가)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_discover_actors.py`에 클래스 추가:

```python
class TestMergeAndPromote(unittest.TestCase):
    def test_merge_dedup_and_window(self):
        import scripts.discover_actors as da
        data = {"sightings": {"홍길동": [
            {"corp_code": "c1", "rcept_no": "R1", "date": "2026-06"}]}}
        new = [{"name": "홍길동", "corp_code": "c1", "rcept_no": "R1", "date": "2026-06"},  # 중복
               {"name": "홍길동", "corp_code": "c2", "rcept_no": "R2", "date": "2026-06"}]  # 신규
        changed = da.merge_sightings(data, new, window_months=12)
        self.assertTrue(changed)
        rcepts = {e["rcept_no"] for e in data["sightings"]["홍길동"]}
        self.assertEqual(rcepts, {"R1", "R2"})

    def test_merge_drops_old_outside_window(self):
        import scripts.discover_actors as da
        data = {"sightings": {"김갑": [
            {"corp_code": "c1", "rcept_no": "OLD", "date": "2000-01"}]}}
        changed = da.merge_sightings(data, [], window_months=12)
        self.assertTrue(changed)
        self.assertNotIn("김갑", data["sightings"])  # 전부 윈도우 밖 → 제거

    def test_promote_two_distinct_companies(self):
        import scripts.discover_actors as da
        sd = {"sightings": {"홍길동": [
            {"corp_code": "c1", "corp": "A", "rcept_no": "R1", "date": "2026-06"},
            {"corp_code": "c2", "corp": "B", "rcept_no": "R2", "date": "2026-06"}]}}
        kd = {"actors": {}}
        promoted = da.promote_repeat_actors(sd, kd, n=2)
        self.assertEqual(promoted, ["홍길동"])
        self.assertIn("홍길동", kd["actors"])
        self.assertEqual(kd["actors"]["홍길동"][0]["status"], "auto_matched")

    def test_promote_skips_single_company(self):
        import scripts.discover_actors as da
        sd = {"sightings": {"외톨이": [
            {"corp_code": "c1", "corp": "A", "rcept_no": "R1", "date": "2026-06"}]}}
        kd = {"actors": {}}
        self.assertEqual(da.promote_repeat_actors(sd, kd, n=2), [])
        self.assertEqual(kd["actors"], {})

    def test_promote_skips_already_discovered(self):
        import scripts.discover_actors as da
        sd = {"sightings": {"홍길동": [
            {"corp_code": "c1", "corp": "A", "rcept_no": "R1", "date": "2026-06"},
            {"corp_code": "c2", "corp": "B", "rcept_no": "R2", "date": "2026-06"}]}}
        kd = {"actors": {"홍길동": [{"source": "자동 발굴", "status": "auto_matched"}]}}
        self.assertEqual(da.promote_repeat_actors(sd, kd, n=2), [])  # 이미 발굴 등재
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_discover_actors.py::TestMergeAndPromote -q`
Expected: FAIL — `AttributeError: ... 'merge_sightings'`

- [ ] **Step 3: 구현 추가**

`scripts/discover_actors.py`에 추가:

```python
def merge_sightings(data: dict, new: list, window_months: int = WINDOW_MONTHS) -> bool:
    """new sighting을 data에 병합. (corp_code,rcept_no) 중복 스킵, window 밖 제거. 변경 여부."""
    s = data.setdefault("sightings", {})
    changed = False
    for rec in new:
        nm = rec.get("name", "")
        if not nm:
            continue
        lst = s.setdefault(nm, [])
        if any(e.get("rcept_no") == rec.get("rcept_no") and
               e.get("corp_code") == rec.get("corp_code") for e in lst):
            continue
        lst.append({k: rec[k] for k in ("corp", "corp_code", "date", "rcept_no", "signals") if k in rec})
        changed = True
    cutoff = (datetime.now() - timedelta(days=window_months * 30)).strftime("%Y-%m")
    for nm in list(s.keys()):
        kept = [e for e in s[nm] if (e.get("date") or "9999-99") >= cutoff]
        if len(kept) != len(s[nm]):
            changed = True
        if kept:
            s[nm] = kept
        else:
            del s[nm]
            changed = True
    return changed


def promote_repeat_actors(sightings_data: dict, known_data: dict, n: int = N_THRESHOLD) -> list:
    """서로 다른 corp_code n개+ 인물을 known_actors에 auto_matched(자동 발굴)로 등재."""
    actors = known_data.setdefault("actors", {})
    promoted = []
    for nm, recs in sightings_data.get("sightings", {}).items():
        corp_codes = {r.get("corp_code") for r in recs if r.get("corp_code")}
        if len(corp_codes) < n:
            continue
        if any(r.get("source") == "자동 발굴" for r in actors.get(nm, [])):
            continue  # 이미 발굴 등재
        corp_names = sorted({r.get("corp") for r in recs if r.get("corp")})
        actors.setdefault(nm, []).append({
            "source": "자동 발굴",
            "status": "auto_matched",
            "evidence": f"문제 회사 {len(corp_codes)}곳 인수자 반복 등장: {'·'.join(corp_names[:5])}",
            "url": "https://dart.fss.or.kr",
            "date": "",
            "tags": ["자동 발굴", "동명이인 미확인", "반복 등장"],
        })
        promoted.append(nm)
    return promoted
```

- [ ] **Step 4: 통과 확인**

Run: `python -m pytest tests/test_discover_actors.py -q`
Expected: PASS (9 passed)

- [ ] **Step 5: 커밋**

```bash
git add scripts/discover_actors.py tests/test_discover_actors.py
git commit -m "feat(discover): merge sightings (12mo window) + promote N=2 repeat actors"
```

---

## Task 4: `main()` + 워크플로우 private repo 통합

**Files:**
- Modify: `scripts/discover_actors.py` (main 추가)
- Modify: `.github/workflows/refresh-known-actors.yml`

- [ ] **Step 1: main() 추가**

`scripts/discover_actors.py` 끝에 추가:

```python
def _load(path: Path, empty: dict) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return dict(empty)


def main():
    key = _api_key()
    if not key:
        raise SystemExit("DART_API_KEY 또는 tmp/_apikey.txt 필요")
    sightings_path = Path(os.environ.get("SIGHTINGS_PATH") or _DEFAULT_SIGHTINGS)
    sdata = _load(sightings_path, {"version": 1, "sightings": {}})
    kdata = _load(KNOWN_PATH, {"version": 1, "actors": {}})

    new = collect_problem_sightings(key)
    s_changed = merge_sightings(sdata, new)
    promoted = promote_repeat_actors(sdata, kdata)

    if s_changed:
        sightings_path.parent.mkdir(parents=True, exist_ok=True)
        sdata["updated"] = datetime.now().strftime("%Y-%m-%d")
        sightings_path.write_text(json.dumps(sdata, ensure_ascii=False, indent=1), encoding="utf-8")
    if promoted:
        KNOWN_PATH.write_text(json.dumps(kdata, ensure_ascii=False, indent=1), encoding="utf-8")
        body = ("자동 발굴 — known_actors 신규 등재 (사실 표기 · 판정 아님)\n\n"
                + "\n".join(f"  - {nm}" for nm in promoted)
                + "\n\n자동 발굴은 동명이인 미확인 — 원본 공시로 확인 필요.")
        send_mail("[known_actors] 자동 발굴 신규 등재", body)

    print(f"sightings {'갱신' if s_changed else '무변경'} · 신규 등재 {len(promoted)}건")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: import 검증 (순환 import 없음)**

Run: `python -c "import scripts.discover_actors as d; print('OK', d.N_THRESHOLD)"`
Expected: `OK 2`

- [ ] **Step 3: 워크플로우에 private repo checkout + discover step 추가**

`.github/workflows/refresh-known-actors.yml`의 `steps:`에서 기존 "Refresh known_actors" step **뒤**에 추가(같은 job):

```yaml
      - name: Checkout sightings (private)
        uses: actions/checkout@v5
        with:
          repository: anboyu-alt/dart-risk-mcp-sightings
          token: ${{ secrets.SIGHTINGS_REPO_TOKEN }}
          path: _sightings
      - name: Discover actors
        env:
          DART_API_KEY: ${{ secrets.DART_API_KEY }}
          MAIL_USER: ${{ secrets.MAIL_USER }}
          MAIL_APP_PASSWORD: ${{ secrets.MAIL_APP_PASSWORD }}
          MAIL_TO: ${{ secrets.MAIL_TO }}
          SIGHTINGS_PATH: _sightings/sightings.json
        run: python scripts/discover_actors.py
      - name: Commit sightings (private)
        working-directory: _sightings
        run: |
          if ! git diff --quiet sightings.json 2>/dev/null || [ -n "$(git status --porcelain sightings.json)" ]; then
            git config user.name "github-actions[bot]"
            git config user.email "github-actions[bot]@users.noreply.github.com"
            git add sightings.json
            git commit -m "chore: sightings auto-update"
            git push
          else
            echo "sightings 변경 없음"
          fi
```

그리고 기존 "Commit if changed"(public known_actors) step은 그대로 두되, discover가 known_actors를 바꿀 수 있으므로 **이 step이 discover step 뒤에 오도록** 순서를 확인한다(기존 step이 마지막이면 됨).

- [ ] **Step 4: YAML 검증**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/refresh-known-actors.yml',encoding='utf-8')); print('YAML OK')"`
Expected: `YAML OK`

- [ ] **Step 5: 커밋**

```bash
git add scripts/discover_actors.py .github/workflows/refresh-known-actors.yml
git commit -m "feat(discover): main orchestration + private sightings repo in cron"
```

---

## Task 5: 라이브 실행 + CLAUDE.md 문서

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: 라이브 1회 실행 (로컬, sightings는 tmp)**

Run:
```bash
PYTHONPATH="$(pwd)" PYTHONIOENCODING=utf-8 \
DART_API_KEY="$(cat /c/Users/anboy/vibecoding/dart-risk-mcp/tmp/_apikey.txt | tr -d '[:space:]')" \
SIGHTINGS_PATH="tmp/sightings.json" \
python scripts/discover_actors.py
```
Expected: "sightings 갱신/무변경 · 신규 등재 N건" 정상 종료. `tmp/sightings.json`이 생성되며 문제 회사 개인 인수자가 쌓임(매칭 0이어도 정상). known_actors.json은 N=2 도달 없으면 불변. **tmp/sightings.json은 검토용 — 커밋하지 않는다(tmp/는 추적 제외).**

- [ ] **Step 2: 생성 sightings 육안 검증**

`tmp/sightings.json`을 열어 (1) 개인명만(조합·법인 없음), (2) corp/signals 사실 기록인지 확인. 조합명이 섞였으면 `_ORG_PAT`를 보강 후 Task 1~2 재실행.

- [ ] **Step 3: 전체 스위트**

Run: `python -m pytest tests/ -q`
Expected: 신규 회귀 0(사전 존재 env 실패 2건 외). discover 9개 PASS.

- [ ] **Step 4: CLAUDE.md 갱신**

1. 디렉토리/스크립트 절: `scripts/discover_actors.py`(문제 회사 자동 발굴) 추가
2. known_actors `status` 설명에 `auto_matched`가 **두 경로**(시장 이름 매칭 / 문제회사 반복 발굴)임을 명시
3. 노출 경계 한 줄: "sightings(1회 포함)는 **private repo**(제작자만), known_actors(N=2 등재)는 public"
4. 운영 안내: private repo `dart-risk-mcp-sightings` + `SIGHTINGS_REPO_TOKEN` Secret
5. 비범위 정합: 유저 도구 시장 자동 스캔은 비범위, 발굴은 GitHub Actions 운영 전용

- [ ] **Step 5: 커밋**

```bash
git add CLAUDE.md
git commit -m "docs: document actor discovery (problem-company sightings, N=2 promotion)"
```

---

## 검증 체크리스트 (완료 전)

- [ ] `test_discover_actors.py` 9개 PASS (predicate·person·signal_keys·collect·merge·promote)
- [ ] 전체 스위트: 신규 회귀 0
- [ ] import 순환 없음(`scripts.discover_actors` 로드 OK)
- [ ] YAML OK (private checkout + discover + sightings push)
- [ ] 라이브: discover 정상 종료, sightings에 개인명만(조합 제외)
- [ ] 버전·PyPI 불변(패키지 코드 미변경)
- [ ] CLAUDE.md 발굴·노출 경계 문서화
- [ ] 운영 안내: private repo + `SIGHTINGS_REPO_TOKEN` Secret (사용자에게 안내)
```
