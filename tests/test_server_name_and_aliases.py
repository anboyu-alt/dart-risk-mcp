"""호출명을 하나로 모으고, 부르는 말은 여러 개를 알아듣게 한다.

배경(2026-09-14 실측). 이름이 네 곳에 서로 다르게 적혀 있었고, 그중
**가장 많이 쓰일 경로가 부를 수 없는 이름**이었다.

    .mcpb 확장      display_name "DART 리스크 분석 (불공정거래 위험 모니터링)"
                    → 도구 접두어 `DART_________________________`(언더스코어 29개)
    setup.py        dart-risk-analyzer
    README 수동     dart-risk
    FastMCP()       dart-risk-analyzer

도구 이름의 비ASCII 문자는 클라이언트가 `_`로 치환한다. 그래서 한글
display_name은 **부를 수 있는 이름이 아예 남지 않는다** — 옆에 붙은
`korean-dart`는 ASCII라 "korean-dart로"가 그냥 되는데 우리만 안 됐다.

⚠ 접두어(서버 이름)는 프로토콜상 **하나뿐**이다. 별칭을 여러 개 갖고
싶으면 서버를 여러 번 등록하는 게 아니라(도구가 33×N개로 중복 노출된다)
`FastMCP(instructions=...)`에 적는다 — 그 문장은 설치한 사람이 아무 설정도
하지 않아도 모든 세션의 시스템 프롬프트에 실린다.

⚠ `examples/*.md`는 **과거 보고서 산출물**이라 그때의 이름이 사실이다.
이 검사의 대상이 아니다(골든과 같은 성격).
"""

import json
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

SERVER_NAME = "dart-risk"

# 사용자가 부를 법한 표기. 한글은 접두어로는 못 쓰지만 instructions 안의
# 텍스트로는 문제없다.
ALIASES = ["dart-risk", "dartrisk", "다트리스크", "다트 리스크"]

# 클라이언트가 도구 이름을 만들 때 살려 두는 문자. 이 밖은 `_`가 된다.
_TOOL_NAME_SAFE = re.compile(r"^[A-Za-z0-9_-]+$")

# 다른 DART 도구를 밀어내는 말. 제작자 결정(2026-09-14): 우선순위를
# 선점하지 않고 우리가 무엇을 하는지만 말한다.
_PRIORITY_GRAB = ["항상", "반드시", "우선", "먼저 이 서버", "다른 도구 대신"]

# 매 세션 시스템 프롬프트에 실리므로 짧아야 한다.
_MAX_INSTRUCTIONS = 400


def _server_py() -> str:
    return (ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")


def _manifest() -> dict:
    return json.loads((ROOT / "extension" / "manifest.json").read_text(encoding="utf-8"))


class TestServerName(unittest.TestCase):
    def test_FastMCP_이름이_dart_risk다(self):
        from dart_risk_mcp.server import mcp

        self.assertEqual(mcp.name, SERVER_NAME)

    def test_확장_display_name이_도구_이름에서_뭉개지지_않는다(self):
        name = _manifest()["display_name"]
        self.assertTrue(
            _TOOL_NAME_SAFE.match(name),
            f"display_name {name!r}은 도구 접두어에서 `_`로 치환된다 — "
            "설치자가 이 서버를 부를 이름이 남지 않는다",
        )

    def test_확장_display_name이_서버_이름과_같다(self):
        self.assertEqual(_manifest()["display_name"], SERVER_NAME)

    def test_setup의_기본_등록_이름이_같다(self):
        from dart_risk_mcp import setup as setup_mod

        src = Path(setup_mod.__file__).read_text(encoding="utf-8")
        self.assertNotIn("dart-risk-analyzer", src)
        self.assertIn(f'default="{SERVER_NAME}"', src)

    def test_README_수동_설정_키가_같다(self):
        readme = (ROOT / "README.md").read_text(encoding="utf-8")
        self.assertIn(f'"{SERVER_NAME}": {{', readme)

    def test_옛_이름이_코드에_남아_있지_않다(self):
        for rel in ("dart_risk_mcp/server.py", "dart_risk_mcp/setup.py"):
            with self.subTest(rel):
                self.assertNotIn(
                    "dart-risk-analyzer",
                    (ROOT / rel).read_text(encoding="utf-8"),
                )


class TestAliases(unittest.TestCase):
    def _instructions(self) -> str:
        from dart_risk_mcp.server import mcp

        self.assertTrue(mcp.instructions, "instructions가 비어 있다")
        return mcp.instructions

    def test_별칭_네_표기가_모두_실려_있다(self):
        text = self._instructions()
        for alias in ALIASES:
            with self.subTest(alias):
                self.assertIn(alias, text)

    def test_instructions가_짧다(self):
        text = self._instructions()
        self.assertLessEqual(
            len(text),
            _MAX_INSTRUCTIONS,
            f"{len(text)}자 — 매 세션 컨텍스트를 먹는다",
        )

    def test_다른_도구를_밀어내는_말을_쓰지_않는다(self):
        text = self._instructions()
        for word in _PRIORITY_GRAB:
            with self.subTest(word):
                self.assertNotIn(word, text)

    def test_소스에_직접_적혀_있다(self):
        """설치한 사람이 아무 설정도 안 해도 실리려면 서버가 스스로 알려야 한다."""
        src = _server_py()
        self.assertIn("instructions=", src)


if __name__ == "__main__":
    unittest.main()
