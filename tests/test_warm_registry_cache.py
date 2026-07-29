"""scripts/warm_registry_cache.py 테스트 (SE-5c 최종 리뷰 Finding 5·3).

이 저장소는 "스크립트는 테스트하지 않는다"는 관행을 갖고 있지만, 이
스크립트는 그 관행이 전제하는 "혼자 돌고 아무것도 안 남기는 도구"가 아니다:

1. **공유 상태에 쓴다** — 프로덕션 Supabase의 레지스트리 캐시를 덮어쓴다.
   여기가 깨지면 SE 사용자 전원이 잘못된(또는 빈) 레지스트리를 본다.
2. **public 채널에 찍는다** — GitHub Actions 로그는 public이고, 이 스크립트가
   다루는 데이터는 실명 레지스트리다. 표준출력에 인물명·회사명이 한 글자라도
   새면 그건 되돌릴 수 없는 노출이다.

그래서 여기서는 **stdout만** 검증한다 — 네트워크는 전부 대역으로 막는다.
"""
from __future__ import annotations

import contextlib
import io
import os
import unittest
from unittest import mock

from scripts import warm_registry_cache as warm

# 대역 레지스트리 — 실명이 로그로 새는지 보기 위한 미끼다. 이 문자열들이
# stdout에 나타나면 그 자체가 결함이다.
_ACTOR_A = "홍길동"
_ACTOR_B = "김철수"
_COMPANY_A = "가나다전자"
_COMPANY_B = "라마바홀딩스"
_FAKE_REGISTRY = {
    "version": 1,
    "actors": {
        _ACTOR_A: [{"source": "s", "evidence": "e", "status": "verified",
                    "companies": [_COMPANY_A]}],
        _ACTOR_B: [{"source": "s", "evidence": "e", "status": "auto_matched",
                    "companies": [_COMPANY_B]}],
    },
}

_SECRETS = {
    "SUPABASE_URL": "https://example.supabase.co",
    "SUPABASE_SERVICE_KEY": "service-key",
    "NOTION_TOKEN": "notion-token",
    "DB_KNOWN_ACTORS": "db-id",
}


class _FakeCache:
    def __init__(self, config=None, put_exc=None):
        self.put_exc = put_exc
        self.puts = []

    def put_json(self, key, value, ttl_seconds):
        self.puts.append((key, value, ttl_seconds))
        if self.put_exc:
            raise self.put_exc


def _run(env, **patches):
    """main()을 격리 실행하고 (반환코드, stdout)을 돌려준다.

    `.env.local`(로컬 개발자 기계에 있을 수 있다)을 읽지 않도록 load_env_file을
    막는다 — 그러지 않으면 테스트가 기계마다 다르게 돈다.
    """
    buf = io.StringIO()
    stack = [
        mock.patch.dict(os.environ, env, clear=True),
        mock.patch.object(warm, "load_env_file", lambda: None),
    ]
    stack.extend(patches.get("extra", []))
    with contextlib.ExitStack() as es:
        for ctx in stack:
            es.enter_context(ctx)
        with contextlib.redirect_stdout(buf):
            rc = warm.main()
    return rc, buf.getvalue()


def _no_names(testcase, out):
    for secret in (_ACTOR_A, _ACTOR_B, _COMPANY_A, _COMPANY_B):
        testcase.assertNotIn(secret, out, f"public 로그에 '{secret}'이 새어나왔다")


class TestSkipBranches(unittest.TestCase):
    """시크릿이 없으면 조용히 건너뛴다 — 워크플로를 실패시키지 않는다."""

    def test_missing_supabase_secrets_skips_with_zero(self):
        env = {"NOTION_TOKEN": "t", "DB_KNOWN_ACTORS": "db"}
        rc, out = _run(env)
        self.assertEqual(rc, 0)
        self.assertIn("[SKIP]", out)
        self.assertIn("SUPABASE", out)

    def test_missing_notion_secrets_skips_with_zero(self):
        env = {"SUPABASE_URL": "u", "SUPABASE_SERVICE_KEY": "k"}
        rc, out = _run(env)
        self.assertEqual(rc, 0)
        self.assertIn("[SKIP]", out)
        self.assertIn("NOTION_TOKEN", out)

    def test_skip_branches_touch_no_network(self):
        """스킵 경로는 Notion·Supabase를 아예 부르지 않는다."""
        with mock.patch("dart_risk_mcp.core.known_actors.fetch_registry_from_notion") as f:
            rc, _ = _run({})
        self.assertEqual(rc, 0)
        f.assert_not_called()


class TestOutputCarriesNoNames(unittest.TestCase):
    """[OK]/[FAIL]/[WARN] 어느 경로로 끝나든 stdout에 실명이 없어야 한다."""

    def _extra(self, *, notion=_FAKE_REGISTRY, readback=(True, 2, ""), cache=None):
        return [
            mock.patch("dart_risk_mcp.core.known_actors.fetch_registry_from_notion",
                       return_value=notion),
            mock.patch("se_server.config.SEConfig.from_env", return_value=object()),
            mock.patch("se_server.cache.SupabaseCache",
                       side_effect=lambda cfg: cache or _FakeCache()),
            mock.patch.object(warm, "_readback_in_child_process", return_value=readback),
        ]

    def test_ok_path(self):
        rc, out = _run(_SECRETS, extra=self._extra())
        self.assertEqual(rc, 0)
        self.assertIn("[OK]", out)
        self.assertIn("인물 2명", out)   # 수는 찍는다
        _no_names(self, out)

    def test_fail_path_notion_returned_garbage(self):
        rc, out = _run(_SECRETS, extra=self._extra(notion=None))
        self.assertEqual(rc, 0)
        self.assertIn("[FAIL]", out)
        _no_names(self, out)

    def test_fail_path_readback_failed(self):
        rc, out = _run(_SECRETS, extra=self._extra(
            readback=(False, 0, "자식 예외 유형 RuntimeError")))
        self.assertEqual(rc, 0)
        self.assertIn("[FAIL]", out)
        self.assertIn("RuntimeError", out)
        _no_names(self, out)

    def test_fail_path_put_raised(self):
        cache = _FakeCache(put_exc=RuntimeError("boom"))
        rc, out = _run(_SECRETS, extra=self._extra(cache=cache))
        self.assertEqual(rc, 0)
        self.assertIn("[FAIL]", out)
        self.assertIn("RuntimeError", out)
        _no_names(self, out)

    def test_warn_path_readback_count_mismatch_returns_zero(self):
        """썼다고 믿은 인물 수와 다시 읽은 수가 다르면 [WARN]으로 남기고
        exit 0 — 레지스트리 갱신 자체는 이미 끝났으므로 워크플로를
        실패시키지 않는다."""
        rc, out = _run(_SECRETS, extra=self._extra(readback=(True, 1, "")))
        self.assertEqual(rc, 0)
        self.assertIn("[WARN]", out)
        self.assertIn("쓰기 2명", out)
        self.assertIn("읽기 1명", out)
        _no_names(self, out)


class TestChildOutputIsNeverPassedThrough(unittest.TestCase):
    """SE-5c 최종 리뷰 Finding 3 — 자식 프로세스 출력은 형태로 제한된 값만
    통과한다. 길이를 자르는 것(예전 구현: stderr 마지막 300자)은 무제한
    내용 채널을 닫지 못한다.
    """

    class _Proc:
        def __init__(self, stdout="", stderr="", returncode=0):
            self.stdout, self.stderr, self.returncode = stdout, stderr, returncode

    def _run_child(self, proc):
        with mock.patch.object(warm.subprocess, "run", return_value=proc):
            return warm._readback_in_child_process()

    def test_stderr_text_is_not_returned(self):
        leak = f"Traceback: {_ACTOR_A} at {_COMPANY_A} https://x.supabase.co/key=abc"
        ok, n, reason = self._run_child(self._Proc(stderr=leak, returncode=1))
        self.assertFalse(ok)
        self.assertEqual(n, 0)
        _no_names(self, reason)
        self.assertNotIn("supabase", reason)
        self.assertNotIn("abc", reason)

    def test_error_type_token_is_reported(self):
        ok, _, reason = self._run_child(
            self._Proc(stdout="READBACK_ERR ConnectionError\n"))
        self.assertFalse(ok)
        self.assertIn("ConnectionError", reason)

    def test_malformed_error_token_is_dropped(self):
        """READBACK_ERR 뒤에 식별자가 아닌 것이 오면 버린다 — 자식이(또는
        자식 출력에 섞여 들어온 무언가가) 임의 문자열을 실어 보내는 경로를
        막는다."""
        ok, _, reason = self._run_child(self._Proc(
            stdout=f"READBACK_ERR {_ACTOR_A} 님이 {_COMPANY_A}에 있습니다\n",
            returncode=3))
        self.assertFalse(ok)
        _no_names(self, reason)
        self.assertIn("3", reason)  # 종료코드로만 보고

    def test_success_line_is_parsed(self):
        ok, n, reason = self._run_child(self._Proc(stdout="READBACK_OK 1258\n"))
        self.assertTrue(ok)
        self.assertEqual(n, 1258)
        self.assertEqual(reason, "")

    def test_stderr_presence_without_type_is_reported_as_fact_only(self):
        ok, _, reason = self._run_child(
            self._Proc(stderr=f"{_ACTOR_B} 경고", returncode=0))
        self.assertFalse(ok)
        _no_names(self, reason)
        self.assertIn("stderr", reason)


if __name__ == "__main__":
    unittest.main()
