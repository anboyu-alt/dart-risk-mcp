"""로컬 개발 릴레이의 환경변수 키 폴백 — **값이 새지 않는지**를 함께 잠근다.

`scripts/dev_relay.py`는 브라우저가 키를 보내지 않았을 때만 `DART_API_KEY`로
채운다. 개발자가 MCP용으로 이미 가진 키를 브라우저에 다시 붙여넣지 않아도
되게 하려는 것이다.

⚠ **경계가 2026-09-13에 바뀌었다.** 옛 규칙은 "공용 릴레이에 서버 키 금지"였다
(근거: *"그 주소를 아는 누구나 제작자의 한도를 쓴다"*). 키 없는 방문자에게 하루
몇 곳을 열어 주기로 하면서 `api/[endpoint].js`는 서버 키를 갖게 됐고, 그 위험은
쿼터(전역 일일 상한 + IP별 스캔 상한)가 대신 막는다. 그래서 이 파일이 지키는
것은 이제 셋이다.

- `relay/worker.js`(Cloudflare 미러)에는 여전히 서버 키가 없을 것 — 쿼터
  저장소가 붙지 않은 경로라 옛 위험이 그대로다.
- `api/[endpoint].js`가 서버 키를 쓰면 **쿼터 검사도 반드시 있을 것.**
- 사용자 키가 실린 요청에는 캐시 헤더가 붙지 않을 것 — 캐시 키에 남의 인증키가
  섞이면 안 된다.
"""
import importlib.util
import os
import pathlib
import re

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_RELAY = _ROOT / "scripts" / "dev_relay.py"


def _load():
    spec = importlib.util.spec_from_file_location("dev_relay_probe", _RELAY)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


@pytest.fixture()
def relay(monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "ENVKEY0000")
    return _load()


def test_키가_없으면_환경변수로_채운다(relay):
    out = relay._with_key("corp_code=00126380&bsns_year=2024")
    assert "crtfc_key=ENVKEY0000" in out
    assert "corp_code=00126380" in out


def test_브라우저_키가_있으면_그것을_쓴다(relay):
    """환경변수가 사용자의 선택을 덮어쓰면 안 된다."""
    out = relay._with_key("crtfc_key=USERKEY&corp_code=00126380")
    assert "crtfc_key=USERKEY" in out
    assert "ENVKEY0000" not in out


def test_빈_키는_없는_것으로_본다(relay):
    """`crtfc_key=`(빈 값)는 URLSearchParams가 만드는 실제 형태다."""
    out = relay._with_key("crtfc_key=&corp_code=00126380")
    assert "crtfc_key=ENVKEY0000" in out
    assert out.count("crtfc_key") == 1


def test_환경변수가_없으면_그대로_둔다(monkeypatch):
    monkeypatch.delenv("DART_API_KEY", raising=False)
    mod = _load()
    q = "corp_code=00126380"
    assert mod._with_key(q) == q


def test_health가_키_값을_내보내지_않는다():
    """있다/없다 불리언만 나가야 한다 — 값이 나가면 릴레이가 키 배포처가 된다."""
    src = _RELAY.read_text(encoding="utf-8")
    block = src[src.index('/api/health'):src.index('/api/health') + 900]
    assert '"server_key": bool(' in block
    assert "_env_key()" in block
    # 키 값을 그대로 넣는 형태가 없어야 한다
    assert not re.search(r'"(key|api_key|crtfc_key)"\s*:\s*_env_key\(\)', block)


def _code_only(rel: str) -> str:
    """주석을 걷어낸 소스 — 주석에서 이름을 언급하는 것은 허용한다."""
    src = (_ROOT / rel).read_text(encoding="utf-8")
    return "\n".join(
        l for l in src.splitlines()
        if not l.lstrip().startswith(("//", "*", "/*"))
    )


def test_클라우드플레어_미러에는_서버_키_주입이_없다():
    """relay/worker.js는 **쿼터 저장소가 붙지 않은 경로**다.

    Vercel 릴레이는 2026-09-13에 서버 키를 갖게 됐지만(아래 테스트), 그 안전은
    전역·IP 카운터가 받쳐 준다. 이 미러에는 그것이 없으므로 키를 두면 옛
    위험이 그대로다 — 주소를 아는 누구나 제작자 한도를 쓴다.
    """
    assert "DART_API_KEY" not in _code_only("relay/worker.js"), (
        "relay/worker.js가 서버 키를 주입한다 — 이 경로에는 쿼터가 없다"
    )


def test_서버_키를_쓰는_릴레이는_쿼터_검사를_함께_갖는다():
    """`api/[endpoint].js`의 경계 재정의(2026-09-13).

    옛 경계는 "공용 릴레이에 서버 키 금지"였고 근거는 *"그 주소를 아는 누구나
    제작자의 한도를 쓴다"*였다. 키 없는 방문자에게 하루 몇 곳을 열어 주기로
    하면서 그 전제를 **쿼터가 대신 막는다** — 전역 일일 상한과 IP별 스캔 상한.

    그러므로 금지할 것은 서버 키 자체가 아니라 **쿼터 없는 서버 키**다.
    """
    code = _code_only("api/[endpoint].js")
    if "DART_API_KEY" not in code:
        return  # 서버 키를 쓰지 않는 배포 — 옛 상태로 돌아간 것이고 안전하다
    assert "checkQuota" in code, "서버 키를 쓰면서 쿼터 검사가 없다"
    assert "DAILY_GLOBAL_CAP" in code, "전역 일일 상한이 없다"
    assert "DAILY_IP_SCANS" in code, "IP별 상한이 없다"
    # 검사 결과를 실제로 쓰는가 — 계산만 하고 버리면 방어가 아니다
    assert "429" in code, "쿼터 초과를 거절하지 않는다"


def test_서버_키_값은_브라우저_키를_덮어쓰지_않는다():
    """환경변수가 사용자의 선택을 덮어쓰면 안 된다 — dev_relay와 같은 우선순위."""
    code = _code_only("api/[endpoint].js")
    if "DART_API_KEY" not in code:
        return
    # 브라우저 키가 있는지 먼저 보고, 없을 때만 서버 키를 넣는 형태여야 한다
    assert "browserKey" in code
    idx_browser = code.index("browserKey")
    idx_server = code.index("DART_API_KEY")
    assert idx_browser < idx_server, (
        "서버 키를 먼저 넣고 있다 — 브라우저 키가 있으면 그것을 써야 한다"
    )


def test_사용자_키가_실린_요청은_캐시하지_않는다():
    """캐시 키에 남의 인증키가 섞이면 안 된다.

    `api/doc.py`가 캐시를 걸 수 있는 근거가 *"키가 URL에 없어 캐시 키 안전"*
    이었다. 릴레이는 키를 쿼리로 받으므로, 서버 키 경로에서만 캐시해야 한다.
    """
    code = _code_only("api/[endpoint].js")
    if "s-maxage" not in code:
        return  # 캐시를 걸지 않는 상태 — 안전하다
    assert "cacheable" in code
    # cacheable의 첫 관문이 "서버 키를 썼는가"여야 한다
    body = code[code.index("function cacheable"):]
    body = body[:body.index("\n}")]
    first = body.split("\n")[1].strip()
    assert "usedServerKey" in first, (
        f"cacheable의 첫 검사가 서버 키 여부가 아니다: {first!r}"
    )
