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

from dart_risk_mcp.core.dart_client import (  # noqa: E402
    fetch_company_disclosures,
    fetch_disclosure_full,
    resolve_corp,
)
from dart_risk_mcp.core.signals import match_signals  # noqa: E402
from se_server.cache import MemoryCache, SupabaseCache  # noqa: E402
from se_server.config import SEConfig  # noqa: E402
from se_server.http_cache import install  # noqa: E402


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
    corp_name, info = resolve_corp(company, api_key)
    if not info:
        raise ValueError(f"기업을 찾지 못했습니다: {company}")

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
    install(backend)

    cold = run_once(args.company, api_key, args.years)
    print(
        f"콜드: {cold['seconds']:.1f}초 "
        f"(공시 {cold['disclosures']}건 · 원문 {cold['documents']}건)"
    )

    warm = run_once(args.company, api_key, args.years)
    print(f"웜  : {warm['seconds']:.1f}초")

    if warm["seconds"] > 0:
        print(f"단축 배수: {cold['seconds'] / warm['seconds']:.1f}배")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
