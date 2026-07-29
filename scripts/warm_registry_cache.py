"""cron이 Notion 레지스트리를 Supabase 캐시에 미리 채운다 (SE-5c Task 3).

배경: `dart_risk_mcp/core/known_actors.py`의 캐시 시임(`set_registry_cache`)은
24시간 TTL로 콜드 Notion 조회(15회 POST·약 15초)를 건너뛴다. 하지만 TTL이
만료된 직후 첫 요청은 여전히 그 15초를 문다 — Vercel 함수 제한 아래라면
그 요청은 느린 게 아니라 죽는다(`docs/superpowers/plans/2026-07-29-se-5c-registry-cache.md`
참고).

레지스트리는 이미 매일 cron(`.github/workflows/refresh-known-actors.yml` →
`scripts/refresh_known_actors.py`)으로 재구성된다. 그 작업 직후 이 스크립트가
Supabase 캐시(`se_server.cache.SupabaseCache`)를 같은 데이터로 채우면, TTL
만료 시각에 아무 사용자도 걸리지 않는다 — cron이 만료 전에 매일 새로 채우기
때문이다.

⚠️ 이 저장소는 public이고 워크플로 로그도 public이다. 레지스트리는 실명
데이터다 — 이 스크립트는 **인물 수·바이트 수·소요 시간만** 표준출력에
찍고, 어떤 인물명·회사명도 출력하지 않는다(`scripts/build_network_html.py`가
출력 HTML을 커밋 금지하는 것과 같은 이유 — 노출 경계는 CLAUDE.md 참고).

Supabase Secrets(SUPABASE_URL/SUPABASE_SERVICE_KEY) 미설정 시 조용히
건너뛴다(그 사실은 로그에 남긴다) — 이 스크립트로 Secrets를 설정할 수는
없고, 제작자가 GitHub에서 넣어야 한다. 레지스트리 갱신
(`refresh_known_actors.py`) 자체는 이 스크립트 이전에 이미 끝나 있으므로,
이 스크립트가 무엇을 하다 실패해도 워크플로 전체를 실패시키지 않는다 —
항상 exit 0이고, 성공/실패/스킵은 로그 접두사([OK]/[FAIL]/[WARN]/[SKIP])로
구분한다.

사용:
    python scripts/warm_registry_cache.py

자격증명은 환경변수 또는 `.env.local`에서 런타임에 읽는다(파일에 키를
박지 않는다 — 이 저장소에서 실제로 있었던 사고다). 필요:
NOTION_TOKEN, DB_KNOWN_ACTORS, SUPABASE_URL, SUPABASE_SERVICE_KEY.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import subprocess
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from scripts._console import use_utf8_stdout  # noqa: E402

_ROOT = pathlib.Path(__file__).resolve().parent.parent
_ENV_FILE = _ROOT / ".env.local"


def load_env_file() -> None:
    """`.env.local`이 있으면 런타임에 읽어 os.environ을 채운다(기존 값은 안 덮음).

    로컬 실행 전용 — GitHub Actions에는 이 파일이 없으므로 no-op이고,
    거기서는 워크플로가 시크릿을 환경변수로 직접 주입한다.
    `scripts/se_verify_live.py::load_env_file`과 동일한 패턴.
    """
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


# 별도 프로세스에서 캐시를 읽어 인물 "수"만 출력하는 자식 코드. in-process
# 변수로 "쓴 줄 알았던" 값을 확인하면 실제 왕복이 아니라 로컬 변수를 보는
# 것이라 stale write를 놓칠 수 있다(배포된 실물을 검증하라는 이 프로젝트의
# 교훈, `scripts/se_verify_live.py`의 프로세스 간 검증과 같은 이유) — 그래서
# 반드시 새 파이썬 프로세스를 띄워 Supabase를 다시 왕복한다.
_READBACK_CHILD = """
import sys
sys.path.insert(0, {root!r})
try:
    from se_server.cache import SupabaseCache
    from se_server.config import SEConfig
    from dart_risk_mcp.core.known_actors import _REGISTRY_CACHE_KEY

    cache = SupabaseCache(SEConfig.from_env())
    data = cache.get_json(_REGISTRY_CACHE_KEY)
except Exception as exc:
    # 예외 '유형 이름'만 내보낸다 — 메시지에는 URL·키·인물명이 섞일 수 있다.
    print("READBACK_ERR " + type(exc).__name__)
else:
    if isinstance(data, dict) and isinstance(data.get("actors"), dict):
        print(f"READBACK_OK {{len(data['actors'])}}")
    elif data is None:
        # 캐시에 행이 없거나(미기록) 읽기가 거부됐다(자격증명·RLS). 둘 다
        # get_json이 예외를 삼키고 None을 주므로 여기서는 구분되지 않는다 —
        # 그래도 "형태가 이상함"과는 갈라 놔야 다음 조사가 가능하다.
        print("READBACK_NONE")
    else:
        # 행은 있는데 모양이 다르다. 타입 이름만 낸다(값에는 실명이 있다).
        print("READBACK_SHAPE " + type(data).__name__)
"""

# 자식이 보고한 예외 유형 이름으로 인정할 형태. 파이썬 식별자만 통과시킨다 —
# 공백·따옴표·한글·경로가 섞인 문자열은 전부 버린다.
_ERR_TYPE_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]{0,63}$")


def _readback_in_child_process() -> tuple[bool, int, str]:
    """별도 프로세스에서 캐시를 읽어 (성공 여부, 인물 수, 실패 사유)를 반환한다.

    ⚠️ **자식의 출력 원문은 절대 그대로 통과시키지 않는다.** 이 저장소는
    public이고 Actions 로그도 public인데, 자식이 다루는 데이터는 실명
    레지스트리다. 예외 메시지·stderr에는 Supabase URL, 응답 본문 조각,
    인물명이 섞일 수 있다 — 길이를 자르는 것으로는 그 채널을 닫을 수 없다
    (SE-5c 최종 리뷰 Finding 3). 그래서 반환하는 사유는 **길이가 아니라
    형태로 제한된 값**만으로 조립한다: 파이썬 식별자 형태의 예외 유형
    이름, 정수 종료코드, 또는 "stderr가 있었다"는 사실 자체뿐이다.
    """
    code = _READBACK_CHILD.format(root=str(_ROOT))
    proc = subprocess.run(
        [sys.executable, "-c", code], capture_output=True, text=True,
        encoding="utf-8", errors="replace", env=os.environ.copy(), cwd=str(_ROOT))
    err_type = ""
    marker = ""
    for line in (proc.stdout or "").splitlines():
        if line.startswith("READBACK_OK "):
            try:
                return True, int(line.split()[-1]), ""
            except ValueError:
                continue
        if line.startswith("READBACK_ERR "):
            token = line[len("READBACK_ERR "):].strip()
            if _ERR_TYPE_RE.match(token):
                err_type = token
        elif line.startswith("READBACK_NONE"):
            marker = "none"
        elif line.startswith("READBACK_SHAPE "):
            token = line[len("READBACK_SHAPE "):].strip()
            marker = f"shape:{token}" if _ERR_TYPE_RE.match(token) else "shape"

    if err_type:
        reason = f"자식 예외 유형 {err_type}"
    elif marker == "none":
        # 2026-07-29 첫 프로덕션 실행이 사유 없는 [FAIL]을 냈다. 쓰기는 실제로
        # 성공했고(별도 확인: 행 존재, 인물 1273명) 읽기만 실패했는데, 그때
        # 자식은 "형태가 아님"과 "아예 없음"을 구분하지 않아 조사가 막혔다.
        # get_json은 자격증명·RLS 거부도 예외를 삼키고 None을 주므로 이 둘은
        # 여기서 갈리지 않는다 — 그 사실까지 문구에 적어 다음 사람이 헛다리를
        # 짚지 않게 한다.
        reason = ("캐시에서 행을 받지 못함(get_json→None) — 미기록·자격증명·"
                  "RLS 중 어느 것인지는 이 신호만으로 갈리지 않음")
    elif marker.startswith("shape"):
        reason = f"행은 있으나 형태가 예상과 다름({marker.split(':', 1)[-1]})"
    elif proc.returncode:
        reason = f"자식 종료코드 {int(proc.returncode)}"
    elif (proc.stderr or "").strip():
        reason = "자식 stderr 있음(내용은 출력하지 않음)"
    else:
        reason = "자식이 아무 표식도 내지 않음"
    return False, 0, reason


def main() -> int:
    use_utf8_stdout()
    load_env_file()

    if not (os.environ.get("SUPABASE_URL") and os.environ.get("SUPABASE_SERVICE_KEY")):
        print("[SKIP] SUPABASE_URL/SUPABASE_SERVICE_KEY 미설정 — 캐시 예열 "
              "건너뜀 (레지스트리 갱신 자체는 이미 끝났습니다)")
        return 0

    if not (os.environ.get("NOTION_TOKEN") and os.environ.get("DB_KNOWN_ACTORS")):
        print("[SKIP] NOTION_TOKEN/DB_KNOWN_ACTORS 미설정 — 캐시 예열 건너뜀")
        return 0

    # 지연 import — Supabase/Notion 미설정 환경(대부분의 로컬 실행)에서
    # se_server를 끌어오지 않게 한다.
    from dart_risk_mcp.core.known_actors import (
        fetch_registry_from_notion, _CACHE_TTL, _REGISTRY_CACHE_KEY)
    from se_server.cache import SupabaseCache
    from se_server.config import SEConfig

    try:
        started = time.monotonic()
        data = fetch_registry_from_notion()
        fetch_s = time.monotonic() - started
    except Exception as exc:
        # fetch_registry_from_notion은 실패 시 예외 없이 None을 반환하도록
        # 설계돼 있다(프로젝트 규칙 — API 실패는 빈 값, 예외 비전파). 이
        # except는 그 계약이 깨진 경우에 대비한 방어선일 뿐이다.
        print(f"[FAIL] Notion 레지스트리 조회 중 예외 ({type(exc).__name__}) — 캐시 예열 스킵")
        return 0

    if not isinstance(data, dict) or not isinstance(data.get("actors"), dict):
        print(f"[FAIL] Notion 레지스트리 조회 실패 ({fetch_s:.1f}초) — 캐시 예열 스킵")
        return 0

    # 필터(should_store) 적용 전 원본을 그대로 캐시한다 — core의 파일 캐시·
    # 주입 캐시가 이미 pre-filter로 저장하는 것과 동일한 결정
    # (Task 1 보고서 "Filter-timing decision" 참고). 필터는 load_known_actors가
    # 매 호출 때 다시 적용하므로 여기서 미리 적용해 캐시할 이유가 없다.
    n_actors = len(data["actors"])
    n_bytes = len(json.dumps(data, ensure_ascii=False).encode("utf-8"))

    try:
        cache = SupabaseCache(SEConfig.from_env())
    except Exception as exc:
        print(f"[FAIL] SupabaseCache 초기화 실패 ({type(exc).__name__}) — "
              f"인물 {n_actors}명, {n_bytes}바이트 (조회 {fetch_s:.1f}초, 쓰기 못함)")
        return 0

    put_started = time.monotonic()
    try:
        cache.put_json(_REGISTRY_CACHE_KEY, data, _CACHE_TTL)
    except Exception as exc:
        # SupabaseCache.put_json 자체가 예외를 삼키는 계약이지만(캐시 쓰기
        # 실패가 갱신 실패로 번지면 안 된다는 원칙), 방어적으로 한 번 더 잡는다.
        print(f"[FAIL] Supabase 캐시 쓰기 중 예외 ({type(exc).__name__}) — "
              f"인물 {n_actors}명, {n_bytes}바이트")
        return 0
    put_s = time.monotonic() - put_started

    verify_started = time.monotonic()
    ok, readback_n, reason = _readback_in_child_process()
    verify_s = time.monotonic() - verify_started

    if not ok:
        print(f"[FAIL] 캐시 읽기 검증 실패 — 인물 {n_actors}명·{n_bytes}바이트를 썼지만 "
              f"별도 프로세스에서 확인되지 않음 (조회 {fetch_s:.1f}초, 쓰기 {put_s:.1f}초, "
              f"검증 {verify_s:.1f}초)" + (f" — {reason}" if reason else ""))
        return 0

    if readback_n != n_actors:
        print(f"[WARN] 캐시 읽기 검증 인물 수 불일치 — 쓰기 {n_actors}명, "
              f"읽기 {readback_n}명 (조회 {fetch_s:.1f}초, 쓰기 {put_s:.1f}초, "
              f"검증 {verify_s:.1f}초)")
        return 0

    print(f"[OK] 레지스트리 캐시 예열 완료 — 인물 {n_actors}명, {n_bytes}바이트 "
          f"(조회 {fetch_s:.1f}초 + 쓰기 {put_s:.1f}초 + 별도 프로세스 검증 {verify_s:.1f}초)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
