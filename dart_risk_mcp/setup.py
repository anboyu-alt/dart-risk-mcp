"""대화형 셋업 — JSON 직접 편집 없이 한 번 실행으로 MCP 클라이언트에 등록.

사용:
    python -m dart_risk_mcp.setup                   # 대화형 메뉴
    python -m dart_risk_mcp.setup --client claude-desktop --api-key 발급키
    python -m dart_risk_mcp.setup --dry-run         # 저장 안 함, 결과만 출력

지원 클라이언트:
- Claude Desktop (macOS·Windows·Linux)
- Cursor (글로벌 ~/.cursor/mcp.json)
- Windsurf (글로벌 ~/.codeium/windsurf/mcp_config.json)
- Claude Code (별도 — `claude mcp add` 명령 사용 안내만)

기존 mcpServers 블록은 보존됩니다. 이미 같은 이름이 등록돼 있으면 덮어쓸지 묻습니다.
저장 전 항상 `.json.bak` 백업 파일을 만듭니다.
"""
from __future__ import annotations

import argparse
import json
import os
import platform
import sys
from pathlib import Path


def claude_desktop_path() -> Path:
    home = Path.home()
    sys_name = platform.system()
    if sys_name == "Windows":
        appdata = os.environ.get("APPDATA")
        base = Path(appdata) if appdata else home / "AppData" / "Roaming"
        return base / "Claude" / "claude_desktop_config.json"
    if sys_name == "Darwin":
        return home / "Library" / "Application Support" / "Claude" / "claude_desktop_config.json"
    return home / ".config" / "Claude" / "claude_desktop_config.json"


def cursor_path() -> Path:
    return Path.home() / ".cursor" / "mcp.json"


def windsurf_path() -> Path:
    return Path.home() / ".codeium" / "windsurf" / "mcp_config.json"


CLIENTS: dict[str, tuple[str, callable]] = {
    "claude-desktop": ("Claude Desktop", claude_desktop_path),
    "cursor": ("Cursor (글로벌 설정)", cursor_path),
    "windsurf": ("Windsurf (글로벌 설정)", windsurf_path),
}

SERVER_BLOCK_TEMPLATE = {
    "command": "python",
    "args": ["-m", "dart_risk_mcp"],
    "env": {},  # DART_API_KEY를 채워 넣음
}


def _interactive_select_client() -> str:
    print("어떤 AI 클라이언트에 등록할까요?\n")
    keys = list(CLIENTS.keys())
    for i, key in enumerate(keys, 1):
        label, path_fn = CLIENTS[key]
        path = path_fn()
        existing = "✓ 파일 있음" if path.exists() else "(파일 없음 — 새로 생성)"
        print(f"  {i}. {label}  {existing}")
    print("  q. 취소\n")
    print("Claude Code 사용자는 'q'로 취소하고 다음 명령을 직접 사용하세요:")
    print("  claude mcp add dart-risk-analyzer --env DART_API_KEY=발급키 -- python -m dart_risk_mcp\n")
    while True:
        choice = input("번호 입력: ").strip().lower()
        if choice == "q":
            sys.exit(0)
        if choice.isdigit():
            idx = int(choice) - 1
            if 0 <= idx < len(keys):
                return keys[idx]
        print(f"  → 1~{len(keys)} 중 하나 또는 q.")


def _ask_api_key() -> str:
    print("\nDART API 키를 입력하세요 (없으면 https://opendart.fss.or.kr 에서 무료 발급).")
    key = input("API 키: ").strip()
    if not key:
        sys.stderr.write("ERROR: API 키 미입력\n")
        sys.exit(2)
    if len(key) != 40 or not all(c.isalnum() for c in key):
        print(f"⚠  DART API 키는 보통 40자 영문/숫자 (현재 {len(key)}자)")
        if input("그래도 진행할까요? [y/N]: ").strip().lower() != "y":
            sys.exit(0)
    return key


def _load_config(path: Path) -> dict:
    if not path.exists():
        return {}
    try:
        text = path.read_text(encoding="utf-8").strip()
        return json.loads(text) if text else {}
    except json.JSONDecodeError as exc:
        sys.stderr.write(
            f"ERROR: 기존 파일이 JSON 문법 오류 — 수동 점검 필요\n  {path}\n  {exc}\n"
        )
        sys.exit(2)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="DART Risk MCP를 AI 클라이언트에 자동 등록",
    )
    parser.add_argument("--client", choices=list(CLIENTS),
                        help="대상 클라이언트 (미지정 시 대화형 메뉴)")
    parser.add_argument("--api-key", help="DART API 키 (미지정 시 stdin 입력)")
    parser.add_argument("--server-name", default="dart-risk-analyzer",
                        help="등록 이름 (기본: dart-risk-analyzer)")
    parser.add_argument("--dry-run", action="store_true",
                        help="저장 안 함, 결과 JSON만 출력")
    parser.add_argument("--force", action="store_true",
                        help="이미 등록된 같은 이름을 덮어쓸지 묻지 않고 자동 덮어씀")
    args = parser.parse_args()

    client_key = args.client or _interactive_select_client()
    label, path_fn = CLIENTS[client_key]
    config_path = path_fn()

    print(f"\n대상: {label}")
    print(f"설정 파일: {config_path}")
    print(f"등록 이름: {args.server_name}\n")

    api_key = args.api_key or os.environ.get("DART_API_KEY") or _ask_api_key()

    data = _load_config(config_path)

    servers = data.setdefault("mcpServers", {})
    if args.server_name in servers and not args.force and not args.dry_run:
        ans = input(f"⚠  '{args.server_name}'가 이미 등록돼 있습니다. 덮어쓸까요? [y/N]: ").strip().lower()
        if ans != "y":
            print("취소.")
            return 0

    block = dict(SERVER_BLOCK_TEMPLATE)
    block["env"] = {"DART_API_KEY": api_key}
    servers[args.server_name] = block

    if args.dry_run:
        print("=== dry-run — 저장하지 않음 ===")
        print(json.dumps(data, indent=2, ensure_ascii=False))
        return 0

    if config_path.exists():
        backup = config_path.with_suffix(config_path.suffix + ".bak")
        backup.write_text(config_path.read_text(encoding="utf-8"), encoding="utf-8")
        print(f"백업 → {backup}")

    config_path.parent.mkdir(parents=True, exist_ok=True)
    config_path.write_text(
        json.dumps(data, indent=2, ensure_ascii=False) + "\n",
        encoding="utf-8",
    )
    print(f"✓ 등록 완료 → {config_path}\n")
    print(f"다음 단계: {label}을 완전히 종료 후 재시작하세요.")
    print("(Windows: 작업 표시줄 트레이 아이콘에서 종료. macOS: ⌘+Q.)")
    print("\n재시작 후 망치 아이콘에 23개 도구가 보이면 설치 성공입니다.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
