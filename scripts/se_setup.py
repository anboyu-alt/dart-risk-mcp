"""SE Supabase 셋업·진단 — 무엇이 준비됐고 무엇이 남았는지 알려준다.

SQL(DDL)은 이 스크립트가 할 수 없다. Supabase는 PostgREST로 DDL을 허용하지
않고, Management API는 별도 개인 액세스 토큰을 요구한다. 대신:

- Storage 버킷은 **자동 생성**한다 (Storage REST로 가능)
- 테이블·컬럼은 **존재 여부만 확인**하고, 없으면 실행할 SQL 파일을 알려준다

사용:
    python scripts/se_setup.py            # 진단 + 버킷 생성
    python scripts/se_setup.py --check    # 진단만 (아무것도 만들지 않음)

자격증명은 환경변수 또는 .env.local에서 읽는다:
    SUPABASE_URL=https://xxxxx.supabase.co
    SUPABASE_SERVICE_KEY=<secret 또는 legacy service_role 키>
    SE_CACHE_BUCKET=se-cache        (선택, 기본값 se-cache)

**키는 출력하지 않는다.** 형식과 앞 몇 자만 표시한다.
"""
import argparse
import os
import pathlib
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts._console import use_utf8_stdout  # noqa: E402

import requests  # noqa: E402

from se_server.supabase_rest import auth_headers, looks_like_jwt  # noqa: E402

_ENV_FILE = pathlib.Path(__file__).resolve().parent.parent / ".env.local"
_SETUP_SQL = "se_server/sql/setup_all.sql"

OK = "  [OK]  "
NG = "  [--]  "
WARN = "  [!!]  "


def load_env_file() -> None:
    """.env.local이 있으면 환경변수로 읽어들인다(이미 설정된 값은 덮지 않는다)."""
    if not _ENV_FILE.exists():
        return
    for raw in _ENV_FILE.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        name, _, value = line.partition("=")
        name, value = name.strip(), value.strip().strip('"').strip("'")
        if name and name not in os.environ:
            os.environ[name] = value


def mask(key: str) -> str:
    """키를 안전하게 표시한다. 앞 12자만 보여준다."""
    if not key:
        return "(비어 있음)"
    return f"{key[:12]}… ({len(key)}자)"


def describe_key(key: str) -> str:
    if looks_like_jwt(key):
        return "legacy service_role (JWT)"
    if key.startswith("sb_secret_"):
        return "신형 secret"
    if key.startswith("sb_publishable_"):
        return "⚠ publishable — 권한이 부족합니다. secret 키가 필요합니다"
    return "알 수 없는 형식"


def check_env() -> tuple[str, str, str]:
    url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    key = os.environ.get("SUPABASE_SERVICE_KEY") or ""
    bucket = os.environ.get("SE_CACHE_BUCKET") or "se-cache"

    print("환경변수")
    print(f"{OK if url else NG}SUPABASE_URL          {url or '(비어 있음)'}")
    print(f"{OK if key else NG}SUPABASE_SERVICE_KEY  {mask(key)}")
    if key:
        note = describe_key(key)
        marker = WARN if note.startswith("⚠") else OK
        print(f"{marker}키 형식               {note}")
    print(f"{OK}SE_CACHE_BUCKET       {bucket}")

    if not url or not key:
        print()
        print("환경변수가 없습니다. .env.local에 아래처럼 넣거나 setx로 설정하세요:")
        print("    SUPABASE_URL=https://xxxxx.supabase.co")
        print("    SUPABASE_SERVICE_KEY=여기에키")
        return "", "", bucket
    return url, key, bucket


def check_table(session, url: str, key: str, table: str, columns: list[str]) -> bool:
    """테이블과 컬럼이 존재하는지 PostgREST로 확인한다."""
    try:
        resp = session.get(
            f"{url}/rest/v1/{table}",
            headers=auth_headers(key),
            params={"select": ",".join(columns), "limit": 0},
            timeout=15,
        )
    except Exception as exc:
        print(f"{NG}{table:12} 연결 실패: {type(exc).__name__}")
        return False

    if resp.status_code == 200:
        print(f"{OK}{table:12} 존재 (컬럼 {', '.join(columns)} 확인)")
        return True
    if resp.status_code in (401, 403):
        print(f"{NG}{table:12} 인증 거부 (HTTP {resp.status_code}) — 키를 확인하세요")
        return False
    # 404/400 = 테이블 또는 컬럼 없음
    print(f"{NG}{table:12} 없음 또는 컬럼 불일치 (HTTP {resp.status_code})")
    return False


def check_bucket(session, url: str, key: str, bucket: str, create: bool) -> bool:
    """Storage 버킷 존재를 확인하고, 없으면(create=True) 만든다."""
    try:
        resp = session.get(
            f"{url}/storage/v1/bucket/{bucket}", headers=auth_headers(key), timeout=15
        )
    except Exception as exc:
        print(f"{NG}버킷 {bucket:8} 연결 실패: {type(exc).__name__}")
        return False

    if resp.status_code == 200:
        try:
            is_public = bool((resp.json() or {}).get("public"))
        except ValueError:
            is_public = False
        if is_public:
            print(f"{WARN}버킷 {bucket:8} 존재하나 **public** 입니다 — private으로 바꾸세요")
            return False
        print(f"{OK}버킷 {bucket:8} 존재 (private)")
        return True

    if resp.status_code in (401, 403):
        print(f"{NG}버킷 {bucket:8} 인증 거부 (HTTP {resp.status_code}) — 키를 확인하세요")
        return False

    if not create:
        print(f"{NG}버킷 {bucket:8} 없음 (--check 모드라 만들지 않음)")
        return False

    try:
        made = session.post(
            f"{url}/storage/v1/bucket",
            headers={**auth_headers(key), "Content-Type": "application/json"},
            json={"name": bucket, "id": bucket, "public": False},
            timeout=15,
        )
    except Exception as exc:
        print(f"{NG}버킷 {bucket:8} 생성 실패: {type(exc).__name__}")
        return False

    if made.status_code < 300:
        print(f"{OK}버킷 {bucket:8} 생성함 (private)")
        return True
    print(f"{NG}버킷 {bucket:8} 생성 실패 (HTTP {made.status_code})")
    return False


def main() -> int:
    use_utf8_stdout()
    parser = argparse.ArgumentParser(description="SE Supabase 셋업·진단")
    parser.add_argument("--check", action="store_true",
                        help="진단만 수행하고 아무것도 만들지 않는다")
    args = parser.parse_args()

    load_env_file()
    url, key, bucket = check_env()
    if not url or not key:
        return 1

    session = requests.Session()

    print()
    print("테이블 (SQL Editor에서 만들어야 합니다)")
    tables_ok = all([
        check_table(session, url, key, "se_cache", ["key", "value", "expires_at"]),
        check_table(session, url, key, "se_jobs",
                    ["job_id", "state", "status", "user_id", "updated_at"]),
    ])

    print()
    print("Storage")
    bucket_ok = check_bucket(session, url, key, bucket, create=not args.check)

    print()
    if tables_ok and bucket_ok:
        print("모두 준비됐습니다. 다음: python scripts/se_verify_live.py")
        return 0

    if not tables_ok:
        print(f"테이블이 없습니다. Supabase SQL Editor에서 `{_SETUP_SQL}` 전체를")
        print("붙여넣고 실행하세요 (멱등이라 여러 번 실행해도 안전합니다).")
    if not bucket_ok:
        print(f"버킷 `{bucket}`을 Storage에서 private으로 만드세요.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
