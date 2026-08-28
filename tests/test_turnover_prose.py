"""회전율·CCC 지표 해설(`core/explain.py`의 `TURNOVER_PROSE`) 검증.

v1.21.3 — 사용자 제보 "높아지면 좋은건지 나쁜건지 모르는 사용자들도 있다"에
대응해 6항목(매출채권·재고자산·매입채무·운전자본·총자산 회전율 + CCC) 해설을
추가했다. 이 파일은 세 가지를 잠근다.

  ① 콘텐츠 완결성 — 6항목 전부, 다섯 키(label/formula/meaning/fall/caveat)
     전부 비어 있지 않다.
  ② v0.8.5 무판정 원칙 — "위험"·"양호"·"우수"·"나쁨"·"점수"·"등급" 같은
     판정 어휘가 없다. 단 "나쁘지는 않습니다"류 부정형 안에 우연히 섞이는
     문자열은 오탐이 아니다("나쁨"과 "나쁘지"는 다른 문자열이다).
  ③ "높을수록 좋다"류 단정 금지 — payable(매입채무회전율)·working_capital
     (운전자본회전율)은 방향과 좋고 나쁨이 일치하지 않는 지표라, 실제로
     반전 경로가 caveat에 적혀 있는지 확인한다.

배선 드리프트 방지: export_tool_data.py가 이 dict를 그대로
`docs/tool/signals-data.json`의 `turnover_prose` 키로 내보내는지(문구 복제
금지 — core가 바뀌면 뷰어만 조용히 낡는 사고를 막는다), 뷰어 JS가 실제로
그 키를 읽는지도 함께 고정한다.
"""
import json
import os
import pathlib
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from dart_risk_mcp.core.explain import TURNOVER_PROSE, turnover_prose  # noqa: E402

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_REQUIRED_KEYS = {"receivable", "inventory", "payable", "working_capital",
                  "asset", "ccc"}
_PROSE_FIELDS = ("label", "formula", "meaning", "fall", "caveat")
# v0.8.5 무판정 원칙 — 회전율 해설에서 금지되는 판정 어휘. "나쁨"은 정확히
# 이 세 글자가 없어야 한다는 뜻이지, "나쁘지"(나쁘/지)까지 막지 않는다 —
# 두 문자열은 애초에 다르다(부분 문자열 관계가 아니다).
_BANNED_VERDICT_WORDS = ("위험", "양호", "우수", "나쁨", "점수", "등급")


class TestTurnoverProseContent(unittest.TestCase):
    def test_6항목이_전부_있다(self):
        self.assertEqual(set(TURNOVER_PROSE.keys()), _REQUIRED_KEYS)

    def test_다섯_키가_전부_비어있지_않다(self):
        for key, entry in TURNOVER_PROSE.items():
            self.assertEqual(
                set(entry.keys()), set(_PROSE_FIELDS),
                f"{key}의 키 구성이 다섯 필드와 다르다: {sorted(entry.keys())}",
            )
            for field in _PROSE_FIELDS:
                value = entry[field]
                self.assertIsInstance(value, str, f"{key}.{field}는 문자열이어야 한다")
                self.assertTrue(value.strip(), f"{key}.{field}가 비어 있다")

    def test_turnover_prose_헬퍼가_동작한다(self):
        self.assertEqual(turnover_prose("ccc"), TURNOVER_PROSE["ccc"])
        self.assertEqual(turnover_prose("존재하지-않는-키"), {})


class TestNoVerdictVocabulary(unittest.TestCase):
    def test_판정_어휘가_없다(self):
        for key, entry in TURNOVER_PROSE.items():
            text = " ".join(entry[f] for f in _PROSE_FIELDS)
            for banned in _BANNED_VERDICT_WORDS:
                self.assertNotIn(
                    banned, text,
                    f"{key}의 해설에 판정 어휘 {banned!r}가 있다: {text!r}",
                )

    def test_부정형_나쁘지는_않습니다는_오탐이_아니다(self):
        """payable.fall의 "나쁘지는 않습니다"가 금지어 "나쁨"에 걸리지 않는지
        회귀 고정 — 이 문구 자체가 이 테스트 파일이 존재하는 이유다."""
        fall = TURNOVER_PROSE["payable"]["fall"]
        self.assertIn("나쁘지는 않습니다", fall)
        self.assertNotIn("나쁨", fall)


class TestReversalCaveatsPresent(unittest.TestCase):
    """"높을수록 좋다"류 단정을 금지하는 것과, 실제로 반전 경로가 적혀
    있는지는 다른 문제다 — 전자만 보면 caveat을 아예 안 써도 통과한다."""

    def test_매입채무회전율_caveat이_높다고_좋은_것이_아니라고_말한다(self):
        caveat = TURNOVER_PROSE["payable"]["caveat"]
        self.assertIn("⚠", caveat)
        self.assertIn("높다고", caveat)
        self.assertIn("아닙니다", caveat)

    def test_운전자본회전율_caveat이_분모_축소로_인한_상승을_경고한다(self):
        caveat = TURNOVER_PROSE["working_capital"]["caveat"]
        self.assertIn("⚠", caveat)
        # 유동부채가 늘어(분모가 줄어) 값이 커질 수 있다는 반전 경로.
        self.assertIn("분모가 줄어", caveat)
        self.assertIn("유동부채가 늘면", caveat)

    def test_그_외_항목은_reversal_마커가_필수는_아니다(self):
        """receivable·inventory·asset·ccc는 방향과 뜻이 대체로 일치하는
        지표라 ⚠ 강한 반전 경고가 의무는 아니다 — 있어도 되고 없어도 된다.
        이 테스트는 위 두 항목만 강제하는 설계를 문서화한다(회귀 방지용
        assert 없이 통과시킨다)."""
        for key in ("receivable", "inventory", "asset", "ccc"):
            self.assertIn(key, TURNOVER_PROSE)


class TestExportWiring(unittest.TestCase):
    """export_tool_data.py가 TURNOVER_PROSE를 그대로 내보내는지 — 문구
    복제 금지(CLAUDE.md의 _FS_ALIAS_KEYS와 같은 이유)."""

    def test_build_signals_data가_core와_완전히_같은_turnover_prose를_낸다(self):
        from export_tool_data import build_signals_data  # noqa: E402

        data = build_signals_data()
        self.assertIn("turnover_prose", data)
        exported = data["turnover_prose"]
        core_as_plain = {k: dict(v) for k, v in TURNOVER_PROSE.items()}
        self.assertEqual(exported, core_as_plain)

    def test_배포된_signals_data_json이_core와_완전히_같다(self):
        """빌드 함수만 맞고 커밋된 산출물이 낡아 있으면(재생성 누락)
        뷰어는 여전히 옛 문구를 보여준다 — 파일 자체를 대조한다."""
        json_path = _ROOT / "docs" / "tool" / "signals-data.json"
        self.assertTrue(json_path.exists(), "signals-data.json이 없다")
        data = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertIn(
            "turnover_prose", data,
            "signals-data.json에 turnover_prose가 없다 — "
            "scripts/export_tool_data.py 재실행 필요",
        )
        exported = data["turnover_prose"]
        core_as_plain = {k: dict(v) for k, v in TURNOVER_PROSE.items()}
        self.assertEqual(
            exported, core_as_plain,
            "signals-data.json의 turnover_prose가 core와 다르다 — "
            "python scripts/export_tool_data.py로 재생성해야 한다",
        )

    def test_score_severity_confidence를_내보내지_않는다(self):
        """v0.8.5 무점수 원칙 — 다섯 필드 밖의 판정성 키가 섞여 들면 안 된다."""
        for key, entry in TURNOVER_PROSE.items():
            for forbidden in ("score", "severity", "confidence", "base_score"):
                self.assertNotIn(forbidden, entry)


class TestViewerReadsTurnoverProse(unittest.TestCase):
    """뷰어(docs/tool/index.html)가 DATA.turnover_prose를 실제로 읽는지 —
    데이터만 내보내고 소비하는 쪽이 없으면 해설이 화면에 나타나지 않는다."""

    def setUp(self):
        self.html = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")

    def test_DATA_turnover_prose_참조가_존재한다(self):
        self.assertIn("DATA.turnover_prose", self.html)

    def test_turnoverProseHTML_함수가_있고_회전율_블록에서_호출된다(self):
        self.assertIn("function turnoverProseHTML()", self.html)
        i = self.html.index("function turnoverTrendBlockHTML(")
        block = self.html[i:i + 6000]
        self.assertIn("turnoverProseHTML()", block)

    def test_esc를_거쳐_렌더한다(self):
        i = self.html.index("function turnoverProseHTML()")
        j = self.html.index("\n}", i)
        body = self.html[i:j]
        # label/formula/meaning/fall/caveat 다섯 필드 전부 esc()를 통과해야
        # DART 응답에 섞인 특수문자가 레이아웃을 깨거나 주입 경로가 되지 않는다.
        for field in ("p.label", "p.formula", "p.meaning", "p.fall", "p.caveat"):
            self.assertIn(f"esc({field})", body, f"{field}가 esc()를 거치지 않는다")


if __name__ == "__main__":
    unittest.main()


def test_MCP는_값이_나온_지표만_해설한다():
    """6항목을 늘 붙이면 삼성전자 3년이 1,412 → 2,769자로 배가 되고, 그 절반이
    회사와 무관한 고정 문구가 된다. 스팩·금융업에서는 값이 두어 개인데 해설만
    여섯 개 붙는다. 계산되지 않은 지표의 사유는 이미 「관찰된 사실」에 있다.

    뷰어는 접힌 `<details>`라 6항목 전부를 담는다 — 거기서는 방해가 없다.
    """
    import pathlib
    src = (pathlib.Path(__file__).resolve().parents[1]
           / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
    i = src.index('lines.append("**지표 읽는 법**")')
    head = src[i - 900:i]
    assert "_prose_keys" in head, "해설 대상을 추리지 않는다"
    assert 'get("value") is not None' in head, "값이 나온 지표만 고르는 조건이 없다"
    assert 'per_year[y]["ccc"]' in head, "CCC는 별도 판정이 필요하다"


def test_뷰어는_여섯_항목을_전부_담는다():
    """접힘이라 방해가 없고, 계산되지 않은 지표일수록 뜻을 알고 싶을 수 있다."""
    import pathlib
    html = (pathlib.Path(__file__).resolve().parents[1]
            / "docs" / "tool" / "index.html").read_text(encoding="utf-8")
    i = html.index("function turnoverProseHTML(")
    body = html[i:i + 1600]
    assert "TURNOVER_PROSE_KEY_MAP" in body or "ccc" in body
    # 값이 있는 지표만 고르는 조건이 뷰어에 들어가면 안 된다
    assert "value !== null" not in body, "뷰어까지 추리면 접힘의 이점이 없다"
