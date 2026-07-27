# 리스크 뷰어 SE — 사용 안내

DART 공시 기반 불공정거래 위험 모니터링 도구를 인가된 사용자에게 웹으로
보여주는 화면입니다. 빌드 스텝도 외부 CDN도 없는 순수 정적 HTML/JS
(`index.html`·`app.js`·`ui.js`)이며, Vercel 서버리스 함수(`se_server/`,
`/api/se/*`)와 Supabase(인증 + Postgres 캐시/작업 상태)로 동작합니다.

## 계정 발급

이 화면은 회원가입 폼을 두지 않습니다(브리프: "인가 경계가 사라진다") —
계정은 **제작자가 Supabase 콘솔에서 직접 생성**합니다.

1. [Supabase 대시보드](https://supabase.com/dashboard) → 해당 프로젝트 →
   **Authentication → Users → Add user**
2. 이메일·비밀번호를 입력해 사용자를 만듭니다(이메일 확인 절차는 끕니다 —
   초대 링크를 따로 보내지 않는 내부 배포이므로).
3. 발급한 이메일·비밀번호를 사용자에게 안전한 채널로 전달합니다(평문 메신저
   대신 비밀번호 관리자 공유 등).
4. 사용자는 `/se/`에서 그 이메일·비밀번호로 로그인합니다. 로그인은
   `docs/tool/se/ui.js`의 `gotrue()`가 Supabase GoTrue REST를 SDK 없이
   직접 호출합니다(`POST {SUPABASE_URL}/auth/v1/token?grant_type=password`).

계정을 회수하려면 같은 화면에서 **Delete user**로 지웁니다 — 서버는 세션을
저장하지 않으므로(각 요청의 `Authorization: Bearer` 토큰만 검증) 별도
무효화 절차가 없습니다.

## DART API 키 보관 위치

- **서버는 DART 키를 저장하지 않습니다.** 사용자가 로그인 화면에서 입력한
  키는 브라우저 `localStorage`(`se_dart_key`)에만 남고, 매 요청마다
  `X-DART-Key` 헤더로 동봉됩니다(쿼리스트링에는 절대 싣지 않습니다 — URL
  로그·리퍼러에 남기 때문입니다. `test_dart_key_is_sent_as_header_only`가
  이를 정적으로 검증합니다).
- 서버(`se_server/`)는 각 요청에 실린 `X-DART-Key`를 그 요청 처리 동안만
  메모리에서 사용하고 어디에도 영속시키지 않습니다.
- 로그아웃(`doLogout()`)은 세션과 DART 키 양쪽을 모두 지웁니다 — 공용 PC에서
  다음 사용자가 앞사람의 키로 조회하지 못하게 하기 위해서입니다.
- 서버 자신이 필요로 하는 값(Supabase 자격증명 등)은 Vercel 환경변수입니다
  (`SUPABASE_URL`·`SUPABASE_SERVICE_KEY`·`SUPABASE_ANON_KEY`·
  `SE_CACHE_BUCKET`, `se_server/config.py` 참고). 이 값들도 사용자의 DART
  키와는 무관합니다.

## 이번 태스크(Task 5)에서 다룬 것

- **오류 표시**: `renderFailures(failed)`가 가져오지 못한 섹션을 화면에
  보여줍니다. 폴링마다 다시 불리므로 **누적하지 않고 교체**합니다(고정 노드
  `#sec-failures`를 재사용 — `renderSection`이 `sec-<key>`를 재사용하는
  방식과 동일). 서버가 이미 키를 스크럽해 보내므로(`runner._scrub`) 원인을
  숨기지 않습니다.
- **중단·재개**: 작업 상태는 Postgres에 있으므로 브라우저는 `job_id`만
  `localStorage`(`se_job`)에 남기면 탭을 닫았다 열어도 이어받습니다
  (`rememberJob`/`forgetJob`/`resumeIfAny`). 다만 `resumeTarget(saved, now)`가
  **12시간(`RESUME_WINDOW_MS`)보다 오래된 작업은 걸러냅니다** — 며칠 전
  작업을 조용히 이어받으면 사용자는 방금 새로 분석한 줄 오해하기 때문입니다.
  폴링 루프 자체는 `pollUntilDone(jobId, dartKey)`로 분리해 `analyze()`(새
  작업)와 `resumeIfAny()`(이어받는 작업)가 공유합니다.
- **폴링 루프의 네트워크 예외 안내**: `token()` 갱신 실패(세션 만료 등)는
  이미 `showGate()`로 로그인 화면을 띄우므로 추가 안내가 필요 없지만
  (`e.userSafe === true`), `fetch` 자체가 던지는 네트워크 예외 등은 그전엔
  안내 없이 폴링만 조용히 멈췄습니다 — 진행률 바가 멈춘 채 남아 사용자가
  원인을 알 수 없었습니다. 이제 `e.userSafe`가 아닌 예외는 진행률 바에
  최소 안내를 남기고 멈춥니다.
- **섹션 재귀 깊이 상한**: `sectionBlocks(value, depth)`에 상한
  (`MAX_SECTION_DEPTH = 20`)을 두었습니다. 서버 응답은 `JSON.parse` 산물이라
  현재는 도달 불가능하지만, 예상 밖으로 깊은 중첩이 오면 상한에 걸린 사실
  자체를 텍스트 블록으로 남깁니다(조용히 잘라내지 않습니다 — 이 화면
  전체의 원칙입니다).
- **섹션 제목 한글화**: `sectionHolder`의 `h2` 제목이 `label(key)`를 씁니다
  — `app.js`의 `LABELS`에 등록된 12개 1단 섹션 키(`fund_usage` 등)는
  한국어로, 등록되지 않은 키는 원본 그대로 나옵니다(숨기지 않습니다).

## 이번 태스크에서 다루지 않은 것 (SE-4c로 이월)

- **② 자금 체인, ③ 자금 시계열 레인**: 파생 로직을 `se_server/view/`에
  두고 pytest로 먼저 검증한 뒤 화면에 얹을 예정입니다. 지금 화면은 서버가
  준 섹션 값을 있는 그대로(표/텍스트로만) 보여줄 뿐, 여러 섹션을 엮어
  새로운 뷰를 파생시키지 않습니다.
- **라벨 맵 보강**: `LABELS`는 확신이 선 필드만 담습니다. 실제 서버 응답을
  더 보고 확신이 서는 필드가 늘어나면 그때 추가합니다.
- **회사 입력 → 분석 시작 폼**: `analyze(company, lookbackYears)`는 정의돼
  있지만, 이 화면에는 아직 회사명을 입력해 분석을 시작시키는 UI 요소(폼·
  버튼)가 없습니다. 로그인 이후 화면(`#main`)은 현재 빈 상태에서
  시작하며, `resumeIfAny()`만 자동으로 동작합니다. 이는 이전 태스크들
  (SE-4b 계열)에서 남은 공백으로 보이며, 이번 태스크(오류·재개·문서화)의
  범위 밖이라 여기서는 건드리지 않았습니다 — Step 7 인수 체크리스트의
  "로그인 후 회사 입력"을 프로덕션에서 실제로 확인하려면 이 폼이 먼저
  붙어야 합니다.
- **서버 주도 자동 완주·워터마크**: 의도적으로 하지 않습니다(사용자 결정).

## 프로덕션 확인 절차 (Step 7 — 사람이 브라우저에서 확인)

화면 거동은 사람 눈으로만 판정되므로 자동화하지 않습니다. 배포 후
`/se/`(Vercel `outputDirectory: docs/tool` + `rewrites: /api/se/* → /api/index`,
`vercel.json` 참고)에서 아래를 확인합니다.

| 확인 | 통과 기준 |
|---|---|
| `/se/` 접속 | 로그인 화면이 뜬다 |
| 잘못된 비밀번호 | 계정 존재 여부가 드러나지 않는 문구(`gotrue()`가 서버 원문 대신 다듬은 문구만 노출) |
| 로그인 후 회사 입력 | 헤더가 먼저 뜨고 섹션이 위에서부터 채워진다 (※ 위 "다루지 않은 것" 참고 — 회사 입력 UI가 아직 없다면 `analyze()`를 콘솔에서 직접 호출해 확인) |
| 개발자도구 Network | 같은 섹션 키를 두 번 받지 않는다 (`nextKeysToFetch`) |
| 개발자도구 Network | 진행률 응답(`GET /api/se/analyze/<id>`)이 수 KB대다 |
| 인물 이름 클릭 | 패널에 status·동명이인 경고·면책이 함께 뜬다 (`openActorPanel`) |
| 공시 제목(접수번호) 클릭 | 원문이 뜨고 본문 스크롤 위치가 유지된다 (`openDocPanel`) |
| 탭 닫았다 열기 | 12시간 내면 이어받는다(`resumeIfAny`), 12시간을 넘기면 새로 시작한다(`resumeTarget`) |
| 로그아웃 후 | DART 키(`localStorage.se_dart_key`)와 세션(`localStorage.se_session`)이 지워진다 |

사전 점검이 필요하면 `python scripts/se_setup.py --check`(테이블·버킷
존재 확인)와 `python scripts/se_verify_live.py`(Supabase 실측, 프로세스
경계를 넘는 캐시 검증까지 포함)를 먼저 돌립니다. 두 스크립트 모두 자격증명을
출력하지 않습니다.
