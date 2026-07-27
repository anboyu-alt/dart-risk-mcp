"""SE HTTP API 계층.

요청 처리는 프레임워크와 무관한 순수 함수로 두고, Vercel 어댑터(api/index.py)는
얇게 유지한다. 라우팅을 파일 배치가 아니라 코드에 두는 이유는 테스트 가능성이다.
"""
from se_server.api.types import Request, Response

__all__ = ["Request", "Response"]
