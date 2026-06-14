# 설계: known_actors 변경 이메일 알림 + 제작자 관리 안내

- 날짜: 2026-06-14
- 범위: cron 변경 시 제작자 이메일 통지 + README 안내 (버전업 없음)
- 상태: 사용자 리뷰 대기

## 배경 / 문제

known_actors 자동 갱신은 매일 cron으로 돌며 변경 시 master에 조용히 커밋한다.
제작자는 매일 검토할 여력이 없으므로, 변경이 생겼을 때만 **제작자 이메일로 DB 요약**을
받아 능동적으로 확인하고자 한다.

public repo라 데이터·이슈는 공개되지만, **이메일은 비공개 채널**이고 SMTP 자격증명은
GitHub Secret에 두므로 노출되지 않는다. 데이터 자체(유저용 공개 데이터)는 그대로 둔다.

## 핵심 결정 (확정)

1. **이메일만(이슈 없음)** — 비공개 알림 목적상 public 이슈는 부적합. 제작자 Gmail로 발송.
2. **Gmail + smtplib** — Python 표준 라이브러리만(외부 라이브러리 0 원칙 유지).
3. **변경 시에만 발송** — 변화 없는 날은 메일 없음.
4. **버전업 없음** — 워크플로우·스크립트(CI)와 README(docs)만 변경. PyPI 패키지 코드 불변, 1.3.0 유지.
5. **유저 연락 경로** — README에서 "명단 이의·문의는 제작자에게 직접 연락(GitHub 프로필 연락처)". 공개 이슈 강제 안 함.

## 컴포넌트

### 1. `scripts/refresh_known_actors.py`에 추가

- `build_change_summary(data: dict, matches: dict) -> str`
  - status별 집계: `verified`/`maintainer_seed`/`auto_matched` 각 인물 수
  - 이번 변경분(`matches`)의 각 항목: `인물 — 회사 evidence — rcept_no`
  - 사실+면책 톤(판정 없음). 순수 문자열 반환(I/O 없음 → 테스트 용이).
- `send_mail(subject: str, body: str) -> bool`
  - env: `MAIL_USER`(Gmail 주소), `MAIL_APP_PASSWORD`(앱 비밀번호), `MAIL_TO`(수신).
  - 하나라도 없으면 **발송 스킵하고 `False` 반환**(로컬 실행·미설정 시 graceful).
  - `smtplib.SMTP("smtp.gmail.com", 587)` → `starttls()` → `login` → `send_message`.
    `email.message.EmailMessage`로 구성(둘 다 표준 라이브러리).
  - 발송 성공 시 `True`. 예외는 잡아 `False`(파이프라인 실패시키지 않음).
- `main()`: 변경(`changed`)이 있을 때만 `summary = build_change_summary(data, matches)` →
  `send_mail("[known_actors] 자동 갱신 변경 알림", summary)`. 결과를 print.

### 2. 워크플로우 `.github/workflows/refresh-known-actors.yml`

- 스크립트 step의 `env`에 추가:
  ```yaml
  MAIL_USER: ${{ secrets.MAIL_USER }}
  MAIL_APP_PASSWORD: ${{ secrets.MAIL_APP_PASSWORD }}
  MAIL_TO: ${{ secrets.MAIL_TO }}
  ```
  (`DART_API_KEY`와 같은 step의 env로 병기.)

### 3. README 갱신

- 기존 known_actors 면책 항목의 "등재 이의는 GitHub Issues" 문구를
  "인물 명단은 제작자가 직접 관리합니다. 명단 관련 이의·문의는 제작자에게 직접
  연락해 주세요(GitHub 프로필의 연락처)."로 변경.
- (CLAUDE.md의 등재 기준 "등재 이의는 GitHub Issues"도 동일 취지로 정합화 — 단,
  내부 문서이므로 GitHub Issues 경로는 유지하되 "제작자 직접 연락"을 병기.)

## 데이터 흐름

```
[cron] refresh_known_actors.main()
  collect_auto_matches → merge_auto_matches(changed?)
    changed=True → build_change_summary → send_mail(Gmail, Secret) → 제작자 수신
    changed=False → 메일 없음
```

## 오류 처리

- 자격증명 미설정 → `send_mail`이 `False`(스킵). 갱신 자체는 정상 진행.
- SMTP 예외(네트워크·인증 실패) → 잡아서 `False`. cron 실패시키지 않음(데이터 커밋은 이미 완료).

## 테스트 (TDD)

`tests/test_refresh_known_actors.py`에 추가:
1. `build_change_summary` — verified/seed/auto 집계 수치 + 변경분 인물·회사·rcept_no가 본문에 포함.
2. `send_mail` 자격증명 미설정 → `False`(발송 안 함). `smtplib.SMTP`가 호출되지 않음(mock).
3. `send_mail` 자격증명 설정 + smtplib mock → `True`, `send_message` 1회 호출.

## 비범위

- 이슈 자동 생성 — 비공개 목적상 제외.
- 데이터 자체 비공개(private repo) — 유저용 공개 데이터라 유지.
- 버전 변경·PyPI 재배포 — 패키지 코드 불변.
- 메일 첨부·HTML 서식 — 평문 요약으로 충분(YAGNI).

## 운영 안내 (구현 후)

- GitHub repo Secret에 `MAIL_USER`/`MAIL_APP_PASSWORD`/`MAIL_TO` 등록.
- Gmail은 2단계 인증 계정에서 "앱 비밀번호" 발급해 `MAIL_APP_PASSWORD`로 사용.
