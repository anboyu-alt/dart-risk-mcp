"""tool_server.doc.handle_doc — 공개 뷰어 원문 추출 몸통의 단위 테스트.

DART 호출(fetch_disclosure_full)은 모킹한다. 실패 분기 규칙은
옛 SE `_disclosure`에서 검증된 것과 동일해야 한다:
files 없음=502(못 받음), text 없음=404(원문 없음).
"""
import pytest

import tool_server.doc as doc_mod
from tool_server.doc import (
    MAX_CHARS_DEFAULT,
    MAX_CHARS_MAX,
    MAX_CHARS_MIN,
    _clamp_max_chars,
    handle_doc,
)

RCEPT = "20260612900563"


def _ok_result(text="본문 텍스트", truncated=False):
    return {
        "files": [{"name": "doc.xml", "size": 1234}],
        "text": text,
        "char_count": len(text),
        "truncated": truncated,
    }


def test_missing_api_key_returns_400():
    status, body = handle_doc({"rcept_no": RCEPT}, "")
    assert status == 400
    assert "X-DART-Key" in body["error"]


@pytest.mark.parametrize("bad", ["", "1234", "abcdefghijklmn", "2026061290056", "202606129005631"])
def test_bad_rcept_no_returns_400(bad):
    status, body = handle_doc({"rcept_no": bad}, "key")
    assert status == 400
    assert "rcept_no" in body["error"]


def test_fetch_failure_files_empty_returns_502(monkeypatch):
    monkeypatch.setattr(doc_mod, "fetch_disclosure_full",
                        lambda *a, **k: {"files": [], "text": "", "char_count": 0, "truncated": False})
    status, body = handle_doc({"rcept_no": RCEPT}, "key")
    assert status == 502


def test_fetch_exception_returns_502(monkeypatch):
    def boom(*a, **k):
        raise RuntimeError("network")
    monkeypatch.setattr(doc_mod, "fetch_disclosure_full", boom)
    status, body = handle_doc({"rcept_no": RCEPT}, "key")
    assert status == 502


def test_empty_text_returns_404(monkeypatch):
    monkeypatch.setattr(doc_mod, "fetch_disclosure_full",
                        lambda *a, **k: {"files": [{"name": "x"}], "text": "", "char_count": 0, "truncated": False})
    status, body = handle_doc({"rcept_no": RCEPT}, "key")
    assert status == 404


def test_success_shape(monkeypatch):
    monkeypatch.setattr(doc_mod, "fetch_disclosure_full",
                        lambda *a, **k: _ok_result("원문", truncated=True))
    status, body = handle_doc({"rcept_no": RCEPT}, "key")
    assert status == 200
    assert body == {"rcept_no": RCEPT, "text": "원문", "char_count": 2, "truncated": True}


def test_max_chars_is_clamped_and_forwarded(monkeypatch):
    seen = {}

    def fake(rcept_no, api_key, max_chars=None):
        seen["max_chars"] = max_chars
        return _ok_result()

    monkeypatch.setattr(doc_mod, "fetch_disclosure_full", fake)

    handle_doc({"rcept_no": RCEPT, "max_chars": "50"}, "key")
    assert seen["max_chars"] == MAX_CHARS_MIN

    handle_doc({"rcept_no": RCEPT, "max_chars": "999999"}, "key")
    assert seen["max_chars"] == MAX_CHARS_MAX

    handle_doc({"rcept_no": RCEPT}, "key")
    assert seen["max_chars"] == MAX_CHARS_DEFAULT


def test_clamp_max_chars_garbage_falls_back_to_default():
    assert _clamp_max_chars("abc") == MAX_CHARS_DEFAULT
    assert _clamp_max_chars(None) == MAX_CHARS_DEFAULT
    assert _clamp_max_chars("") == MAX_CHARS_DEFAULT


def test_no_judgement_wording_in_bodies(monkeypatch):
    """무판정 원칙 — 서버 응답에 판정성 어휘가 섞이지 않는다."""
    monkeypatch.setattr(doc_mod, "fetch_disclosure_full", lambda *a, **k: _ok_result())
    for query, key in [({"rcept_no": RCEPT}, "key"), ({"rcept_no": "bad"}, "key"), ({"rcept_no": RCEPT}, "")]:
        _, body = handle_doc(query, key)
        joined = " ".join(str(v) for v in body.values() if isinstance(v, str))
        for banned in ("위험도", "등급", "점수"):
            assert banned not in joined
