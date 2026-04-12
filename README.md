# dart-risk-mcp

DART 전자공시 기반 한국 기업 투자 위험 분석 MCP 서버.

AI 대화 중에 **"이 기업 투자해도 괜찮아?"** 라고 물으면 최근 공시를 분석해서 위험 등급과 리포트를 돌려줍니다.

---

## 이게 뭔가요?

한국 금융감독원 DART 공시 시스템에서 최근 공시를 가져와 주가조작 세력이 자주 쓰는 패턴(전환사채 발행, 제3자배정 유상증자, 최대주주 변경, 횡령·배임 등)을 탐지합니다.

166건의 실제 사건 기사를 분석해 만든 27가지 조작 유형 분류 체계를 사용합니다.

**탐지 신호:**

| 신호 | 점수 | 예시 공시 |
|------|------|----------|
| CB/BW 발행 | 3점 | 전환사채권발행결정, 리픽싱 |
| 제3자배정 증자 | 4점 | 제3자배정 유상증자결정 |
| 최대주주 변경 | 3점 | 최대주주변경, 대주주변경 |
| 임원 변동 | 2점 | 임원의변동, 대표이사변경 |
| 횡령·배임 | 5점 | 횡령, 배임, 불공정거래 |
| 감사의견 이상 | 4점 | 한정의견, 의견거절 |
| 조회공시 | 3점 | 조회공시, 거래정지, 주가이상 |
| 경영권 변동 | 3점 | 경영권변동, 합병결정, 공개매수 |

**위험 등급:** 7점↑ 위험 / 10점↑ 고위험 / 15점↑ 매우위험

---

## 사용 예시

```
에코프로 최근 공시 분석해줘
→ 📊 기업 리스크 분석: 에코프로비엠
   🟠 위험 등급: 고위험 (11점)
   ...

접수번호 20240315000123 공시가 위험한 건지 봐줘
→ 📋 공시 리스크 분석: 전환사채권발행결정
   ...

CB 발행이랑 최대주주 변경이 같이 나왔을 때 어떤 의미야?
→ 📚 신호 위험 해석: "The Founder Fade" 패턴 감지
   ...
```

---

## 준비물

**DART API 키** (무료)

1. [opendart.fss.or.kr](https://opendart.fss.or.kr) 접속
2. 회원가입 → 로그인 → 오픈API → 인증키 신청
3. 이메일로 인증키 수령 (보통 당일)

---

## 설치 방법

### Claude Desktop

설정 파일을 열고 아래 내용을 추가합니다.

**파일 위치:**
- macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
- Windows: `%APPDATA%\Claude\claude_desktop_config.json`

```json
{
  "mcpServers": {
    "dart-risk-analyzer": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/anboyu-alt/dart-risk-mcp", "dart-risk-mcp"],
      "env": {
        "DART_API_KEY": "여기에_발급받은_키_입력"
      }
    }
  }
}
```

저장 후 Claude Desktop 재시작.

### Cursor / Windsurf / Claude Code

프로젝트 루트에 `.mcp.json` 파일 생성:

```json
{
  "mcpServers": {
    "dart-risk-analyzer": {
      "command": "uvx",
      "args": ["--from", "git+https://github.com/anboyu-alt/dart-risk-mcp", "dart-risk-mcp"],
      "env": {
        "DART_API_KEY": "여기에_발급받은_키_입력"
      }
    }
  }
}
```

저장 후 에디터 재시작 또는 MCP 서버 새로고침.

> **`uvx`가 없다면:** `pip install uv` 또는 [uv 공식 설치 페이지](https://docs.astral.sh/uv/getting-started/installation/)

---

## 자주 묻는 질문

**Q. 설치 후 도구가 안 보여요.**
→ 앱을 완전히 종료 후 재시작. 첫 실행 시 GitHub에서 패키지를 받아야 해서 1~2분 걸릴 수 있습니다.

**Q. DART_API_KEY 오류가 나요.**
→ `.mcp.json`의 `"여기에_발급받은_키_입력"` 부분을 실제 키로 교체했는지 확인.

**Q. 기업명을 입력했는데 못 찾는다고 해요.**
→ 정식 상장사명으로 입력하거나 종목코드 6자리를 사용하세요. (예: `에코프로` 대신 `에코프로비엠`, 또는 `247540`)

**Q. 처음 실행이 느려요.**
→ DART에서 전체 상장사 목록(9만여 개)을 받아오기 때문에 첫 실행은 10~20초 걸립니다. 이후 24시간 동안 캐시됩니다.

---

## 라이선스

무료로 자유롭게 사용·수정·배포할 수 있습니다. 출처(GitHub 주소)만 남겨주세요.

(MIT License — 매사추세츠 공과대학과 무관한, 오픈소스에서 가장 널리 쓰이는 자유 사용 허가 형식입니다)
