# dart-risk-mcp

개인 작업용. DART 공시를 흐름으로 읽어 불공정거래 신호를 사실로 표기하는 MCP 서버.

## 돌리기

```bash
pip install -e .
python -m dart_risk_mcp
```

```json
{
  "mcpServers": {
    "dart-risk": {
      "command": "python",
      "args": ["-m", "dart_risk_mcp"],
      "env": { "DART_API_KEY": "..." }
    }
  }
}
```

- `DART_API_KEY` 필수
- `KRX_API_KEY` · `KIS_APP_KEY` + `KIS_APP_SECRET` 선택 — 시세 대조용(KRX 먼저, 빈 날은 KIS)

## 메모

- 설계·실측 근거는 전부 `CLAUDE.md`
- 보류한 판단은 `docs/DEFERRED-DECISIONS.md`
- 뷰어 소스는 `docs/tool/`
- 테스트는 키 없이: `env -u DART_API_KEY python -m pytest tests/ -q`
- 골든 재생성: `python scripts/regen_goldens.py`
- 릴리스 순서: `CLAUDE.md` 「릴리스 정책」

MIT. 일부 로직은 kreports-dart-mcp(Apache 2.0)에서 이식 — `THIRD_PARTY_NOTICES.md`.
