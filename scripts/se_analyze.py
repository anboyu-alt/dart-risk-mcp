"""SE 분석 작업 실행 — 청크 실행과 재개를 실측한다.

사용:
    python scripts/se_analyze.py 셀트리온 --years 1 --budget 20

    # 진행 상태만 확인
    python scripts/se_analyze.py --job-id <ID> --status

API 키는 환경변수 DART_API_KEY 또는 tmp/_apikey.txt에서 읽는다.
키는 호출 인자로만 흐르며 작업 레코드에 저장되지 않는다.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dart_risk_mcp.core.dart_client import resolve_corp  # noqa: E402
from se_server.cache import MemoryCache  # noqa: E402
from se_server.http_cache import install  # noqa: E402
from se_server.jobs import MemoryJobStore  # noqa: E402
from se_server.jobs import runner  # noqa: E402

# 진행이 전혀 없는 단계가 이만큼 연속되면 중단한다(무한 루프 방지).
# stalled=True(남은 항목이 전부 oversized인데 예산 부족)는 이 카운트를 기다리지
# 않고 즉시 중단한다 — 같은 예산으로 반복해도 영원히 나아지지 않기 때문이다.
_MAX_STALLED_STEPS = 3


def _load_api_key() -> str:
    key = os.environ.get("DART_API_KEY", "").strip()
    if key:
        return key
    path = os.path.join(os.path.dirname(__file__), "..", "tmp", "_apikey.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    raise ValueError("DART_API_KEY 환경변수 또는 tmp/_apikey.txt가 필요합니다")


def run_to_completion(company, api_key, lookback_years, store, budget_seconds, now=time.monotonic):
    """작업을 만들고 done이 될 때까지 run_step을 반복한다.

    반환: (job_id, 단계별 StepResult 목록)
    """
    corp_name, info = resolve_corp(company, api_key)
    if not info:
        raise ValueError(f"기업을 찾지 못했습니다: {company}")

    job = runner.create_job(corp_name or company, info["corp_code"], lookback_years, store)
    steps = []
    stalled = 0

    while True:
        result = runner.run_step(
            job.job_id, api_key, store, budget_seconds=budget_seconds, now=now
        )
        steps.append(result)
        if result.done:
            break
        if result.stalled:
            # 남은 항목이 전부 oversized인데 예산이 부족해 아무것도 시작하지
            # 못했다. 같은 예산으로 다시 돌아도 결과가 같으므로 즉시 중단한다.
            raise RuntimeError(
                f"예산 부족으로 정체되었습니다 ({result.finished}/{result.total} 완료). "
                "--budget을 늘려 재실행하세요."
            )
        if result.processed == 0:
            stalled += 1
            if stalled >= _MAX_STALLED_STEPS:
                raise RuntimeError(
                    f"진행이 멈췄습니다 ({result.finished}/{result.total} 완료). "
                    "예산이 너무 작아 어떤 항목도 시작하지 못했을 수 있습니다."
                )
        else:
            stalled = 0

    return job.job_id, steps


def main() -> int:
    # Windows 콘솔 기본 코드페이지(cp949)는 "—" 같은 문자를 인코딩하지 못해
    # UnicodeEncodeError로 죽는다(라이브 실측 중 실제로 재현). PYTHONIOENCODING을
    # 강제하는 대신 여기서 stdout을 utf-8로 재설정해 별도 환경변수 없이도 동작하게 한다.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")

    parser = argparse.ArgumentParser(description="SE 분석 작업 실행")
    parser.add_argument("company", help="기업명 또는 종목코드")
    parser.add_argument("--years", type=int, default=1, help="조회 연수 (기본 1)")
    parser.add_argument("--budget", type=float, default=45.0,
                        help="단계당 시간 예산 초 (기본 45). "
                             "runner.OVERSIZED_RESERVE(20초)보다 커야 한다 — "
                             "이하이면 oversized 항목을 영원히 시작할 수 없어 "
                             "run_step이 즉시 ValueError로 거부한다")
    args = parser.parse_args()

    api_key = _load_api_key()
    install(MemoryCache())
    store = MemoryJobStore()

    started = time.monotonic()
    job_id, steps = run_to_completion(
        args.company, api_key, args.years, store, args.budget
    )
    elapsed = time.monotonic() - started

    job = store.load(job_id)
    failed = [i for i in job.items if i.status == "failed"]

    print(f"작업 {job_id} — {len(steps)}단계 · {elapsed:.1f}초")
    for n, step in enumerate(steps, 1):
        print(f"  {n}단계: {step.processed}건 처리 ({step.finished}/{step.total})")
    if failed:
        print(f"\n실패 {len(failed)}건 (나머지는 정상 수집):")
        for item in failed[:10]:
            print(f"  - {item.key}: {item.error[:80]}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
