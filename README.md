# dart-risk-mcp

DART 전자공시 기반 한국 기업 주가조작 위험 분석 MCP 서버.

"이 기업 투자해도 괜찮아?"라는 질문에 DART 공시 데이터로 답합니다.

## 기능

- **`analyze_company_risk`** — 기업명/종목코드로 최근 공시 분석 후 위험 등급 및 종합 리포트 반환
- **`check_disclosure_risk`** — 공시 접수번호/제목으로 해당 공시의 신호 유형·CB 인수자·원문 분석
- **`find_risk_precedents`** — 신호 조합별 위험 해석 및 복합 패턴 감지

## 탐지 신호

| 신호 | 점수 | 설명 |
|------|------|------|
| CB_BW | 3점 | 전환사채·BW 발행, 리픽싱 |
| 3PCA | 4점 | 제3자배정 유상증자 |
| SHAREHOLDER | 3점 | 최대주주 변경 |
| EXEC | 2점 | 임원 변동 |
| EMBEZZLE | 5점 | 횡령·배임·불공정거래 |
| AUDIT | 4점 | 감사의견 한정·거절 |
| INQUIRY | 3점 | 조회공시·거래정지 |
| MGMT | 3점 | 경영권 변동·합병·분할 |

**위험 등급**: 7점 이상 위험 / 10점 이상 고위험 / 15점 이상 매우위험

## 설치

### Claude Code (로컬)

```bash
pip install dart-risk-mcp
```

`.mcp.json`에 추가:

```json
{
  "mcpServers": {
    "dart-risk-analyzer": {
      "command": "dart-risk-mcp",
      "env": {
        "DART_API_KEY": "your_key_here"
      }
    }
  }
}
```

### uvx (설치 없이 실행)

```json
{
  "mcpServers": {
    "dart-risk-analyzer": {
      "command": "uvx",
      "args": ["dart-risk-mcp"],
      "env": {
        "DART_API_KEY": "your_key_here"
      }
    }
  }
}
```

## DART API 키 발급

1. [DART OpenAPI](https://opendart.fss.or.kr/) 접속
2. 회원가입 → API 신청 → 인증키 발급 (무료)

## 사용 예시

Claude Code에서:

```
에코프로 이 기업 투자해도 괜찮을까? 리스크 분석 해줘
→ analyze_company_risk("에코프로") 자동 호출

접수번호 20240315000123 공시 분석해줘
→ check_disclosure_risk(rcept_no="20240315000123") 호출

CB 발행 + 최대주주 변경 조합이 과거에 어떻게 됐어?
→ find_risk_precedents(["CB_BW", "SHAREHOLDER"]) 호출
```

## 신호 분류 체계

166건의 현장 기사(2025~2026)에서 도출한 27가지 기업 조작 유형을 기반으로 한 분류 체계를 사용합니다.

복합 패턴 예시:
- **Founder Fade**: CB 발행 + 최대주주 변경 (창업자 엑시트 전형 패턴)
- **Debt Spiral**: CB_BW + 감자 + 유상증자 (부채 돌려막기)

## 라이선스

MIT
