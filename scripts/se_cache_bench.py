"""SE 캐시 효과 실측 — 같은 회사를 두 번 조회해 콜드/웜 시간을 비교한다.

사용:
    # 인메모리(같은 프로세스 내 2회차만 확인)
    python scripts/se_cache_bench.py 셀트리온

    # Supabase 백엔드 (SUPABASE_URL·SUPABASE_SERVICE_KEY 필요)
    python scripts/se_cache_bench.py 셀트리온 --backend supabase

API 키는 환경변수 DART_API_KEY 또는 tmp/_apikey.txt에서 읽는다.
"""
import argparse
import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from dart_risk_mcp.core import dart_client  # noqa: E402
from dart_risk_mcp.core.dart_client import (  # noqa: E402
    fetch_company_disclosures,
    fetch_disclosure_full,
    resolve_corp,
)
from dart_risk_mcp.core.signals import match_signals  # noqa: E402
from se_server.cache import MemoryCache, SupabaseCache  # noqa: E402
from se_server.config import SEConfig  # noqa: E402
from se_server.http_cache import CachingHttp, install  # noqa: E402


def reset_core_process_caches() -> None:
    """core의 프로세스 내 캐시를 비운다.

    콜드/웜을 같은 프로세스에서 재면 SE 캐시와 무관한 두 캐시가 웜 실행을
    앞당겨 측정을 과대평가한다:

    - `_corp_cache`: 한 번 채워지면 `resolve_corp`가 재조회를 아예 건너뛴다.
      게다가 corpCode.xml은 SE 캐시의 `_NEVER_CACHE` 대상이라 이 단축분은
      SE와 전혀 무관하다.
    - `_zip_cache`: `_fetch_document_zip`이 `_retry`(SE 캐시 진입점)를
      호출하기 **전에** 확인하므로, 최근 5건은 SE 캐시에 닿지도 않는다.

    실서비스(Vercel)는 요청마다 새 프로세스라 두 캐시가 존재하지 않는다.
    비워야 측정이 배포 환경에 가까워진다.
    """
    dart_client._corp_cache.clear()
    dart_client._zip_cache.clear()


class CountingHttp:
    """SE 캐시 적중·미스를 세어 단축분의 귀속을 명시한다.

    "몇 배 빨라졌다"만으로는 그 단축이 SE 캐시 덕분인지 알 수 없다.
    적중 수가 0인데 빨라졌다면 그 측정은 SE 캐시 효과가 아니다.
    """

    def __init__(self, inner: CachingHttp) -> None:
        self.inner = inner
        self.hits = 0
        self.misses = 0

    def get(self, url: str, params: dict):
        result = self.inner.get(url, params)
        if result is None:
            self.misses += 1
        else:
            self.hits += 1
        return result

    def put(self, url: str, params: dict, status: int, headers: dict, body: bytes) -> None:
        self.inner.put(url, params, status, headers, body)

    def reset_counts(self) -> None:
        self.hits = 0
        self.misses = 0


def _load_api_key() -> str:
    key = os.environ.get("DART_API_KEY", "").strip()
    if key:
        return key
    path = os.path.join(os.path.dirname(__file__), "..", "tmp", "_apikey.txt")
    if os.path.exists(path):
        with open(path, encoding="utf-8") as f:
            return f.read().strip()
    raise ValueError("DART_API_KEY 환경변수 또는 tmp/_apikey.txt가 필요합니다")


def run_once(company: str, api_key: str, lookback_years: int) -> dict:
    """회사 하나를 스펙 §6.1의 1·2단 범위로 조회하고 소요 시간을 잰다."""
    started = time.monotonic()
    # resolve_corp는 실패 시 None을 반환한다. 곧바로 언패킹하면 TypeError가 나서
    # 아래의 친절한 오류 메시지에 도달하지 못한다.
    resolved = resolve_corp(company, api_key)
    if not resolved:
        raise ValueError(f"기업을 찾지 못했습니다: {company}")
    corp_name, info = resolved

    items = fetch_company_disclosures(
        info["corp_code"], api_key, lookback_days=365 * lookback_years
    )
    documents = 0
    for item in items:
        if not match_signals(item.get("report_nm", "")):
            continue
        fetch_disclosure_full(item["rcept_no"], api_key)
        documents += 1

    return {
        "seconds": time.monotonic() - started,
        "disclosures": len(items),
        "documents": documents,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="SE 캐시 효과 실측")
    parser.add_argument("company", help="기업명 또는 종목코드")
    parser.add_argument("--years", type=int, default=1, help="조회 연수 (기본 1)")
    parser.add_argument(
        "--backend", choices=["memory", "supabase"], default="memory",
        help="캐시 백엔드 (기본 memory)",
    )
    args = parser.parse_args()

    api_key = _load_api_key()
    backend = (
        SupabaseCache(SEConfig.from_env())
        if args.backend == "supabase"
        else MemoryCache()
    )
    counter = CountingHttp(install(backend))
    dart_client.set_http_cache(counter)

    # core의 프로세스 내 캐시를 비워야 SE 캐시 효과만 남는다.
    reset_core_process_caches()
    cold = run_once(args.company, api_key, args.years)
    cold_hits, cold_misses = counter.hits, counter.misses
    print(
        f"콜드: {cold['seconds']:.1f}초 "
        f"(공시 {cold['disclosures']}건 · 원문 {cold['documents']}건 · "
        f"SE 캐시 적중 {cold_hits}/{cold_hits + cold_misses})"
    )

    reset_core_process_caches()
    counter.reset_counts()
    warm = run_once(args.company, api_key, args.years)
    warm_hits, warm_misses = counter.hits, counter.misses
    print(
        f"웜  : {warm['seconds']:.1f}초 "
        f"(SE 캐시 적중 {warm_hits}/{warm_hits + warm_misses})"
    )

    if warm["seconds"] > 0:
        print(f"단축 배수: {cold['seconds'] / warm['seconds']:.1f}배")

    # 적중 수가 0이면 단축은 SE 캐시 때문이 아니다 — 수치를 그대로 믿으면 안 된다.
    if warm_hits == 0:
        print("⚠ 웜 실행의 SE 캐시 적중이 0건입니다 — 단축분은 SE 캐시 효과가 아닙니다.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
