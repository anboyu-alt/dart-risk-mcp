"""로컬 개발 릴레이의 환경변수 키 폴백 — **값이 새지 않는지**를 함께 잠근다.

`scripts/dev_relay.py`는 브라우저가 키를 보내지 않았을 때만 `DART_API_KEY`로
채운다. 개발자가 MCP용으로 이미 가진 키를 브라우저에 다시 붙여넣지 않아도
되게 하려는 것이다.

⚠ 이 폴백은 **로컬 릴레이에만** 있다. `relay/worker.js`·`api/[endpoint].js`는
공용 배포라 서버 키를 주입하면 그 주소를 아는 누구나 제작자의 한도를 쓴다.
이 파일이 그 경계를 기계로 지킨다.
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


def test_공용_릴레이에는_서버_키_주입이_없다():
    """Vercel·Cloudflare 릴레이가 환경변수 키를 넣기 시작하면 여기서 걸린다."""
    for rel in ("relay/worker.js", "api/[endpoint].js"):
        src = (_ROOT / rel).read_text(encoding="utf-8")
        # 주석에서 언급하는 것은 허용 — 실제 참조만 본다
        code = "\n".join(
            l for l in src.splitlines()
            if not l.lstrip().startswith(("//", "*", "/*"))
        )
        assert "DART_API_KEY" not in code, (
            f"{rel}이 서버 키를 주입한다 — 공용 주소라 누구나 제작자 한도를 쓴다"
        )
