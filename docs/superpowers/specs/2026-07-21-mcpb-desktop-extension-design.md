# MCPB Desktop Extension (원클릭 설치) — 설계 문서

- 날짜: 2026-07-21
- 상태: 승인됨(사용자 위임 — spec 상세 검토 생략 요청)
- 범위: Phase 1 (.mcpb Desktop Extension). Phase 2(원격 커스텀 커넥터)는 별도 spec.

## 목표

Claude Desktop 사용자가 **터미널 없이 원클릭**으로 dart-risk-mcp를 설치하게 한다.
Releases에서 `.mcpb` 다운로드 → Claude Desktop 설정 → Extensions에서 열기 →
설정 칸에 DART API 키 붙여넣기 → 끝.

## 배경 / 사실 확인 (MCPB 공식 스펙)

- DXT → **MCPB(MCP Bundles)** 로 리네이밍. CLI `@anthropic-ai/mcpb`(`mcpb init`, `mcpb pack`).
- `.mcpb` = zip(manifest.json + 서버). Claude Desktop이 원클릭 설치/자동업데이트/설정 UI 제공.
- `server.type`: `node` | `python` | `binary` | **`uv`**.
  - `python` 타입: **모든 의존성을 번들에 포함**(`server/lib` 또는 `server/venv`). 우리는 `mcp → pydantic-core`(네이티브 컴파일 휠) 때문에 **플랫폼·파이썬버전별 빌드가 강제**됨.
  - **`uv` 타입(채택)**: 의존성을 `pyproject.toml`로 선언하고 **호스트(Claude Desktop)가 UV로 설치**. 네이티브 휠은 설치 시점에 플랫폼에 맞게 해결 → **단일 크로스플랫폼 번들** 하나로 끝. (UV Runtime은 스펙 v0.4+.)
- `user_config` 필드(`type: string`, `sensitive: true`, `required: true`) → `mcp_config.env`에서 `${user_config.<key>}`로 주입.

## 결정 사항

1. **전송 방식은 stdio 그대로.** 서버 코드/도구 무변경 → 기존 pip·setup 사용자 제로 회귀.
2. **`uv` 서버 타입 단일 번들.** OS 1개 번들, 용량 작고 유지 단순.
3. **파이썬 사전 설치는 가정**(사용자 결정). uv 타입은 호스트가 의존성/런타임을 관리하므로 실사용상 부담이 더 작음.
4. **기존 설치 경로(pip + `python -m dart_risk_mcp.setup`) 유지.** 원클릭은 "가장 쉬운 길"로 최상단에 **추가**하되 기존 안내는 삭제하지 않음(Cursor·Windsurf·Claude Code·비Claude Desktop 대안).

## 산출물 (저장소)

- `extension/manifest.json`
  - `manifest_version`: uv 요구 버전(빌드 시 `mcpb` CLI/MANIFEST.md 스키마로 확정).
  - `name`, `display_name`, `version`(pyproject와 동기), `description`(**"공시 기반 불공정거래 위험 모니터링"** 포지셔닝 유지), `long_description`.
  - `author`, `repository`, `homepage`, `license: MIT`, `keywords`, `icon`.
  - `server.type: "uv"`, `entry_point`, `mcp_config`(command/args는 `mcpb init` 스캐폴딩으로 확정), `env: { "DART_API_KEY": "${user_config.dart_api_key}" }`.
  - `user_config.dart_api_key`: `type: string`, `sensitive: true`, `required: true`, `title: "DART API 키"`, `description`(무료 발급 https://opendart.fss.or.kr 안내).
  - `compatibility`: `runtimes.python ">=3.11"`, `platforms: ["darwin","win32","linux"]`, `claude_desktop`: uv 지원 최소 버전 명시.
- `extension/pyproject.toml` — 런타임 의존성(`mcp`, `requests`)만 선언. 우리 `dart_risk_mcp` 소스를 번들에 포함(버전 고정·자기완결, pip 미의존).
- `.mcpbignore` — `tests/`·`docs/`·`__pycache__`·`.venv`·기타 비런타임 제외.
- `extension/icon.png` — 확장 목록 아이콘(단순).

## 빌드 · 배포

- 로컬: `npm i -g @anthropic-ai/mcpb` → `mcpb pack` → `dart-risk-mcp.mcpb`.
- CI: `.github/workflows/build-mcpb.yml` — 릴리스 태그 시 `mcpb pack` 실행 후 **GitHub Release에 `.mcpb` 첨부**. `actions/checkout@v5`, Node 24 러너(메모리 지침: Node 24 강제·checkout@v5·setup-python@v6+).
- 버전 동기화: `manifest.json.version == pyproject.toml.version`(현재 1.6.0). 불일치 검사 테스트로 강제.

## 문서

- `README.md` · `docs/index.html`: 최상단에 "가장 쉬운 설치 — 원클릭 확장(.mcpb)" 경로 추가(터미널 0). 기존 pip 5단계 가이드는 "다른 방법"으로 유지.

## 테스트 · 회귀 영향

- 신규 테스트: manifest **JSON 유효성 + 필수 필드 존재 + 버전 동기화**.
- 기존: 서버/도구/파이썬 코드 무변경 → 기존 테스트 459개·골드 133건·hygiene 무영향.
- 하위 호환: 기존 설치 경로 전부 보존(삭제 없음).

## 남은 리스크 (구현 시 공식 문서로 확정)

- `uv` 타입의 정확한 `manifest_version`·`mcp_config` 필드 형태 → `mcpb init` + MANIFEST.md 스키마로 확정.
- uv 런타임 지원 최소 Claude Desktop 버전 → `compatibility.claude_desktop`에 반영.
- `mcpb pack`이 우리 소스+pyproject를 올바르게 담는지 실팩 검증(CI/로컬).

## 비범위 (Phase 1)

- 원격 호스팅, Streamable HTTP 전환, OAuth/키 등록 화면 → 전부 Phase 2.
- Claude Desktop 외 앱의 확장 디렉터리 등재 → 후속.
