"""기업 검색 폴백 — 공개 뷰어 /api/corp 몸통.

뷰어(docs/tool/corp-map.json)는 상장(종목코드 보유) 법인만 담고, 자동완성이
빗나가면 사용자는 검색을 시도할 방법 자체가 없었다(검색 버튼 미노출 구조,
실측 사례: 앤로보틱스/구 협진 — 동명 법인 충돌로 corp-map.json에서 누락돼
있던 동안 이름·종목코드 어느 쪽으로도 찾을 수 없었다). 이 엔드포인트는
corpCode.xml 전체(비상장 포함)와 corp-aliases.json(옛 상호)에서 후보를
찾아 뷰어의 수동 폴백 검색에 쓰인다.

core의 `_load_corp_codes`/`_corp_cache`를 그대로 재사용한다 — 동명 법인
충돌 정책(상장 우선)이 이미 거기 있으므로 여기서 다시 구현하지 않는다.

HTTP 껍데기(api/corp.py)와 분리된 순수 함수라 단위 테스트가 가능하다.
"""
import re

from dart_risk_mcp.core import dart_client as dc

MIN_QUERY_LEN = 2
MAX_RESULTS = 8
_STOCK_CODE_RE = re.compile(r"^\d{6}$")

_DART_FETCH_FAILED_MSG = (
    "DART 기업 목록을 받지 못했습니다. 잠시 후 다시 시도하세요."
)


def _candidate(name: str, info: dict, alias_of: str | None = None) -> dict:
    return {
        "name": name,
        "corp_code": info.get("corp_code", ""),
        "stock_code": info.get("stock_code", ""),
        "listed": bool(info.get("stock_code")),
        "alias_of": alias_of,
    }


def search_corp_candidates(query: str, corp_cache: dict, aliases: dict) -> list[dict]:
    """순수 함수 — 정확 일치(이름/종목코드) > 별칭 정확 일치(현재명 해석) > 부분 일치(짧은 이름순).

    같은 corp_code가 여러 경로(예: 정확 일치와 별칭 해석)로 걸리면 먼저
    나온 쪽만 남긴다(중복 제거). 최대 MAX_RESULTS건.
    """
    q = (query or "").strip()
    if not q:
        return []

    seen_codes: set[str] = set()
    out: list[dict] = []

    def _add(cand: dict) -> None:
        code = cand.get("corp_code", "")
        key = code or f"__noname__:{cand['name']}"
        if key in seen_codes:
            return
        seen_codes.add(key)
        out.append(cand)

    # 1) 정확 일치 (상장·비상장 모두 corp_cache에 있다 — core 동명 충돌
    #    정책으로 이름당 1건만 남아 있음)
    if q in corp_cache:
        _add(_candidate(q, corp_cache[q]))

    # 1b) 종목코드 6자리 정확 일치 — 뷰어 로컬 목록(corp-map.json)에서 이름·
    #     종목코드 둘 다 검색 실패했을 때의 폴백이므로 종목코드 검색도
    #     corp-map 대신 corpCode.xml 전체에서 지원해야 한다.
    if _STOCK_CODE_RE.match(q):
        for name, info in corp_cache.items():
            if info.get("stock_code") == q:
                _add(_candidate(name, info))
                break

    # 2) 별칭 정확 일치 — 옛 상호 입력을 현재 상호로 해석해 표기
    if q in aliases:
        alias = aliases[q]
        current = alias.get("current", "")
        info = corp_cache.get(current)
        if info:
            _add(_candidate(current, info, alias_of=q))
        elif alias.get("corp_code"):
            _add({
                "name": current or q,
                "corp_code": alias.get("corp_code", ""),
                "stock_code": alias.get("stock_code", ""),
                "listed": bool(alias.get("stock_code")),
                "alias_of": q,
            })

    # 3) 부분 일치 — 짧은 이름순(더 구체적으로 일치하는 후보를 위로)
    partial = [(name, info) for name, info in corp_cache.items()
               if name != q and q in name]
    partial.sort(key=lambda kv: len(kv[0]))
    for name, info in partial:
        if len(out) >= MAX_RESULTS:
            break
        _add(_candidate(name, info))

    return out[:MAX_RESULTS]


def handle_corp(query: dict, api_key: str) -> tuple[int, dict]:
    """(status, body) 반환. query는 단일 값 dict (예: {"q": "앤로보틱스"}).

    api/doc.py의 관례를 따른다: X-DART-Key 헤더 필수(400), 입력 검증 실패는
    400, DART corpCode.xml을 못 받으면 502.
    """
    if not api_key:
        return 400, {"error": "X-DART-Key 헤더가 필요합니다"}

    q = (query.get("q") or "").strip()
    if len(q) < MIN_QUERY_LEN:
        return 400, {"error": f"q는 최소 {MIN_QUERY_LEN}자 이상이어야 합니다"}

    try:
        if not dc._corp_cache:
            dc._load_corp_codes(api_key)
    except Exception:
        return 502, {"error": _DART_FETCH_FAILED_MSG}

    if not dc._corp_cache:
        return 502, {"error": _DART_FETCH_FAILED_MSG}

    aliases = dc.load_corp_aliases()
    candidates = search_corp_candidates(q, dc._corp_cache, aliases)

    return 200, {"query": q, "candidates": candidates}
