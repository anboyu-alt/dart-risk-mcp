"""core _retry 시임에 꽂히는 캐시 정책 계층.

두 갈래로 나눈다:
- 원문 ZIP(document.xml, fnlttXbrl.xml): 바이너리이고 rcept_no가 불변이므로
  blob 네임스페이스에 TTL 없이 저장한다.
- 그 외 JSON 엔드포인트: json 네임스페이스에 TTL을 두고 저장한다.

캐시 키에서 crtfc_key(사용자 DART API 키)를 반드시 제외한다. 원문과 공시
데이터는 공개 데이터이므로 전 사용자가 캐시를 공유하며, 키를 키 계산에
포함하면 공유 이점이 사라지고 사용자 자격증명이 저장소에 남는다.

근거: docs/superpowers/specs/2026-07-26-risk-viewer-se-design.md §6.2
"""
from __future__ import annotations

import base64
import hashlib
from urllib.parse import urlencode, urlsplit

from dart_risk_mcp.core import dart_client
from se_server.cache.base import CacheBackend

# ZIP 파일 매직 바이트. blob 저장 전 실제 ZIP인지 확인하는 데 쓴다.
_ZIP_MAGIC = b"PK\x03\x04"

# 캐시 키에서 제외할 파라미터 — 사용자 식별자에 해당한다.
_EXCLUDED_PARAMS = frozenset({"crtfc_key"})

# 바이너리(ZIP)로 응답하는 엔드포인트. blob 네임스페이스에 영구 저장한다.
# rcept_no가 불변 식별자이므로 stale이 발생하지 않는 것들만 넣는다.
_BLOB_ENDPOINTS = frozenset({"document.xml", "fnlttXbrl.xml"})

# 캐시하지 않는 엔드포인트.
# corpCode.xml(전체 기업 코드 목록)은 신규 상장으로 계속 바뀌므로 불변이 아니다.
# core의 _load_corp_codes가 이미 24시간 파일 캐시를 두고 있으며, 여기서 다시
# 캐시하면 그 갱신 주기를 무력화한다.
_NEVER_CACHE = frozenset({"corpCode.xml"})

_DEFAULT_JSON_TTL = 7 * 24 * 3600  # 7일


def _endpoint_of(url: str) -> str:
    """URL 경로의 마지막 조각(엔드포인트 파일명)을 반환한다."""
    return urlsplit(url).path.rsplit("/", 1)[-1]


class CachingHttp:
    """dart_client.set_http_cache()에 주입되는 캐시 어댑터."""

    def __init__(self, backend: CacheBackend, json_ttl_seconds: int = _DEFAULT_JSON_TTL) -> None:
        self.backend = backend
        self.json_ttl_seconds = json_ttl_seconds

    def cache_key(self, url: str, params: dict) -> str:
        """(엔드포인트, 사용자 키를 제외한 파라미터)로 안정적인 키를 만든다.

        값을 URL 인코딩해 정규화한다. 단순 문자열 결합은 값에 `&`나 `=`가
        섞이면 서로 다른 파라미터 조합이 같은 문자열로 축약돼 키가 충돌한다
        (예: {"a": "b&c=d"} 와 {"a": "b", "c": "d"}).
        """
        endpoint = _endpoint_of(url)
        items = sorted(
            (str(k), str(v))
            for k, v in (params or {}).items()
            if k not in _EXCLUDED_PARAMS
        )
        canonical = endpoint + "?" + urlencode(items)
        digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:32]
        return f"{endpoint}/{digest}"

    def _is_blob(self, url: str) -> bool:
        return _endpoint_of(url) in _BLOB_ENDPOINTS

    def _is_cacheable(self, url: str) -> bool:
        return _endpoint_of(url) not in _NEVER_CACHE

    def get(self, url: str, params: dict) -> tuple[int, dict, bytes] | None:
        if not self._is_cacheable(url):
            return None
        key = self.cache_key(url, params)
        if self._is_blob(url):
            body = self.backend.get_blob(key)
            if body is None:
                return None
            return 200, {"Content-Type": "application/zip"}, body

        entry = self.backend.get_json(key)
        if entry is None:
            return None
        body = base64.b64decode(entry["body_b64"])
        return int(entry["status"]), dict(entry.get("headers") or {}), body

    def put(self, url: str, params: dict, status: int, headers: dict, body: bytes) -> None:
        if status != 200 or not self._is_cacheable(url):
            return
        key = self.cache_key(url, params)
        if self._is_blob(url):
            # DART /document.xml은 키 오류·조회 실패 시에도 HTTP 200으로
            # 응답하면서 바디에 JSON/텍스트 오류 메시지를 담는다(core의
            # _fetch_document_zip이 같은 이유로 Content-Type을 검사한다).
            # blob은 TTL 없이 영구 보관되고 캐시 키가 crtfc_key를 제외해
            # 전 사용자가 공유하므로, 오류 바디가 한 번 들어가면 해당
            # rcept_no가 모두에게 영구히 조회 불가가 된다. 실제 ZIP인지
            # 확인한 뒤에만 저장한다.
            if not body.startswith(_ZIP_MAGIC):
                return
            self.backend.put_blob(key, body)
            return
        self.backend.put_json(
            key,
            {
                "status": status,
                "headers": {"Content-Type": (headers or {}).get("Content-Type", "application/json")},
                "body_b64": base64.b64encode(body).decode("ascii"),
            },
            ttl_seconds=self.json_ttl_seconds,
        )


def install(backend: CacheBackend, json_ttl_seconds: int = _DEFAULT_JSON_TTL) -> CachingHttp:
    """CachingHttp를 만들어 core 시임에 주입하고 반환한다."""
    http = CachingHttp(backend, json_ttl_seconds=json_ttl_seconds)
    dart_client.set_http_cache(http)
    return http
