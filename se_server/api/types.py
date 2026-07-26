"""HTTP 요청·응답 자료구조.

Vercel의 BaseHTTPRequestHandler에 묶이지 않도록 최소한의 형태만 둔다.
어댑터가 이 형태로 변환해 넘기고, 핸들러는 프레임워크를 모른다.
"""
from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Request:
    method: str
    path: str
    headers: dict = field(default_factory=dict)
    body: dict = field(default_factory=dict)

    def header(self, name: str) -> str:
        """헤더를 대소문자 무시로 조회한다.

        HTTP 헤더 이름은 대소문자를 구분하지 않는데, 클라이언트·프록시마다
        표기가 달라 정확히 일치시키려 들면 조용히 못 찾는다.
        """
        target = name.lower()
        for key, value in self.headers.items():
            if key.lower() == target:
                return value
        return ""


@dataclass
class Response:
    status: int
    body: dict = field(default_factory=dict)

    @classmethod
    def error(cls, status: int, message: str) -> "Response":
        return cls(status=status, body={"error": message})
