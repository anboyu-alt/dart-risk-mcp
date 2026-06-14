# known_actors 변경 이메일 알림 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** cron 자동 갱신이 known_actors에 변경을 만들면 제작자에게 DB 요약 이메일(Gmail)을 보내고, README에 제작자 직접 관리·연락 안내를 추가한다.

**Architecture:** `scripts/refresh_known_actors.py`에 `build_change_summary`(요약 텍스트)와 `send_mail`(smtplib/Gmail) 함수를 추가하고, `main()`이 변경 시에만 발송한다. 자격증명은 GitHub Secret(없으면 발송 스킵). 버전·PyPI 패키지 코드는 불변.

**Tech Stack:** Python 표준 `smtplib`·`email.message`(외부 라이브러리 0), GitHub Actions, `unittest`+`pytest`.

---

## File Structure

- `scripts/refresh_known_actors.py` — `build_change_summary`·`send_mail` 추가 + `main()` 발송 (수정)
- `.github/workflows/refresh-known-actors.yml` — `MAIL_*` Secret env 추가 (수정)
- `tests/test_refresh_known_actors.py` — 요약·발송 테스트 추가 (수정)
- `README.md` / `CLAUDE.md` — 제작자 관리·연락 안내 (수정)

---

## Task 1: `build_change_summary` + `send_mail` + main 발송

**Files:**
- Modify: `scripts/refresh_known_actors.py`
- Test: `tests/test_refresh_known_actors.py` (추가)

- [ ] **Step 1: 실패 테스트 작성**

`tests/test_refresh_known_actors.py`의 `TestRefreshKnownActors`에 추가:

```python
    def test_build_change_summary_includes_counts_and_changes(self):
        import scripts.refresh_known_actors as rk
        data = {"actors": {"신승수": [{"status": "verified"}],
                           "이준민": [{"status": "maintainer_seed"}]}}
        matches = {"이준민": [{"evidence": "△△전자 CB 인수자로 등장", "rcept_no": "R1"}]}
        s = rk.build_change_summary(data, matches)
        self.assertIn("verified 1", s)
        self.assertIn("maintainer_seed 1", s)
        self.assertIn("이준민", s)
        self.assertIn("R1", s)

    def test_send_mail_skips_without_credentials(self):
        import os
        import scripts.refresh_known_actors as rk
        from unittest.mock import patch
        with patch.dict("os.environ", {}, clear=False):
            for k in ("MAIL_USER", "MAIL_APP_PASSWORD", "MAIL_TO"):
                os.environ.pop(k, None)
            with patch.object(rk.smtplib, "SMTP") as smtp:
                ok = rk.send_mail("s", "b")
        self.assertFalse(ok)
        smtp.assert_not_called()

    def test_send_mail_sends_with_credentials(self):
        import scripts.refresh_known_actors as rk
        from unittest.mock import patch, MagicMock
        with patch.dict("os.environ", {"MAIL_USER": "u@gmail.com",
                                       "MAIL_APP_PASSWORD": "p", "MAIL_TO": "t@x.com"}):
            srv = MagicMock()
            srv.__enter__.return_value = srv
            with patch.object(rk.smtplib, "SMTP", return_value=srv):
                ok = rk.send_mail("s", "b")
        self.assertTrue(ok)
        srv.send_message.assert_called_once()
```

- [ ] **Step 2: 실패 확인**

Run: `python -m pytest tests/test_refresh_known_actors.py -q`
Expected: FAIL — `AttributeError: module 'scripts.refresh_known_actors' has no attribute 'build_change_summary' / 'smtplib' / 'send_mail'`

- [ ] **Step 3: 구현 — import + 두 함수 추가**

`scripts/refresh_known_actors.py` 상단 import에 추가:

```python
import smtplib
from email.message import EmailMessage
```

그리고 `merge_auto_matches` 함수 **뒤, `main` 앞**에 추가:

```python
def build_change_summary(data: dict, matches: dict) -> str:
    """status별 집계 + 이번 변경분을 평문 요약으로 반환 (사실 표기·판정 아님)."""
    counts = {"verified": 0, "maintainer_seed": 0, "auto_matched": 0}
    for recs in data.get("actors", {}).values():
        for r in recs:
            st = r.get("status", "")
            if st in counts:
                counts[st] += 1
    lines = [
        "known_actors 자동 갱신 — 변경 알림 (사실 표기 · 판정 아님)",
        "",
        f"현재 등재 근거: verified {counts['verified']} · "
        f"maintainer_seed {counts['maintainer_seed']} · auto_matched {counts['auto_matched']}",
        "",
        "이번 추가:",
    ]
    for name, recs in matches.items():
        for r in recs:
            lines.append(f"  - {name} — {r.get('evidence', '')} (접수 {r.get('rcept_no', '')})")
    lines.append("")
    lines.append("자동 매칭은 동명이인 미확인 — 원본 공시로 확인 필요. 판정 아님.")
    return "\n".join(lines)


def send_mail(subject: str, body: str) -> bool:
    """제작자 Gmail로 발송. 자격증명(env) 미설정 시 스킵(False). 예외도 False."""
    user = os.environ.get("MAIL_USER")
    pw = os.environ.get("MAIL_APP_PASSWORD")
    to = os.environ.get("MAIL_TO")
    if not (user and pw and to):
        return False
    try:
        msg = EmailMessage()
        msg["Subject"] = subject
        msg["From"] = user
        msg["To"] = to
        msg.set_content(body)
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.starttls()
            s.login(user, pw)
            s.send_message(msg)
        return True
    except Exception:
        return False
```

- [ ] **Step 4: main()에서 변경 시 발송**

`main()`의 `if changed:` 블록을 다음으로 교체:

```python
    if changed:
        DATA_PATH.write_text(json.dumps(data, ensure_ascii=False, indent=1), encoding="utf-8")
        n = sum(len(v) for v in matches.values())
        summary = build_change_summary(data, matches)
        sent = send_mail("[known_actors] 자동 갱신 변경 알림", summary)
        print(f"갱신: {n}건 근거 추가" + (" (메일 발송)" if sent else " (메일 스킵)"))
    else:
        print("변경 없음")
```

- [ ] **Step 5: 통과 확인**

Run: `python -m pytest tests/test_refresh_known_actors.py -q`
Expected: PASS (기존 4 + 신규 3 = 7 passed)

- [ ] **Step 6: 커밋**

```bash
git add scripts/refresh_known_actors.py tests/test_refresh_known_actors.py
git commit -m "feat(scripts): email maintainer on known_actors change (smtplib/Gmail)"
```

---

## Task 2: 워크플로우 Secret env + README/CLAUDE.md 안내

**Files:**
- Modify: `.github/workflows/refresh-known-actors.yml`
- Modify: `README.md`, `CLAUDE.md`

- [ ] **Step 1: 워크플로우 env 추가**

`.github/workflows/refresh-known-actors.yml`의 "Refresh known_actors" step `env`를 다음으로 교체:

```yaml
      - name: Refresh known_actors
        env:
          DART_API_KEY: ${{ secrets.DART_API_KEY }}
          MAIL_USER: ${{ secrets.MAIL_USER }}
          MAIL_APP_PASSWORD: ${{ secrets.MAIL_APP_PASSWORD }}
          MAIL_TO: ${{ secrets.MAIL_TO }}
        run: python scripts/refresh_known_actors.py
```

- [ ] **Step 2: YAML 검증**

Run: `python -c "import yaml; yaml.safe_load(open('.github/workflows/refresh-known-actors.yml',encoding='utf-8')); print('YAML OK')"`
Expected: `YAML OK`

- [ ] **Step 3: README 안내 변경**

`README.md`의 known_actors 면책 항목에서 "등재 이의는 [GitHub Issues](...)." 문장을 다음으로 교체:

```markdown
인물 명단은 **제작자가 직접 관리**하며, 명단 관련 이의·문의는 제작자에게 직접 연락해 주세요(GitHub 프로필의 연락처).
```

(해당 줄은 `- **인물 낙인 안 함** — ...` 항목의 마지막 문장이다. "등재 이의는 [GitHub Issues](https://github.com/anboyu-alt/dart-risk-mcp/issues)." 부분만 위 문장으로 바꾼다.)

- [ ] **Step 4: CLAUDE.md 안내 정합화**

`CLAUDE.md`의 등재 기준 줄에서 "등재 이의는 GitHub Issues"를 "명단은 제작자가 직접 관리·연락(GitHub 프로필); 변경 시 제작자 이메일 통지(cron)"로 변경. status·자동 갱신 설명 근처에 "변경 시 `send_mail`로 제작자 Gmail 통지(자격증명 `MAIL_*` Secret)" 한 줄 추가.

- [ ] **Step 5: 전체 스위트 + 커밋**

Run: `python -m pytest tests/ -q`
Expected: 신규 회귀 0.

```bash
git add .github/workflows/refresh-known-actors.yml README.md CLAUDE.md
git commit -m "ci+docs: mail secrets env; maintainer-managed roster contact note"
```

---

## 검증 체크리스트 (완료 전)

- [ ] `test_refresh_known_actors.py` 7개 PASS (집계 요약·발송 스킵·발송)
- [ ] 전체 스위트: 신규 회귀 0
- [ ] YAML OK (MAIL_* env)
- [ ] README·CLAUDE.md 제작자 관리·연락 안내 반영
- [ ] 버전·PyPI 불변(패키지 코드 변경 없음 확인)
- [ ] 운영 안내: `MAIL_USER`/`MAIL_APP_PASSWORD`/`MAIL_TO` Secret 등록 (구현 후 사용자에게 안내)
```
