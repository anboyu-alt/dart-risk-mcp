"""MCPB(uv 런타임) 진입점 — Claude Desktop 확장에서 실행됩니다.

- DART_API_KEY는 확장 설정(user_config)에서 환경변수로 주입됩니다.
- 서버 로직 자체는 PyPI 패키지 dart-risk-mcp(pyproject.toml에 고정)가 제공합니다.
- stdio 전송으로 동작하며, 서버 코드는 이 파일에서 수정하지 않습니다.
"""
from dart_risk_mcp.server import main

if __name__ == "__main__":
    main()
