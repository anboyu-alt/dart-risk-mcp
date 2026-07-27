"""app.js 순수 함수 검증 — node 서브프로세스로 실제 실행한다.

브라우저 로직을 테스트 밖에 두면 이 저장소의 유일한 품질 장치인 pytest가
닿지 않는다. app.js는 DOM도 네트워크도 만지지 않는 순수 함수만 담으므로
node로 그대로 부를 수 있다.
"""
import json
import pathlib
import shutil
import subprocess
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_APP = _ROOT / "docs" / "tool" / "se" / "app.js"
_NODE = shutil.which("node")


def run_js(expression: str):
    """app.js를 로드해 표현식을 평가하고 결과를 JSON으로 받는다."""
    # export를 전역에 통째로 얹는다. 고정 목록을 두면 함수가 늘 때마다
    # 목록을 고쳐야 하고, 빠뜨리면 "정의되지 않음"으로 엉뚱하게 실패한다.
    script = (
        f"Object.assign(globalThis, require({json.dumps(str(_APP))}));\n"
        f"process.stdout.write(JSON.stringify({expression}));\n"
    )
    # encoding을 명시하지 않으면 Windows에서 로케일 기본 인코딩(cp949 등)으로
    # 디코딩을 시도한다. node는 stdout에 UTF-8 바이트를 쓰므로(한글 문구가
    # 여기 섞여 있다 — pollDecision의 reason, SECTION_GROUPS의 제목 등),
    # 로케일이 다르면 UnicodeDecodeError가 나거나 운 좋게 우연히 다른 문자로
    # 잘못 디코딩될 수 있다.
    out = subprocess.run(
        [_NODE, "-e", script], capture_output=True, text=True, encoding="utf-8"
    )
    if out.returncode != 0:
        raise AssertionError(f"node 실행 실패:\n{out.stderr}")
    return json.loads(out.stdout)


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestNextKeysToFetch(unittest.TestCase):
    def test_returns_keys_not_yet_fetched(self):
        got = run_js('nextKeysToFetch(["a","b","c"], ["a"])')
        self.assertEqual(got, ["b", "c"])

    def test_returns_empty_when_all_fetched(self):
        self.assertEqual(run_js('nextKeysToFetch(["a","b"], ["a","b"])'), [])

    def test_never_refetches_across_polls(self):
        """폴링이 반복돼도 같은 키를 두 번 주지 않아야 한다.

        SE-4a가 없앤 737KB 문제가 되돌아오는 경로가 정확히 여기다.
        """
        got = run_js(
            '(() => { const seen=[]; let out=[];'
            ' for (const poll of [["a"],["a","b"],["a","b","c"]]) {'
            '   const n = nextKeysToFetch(poll, seen); out = out.concat(n);'
            '   for (const k of n) seen.push(k); }'
            ' return out; })()'
        )
        self.assertEqual(got, ["a", "b", "c"], "같은 섹션을 다시 받고 있습니다")

    def test_ignores_unknown_extra_keys_in_fetched(self):
        self.assertEqual(run_js('nextKeysToFetch(["a"], ["zzz"])'), ["a"])


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestPollDecision(unittest.TestCase):
    def test_stops_when_done(self):
        got = run_js('pollDecision({done: true, stalled: false, processed: 3})')
        self.assertTrue(got["shouldStop"])

    def test_stops_when_stalled(self):
        """진행이 멈췄는데 계속 부르면 DART 호출 한도만 태운다."""
        got = run_js('pollDecision({done: false, stalled: true, processed: 0})')
        self.assertTrue(got["shouldStop"])
        self.assertTrue(got["reason"], "멈춘 이유를 사용자에게 말해야 합니다")

    def test_continues_while_progressing(self):
        got = run_js('pollDecision({done: false, stalled: false, processed: 2})')
        self.assertFalse(got["shouldStop"])

    def test_missing_fields_do_not_loop_forever(self):
        """응답이 예상과 달라도 무한 루프에 빠지면 안 된다."""
        got = run_js("pollDecision({})")
        self.assertTrue(got["shouldStop"])


@unittest.skipUnless(_NODE, "node가 없어 app.js 순수 함수를 검증할 수 없습니다")
class TestSectionGroups(unittest.TestCase):
    def test_covers_all_stage1_keys_except_header(self):
        """registry의 1단 키 13개가 화면 어딘가에는 나와야 한다.

        빠지면 데이터를 받아놓고 보여주지 않는 것이다.
        """
        from se_server.jobs.registry import STAGE1_SPECS

        groups = run_js("SECTION_GROUPS")
        shown = {k for g in groups for k in g["keys"]}
        expected = {s.key for s in STAGE1_SPECS} - {"company_info"}  # 헤더는 별도
        self.assertEqual(expected - shown, set(),
                         "화면에 안 나오는 섹션이 있습니다")
        self.assertEqual(shown - expected, set(),
                         "registry에 없는 섹션 키를 그리려 합니다")


if __name__ == "__main__":
    unittest.main()
