"""공개 뷰어 무료 조회 쿼터 — 세 층이 서로 어긋나지 않는지 잠근다.

릴레이가 운영자 키로 DART를 대신 호출해 주면서 생긴 장치다. 판정이 **세 곳에
흩어져 있다**는 것이 이 파일의 존재 이유다.

    브라우저 (docs/tool/index.html)  개인 5곳, (종목, 창) 단위
    JS 릴레이 (api/[endpoint].js)    전역 상한 + IP별 스캔 상한
    Python 함수 (tool_server/quota.py)  같은 Redis 키로 전역 상한

셋이 같은 저장소를 쓰므로 상수나 키 형식이 갈리면 한쪽만 막히거나 한쪽만 샌다.
CLAUDE.md의 「쌍둥이 패리티」와 같은 부류의 위험이다.
"""
from __future__ import annotations

import json
import os
import pathlib
import re
import shutil
import subprocess
from datetime import datetime, timezone

import pytest

from tool_server import quota

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_RELAY_JS = _ROOT / "api" / "[endpoint].js"
_VIEWER = _ROOT / "docs" / "tool" / "index.html"
_HEALTH_JS = _ROOT / "api" / "health.js"


def _js(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def _js_const(src: str, name: str) -> int:
    m = re.search(rf"const {name} = ([0-9*\s]+);", src)
    assert m, f"{name}을 찾지 못했다"
    return int(eval(m.group(1)))  # noqa: S307 — 정수 리터럴·곱셈만 매칭된다


# ── 상수 일치 ────────────────────────────────────────────────

def test_전역_상한이_두_런타임에서_같다():
    assert _js_const(_js(_RELAY_JS), "DAILY_GLOBAL_CAP") == quota.DAILY_GLOBAL_CAP


def test_IP_상한이_두_런타임에서_같다():
    assert _js_const(_js(_RELAY_JS), "DAILY_IP_SCANS") == quota.DAILY_IP_SCANS


def test_TTL이_두_런타임에서_같다():
    assert _js_const(_js(_RELAY_JS), "QUOTA_TTL") == 48 * 3600


def test_레디스_키_형식이_두_런타임에서_같다():
    """키가 갈리면 두 경로가 **서로 다른 카운터**를 올려 상한이 두 배가 된다."""
    js = _js(_RELAY_JS)
    assert "q:g:${day}" in js
    assert "q:s:${ip}:${day}" in js
    py = (_ROOT / "tool_server" / "quota.py").read_text(encoding="utf-8")
    assert 'f"q:g:{d}"' in py
    assert 'f"q:s:{client_ip}:{d}"' in py


# ── KST 날짜 축 ──────────────────────────────────────────────

@pytest.mark.parametrize("iso,expect", [
    # KST 자정 직후 — UTC로는 아직 전날이다
    ("2026-09-12T15:00:01Z", "20260913"),
    # KST 자정 직전
    ("2026-09-12T14:59:59Z", "20260912"),
    # 해 넘김
    ("2025-12-31T15:00:00Z", "20260101"),
])
def test_KST_기준으로_날짜가_바뀐다(iso, expect):
    """UTC로 세면 화면의 「오늘」과 어긋난다.

    뷰어가 시간축을 KST로 정리하면서 `end_de`가 하루 밀려 그날 오전 공시를
    누락하던 문제를 고친 전례가 있다 — 같은 축이어야 한다.
    """
    t = datetime.fromisoformat(iso.replace("Z", "+00:00")).astimezone(timezone.utc)
    assert quota.kst_day(t) == expect


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_JS와_파이썬의_KST_날짜가_같다():
    """두 런타임이 다른 날짜를 쓰면 자정 언저리에 카운터가 갈린다."""
    src = _js(_RELAY_JS)
    body = src[src.index("function kstDay()"):]
    body = body[:body.index("\n}") + 2]
    probes = ["2026-09-12T15:00:01Z", "2026-09-12T14:59:59Z", "2025-12-31T15:00:00Z"]
    script = body + "\n" + "\n".join(
        f'console.log(((d)=>{{const _o=Date.now;Date.now=()=>Date.parse("{p}");'
        f'const r=kstDay();Date.now=_o;return r;}})());' for p in probes
    )
    out = subprocess.run(["node", "-e", script], capture_output=True, text=True, timeout=20)
    assert out.returncode == 0, out.stderr
    got = out.stdout.split()
    want = [quota.kst_day(datetime.fromisoformat(p.replace("Z", "+00:00"))) for p in probes]
    assert got == want


# ── 저장소가 없거나 실패할 때 ─────────────────────────────────

def test_저장소가_없으면_통과시킨다(monkeypatch):
    """판정할 수 없는 것을 거절로 바꾸지 않는다 — 쿼터는 가용성을 깎는 장치가 아니다."""
    monkeypatch.delenv("UPSTASH_REDIS_REST_URL", raising=False)
    monkeypatch.delenv("UPSTASH_REDIS_REST_TOKEN", raising=False)
    assert not quota.enabled()
    assert quota.check_and_count("1.2.3.4", is_scan_start=True) == quota.ALLOW


def test_저장소_호출이_실패하면_통과시킨다(monkeypatch):
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://example.invalid")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "t")
    monkeypatch.setattr(quota, "_pipeline", lambda cmds: None)
    assert quota.check_and_count("1.2.3.4", is_scan_start=True) == quota.ALLOW


def test_전역_상한을_넘으면_거절한다(monkeypatch):
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://example.invalid")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "t")
    monkeypatch.setattr(quota, "_pipeline",
                        lambda cmds: [{"result": quota.DAILY_GLOBAL_CAP + 1}, {"result": 1}])
    assert quota.check_and_count(None, is_scan_start=False) == quota.DENY_GLOBAL


def test_IP_상한을_넘으면_거절한다(monkeypatch):
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://example.invalid")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "t")
    monkeypatch.setattr(quota, "_pipeline", lambda cmds: [
        {"result": 10}, {"result": 1},
        {"result": quota.DAILY_IP_SCANS + 1}, {"result": 1},
    ])
    assert quota.check_and_count("1.2.3.4", is_scan_start=True) == quota.DENY_IP


def test_스캔_시작이_아니면_IP를_세지_않는다(monkeypatch):
    """2페이지 이후는 같은 스캔의 연속이다 — 세면 한 번 조회가 여러 번이 된다."""
    seen = {}
    monkeypatch.setenv("UPSTASH_REDIS_REST_URL", "https://example.invalid")
    monkeypatch.setenv("UPSTASH_REDIS_REST_TOKEN", "t")

    def fake(cmds):
        seen["cmds"] = cmds
        return [{"result": 1}, {"result": 1}]

    monkeypatch.setattr(quota, "_pipeline", fake)
    quota.check_and_count("1.2.3.4", is_scan_start=False)
    keys = [c[1] for c in seen["cmds"]]
    assert not any(k.startswith("q:s:") for k in keys)


# ── 거절 문구 ────────────────────────────────────────────────

def test_전역과_IP_거절을_다른_문구로_적는다():
    """「남이 다 썼다」와 「내가 다 썼다」는 다른 사실이다.

    섞으면 방문자가 남의 소진을 자기 탓으로 오해한다.
    """
    g = quota.deny_payload(quota.DENY_GLOBAL)
    i = quota.deny_payload(quota.DENY_IP)
    assert g["message"] != i["message"]
    assert g["quota"] == "global" and i["quota"] == "ip"
    for p in (g, i):
        assert "인증키" in p["message"], "다음에 할 일을 안 알려 준다"


# ── 캐시 정책 ────────────────────────────────────────────────

def test_신선도가_필요한_엔드포인트는_캐시하지_않는다():
    """공시는 수시로 접수된다 — 목록과 메자닌 발행결정은 매번 실호출해야 한다."""
    src = _js(_RELAY_JS)
    block = src[src.index("const NO_CACHE_ENDPOINTS"):]
    block = block[:block.index("]);")]
    for ep in ("list.json", "cvbdIsDecsn.json", "bdwtIsDecsn.json", "exbdIsDecsn.json"):
        assert ep in block, f"{ep}이 캐시 제외 목록에 없다"


def test_DART_오류_본문은_캐시하지_않는다():
    """DART는 오류를 **HTTP 200 본문**으로 준다(020 한도 초과·800 점검).

    상태코드만 보면 한도 초과 응답을 6시간 붙들어 풀린 뒤에도 같은 거짓말이
    남는다. 013(자료 없음)은 정상 부재라 캐시한다 — 그것까지 빼면 캐시가
    통째로 무력해진다.
    """
    src = _js(_RELAY_JS)
    body = src[src.index("function cacheable"):]
    body = body[:body.index("\n}")]
    assert '"000"' in body and '"013"' in body
    assert "JSON.parse" in body, "본문 status를 보지 않는다"


# ── 뷰어 게이트 ──────────────────────────────────────────────

def test_게이트가_analyze_안에_있다():
    """모든 진입점이 `analyze()`를 거친다 — 딥링크·최근 스캔·즐겨찾기·폴백
    후보·본문 링크·자동완성. `submitScan()`에만 두면 여섯 경로가 우회한다.
    """
    src = _js(_VIEWER)
    body = src[src.index("async function analyze(name, override)"):]
    body = body[:body.index("\n/* ── 결과 구축")]
    assert "quotaUsed() >= FREE_SCANS" in body
    assert "quotaCounted" in body


def test_실패한_조회는_한도를_깎지_않는다():
    """카운트는 목록을 실제로 받은 **뒤**에 일어나야 한다.

    한도 초과·점검·네트워크 실패로 아무것도 못 받은 조회가 몫을 깎으면,
    사용자는 보지도 못한 것의 값을 치른다.
    """
    src = _js(_VIEWER)
    body = src[src.index("async function analyze(name, override)"):]
    body = body[:body.index("\n/* ── 결과 구축")]
    assert body.index("await fetchDisclosureList") < body.index("quotaAdd("), (
        "목록을 받기 전에 카운트한다"
    )


def test_게이트가_안내를_보이는_화면으로_데려간다():
    """안내는 검색 화면 안에 찍힌다.

    결과 화면에서 본문 링크·최근 스캔으로 들어와 막히면 그 화면이 보이지 않아
    **"눌렀는데 아무 일도 안 일어난다"**가 된다(라이브에서 실제로 그랬다:
    `scr-scan visible: False`인 채 안내만 찍혔다).
    """
    src = _js(_VIEWER)
    body = src[src.index("async function analyze(name, override)"):]
    body = body[:body.index("\n/* ── 결과 구축")]
    gate = body[body.index("if (gated)"):]
    gate = gate[:gate.index("\n  }")]
    assert 'showScreen("scan")' in gate


def test_자기_키를_쓰면_한도가_적용되지_않는다():
    """자기 키를 넣은 사람은 자기 한도를 쓴다 — 우리가 막을 이유가 없다."""
    src = _js(_VIEWER)
    body = src[src.index("async function analyze(name, override)"):]
    body = body[:body.index("\n/* ── 결과 구축")]
    assert "!hasOwnKey()" in body


def test_소진_안내를_두_번_적지_않는다():
    """게이트에 걸리면 `#status`가 이미 같은 문장을 말한다.

    라이브에서 같은 문단이 위아래로 두 번 나왔다. 아직 막히지 않았지만 몫을 다
    쓴 상태에서만 목록 아래에서 미리 알린다 — 다음 조회를 시도하기 전에 알아야
    쓸모가 있다.
    """
    src = _js(_VIEWER)
    body = src[src.index("function renderQuota()"):]
    body = body[:body.index("\n}")]
    assert "statusSaysIt" in body
    assert "!statusSaysIt" in body, "중복 검사 결과를 쓰지 않는다"


def test_소개_문구가_키_없는_조회를_말한다():
    """화면이 제 동작과 다른 것을 말하면 안 된다.

    옛 문구는 *"조회에는 본인의 무료 DART API 키가 필요합니다"*였다 — 키 없이
    하루 몇 곳이 열린 뒤로는 사실이 아니다.
    """
    src = _js(_VIEWER)
    intro = src[src.index("WHAT IS THIS"):]
    intro = intro[:intro.index("</ul>")]
    assert "키 없이" in intro
    assert "조회에는 <strong style=\"color:var(--tx)\">본인의 무료 DART API 키</strong>가 필요합니다" not in intro


def test_쿼터_저장소_읽기가_감싸져_있다():
    """기존 localStorage 읽기가 손상된 값에 throw하던 전철을 밟지 않는다."""
    src = _js(_VIEWER)
    body = src[src.index("function quotaLoad()"):]
    body = body[:body.index("\n}")]
    assert "try" in body and "catch" in body


def test_한도_안내가_키_발급_경로를_알려_준다():
    """소진 화면이 다음에 할 일을 말해야 한다 — 개인 키는 즉시 발급된다."""
    src = _js(_VIEWER)
    block = src[src.index("const QUOTA_DONE_HTML"):]
    block = block[:block.index(";\nfunction quotaKey")]
    assert "opendart.fss.or.kr" in block
    assert "즉시" in block
    assert "브라우저에만" in block, "키가 서버로 가지 않는다는 사실이 빠졌다"


def test_429를_릴레이_오류로_뭉뚱그리지_않는다():
    """할 일이 다르다 — 릴레이 주소 확인이 아니라 키 입력·내일 재시도다."""
    src = _js(_VIEWER)
    body = src[src.index("async function dartGet(endpoint, params)"):]
    body = body[:body.index("\n}")]
    assert "r.status === 429" in body
    assert body.index("429") < body.index("릴레이 오류"), (
        "429가 일반 오류 분기보다 뒤에 있어 도달하지 않는다"
    )


def test_무료_조회_수는_서버가_알려_준다():
    """뷰어에 숫자를 박아 두면 서버가 값을 바꿨을 때 화면만 옛 숫자를 말한다."""
    src = _js(_VIEWER)
    body = src[src.index("async function probeServerKey()"):]
    body = body[:body.index("\n}")]
    assert "free_scans" in body
    health = (_ROOT / "api" / "health.js").read_text(encoding="utf-8")
    assert "free_scans" in health


def test_health가_키_값을_내보내지_않는다():
    """공용 health도 있다/없다 불리언만 — 값이 나가면 릴레이가 키 배포처가 된다."""
    health = (_ROOT / "api" / "health.js").read_text(encoding="utf-8")
    assert "server_key: !!(process.env.DART_API_KEY" in health
    assert not re.search(r"(key|crtfc_key)\s*:\s*process\.env\.DART_API_KEY", health)


# ── /api/health 의 쿼터 상태 (2026-09-13) ───────────────────
#
# 쿼터는 저장소에 못 닿으면 조용히 통과시킨다(가용성을 깎지 않는다는 설계).
# 그러면 Upstash 한도를 넘겨도 화면에 아무것도 안 나타나고 **예산 방어만
# 사라진다** — 운영자가 확인할 창구가 이것뿐이라 여기가 틀리면 알 길이 없다.

def _run_health(env: dict, query: dict) -> dict:
    """`api/health.js`의 handler를 node로 실제 실행해 응답 본문을 돌려준다."""
    script = (
        f'const mod = await import({str(_HEALTH_JS)!r});\n'
        'const res = { setHeader(){}, status(){return this;},'
        ' json(o){console.log(JSON.stringify(o));}, end(){} };\n'
        f'await mod.default({{ method: "GET", query: {json.dumps(query)} }}, res);\n'
    )
    out = subprocess.run(
        ["node", "--input-type=module", "-e", script],
        capture_output=True, text=True, timeout=30,
        env={**os.environ, **env},
    )
    assert out.returncode == 0, out.stderr
    return json.loads(out.stdout.strip().splitlines()[-1])


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_health의_전역_상한이_다른_런타임과_같다():
    """세 번째 중복이다 — 갈리면 이 화면이 실제와 다른 분모를 보여 준다."""
    assert _js_const(_js(_HEALTH_JS), "DAILY_GLOBAL_CAP") == quota.DAILY_GLOBAL_CAP


def test_health가_같은_레디스_키를_읽는다():
    """다른 키를 읽으면 늘 0이 나와 「한가하다」는 거짓 안심을 준다."""
    assert "q:g:${day}" in _js(_HEALTH_JS)


def test_health가_카운터를_올리지_않는다():
    """상태를 보는 행위가 카운터를 올리면 안 된다 — `GET`이지 `INCR`가 아니다."""
    src = _js(_HEALTH_JS)
    body = src[src.index("async function quotaStatus()"):]
    body = body[:body.index("\nexport default")]
    assert "/get/" in body
    assert "INCR" not in body and "incr" not in body


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_quota_파라미터가_없으면_저장소를_치지_않는다():
    """뷰어가 부팅마다 부르는 경로다.

    기본 응답에 쿼터를 넣으면 **방문자 수만큼** Upstash 명령이 늘고 부팅도
    그만큼 느려진다. 쿼터 상태는 운영자만 보면 되는 값이다.
    """
    body = _run_health(
        {"DART_API_KEY": "x", "UPSTASH_REDIS_REST_URL": "https://example.invalid",
         "UPSTASH_REDIS_REST_TOKEN": "t"}, {})
    assert "quota" not in body
    assert body["server_key"] is True


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_설정_안_함과_못_닿음을_가른다():
    """둘을 뭉치면 설정을 빠뜨린 것과 한도를 넘긴 것이 같은 화면으로 보인다."""
    off = _run_health({"DART_API_KEY": "x", "UPSTASH_REDIS_REST_URL": "",
                       "UPSTASH_REDIS_REST_TOKEN": ""}, {"quota": "1"})
    assert off["quota"]["configured"] is False

    dead = _run_health(
        {"DART_API_KEY": "x", "UPSTASH_REDIS_REST_URL": "https://example.invalid",
         "UPSTASH_REDIS_REST_TOKEN": "t"}, {"quota": "1"})
    assert dead["quota"]["configured"] is True
    assert dead["quota"]["reachable"] is False


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_못_읽은_카운터는_0이_아니라_null이다():
    """「오늘 한 건도 안 썼다」와 「못 읽었다」는 다른 사실이다.

    0으로 내면 한도를 넘겨 조회가 막힌 상태가 **가장 한가한 상태**로 보인다.
    """
    dead = _run_health(
        {"DART_API_KEY": "x", "UPSTASH_REDIS_REST_URL": "https://example.invalid",
         "UPSTASH_REDIS_REST_TOKEN": "t"}, {"quota": "1"})
    assert dead["quota"]["today_calls"] is None


@pytest.mark.skipif(not shutil.which("node"), reason="node 없음")
def test_정상_응답이면_오늘_사용량을_읽는다():
    """응답 파싱이 깨지면 운영자가 늘 `null`만 보게 된다."""
    import http.server
    import threading

    class _H(http.server.BaseHTTPRequestHandler):
        def log_message(self, *a): pass

        def do_GET(self):
            payload = b'{"result":"3421"}'
            self.send_response(200)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(payload)))
            self.end_headers()
            self.wfile.write(payload)

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    try:
        body = _run_health(
            {"DART_API_KEY": "x",
             "UPSTASH_REDIS_REST_URL": f"http://127.0.0.1:{srv.server_port}",
             "UPSTASH_REDIS_REST_TOKEN": "t"}, {"quota": "1"})
    finally:
        srv.shutdown()
    assert body["quota"]["reachable"] is True
    assert body["quota"]["today_calls"] == 3421
    assert body["quota"]["daily_cap"] == quota.DAILY_GLOBAL_CAP
