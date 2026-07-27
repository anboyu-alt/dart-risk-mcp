"""배포된 SE API 종단 검증 — 인증 벽 뒤를 실제로 통과해 본다.

지금까지 확인한 것은 인증 **거부**까지였다. 실제로 인증을 통과했을 때
작업 생성·진행·조회가 되는지, 그리고 **교차 사용자 격리**가 배포 환경에서
실제로 걸리는지는 확인되지 않았다.

이 스크립트는 임시 테스트 계정 2개를 만들어 그 경로를 밟고, **끝나면
반드시 지운다**(실패해도 finally에서 정리).

사용:
    python scripts/se_verify_api.py                       # 프로덕션
    python scripts/se_verify_api.py --base http://...     # 다른 배포
    python scripts/se_verify_api.py --keep-users          # 정리 생략(디버깅)

필요한 자격증명(.env.local 또는 환경변수):
    SUPABASE_URL, SUPABASE_SERVICE_KEY   — 테스트 계정 생성·삭제용
    DART_API_KEY                          — 작업 실행용 (tmp/_apikey.txt도 가능)

**어떤 키도 출력하지 않는다.**
"""
import argparse
import os
import pathlib
import secrets
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts._console import use_utf8_stdout  # noqa: E402

import requests  # noqa: E402

from se_server.supabase_rest import auth_headers  # noqa: E402

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_ENV_FILE = _ROOT / ".env.local"
_DEFAULT_BASE = "https://dart-risk-mcp.vercel.app"

PASS = "  [PASS]  "
FAIL = "  [FAIL]  "
INFO = "  [ .. ]  "

_failures: list[str] = []


def load_env() -> None:
    if _ENV_FILE.exists():
        for raw in _ENV_FILE.read_text(encoding="utf-8").splitlines():
            line = raw.strip()
            if line and not line.startswith("#") and "=" in line:
                k, _, v = line.partition("=")
                os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))
    if not os.environ.get("DART_API_KEY"):
        p = _ROOT / "tmp" / "_apikey.txt"
        if p.exists():
            os.environ["DART_API_KEY"] = p.read_text(encoding="utf-8").strip()


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"{PASS if ok else FAIL}{label}{('  — ' + detail) if detail else ''}")
    if not ok:
        _failures.append(label)
    return ok


class TestUser:
    """임시 Supabase 계정. 컨텍스트를 벗어나면 지운다."""

    def __init__(self, session, supabase_url: str, service_key: str, tag: str):
        self.session = session
        self.url = supabase_url
        self.key = service_key
        self.email = f"se-verify-{tag}-{secrets.token_hex(4)}@example.com"
        self.password = secrets.token_urlsafe(24)
        self.user_id = ""
        self.access_token = ""

    def create(self) -> None:
        r = self.session.post(
            f"{self.url}/auth/v1/admin/users",
            headers={**auth_headers(self.key), "Content-Type": "application/json"},
            json={"email": self.email, "password": self.password,
                  "email_confirm": True},
            timeout=20,
        )
        if r.status_code >= 300:
            raise RuntimeError(f"계정 생성 실패 (HTTP {r.status_code})")
        self.user_id = (r.json() or {}).get("id", "")

    def sign_in(self) -> None:
        r = self.session.post(
            f"{self.url}/auth/v1/token",
            headers={**auth_headers(self.key), "Content-Type": "application/json"},
            params={"grant_type": "password"},
            json={"email": self.email, "password": self.password},
            timeout=20,
        )
        if r.status_code >= 300:
            raise RuntimeError(f"로그인 실패 (HTTP {r.status_code})")
        self.access_token = (r.json() or {}).get("access_token", "")
        if not self.access_token:
            raise RuntimeError("access_token을 받지 못했습니다")

    def delete(self) -> bool:
        if not self.user_id:
            return True
        try:
            r = self.session.delete(
                f"{self.url}/auth/v1/admin/users/{self.user_id}",
                headers=auth_headers(self.key), timeout=20)
            return r.status_code < 300
        except Exception:
            return False


def api(session, base: str, method: str, path: str, token: str,
        dart_key: str = "", body: dict | None = None):
    headers = {"Authorization": f"Bearer {token}"}
    if dart_key:
        headers["X-DART-Key"] = dart_key
    if body is not None:
        headers["Content-Type"] = "application/json"
    r = session.request(method, f"{base}{path}", headers=headers,
                        json=body, timeout=60)
    try:
        return r.status_code, r.json()
    except ValueError:
        return r.status_code, {"_raw": r.text[:200]}


def main() -> int:
    use_utf8_stdout()
    parser = argparse.ArgumentParser(description="배포된 SE API 종단 검증")
    parser.add_argument("--base", default=_DEFAULT_BASE)
    parser.add_argument("--company", default="셀트리온")
    parser.add_argument("--steps", type=int, default=2,
                        help="실행할 최대 단계 수 (기본 2 — 쿼터 절약)")
    parser.add_argument("--keep-users", action="store_true",
                        help="테스트 계정을 지우지 않는다(디버깅용)")
    args = parser.parse_args()

    load_env()
    supabase_url = (os.environ.get("SUPABASE_URL") or "").rstrip("/")
    service_key = os.environ.get("SUPABASE_SERVICE_KEY") or ""
    dart_key = os.environ.get("DART_API_KEY") or ""
    if not supabase_url or not service_key:
        print(f"{FAIL}SUPABASE_URL·SUPABASE_SERVICE_KEY가 필요합니다")
        return 1
    if not dart_key:
        print(f"{FAIL}DART_API_KEY가 필요합니다")
        return 1

    session = requests.Session()
    alice = TestUser(session, supabase_url, service_key, "alice")
    bob = TestUser(session, supabase_url, service_key, "bob")
    created_job = ""
    # [5]에서 채워진다. [6]의 section·disclosure 검증이 재사용한다
    # (새 작업을 또 만들지 않고 이미 만든 작업의 완료 섹션을 그대로 쓴다).
    final_keys: list[str] = []

    try:
        print(f"대상: {args.base}")
        print(f"{INFO}임시 계정 2개 생성 중…")
        alice.create(); alice.sign_in()
        bob.create(); bob.sign_in()
        check("테스트 계정 생성·로그인", bool(alice.access_token and bob.access_token))

        print("\n[1] 인증된 작업 생성")
        code, body = api(session, args.base, "POST", "/api/se/analyze",
                         alice.access_token, dart_key,
                         {"company": args.company, "lookback_years": 1})
        ok = check("작업 생성 (201)", code == 201, f"HTTP {code} {str(body)[:90]}")
        if not ok:
            return 1
        job_id = created_job = body["job_id"]
        print(f"{INFO}job_id={job_id} · 항목 {body.get('total')}개 · {body.get('company')}")

        print("\n[2] 소유자 조회")
        code, body = api(session, args.base, "GET", f"/api/se/analyze/{job_id}",
                         alice.access_token)
        check("소유자는 조회 가능 (200)", code == 200, f"HTTP {code}")
        check("진행 상태가 담김", "finished" in body and "total" in body,
              f"{body.get('finished')}/{body.get('total')}")

        print("\n[3] 교차 사용자 격리 (배포 환경에서 실제로 걸리는가)")
        code, _ = api(session, args.base, "GET", f"/api/se/analyze/{job_id}",
                      bob.access_token)
        check("타인 조회는 404", code == 404, f"HTTP {code}")
        code, _ = api(session, args.base, "POST",
                      f"/api/se/analyze/{job_id}/step", bob.access_token, dart_key)
        check("타인 진행도 404", code == 404, f"HTTP {code}")

        print(f"\n[4] 단계 실행 (최대 {args.steps}회 — maxDuration이 여기서 드러난다)")
        for n in range(1, args.steps + 1):
            started = time.monotonic()
            code, body = api(session, args.base, "POST",
                             f"/api/se/analyze/{job_id}/step",
                             alice.access_token, dart_key)
            elapsed = time.monotonic() - started
            if code != 200:
                check(f"{n}단계", False, f"HTTP {code} {str(body)[:110]}")
                break
            print(f"{INFO}{n}단계: {elapsed:5.1f}초 · {body.get('processed')}건 처리 "
                  f"· {body.get('finished')}/{body.get('total')} "
                  f"· done={body.get('done')} stalled={body.get('stalled')}")
            check(f"{n}단계 응답 정상", True)
            if body.get("stalled"):
                check("정체 없음", False,
                      "예산이 부족합니다 — maxDuration/budget 조정 필요")
                break
            if body.get("done"):
                break

        print("\n[5] 최종 상태")
        code, body = api(session, args.base, "GET", f"/api/se/analyze/{job_id}",
                         alice.access_token)
        if code == 200:
            keys = body.get("section_keys") or []
            final_keys = keys
            failed = body.get("failed") or []
            print(f"{INFO}{body.get('finished')}/{body.get('total')} 완료 "
                  f"· 섹션 {len(keys)}개 · 실패 {len(failed)}건")
            for item in failed[:5]:
                print(f"         실패: {item.get('key')} — {str(item.get('error'))[:70]}")
            check("최종 조회 정상", True)
            # 이번 계획(SE-4a)의 목적 그 자체 — 진행률 응답이 섹션 본문을
            # 더는 담지 않으므로, 실측 크기가 이전 737KB에서 수 KB로
            # 줄었는지 여기서 눈으로 확인한다.
            resp_size = len(str(body))
            check("진행률 응답이 경량", resp_size < 20000, f"{resp_size:,}자")
            if keys:
                c2, b2 = api(session, args.base, "GET",
                             f"/api/se/analyze/{job_id}/section/{keys[0]}",
                             alice.access_token)
                check("섹션 개별 조회", c2 == 200 and b2.get("key") == keys[0],
                      f"HTTP {c2}")
        else:
            check("최종 조회 정상", False, f"HTTP {code}")

        print("\n[6] 신규 엔드포인트")

        print(f"{INFO}config — 인증 없이 열리는 유일한 경로")
        cfg_resp = session.get(f"{args.base}/api/se/config", timeout=20)
        cfg_ok = check("config: 인증 없이 200", cfg_resp.status_code == 200,
                       f"HTTP {cfg_resp.status_code}")
        try:
            cfg_body = cfg_resp.json() if cfg_ok else {}
        except ValueError:
            cfg_body = {}
        if cfg_ok:
            check("config: supabase_url 포함", bool(cfg_body.get("supabase_url")))
        # 값 자체를 응답 원문에서 찾는다 — 필드명이 아니라 실제 service key가
        # 새어나갔는지를 직접 검증한다(응답 스키마가 바뀌어도 이 검증은 유효하다).
        check("config: service key 비노출", service_key not in cfg_resp.text)

        if final_keys:
            key0 = final_keys[0]
            print(f"{INFO}section — 소유자·타인 격리")
            c3, b3 = api(session, args.base, "GET",
                        f"/api/se/analyze/{job_id}/section/{key0}",
                        alice.access_token)
            check("section: 소유자 200", c3 == 200 and b3.get("key") == key0,
                  f"HTTP {c3}")
            c3, _ = api(session, args.base, "GET",
                       f"/api/se/analyze/{job_id}/section/{key0}",
                       bob.access_token)
            check("section: 타인 404", c3 == 404, f"HTTP {c3}")
        else:
            print(f"{INFO}완료된 섹션이 없어 section 격리 검증을 건너뜁니다"
                  " (--steps를 늘려주세요)")

        doc_rcept_no = ""
        for k in final_keys:
            if k.startswith("doc:"):
                doc_rcept_no = k.split(":", 1)[1]
                break
        print(f"{INFO}disclosure — 인증·실제 공시 원문")
        c4, _ = api(session, args.base, "GET",
                   f"/api/se/disclosure/{doc_rcept_no or '00000000000000'}",
                   "", dart_key)
        check("disclosure: 인증 없이는 401", c4 == 401, f"HTTP {c4}")
        if doc_rcept_no:
            c4, b4 = api(session, args.base, "GET",
                        f"/api/se/disclosure/{doc_rcept_no}",
                        alice.access_token, dart_key)
            check("disclosure: 실제 공시 200", c4 == 200 and bool(b4.get("text")),
                  f"HTTP {c4} · 본문 {len(str(b4.get('text', ''))):,}자")
        else:
            print(f"{INFO}완료된 공시 원문 섹션이 없어 disclosure 실조회를"
                  " 건너뜁니다 (--steps를 늘려주세요)")

        print(f"{INFO}actors — 인증·면책 동반")
        c5, _ = api(session, args.base, "GET",
                   f"/api/se/actors?company={args.company}", "")
        check("actors: 인증 없이는 401", c5 == 401, f"HTTP {c5}")
        c5, b5 = api(session, args.base, "GET",
                    f"/api/se/actors?company={args.company}", alice.access_token)
        check("actors: 인증되면 200", c5 == 200, f"HTTP {c5}")
        check("actors: 면책 문구 동반", bool(b5.get("disclaimer")))

        return 1 if _failures else 0

    finally:
        # 검증이 만든 작업 레코드도 치운다. 남겨두면 소유자가 삭제된
        # 고아 레코드가 쌓인다.
        if created_job and not args.keep_users:
            try:
                r = session.delete(
                    f"{supabase_url}/rest/v1/se_jobs",
                    headers=auth_headers(service_key),
                    params={"job_id": f"eq.{created_job}"}, timeout=20)
                print(f"{PASS if r.status_code < 300 else FAIL}작업 레코드 삭제")
            except Exception:
                print(f"{FAIL}작업 레코드 삭제")

        if args.keep_users:
            print(f"\n{INFO}--keep-users 지정 — 계정을 남깁니다")
        else:
            print(f"\n{INFO}테스트 계정 정리 중…")
            ok_a, ok_b = alice.delete(), bob.delete()
            print(f"{PASS if ok_a and ok_b else FAIL}테스트 계정 삭제")
        if _failures:
            print(f"\n실패 {len(_failures)}건:")
            for name in _failures:
                print(f"  - {name}")
        else:
            print("\n전부 통과했습니다.")


if __name__ == "__main__":
    raise SystemExit(main())
