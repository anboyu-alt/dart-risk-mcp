"""메자닌·희석·재무·자금사용·소유보고·감사 지표 해설(`core/explain.py`의
`METRIC_PROSE`) 검증.

`tests/test_turnover_prose.py`(`TURNOVER_PROSE`)를 본보기로 삼는다 — 같은
필드 계약(label/formula(선택)/meaning/fall(선택)/caveat), 같은 무판정
원칙, 같은 export 배선 검사 구조다. 뷰어의 회전율 패널만 「지표 읽는 법」
접힌 층을 갖고 있었는데, 메자닌·희석·재무·자금사용·소유보고·감사 패널의
수치에는 대응물이 없었다 — 이 파일이 그 데이터·export·테스트를 고정한다.
뷰어 렌더 배선은 다음 과제의 몫이다(④가 그 경계를 고정한다).

  ① 콘텐츠 완결성 — 패널 7개(mezzanine/dilution/financial/fund_usage/
     insider/audit/overview) 키 집합이 브리프의 목록과 정확히 같다.
     entry마다 label·meaning·caveat 필수, formula·fall은 선택, 그 외 키
     없음. 모든 값은 비어 있지 않은 문자열. 문장은
     `(?<=[다요])\\.` 분할 기준으로 60자 이하.
  ② v0.8.5 무판정 원칙 — 판정 어휘가 없고(hygiene 패턴·등급 이모지 부재
     포함), `tests/test_severity_token_leak.py`의 파라미터에도 등록됐다.
  ③ export 일치 — `build_signals_data()["metric_prose"]`가 core와 완전히
     같고, 커밋된 `signals-data.json`과도 같다.
  ④ MCP 비사용 — `server.py` 원문에 `METRIC_PROSE`가 등장하지 않는다.
     뷰어는 접힌 `<details>`라 전부 담아도 방해가 없지만, MCP 원문 블록은
     이미 각자 사실·한계 고지를 갖고 있어(`_MZN_NOT_BALANCE` 등) 같은
     뜻을 접힌 사전으로 한 번 더 붙이면 출력 분량만 늘어난다는 것이
     `TURNOVER_PROSE`가 "값이 나온 지표만" 붙이는 절충과 다른 이 사전의
     결정이다.
  ⑤ 고아 금지 — `tests/test_glossary.py`의 고아 검사 원천 합집합에
     METRIC_PROSE 전 필드를 추가해, 사전 표제어가 여기서도 쓰일 수 있게
     한다(그 파일에서 검증).
  ⑥ 「높을수록 좋」·「낮을수록 좋」류 단정이 caveat에 없다.
"""
import json
import os
import pathlib
import re
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))

from dart_risk_mcp.core.explain import METRIC_PROSE  # noqa: E402

_ROOT = pathlib.Path(__file__).resolve().parents[1]

_REQUIRED_PANEL_KEYS: dict[str, set[str]] = {
    "mezzanine": {
        "overhang", "pct_at_strike", "pct_at_floor", "refix_floor",
        "maturity_not_yet", "exercise_open", "coupon_ytm", "amended",
    },
    "dilution": {"dilutive", "proportional", "decrease", "unknown"},
    "financial": {
        "capital_impairment", "loss_streak", "retained_earnings",
        "cash_rich_loss", "debt_ratio", "current_ratio",
    },
    "fund_usage": {
        "plan_vs_real", "diff_reason", "use_shift", "nearby_signal",
    },
    "insider": {"holding_series", "short_accumulation", "delta_pp"},
    "audit": {"opinion", "auditor_change", "mgmt_issue"},
    "overview": {"amend_rate", "tiers"},
}

_REQUIRED_FIELDS = {"label", "meaning", "caveat"}
_OPTIONAL_FIELDS = {"formula", "fall"}
_ALL_FIELDS = _REQUIRED_FIELDS | _OPTIONAL_FIELDS

# v0.8.5 무판정 원칙 — GLOSSARY·TURNOVER_PROSE와 같은 금지 낱말 목록.
_BANNED_VERDICT_WORDS = (
    "위험", "양호", "우수", "나쁨", "점수", "등급", "위험도", "스코어",
    "매우위험", "고위험", "중위험", "저위험",
    "CRITICAL", "HIGH", "MEDIUM", "LOW", "base_score", "confidence",
)

_SENTENCE_SPLIT_RE = re.compile(r"(?<=[다요])\.")


def _sentences(text: str) -> list[str]:
    return [p for p in _SENTENCE_SPLIT_RE.split(text) if p.strip()]


class TestMetricProseContent(unittest.TestCase):
    def test_패널_7개가_정확히_있다(self):
        self.assertEqual(set(METRIC_PROSE.keys()), set(_REQUIRED_PANEL_KEYS))

    def test_패널별_키_집합이_브리프_목록과_정확히_같다(self):
        for panel, keys in _REQUIRED_PANEL_KEYS.items():
            self.assertEqual(
                set(METRIC_PROSE[panel].keys()), keys,
                f"{panel} 패널 키 불일치: "
                f"{set(METRIC_PROSE[panel].keys()) ^ keys}",
            )

    def test_필수_필드가_전부_있고_그_외_필드가_없다(self):
        for panel, entries in METRIC_PROSE.items():
            for key, entry in entries.items():
                field_keys = set(entry.keys())
                self.assertTrue(
                    _REQUIRED_FIELDS <= field_keys,
                    f"{panel}.{key}에 필수 필드가 빠졌다: "
                    f"{_REQUIRED_FIELDS - field_keys}",
                )
                self.assertTrue(
                    field_keys <= _ALL_FIELDS,
                    f"{panel}.{key}에 정의되지 않은 필드가 있다: "
                    f"{field_keys - _ALL_FIELDS}",
                )

    def test_모든_값이_비어있지_않은_문자열이다(self):
        for panel, entries in METRIC_PROSE.items():
            for key, entry in entries.items():
                for field, value in entry.items():
                    self.assertIsInstance(
                        value, str, f"{panel}.{key}.{field}는 문자열이어야 한다"
                    )
                    self.assertTrue(
                        value.strip(), f"{panel}.{key}.{field}가 비어 있다"
                    )

    def test_문장이_60자_이하다(self):
        for panel, entries in METRIC_PROSE.items():
            for key, entry in entries.items():
                for field, value in entry.items():
                    for sentence in _sentences(value):
                        self.assertLessEqual(
                            len(sentence), 60,
                            f"{panel}.{key}.{field}의 문장이 60자를 넘는다"
                            f"({len(sentence)}자): {sentence!r}",
                        )

    def test_formula가_있는_지표는_브리프가_명시한_지표뿐이다(self):
        """브리프가 "없음"이라 명시한 지표에 formula를 넣지 않았는지 —
        지표별로 계산식·조건이 실제로 있는 것만 formula를 단다."""
        has_formula = {
            "mezzanine": {
                "overhang", "pct_at_strike", "pct_at_floor", "refix_floor",
            },
            "dilution": {"dilutive"},
            "financial": {"capital_impairment", "debt_ratio", "current_ratio"},
            "fund_usage": set(),
            "insider": {"short_accumulation"},
            "audit": set(),
            "overview": {"amend_rate"},
        }
        for panel, keys in has_formula.items():
            for key in keys:
                self.assertIn(
                    "formula", METRIC_PROSE[panel][key],
                    f"{panel}.{key}에 formula가 있어야 한다",
                )
            for key in _REQUIRED_PANEL_KEYS[panel] - keys:
                self.assertNotIn(
                    "formula", METRIC_PROSE[panel][key],
                    f"{panel}.{key}에는 formula가 없어야 한다(브리프: 없음)",
                )


class TestNoVerdictVocabulary(unittest.TestCase):
    def test_판정_어휘가_없다(self):
        for panel, entries in METRIC_PROSE.items():
            for key, entry in entries.items():
                text = " ".join(entry.values())
                for banned in _BANNED_VERDICT_WORDS:
                    self.assertNotIn(
                        banned, text,
                        f"{panel}.{key}에 판정 어휘 {banned!r}가 있다: {text!r}",
                    )

    def test_좋다_나쁘다로_회사를_평가하지_않는다(self):
        """브리프: 「좋다/나쁘다」로 회사를 평가하는 문장 금지 — 방향의
        뜻만 설명한다(예: "부채 부담이 줄었다" O, "재무가 좋아졌다" X)."""
        for panel, entries in METRIC_PROSE.items():
            for key, entry in entries.items():
                text = " ".join(entry.values())
                self.assertNotIn(
                    "좋다", text, f"{panel}.{key}에 '좋다'로 평가하는 문장이 있다"
                )
                self.assertNotIn(
                    "나쁘다", text,
                    f"{panel}.{key}에 '나쁘다'로 평가하는 문장이 있다",
                )

    def test_caveat에_높을수록_좋_낮을수록_좋이_없다(self):
        for panel, entries in METRIC_PROSE.items():
            for key, entry in entries.items():
                caveat = entry["caveat"]
                self.assertNotIn("높을수록 좋", caveat, f"{panel}.{key}")
                self.assertNotIn("낮을수록 좋", caveat, f"{panel}.{key}")

    def test_hygiene_score_grade_patterns가_없다(self):
        from tests.test_golden_output_hygiene import _SCORE_GRADE_PATTERNS

        for panel, entries in METRIC_PROSE.items():
            for key, entry in entries.items():
                text = " ".join(entry.values())
                for pattern, desc in _SCORE_GRADE_PATTERNS:
                    self.assertIsNone(
                        re.search(pattern, text),
                        f"{panel}.{key}가 hygiene 패턴({desc})에 걸린다: {text!r}",
                    )

    def test_hygiene_severity_emoji가_없다(self):
        from tests.test_golden_output_hygiene import _SEVERITY_EMOJI

        for panel, entries in METRIC_PROSE.items():
            for key, entry in entries.items():
                text = " ".join(entry.values())
                for emoji in _SEVERITY_EMOJI:
                    self.assertNotIn(
                        emoji, text,
                        f"{panel}.{key}에 등급 이모지 {emoji!r}가 있다",
                    )


class TestExportWiring(unittest.TestCase):
    """export_tool_data.py가 METRIC_PROSE를 그대로 내보내는지 — 문구
    복제 금지(CLAUDE.md의 _FS_ALIAS_KEYS·turnover_prose·glossary와 같은
    이유)."""

    def test_build_signals_data가_core와_완전히_같은_metric_prose를_낸다(self):
        from export_tool_data import build_signals_data  # noqa: E402

        data = build_signals_data()
        self.assertIn("metric_prose", data)
        exported = data["metric_prose"]
        core_as_plain = {
            panel: {k: dict(v) for k, v in entries.items()}
            for panel, entries in METRIC_PROSE.items()
        }
        self.assertEqual(exported, core_as_plain)

    def test_배포된_signals_data_json이_core와_완전히_같다(self):
        """빌드 함수만 맞고 커밋된 산출물이 낡아 있으면(재생성 누락)
        뷰어는 여전히 옛(또는 없는) 문구를 보게 된다 — 파일 자체를
        대조한다."""
        json_path = _ROOT / "docs" / "tool" / "signals-data.json"
        self.assertTrue(json_path.exists(), "signals-data.json이 없다")
        data = json.loads(json_path.read_text(encoding="utf-8"))
        self.assertIn(
            "metric_prose", data,
            "signals-data.json에 metric_prose가 없다 — "
            "scripts/export_tool_data.py 재실행 필요",
        )
        exported = data["metric_prose"]
        core_as_plain = {
            panel: {k: dict(v) for k, v in entries.items()}
            for panel, entries in METRIC_PROSE.items()
        }
        self.assertEqual(
            exported, core_as_plain,
            "signals-data.json의 metric_prose가 core와 다르다 — "
            "python scripts/export_tool_data.py로 재생성해야 한다",
        )

    def test_score_severity_confidence를_내보내지_않는다(self):
        for panel, entries in METRIC_PROSE.items():
            for key, entry in entries.items():
                for forbidden in ("score", "severity", "confidence", "base_score"):
                    self.assertNotIn(forbidden, entry)


class TestNotWiredIntoMCP(unittest.TestCase):
    """METRIC_PROSE는 MCP 도구 출력(server.py)에는 붙지 않는다.

    뷰어는 접힌 `<details>`라 전부 담아도 방해가 없지만, MCP의 원문 블록
    (메자닌 오버행, 주식 수 변동, scan_financial_anomaly 등)은 이미 그
    자리에서 사실과 한계를 풀어 적고 있다 — 같은 뜻을 접힌 사전으로 한 번
    더 붙이면 대화 컨텍스트를 먹는 출력 분량만 늘어난다.
    `TURNOVER_PROSE`가 "값이 나온 지표만" 붙이는 절충안을 쓴 것과는 다른,
    이 사전에 한정된 결정이다.
    """

    def test_server_py에_METRIC_PROSE가_등장하지_않는다(self):
        src = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
        self.assertNotIn(
            "METRIC_PROSE", src,
            "server.py가 METRIC_PROSE를 참조한다 — 이 과제는 데이터·export·"
            "테스트만이고 MCP 배선은 범위 밖이다(뷰어 렌더도 다음 과제)",
        )


if __name__ == "__main__":
    unittest.main()
