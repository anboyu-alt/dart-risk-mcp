"""SE Supabase 백엔드 라이브 검증 — 인메모리로만 확인했던 것들을 실제로 닫는다.

지금까지 SE-1·SE-2·SE-3의 실측은 전부 `MemoryCache`/`MemoryJobStore`로만
했다. 다음 세 가지가 미검증으로 남아 있다:

1. `SupabaseCache`가 실제 Storage/PostgREST에서 동작하는가
2. `SupabaseJobStore`의 **소유권 격리**가 실제 DB 쿼리로 걸리는가
3. **프로세스 간 영속 캐시** — 지금까지 잰 16.9배는 같은 프로세스 안이라
   Vercel 실제 시나리오(요청마다 새 프로세스)를 검증하지 못했다

3번이 핵심이다. 이 스크립트는 콜드·웜을 **별도 프로세스**로 돌려 캐시가
프로세스 경계를 넘는지 확인한다.

사용:
    python scripts/se_verify_live.py                 # 전체
    python scripts/se_verify_live.py --skip-dart     # DART 호출 없는 부분만
    python scripts/se_verify_live.py --company 셀트리온 --years 1

자격증명은 환경변수 또는 .env.local에서 읽는다. DART 실측에는
DART_API_KEY(또는 tmp/_apikey.txt)도 필요하다.

**어떤 키도 출력하지 않는다.**
"""
import argparse
import os
import pathlib
import subprocess
import sys
import time
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts._console import use_utf8_stdout  # noqa: E402

from se_server.cache import SupabaseCache  # noqa: E402
from se_server.config import SEConfig  # noqa: E402
from se_server.jobs import runner  # noqa: E402
from se_server.jobs.supabase_store import SupabaseJobStore  # noqa: E402

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_ENV_FILE = _ROOT / ".env.local"

PASS = "  [PASS]  "
FAIL = "  [FAIL]  "
SKIP = "  [SKIP]  "

_failures: list[str] = []


def load_env_file() -> None:
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


def check(label: str, ok: bool, detail: str = "") -> bool:
    print(f"{PASS if ok else FAIL}{label}{('  — ' + detail) if detail else ''}")
    if not ok:
        _failures.append(label)
    return ok


# ── 1. 캐시 ────────────────────────────────────────────
def verify_cache(config: SEConfig) -> None:
    print("\n[1] SupabaseCache")
    cache = SupabaseCache(config)
    tag = uuid.uuid4().hex[:12]

    blob_key = f"verify/{tag}.zip"
    payload = b"PK\x03\x04" + tag.encode()
    cache.put_blob(blob_key, payload)
    check("blob 저장·조회 왕복", cache.get_blob(blob_key) == payload)
    check("없는 blob은 None", cache.get_blob(f"verify/없음-{tag}") is None)

    json_key = f"verify/json/{tag}"
    cache.put_json(json_key, {"status": "000", "tag": tag}, ttl_seconds=300)
    got = cache.get_json(json_key)
    check("json 저장·조회 왕복", got is not None and got.get("tag") == tag)

    expired_key = f"verify/json/expired-{tag}"
    cache.put_json(expired_key, {"tag": tag}, ttl_seconds=-10)
    check("만료된 json은 None", cache.get_json(expired_key) is None)

    check("없는 json은 None", cache.get_json(f"verify/json/없음-{tag}") is None)


# ── 2. 작업 저장소 + 소유권 ────────────────────────────
def verify_job_store(config: SEConfig) -> None:
    print("\n[2] SupabaseJobStore + 소유권 격리")
    store = SupabaseJobStore(config)
    tag = uuid.uuid4().hex[:8]
    owner, intruder = f"owner-{tag}", f"intruder-{tag}"

    job = runner.create_job(f"검증회사-{tag}", "00000000", 1, store, user_id=owner)
    check("작업 생성·저장", store.load(job.job_id) is not None)
    check("소유자는 조회 가능", store.load(job.job_id, user_id=owner) is not None)
    check("타인은 조회 불가 (실제 DB 쿼리 필터)",
          store.load(job.job_id, user_id=intruder) is None)

    loaded = store.load(job.job_id, user_id=owner)
    loaded.status = "done"
    store.save(loaded)
    again = store.load(job.job_id, user_id=owner)
    check("갱신 후 재조회", again is not None and again.status == "done")
    check("갱신 후에도 소유자 보존", again is not None and again.user_id == owner)

    try:
        runner.run_step(job.job_id, "DUMMY", store, budget_seconds=30.0,
                        user_id=intruder)
        check("타인은 run_step 불가", False, "예외가 나지 않음")
    except ValueError:
        check("타인은 run_step 불가", True)


# ── 3. 프로세스 간 영속 캐시 ───────────────────────────
_CHILD = r'''
import os, sys, time
sys.path.insert(0, r"{root}")
from se_server.cache import SupabaseCache
from se_server.config import SEConfig
from se_server.http_cache import install
from dart_risk_mcp.core.dart_client import (
    resolve_corp, fetch_company_disclosures, fetch_disclosure_full)
from dart_risk_mcp.core.signals import match_signals

install(SupabaseCache(SEConfig.from_env()))
key = os.environ["DART_API_KEY"]
started = time.monotonic()
resolved = resolve_corp({company!r}, key)
if not resolved:
    print("RESULT unresolved 0 0"); raise SystemExit(1)
_, info = resolved
items = fetch_company_disclosures(info["corp_code"], key,
                                  lookback_days={days}, max_pages={pages})
# 원문까지 연다. 캐시 이득의 대부분이 여기 있고, 목록만 재면 "8~15분 →
# 30초~1분" 주장을 검증하지 못한다. 상한을 두어 검증이 무한정 길어지지
# 않게 한다.
targets = [i["rcept_no"] for i in items if match_signals(i.get("report_nm", ""))]
targets = targets[:{docs}]
for rcept_no in targets:
    fetch_disclosure_full(rcept_no, key)
print(f"RESULT ok {{time.monotonic() - started:.1f}} {{len(items)}} {{len(targets)}}")
'''


def _run_child(company: str, years: int, max_docs: int) -> tuple[float, int, int] | None:
    code = _CHILD.format(root=str(_ROOT), company=company,
                         days=years * 365, pages=years * 10, docs=max_docs)
    proc = subprocess.run([sys.executable, "-c", code], capture_output=True,
                          text=True, encoding="utf-8", errors="replace",
                          env=os.environ.copy(), cwd=str(_ROOT))
    for line in (proc.stdout or "").splitlines():
        if line.startswith("RESULT ok "):
            _, _, secs, total, matched = line.split()
            return float(secs), int(total), int(matched)
    print(f"    (자식 프로세스 실패) {(proc.stderr or '').strip()[-300:]}")
    return None


def verify_cross_process(company: str, years: int, max_docs: int) -> None:
    print("\n[3] 프로세스 간 영속 캐시 (Vercel 실제 시나리오)")
    if not os.environ.get("DART_API_KEY"):
        print(f"{SKIP}DART_API_KEY가 없어 건너뜁니다")
        return

    print("    콜드 실행 (새 프로세스)…")
    cold = _run_child(company, years, max_docs)
    if cold is None:
        check("콜드 실행", False)
        return

    print("    웜 실행 (별도의 새 프로세스)…")
    warm = _run_child(company, years, max_docs)
    if warm is None:
        check("웜 실행", False)
        return

    cold_s, total, matched = cold
    warm_s, _, _ = warm
    print(f"    콜드 {cold_s:.1f}초 → 웜 {warm_s:.1f}초 "
          f"(공시 {total}건, 원문 {matched}건 열람)")

    ok = warm_s < cold_s
    check("캐시가 프로세스 경계를 넘음", ok,
          f"{cold_s / warm_s:.1f}배 단축" if ok and warm_s > 0
          else "웜이 더 빠르지 않음 — 캐시가 안 걸렸을 수 있습니다")


def main() -> int:
    use_utf8_stdout()
    parser = argparse.ArgumentParser(description="SE Supabase 라이브 검증")
    parser.add_argument("--company", default="셀트리온")
    parser.add_argument("--years", type=int, default=1)
    parser.add_argument("--max-docs", type=int, default=15,
                        help="원문을 여는 최대 건수 (기본 15)")
    parser.add_argument("--skip-dart", action="store_true",
                        help="DART 호출이 필요한 검증을 건너뛴다")
    args = parser.parse_args()

    load_env_file()
    if not os.environ.get("DART_API_KEY"):
        path = _ROOT / "tmp" / "_apikey.txt"
        if path.exists():
            os.environ["DART_API_KEY"] = path.read_text(encoding="utf-8").strip()

    try:
        config = SEConfig.from_env()
    except ValueError as exc:
        print(f"{FAIL}환경 설정: {exc}")
        print("먼저 `python scripts/se_setup.py`로 준비 상태를 확인하세요.")
        return 1

    verify_cache(config)
    verify_job_store(config)
    if args.skip_dart:
        print(f"\n[3] 프로세스 간 영속 캐시\n{SKIP}--skip-dart 지정됨")
    else:
        verify_cross_process(args.company, args.years, args.max_docs)

    print()
    if _failures:
        print(f"실패 {len(_failures)}건:")
        for name in _failures:
            print(f"  - {name}")
        return 1
    print("전부 통과했습니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
