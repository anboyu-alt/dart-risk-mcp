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
    "LOAN_ADVANCE_SURGE",
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
    # "종합 스코어"만 막았더니 「※ 본 **스코어**는 …」가 통과해 10개 골든에
    # 실제로 노출돼 있었다(2026-08-23 발견). v0.8.5에서 계산은 제거했는데
    # 문구가 남은 잔재였다. "스코어"는 이 도구 출력에 정상 용법이 없으므로
    # 낱말 자체를 막는다 — 반면 "점수"는 「점수 금지 원칙」처럼 원칙을 밝히는
    # 문장에 쓰이므로 아래 'N점' 형식만 막는다.
    (r"스코어", "'스코어' 표현 (점수 어휘)"),
    (r"종합\s*위험도", "'종합 위험도' 라벨"),
    (r"매우위험|고위험|중위험|저위험", "위험 등급 명칭"),
]
# 위상/위험도를 시각적으로 등급화하던 이모지 세트(v0.8.5에서 전면 제거)
_SEVERITY_EMOJI = ["🔴", "🟠", "🟡", "🟢", "🔵"]

# ────────────────────────────────────────────────────────────────────────────
# v1.0 stable output contract — 출력 표준 계약 검증 3종
# ────────────────────────────────────────────────────────────────────────────

# 도구 단축명 → 첫 줄 정규식 (24종, 6 회사 × 도구 매트릭스의 모든 첫 줄 + 회사 무관 4종)
_FIRST_LINE_PATTERNS: dict[str, str] = {
    # 회사명 단일 인자 14개
    "affiliates":    r"^🏢 \*\*.+\*\* \(\d{6}\) — 타법인 출자현황 \(\d{4}(?: 사업보고서 기준)?\)$",
    "analyze":       r"^📋 \*\*기업 공시 관찰 요약: .+\*\*$",
    "anomaly":       r"^━━━ \[.+\] 공시 구조 관찰 요약 ━━━$",
    "audit_history": r"^📋 \*\*.+\*\* \(\d{6}\) — 감사의견 이력 \(최근 \d+년\)$",
    "capital":       r"^📊 \*\*.+\*\* \(\d{6}\) — 자본구조 추적 \(최근 \d+년\)$",
    "company_info":  r"^🏢 \*\*기업 개요: .+\*\*$",
    "debt_balance":  r"^💰 \*\*.+\*\* \(\d{6}\) — 미상환 채무증권 잔액 \(\d{4}년\)$",
    "exec_comp":     r"^━━━ \[.+\] 임원 보수 현황 \(\d{4}년 \w+\) ━━━$",
    "fs":            r"^📊 \*\*.+\*\*",
    "fund_usage":    r"^💰 \*\*.+\*\* 조달자금 사용내역 \(lookback=\d+년\)$",
    "insider":       r"^━━━ \[.+\] 임원·대주주 지분 변동 시계열 \(최근 \d+년\) ━━━$",
    "scan_fs":       r"^📊 \*\*.+\*\* \(\d{6}\) — 재무 이상 스캔 \(\d{4}, \w+\)$",
    # 기준 사업연도를 붙였다(2026-08-30) — 기말 잔고는 연도마다 크게 달라져
    # 시점을 말하지 않으면 읽는 사람이 알 수 없다.
    "shareholder":   r"^👥 \*\*주주 현황: .+\*\* \(\d{6}\) — \d{4} 사업연도 보고 기준$",
    "timeline":      r"^⏳ \*\*이벤트 타임라인: .+\*\* \(\d{6}\)$",
    "turnover":      r"^📊 \*\*.+\*\* \(\d{6}\) — 회전율 추세 \(\d+년\)$",
    # v1.23.0~v1.26.0 도구 — 2026-09-12까지 골드 매트릭스에 **없었다**
    # (그래서 이 검사가 그 출력을 한 번도 보지 않았다).
    # ⚠ 자료를 못 찾은 경우(🔎)도 유효한 출력이라 두 갈래를 함께 받는다 —
    #   감사보고서·사업보고서는 제출 시점에 매여 회사·연도마다 갈린다.
    "fsfull":        r"^(?:📒 \*\*.+ 전체 계정 재무제표\*\* \(\d{6}\)"
                     r"|🔎 \*\*.+\*\* \(\d{6}\) — .+ 찾지 못했습니다\.)$",
    "revisions":     r"^🗂 \*\*.+\*\* \(\d{6}\) — \d{4} 사업연도 .+ 판본$",
    # rcept 유형이 정해진 둘 + 비상장 전용 하나(2026-09-12에 마저 메웠다).
    # ⚠ `mezz`는 **실패 출력도 유효**하다 — DS005 구조화 조회가 빈 결과를
    #   내는 접수가 실재한다(실측 오르비텍, CLAUDE.md 「부가 발견 2」).
    "notes":         r"^🔎 \*\*\d+\*\* 주석 검색 — ",
    "mezz":          r"^(?:💠 \*\*.+\*\* — .+|❌ .+)$",
    # 비상장은 종목코드가 없어 괄호 안이 corp_code 8자리다.
    "unlisted":      r"^🏢 \*\*.+\*\* \(\d{8}\) — .+$",
    "audit_text":    r"^(?:🧾 \*\*.+\*\* \(\d{6}\) — \d{4} 사업연도 .*감사보고서"
                     r"|🔎 \*\*.+\*\* \(\d{6}\) — .+ 찾지 못했습니다\.)$",
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
    # DS005 주요결정 (자동 탐지, v1.6.0부터 decision_type 정상 해석 — 첫 골드)
    "decision":      r"^📑 \*\*주요사항 결정 공시\*\* \(rcept_no=\d+\)$",
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
    # 임원 직위 — 2026-08-23 추가. find_actor_overlap이 겸직 임원의 직위를
    # 사실로 병기하면서(동명이인을 눈으로 가릴 수 있게) DART 임원현황의
    # `ofcps` 원문 표기가 처음 골든에 들어왔다: 「상무(CSO)/사내이사」·
    # 「사장(CTO)/사내이사」. 내부 flag 코드가 아니라 회사가 적어 낸 직위다.
    # 실측에 나온 두 개만 넣는다 — 안 본 약어를 미리 넣으면 이 검사가
    # 막으려는 것(우리가 만든 라벨에 코드가 새는 것)을 못 잡는다.
    "CSO", "CTO",
    # 재무제표 구분 — 2026-09-12 추가. `get_financial_statements_full`을 이
    # 검사의 코퍼스에 넣자 바로 걸렸다(STX_fsfull.txt의 「연결(CFS)」).
    # ⚠ 이것들은 **사용자가 넣는 인자 값**이다 — `fs_div="CFS"`·
    #   `statement="BS"`처럼 그대로 호출에 쓰므로 화면에 있어야 무엇을 넣을지
    #   안다(내부 flag 코드가 새는 것과 다르다). 도구가 실제로 내는 값만
    #   넣는다 — 안 본 약어를 미리 넣으면 이 검사가 무력해진다.
    "CFS", "OFS", "BS", "IS", "CIS", "CF", "SCE",
    # 통화 코드 — 2026-09-12. `search_notes_in_report` 골드(STX)의 주석
    # 인용문에서 나왔고, 우리 화면도 같은 표기를 낸다(`_currency_footer`가
    # 「이 회사는 **USD**로 보고합니다」라 적는다 — 실측 두산밥캣). 내부 코드가
    # 아니라 ISO 통화 표기다. ⚠ 실측에 나온 하나만 넣는다.
    "USD",
    # 정부·기관
    "MFDS", "FSC", "FSS", "SEC", "NICE", "KFTC", "KRX",
    # 회계 표준 지표
    # OCI: 2026-08-17 추가. 카탈로그 발췌가 '위험 신호' 섹션까지 노출하게 되면서
    # taxonomy 1.6의 한글 라벨 "기타포괄손익(OCI) 처리가 아니라…"가 처음 골든에
    # 등장했다. 내부 flag 코드가 아니라 한글 용어에 병기된 표준 회계 약어라
    # RCPS·IFRS와 같은 부류로 허용한다.
    "ROE", "ROA", "EPS", "EBITDA", "EBIT", "EV", "FCF", "OCI",
    # CCC(현금전환주기): 2026-08-28 track_turnover_trend 추가 — 내부 flag 코드가
    # 아니라 회계·재무 문헌에서 널리 쓰는 표준 지표 약어(DSO+DIO-DPO)다.
    "CCC",
    # 기타 산업 표준
    "OECD", "IFRS", "GAAP", "ESG",
    # MOU: 금감원 카탈로그 발췌 본문(허위 MOU 체결로 주가부양한 사례 요약)에
    # 원문 표기 그대로 등장한다. 내부 flag 코드가 아니다.
    "MOU",
}


# 회사명 접두어가 없는 파일명(도구가 여러 회사를 동시에 받거나 회사 무관인 경우).
# v1.9.0 이전에는 "stem[0].isascii()"로 회사 무관 여부를 판별했는데, 이는
# 회사명이 항상 한글이라는 잘못된 전제였다 — STX처럼 ASCII 티커명 회사가
# 추가되자 "STX_analyze"가 "market_"/"precedents_" 접두어 검사를 모두
# 통과해 전체 stem이 그대로 단축명으로 취급돼(미등록 단축명 오류) 회귀 검증이
# 깨졌다. 명시적 멤버십 검사로 교체해 회사명의 문자 종류에 의존하지 않는다.
_COMPANY_AGNOSTIC_STEMS = {"actor_overlap", "compare_fs"}


def _short_name(fname: str) -> str:
    """파일명에서 도구 단축명을 추출."""
    stem = fname[:-4]  # remove .txt
    # 회사 무관 — actor_overlap, compare_fs, market_xxx, precedents_xxx
    for prefix in ("market_", "precedents_"):
        if stem.startswith(prefix):
            return prefix[:-1]  # "market" or "precedents"
    if stem in _COMPANY_AGNOSTIC_STEMS:
        return stem
    # 회사명(한글 또는 ASCII 티커, 예: STX) prefix
    parts = stem.split("_", 1)
    if len(parts) < 2:
        return stem
    rest = parts[1]
    # rcept 도구는 마지막 _NNNNNNNN(8자리 이상) 제거
    rest = re.sub(r"_\d{8,}$", "", rest)
    return rest


def _our_words_only(path) -> str:
    """골드 본문 중 **우리가 쓴 문장만** 남긴다.

    `get_audit_opinion_text`는 감사보고서 문장을 **원문 그대로 인용하는 것이
    목적**인 도구다(v1.25.0). 그 인용문에 우리 어휘 규칙을 걸면 감사인이 쓴 말을
    지우게 된다 — 실측으로 삼성전자 골드의 「Device Solutions**(DS)** 부문」이
    이 파일의 내부 코드 검사에 걸렸고, 같은 이유로 「위험」·「등급」 같은 낱말도
    감사인 문장에서는 정상이다(`tests/test_audit_opinion_text_tool.py`의
    `_our_words`가 같은 판단을 먼저 했다 — 규칙을 여기로 옮겨 **모든** hygiene
    검사에 일관되게 적용한다).

    인용 블록은 `━━` 줄에서 시작해 우리 문장 표지(📎·ℹ️·표·머리글)에서 끝난다.
    """
    text = path.read_text(encoding="utf-8")
    if path.name.endswith("_audit_text.txt"):
        start, stop = ("━━",), ("📎", "ℹ️", "|", "🧾", "🔎", "접수번호", "원문 ")
    elif path.name.endswith("_notes.txt"):
        # `search_notes_in_report`도 **주석 원문을 발췌해 보여주는 것이 목적**인
        # 도구다(v1.23.0). 「── 주석 N.」부터가 발췌이고 표 줄(`|`)이 그 발췌의
        # 일부라, audit_text의 종료 표지를 그대로 쓰면 첫 표에서 인용이 끊긴다.
        # 여기서는 꼬리말(📎)만 우리 말이다 — 실측 STX 골드의 「담보설정금액
        # (USD)」·「(JPY)」가 이 검사에 걸렸는데, 회사가 낸 표의 통화 표기다.
        start, stop = ("──",), ("📎",)
    else:
        return text
    keep, inside = [], False
    for ln in text.splitlines():
        if ln.startswith(start):
            inside = True
            continue
        if ln.startswith(stop):
            inside = False
        if not inside:
            keep.append(ln)
    return "\n".join(keep)


class TestGoldenOutputHygiene(unittest.TestCase):
    def _iter_fixtures(self) -> list[Path]:
        return sorted(FIXTURES.glob("*.txt"))

    def test_no_internal_flag_codes(self) -> None:
        for path in self._iter_fixtures():
            text = _our_words_only(path)
            for code in _INTERNAL_CODES:
                self.assertNotIn(
                    code, text, f"{path.name}에 내부 flag 코드 '{code}' 노출"
                )

    def test_no_catalog_english_metadata(self) -> None:
        for path in self._iter_fixtures():
            text = _our_words_only(path)
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
            text = _our_words_only(path)
            for abbr in _ABBREV:
                self.assertNotIn(
                    abbr, text, f"{path.name}에 영문 약어 '{abbr.strip()}' 노출"
                )

    def test_no_score_or_grade_labels(self) -> None:
        """v0.8.5: 기업 위험도를 정량화하는 점수·등급 표기가 사용자 출력에 노출되면 안 된다."""
        for path in self._iter_fixtures():
            text = _our_words_only(path)
            for pattern, desc in _SCORE_GRADE_PATTERNS:
                self.assertFalse(
                    re.search(pattern, text),
                    f"{path.name}에 {desc} 노출",
                )

    def test_no_severity_emoji(self) -> None:
        """v0.8.5: 위상·위험도를 시각적으로 등급화하던 이모지 전면 금지."""
        for path in self._iter_fixtures():
            text = _our_words_only(path)
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
            _our_words_only(p) for p in self._iter_fixtures()
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

        단, `*_list.txt`(공시 목록)·`*_doc_*`(공시 원문)은 DART의 공시 제목·원문을
        그대로 옮긴 passthrough라 이 검사 대상이 아니다. 본 검사의 취지는 *우리가
        생성한 라벨*에 내부 flag 코드가 새는 것을 막는 것이고, 원문에 등장하는 실제
        규제기관·표준 약어(FDA·EMA 등)는 false-positive다.
        """
        pat = re.compile(r"\(([A-Z][A-Z_]{1,30})\)")
        for path in self._iter_fixtures():
            # `_view_`도 `_doc_`과 같은 원문 passthrough다(view_disclosure는
            # DART 원문을 페이지 단위로 그대로 옮긴다). 실측: 삼성전자 반기보고서
            # 원문의 "Samsung Semiconductor Asia Holdings Pte. Ltd. (SSAH)".
            if (path.name.endswith("_list.txt")
                    or "_doc_" in path.name
                    or "_view_" in path.name):
                continue
            text = _our_words_only(path)
            for m in pat.finditer(text):
                code = m.group(1)
                self.assertIn(
                    code, _ALLOWED_PAREN_ABBREVS,
                    f"{path.name}에 미등록 영문 코드 괄호 인용 ({code}) 노출 — "
                    "_ALLOWED_PAREN_ABBREVS 검토 또는 한국어 라벨로 교체",
                )


if __name__ == "__main__":
    unittest.main()
