"""MCPB(Desktop Extension) 매니페스트 정합성 검증.

번들 스펙(공식 uv 예제 기준)의 필수 필드와, 세 곳(루트 pyproject·확장 pyproject·
manifest)의 버전이 어긋나지 않는지를 기계적으로 강제한다. 버전이 틀어지면
uv가 잘못된 버전을 당기거나 릴리스 첨부가 어긋나므로, 릴리스 전에 여기서 잡는다.
"""
from __future__ import annotations

import json
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _manifest() -> dict:
    return json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))


def _toml(rel: str) -> dict:
    return tomllib.loads((ROOT / rel).read_text(encoding="utf-8"))


def test_manifest_valid_json_required_fields():
    m = _manifest()
    assert m["manifest_version"] == "0.4"
    assert m["name"] == "dart-risk-mcp"
    assert m["version"]
    assert m["description"]
    assert m["author"]["name"]

    server = m["server"]
    assert server["type"] == "uv"
    assert server["entry_point"] == "src/server.py"

    cfg = server["mcp_config"]
    assert cfg["command"] == "uv"
    assert "${__dirname}" in cfg["args"]
    assert cfg["args"][-1] == "src/server.py"
    # DART 키는 user_config에서 환경변수로 주입된다(평문 하드코딩 금지).
    assert cfg["env"]["DART_API_KEY"] == "${user_config.dart_api_key}"


def test_user_config_key_is_sensitive_and_required():
    uc = _manifest()["user_config"]["dart_api_key"]
    assert uc["type"] == "string"
    assert uc["sensitive"] is True
    assert uc["required"] is True


def test_no_plaintext_key_in_manifest():
    # 실수로 실제 키를 넣지 않았는지: env 값은 반드시 치환 토큰이어야 한다.
    raw = (ROOT / "extension" / "manifest.json").read_text(encoding="utf-8")
    assert "${user_config.dart_api_key}" in raw


def test_versions_in_sync():
    m = _manifest()
    root_version = _toml("pyproject.toml")["project"]["version"]
    ext = _toml("extension/pyproject.toml")["project"]

    assert m["version"] == root_version, "manifest 버전이 패키지 버전과 달라요"
    assert ext["version"] == root_version, "확장 pyproject 버전이 패키지 버전과 달라요"
    assert f"dart-risk-mcp=={root_version}" in ext["dependencies"], (
        "확장 pyproject가 배포 버전을 정확히 고정해야 해요"
    )


def test_compatibility_declares_python_and_platforms():
    c = _manifest()["compatibility"]
    assert c["runtimes"]["python"].startswith(">=3.")
    assert {"darwin", "win32", "linux"}.issubset(set(c["platforms"]))
