"""v0.7.4 / v0.8.5 / v1.0 — 골드 출력에 대한 stable contract 회귀 검증.

실 API 호출 없이 `tests/fixtures/sample_outputs/` 안의 `.txt`만 스캔한다.
렌더러가 내부 키·영문 메타·영문 약어·점수/등급/등급 이모지를 출력 경계 밖으로
흘리거나, 사용자가 학습한 헤더·도구별 첫 줄 형식이 깨지면 실패한다.

검증 9종:
- v0.7.x: 내부 flag 코드 / 카탈로그 영문 메타 / 영문 약어
- v0.8.5: 점수·등급 라벨 / 등급 이모지
- v1.0  : 임계 ≥100 / 도구별 첫 줄 형식 / 핵심 헤더 보존 / 미등록 영문 코드 괄호 인용 차단

재수집 절차: `python scripts/regen_goldens.py` 후 `git diff` 확인.
"""
from __future__ import annotations

import re
import unittest
from pathlib import Path

FIXTURES = Path(__file__).parent / "fixtures" / "sample_outputs"

# 사용자 출력에 절대 노출되면 안 되는 내부 flag 키 (v0.7.1~v0.7.3에서 제거 확정)
_INTERNAL_CODES = [
    "AR_SURGE",
    "INVENTORY_SURGE",
    "CASH_GAP",
    "CAPITAL_IMPAIRMENT",
    "CAPITAL_CHURN",
    "FUND_DIVERSION",
    "FUND_UNREPORTED",
    "DECISION_RELATED_PARTY",
    "DECISION_OVERSIZED",
    "DECISION_NO_EXTVAL",
]
# 카탈로그 MD 원본에 있는 영문 메타 라벨 (v0.7.3 _strip_taxonomy_metadata로 필터링)
_CATALOG_META = [
    "**Severity**",
    "**Base Score**",
    "**Crisis Timeline**",
    "### Red Flags",
]
# v0.7.3에서 한글화된 영문 약어. 공백 포함으로 false-positive(예: 한글 조사 직전의 OCF) 최소화.
_ABBREV = ["OCF "]

# v0.8.5 — 점수·등급·위상 이모지 노출 금지. 기업 위험도를 정량화하지 않는다는 원칙의 기계적 검증.
# 주의: 단순 "점" 글자는 "시점", "관점" 같은 정상 한국어와 충돌하므로 패턴을 좁힌다.
_SCORE_GRADE_PATTERNS = [
    (r"\d+\s*/\s*\d+\s*점", "'N/M점' 형식의 점수 표기"),
    (r"\d+\s*점\s*(?:$|[\s·,\)])", "'N점' 단독 점수 표기"),
    (r"위험\s*등급", "'위험 등급' 라벨"),
    (r"종합\s*스코어", "'종합 스코어' 라벨"),
    (r"종합\s*위험도", "'종합 위험도' 라벨"),
    (r"매우위험|고위험|중위험|저위험", "위험 등급 명칭"),
]
# 위상/위험도를 시각적으로 등급화하던 이모지 세트(v0.8.5에서 전면 제거)
_SEVERITY_EMOJI = ["🔴", "🟠", "🟡", "🟢", "🔵"]

# ────────────────────────────────────────────────────────────────────────────
# v1.0 stable output contract — 출력 표준 계약 검증 3종
# ────────────────────────────────────────────────────────────────────────────

# 도구 단축명 → 첫 줄 정규식 (23종, 6 회사 × 도구 매트릭스의 모든 첫 줄 + 회사 무관 4종)
_FIRST_LINE_PATTERNS: dict[str, str] = {
    # 회사명 단일 인자 13개
    "analyze":       r"^📋 \*\*기업 공시 관찰 요약: .+\*\*$",
    "anomaly":       r"^━━━ \[.+\] 공시 구조 관찰 요약 ━━━$",
    "audit_history": r"^📋 \*\*.+\*\* \(\d{6}\) — 감사의견 이력 \(최근 \d+년\)$",
    "capital":       r"^📊 \*\*.+\*\* \(\d{6}\) — 자본구조 추적 \(최근 \d+년\)$",
    "company_info":  r"^🏢 \*\*기업 개요: .+\*\*$",
    "debt_balance":  r"^💰 \*\*.+\*\* \(\d{6}\) — 채무증권 잔액 \(\d{4}\)$",
    "exec_comp":     r"^━━━ \[.+\] 임원 보수 현황 \(\d{4}년 \w+\) ━━━$",
    "fs":            r"^📊 \*\*.+\*\*",
    "fund_usage":    r"^💰 \*\*.+\*\* 조달자금 사용내역 \(lookback=\d+년\)$",
    "insider":       r"^━━━ \[.+\] 임원·대주주 지분 변동 시계열 \(최근 \d+년\) ━━━$",
    "scan_fs":       r"^📊 \*\*.+\*\* \(\d{6}\) — 재무 이상 스캔 \(\d{4}, \w+\)$",
    "shareholder":   r"^👥 \*\*주주 현황: .+\*\* \(\d{6}\)$",
    "timeline":      r"^⏳ \*\*이벤트 타임라인: .+\*\* \(\d{6}\)$",
    # 종목코드 1개
    "list":          r"^📋 \*\*.+\*\* \(\d{6}\) 공시 접수번호 목록$",
    # rcept 4개
    "doc":           r"^📄 \*\*공시 원문 조회: \d+\*\*$",
    "risk_check":    r"^📋 \*\*공시 리스크 분석\*\*$",
    "sections":      r"^📑 \*\*공시 원문 목차\*\*$",
    "view":          r"^📄 \*\*공시 원문\*\* \(페이지 \d+/\d+\)$",
    # 회사 무관 4종
    "actor_overlap": r"^🔍 \*\*여러 회사를 동시에 드나든 .+\*\*",
    "compare_fs":    r"^📊 \*\*재무 비교\*\* \(\d+개 기업\)$",
    "precedents":    r"^📚 \*\*신호별 해석 — 왜 주목해야 하는지\*\*$",
    "market":        r"^🔍 \*\*시장 공시 스캔\*\* \(preset=[a-z_0-9]+, 최근 \d+일\)$",
    # 기존 단일 disclosure (v0.7.x 골드 — risk_check 이전 명명 잔존)
    "disclosure":    r"^📋 \*\*공시 리스크 분석\*\*$",
}

# 사용자가 학습한 핵심 헤더 8종 — 골드 전체에서 사라지면 contract 깨짐
_CORE_HEADERS = [
    "**시계열**",                                # capital
    "**전년 대비 추세 (DART 재무지표 기준)**",  # scan_fs
    "**공시 원문 목차**",                        # sections
    "**공시 원문**",                             # view
    "**공시 리스크 분석**",                      # risk_check + 기존 disclosure
    "**① 정정공시 비율**",                       # anomaly 5지표
    "**③ 공시의무 위반**",
    "**⑤ 조회공시 빈도**",
]

# v0.8.7 발견 패턴 차단 화이트리스트 — 한국어 본문에 (코드) 형태로 합법 인용되는 영문 약어.
# 이 화이트리스트 외 영문 대문자 코드가 괄호 인용으로 노출되면 fail (예: (CAPITAL_CHURN)).
_ALLOWED_PAREN_ABBREVS = {
    # 채권/우선주
    "CB", "BW", "EB", "RCPS", "BCPS", "CPS",
    # 투자/IR
    "IR", "NDR", "PE", "PEF",
    # 정부·기관
    "MFDS", "FSC", "FSS", "SEC", "NICE", "KFTC", "KRX",
    # 회계 표준 지표
    "ROE", "ROA", "EPS", "EBITDA", "EBIT", "EV",
    # 기타 산업 표준
    "OECD", "IFRS", "GAAP", "ESG",
}


def _short_name(fname: str) -> str:
    """파일명에서 도구 단축명을 추출."""
    stem = fname[:-4]  # remove .txt
    if stem[0].isascii():
        # 회사 무관 — actor_overlap, compare_fs, market_xxx, precedents_xxx
        for prefix in ("market_", "precedents_"):
            if stem.startswith(prefix):
                return prefix[:-1]  # "market" or "precedents"
        return stem  # actor_overlap, compare_fs
    # 한글 회사명 prefix
    parts = stem.split("_", 1)
    if len(parts) < 2:
        return stem
    rest = parts[1]
    # rcept 도구는 마지막 _NNNNNNNN(8자리 이상) 제거
    rest = re.sub(r"_\d{8,}$", "", rest)
    return rest


class TestGoldenOutputHygiene(unittest.TestCase):
    def _iter_fixtures(self) -> list[Path]:
        return sorted(FIXTURES.glob("*.txt"))

    def test_no_internal_flag_codes(self) -> None:
        for path in self._iter_fixtures():
            text = path.read_text(encoding="utf-8")
            for code in _INTERNAL_CODES:
                self.assertNotIn(
                    code, text, f"{path.name}에 내부 flag 코드 '{code}' 노출"
                )

    def test_no_catalog_english_metadata(self) -> None:
        for path in self._iter_fixtures():
            text = path.read_text(encoding="utf-8")
            for token in _CATALOG_META:
                self.assertNotIn(
                    token, text, f"{path.name}에 카탈로그 영문 메타 '{token}' 노출"
                )
            # '## N.M: EnglishTitle' 헤더 라인도 0개여야 함
            self.assertFalse(
                re.search(r"^## \d+\.\d+: [A-Z][^\n]+", text, re.MULTILINE),
                f"{path.name}에 카탈로그 taxonomy 헤더 노출",
            )

    def test_no_english_abbreviations(self) -> None:
        for path in self._iter_fixtures():
            text = path.read_text(encoding="utf-8")
            for abbr in _ABBREV:
                self.assertNotIn(
                    abbr, text, f"{path.name}에 영문 약어 '{abbr.strip()}' 노출"
                )

    def test_no_score_or_grade_labels(self) -> None:
        """v0.8.5: 기업 위험도를 정량화하는 점수·등급 표기가 사용자 출력에 노출되면 안 된다."""
        for path in self._iter_fixtures():
            text = path.read_text(encoding="utf-8")
            for pattern, desc in _SCORE_GRADE_PATTERNS:
                self.assertFalse(
                    re.search(pattern, text),
                    f"{path.name}에 {desc} 노출",
                )

    def test_no_severity_emoji(self) -> None:
        """v0.8.5: 위상·위험도를 시각적으로 등급화하던 이모지 전면 금지."""
        for path in self._iter_fixtures():
            text = path.read_text(encoding="utf-8")
            for emoji in _SEVERITY_EMOJI:
                self.assertNotIn(
                    emoji, text, f"{path.name}에 등급 이모지 '{emoji}' 노출"
                )

    def test_fixture_set_non_empty(self) -> None:
        """v1.0: 골드 다양화 임계를 100개로 상향 (6 회사 × 23 도구 매트릭스 충족)."""
        files = self._iter_fixtures()
        self.assertGreaterEqual(
            len(files), 100,
            f"골드 파일이 100개 미만({len(files)}개) — v1.0 GA 기준 미달. "
            "scripts/regen_goldens.py로 재수집 필요",
        )
        for p in files:
            self.assertGreater(
                p.stat().st_size, 100, f"{p.name}이 100바이트 미만 — 빈 응답일 가능성"
            )

    def test_first_line_format_per_tool(self) -> None:
        """v1.0: 도구별 첫 줄 형식이 stable contract — 23개 단축명별 정규식 매핑."""
        unmatched: list[str] = []
        for path in self._iter_fixtures():
            short = _short_name(path.name)
            pat = _FIRST_LINE_PATTERNS.get(short)
            if pat is None:
                unmatched.append(f"{path.name} (단축명={short})")
                continue
            first = path.read_text(encoding="utf-8").splitlines()[0]
            self.assertRegex(
                first, pat,
                f"{path.name} 첫 줄 형식 깨짐 (단축명={short}): {first!r}",
            )
        self.assertFalse(
            unmatched,
            f"_FIRST_LINE_PATTERNS에 등록되지 않은 골드 파일: {unmatched}",
        )

    def test_core_headers_preserved(self) -> None:
        """v1.0: 사용자가 학습한 핵심 헤더 8종이 골드 전체에서 살아 있어야 한다."""
        all_text = "\n".join(
            p.read_text(encoding="utf-8") for p in self._iter_fixtures()
        )
        for header in _CORE_HEADERS:
            self.assertIn(
                header, all_text,
                f"핵심 헤더 '{header}' 가 골드 전체에서 사라짐 — 렌더러 회귀 의심",
            )

    def test_no_unknown_internal_code_parens(self) -> None:
        """v1.0: v0.8.7 발견 — `(CAPITAL_CHURN)` 등 내부 flag 코드 괄호 인용 회귀 차단.

        화이트리스트(_ALLOWED_PAREN_ABBREVS)에 등록된 표준 영문 약어는 허용한다.
        새 영문 코드를 정상 출력하려는 경우 화이트리스트에 추가하거나 한국어 라벨로 교체.
        """
        pat = re.compile(r"\(([A-Z][A-Z_]{1,30})\)")
        for path in self._iter_fixtures():
            text = path.read_text(encoding="utf-8")
            for m in pat.finditer(text):
                code = m.group(1)
                self.assertIn(
                    code, _ALLOWED_PAREN_ABBREVS,
                    f"{path.name}에 미등록 영문 코드 괄호 인용 ({code}) 노출 — "
                    "_ALLOWED_PAREN_ABBREVS 검토 또는 한국어 라벨로 교체",
                )


if __name__ == "__main__":
    unittest.main()
