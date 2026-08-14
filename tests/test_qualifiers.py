# -*- coding: utf-8 -*-
"""신호 한정층 단위 테스트 — 전부 실측 공시 제목을 케이스로 쓴다."""
from dart_risk_mcp.core.qualifiers import ParsedName, parse_report_name


def test_parse_splits_tag_body_subtitle():
    p = parse_report_name("[첨부정정]유상증자결정(종속회사의주요경영사항)")
    assert p.tags == ("첨부정정",)
    assert p.body == "유상증자결정"
    assert p.subtitles == ("종속회사의주요경영사항",)
    assert p.tail == "결정"


def test_parse_strips_whitespace_inside_subtitle():
    # 실측: '자회사의 주요경영사항'(공백 있음)과 '종속회사의주요경영사항'이 공존
    p = parse_report_name("유상증자결정 (자회사의 주요경영사항)")
    assert p.subtitles == ("자회사의주요경영사항",)


def test_parse_tail_prefers_longest_suffix():
    # '결과보고서'가 '보고서'보다 길어 우선한다
    assert parse_report_name("자기주식취득결과보고서").tail == "결과보고서"


def test_parse_tail_of_wrapper_uses_last_subtitle():
    # '주요사항보고서(...)'는 껍데기 — 실제 행위는 괄호 안에 있다
    assert parse_report_name("주요사항보고서(자기주식취득결정)").tail == "결정"


def test_parse_tail_keeps_body_tail_when_subtitle_has_none():
    p = parse_report_name("주식등의대량보유상황보고서(일반)")
    assert p.body == "주식등의대량보유상황보고서"
    assert p.tail == "보고서"


def test_parse_handles_middle_dot_variant():
    # 'ㆍ'(U+318D)는 DART 실제 표기 — 제거하지 않고 그대로 매칭한다
    p = parse_report_name("최대주주변경을수반하는주식담보제공계약해제ㆍ취소등")
    assert p.tail == "해제ㆍ취소등"


def test_parse_multiple_tags():
    p = parse_report_name("[기재정정][첨부추가]주요사항보고서(전환사채권발행결정)")
    assert p.tags == ("기재정정", "첨부추가")


def test_parse_empty_is_safe():
    p = parse_report_name("")
    assert p == ParsedName(tags=(), body="", subtitles=(), tail="", compact="")


from dart_risk_mcp.core.qualifiers import (  # noqa: E402
    TIER_OBSERVED,
    TIER_PROCEDURAL,
    is_false_amendment,
    qualify_signals,
)

SHAREHOLDER = {"key": "SHAREHOLDER", "label": "최대주주변경"}
TREASURY = {"key": "TREASURY", "label": "자사주매입/처분"}
PCA3 = {"key": "3PCA", "label": "제3자배정유상증자"}
INQUIRY = {"key": "INQUIRY", "label": "조회공시"}
CB_BW = {"key": "CB_BW", "label": "CB/BW발행"}


def _one(report_nm, signals, filing=None):
    """제목 하나를 파싱해 한정한 결과의 첫 항목."""
    return qualify_signals(signals, parse_report_name(report_nm), filing)[0]


# ── R1: 제출인이 회사가 아니면 강등 ──────────────────────────
def test_r1_demotes_when_filer_is_not_the_company():
    q = _one(
        "주식등의대량보유상황보고서(일반)", [SHAREHOLDER],
        {"corp_name": "삼성전자", "flr_nm": "국민연금공단"},
    )
    assert q.tier == TIER_PROCEDURAL
    assert "국민연금공단" in q.reason


def test_r1_keeps_when_filer_is_the_company_despite_suffix_diff():
    # ㈜·(주)·주식회사 표기차는 흡수한다
    q = _one(
        "최대주주변경", [SHAREHOLDER],
        {"corp_name": "아틀라스링크", "flr_nm": "주식회사 아틀라스링크"},
    )
    assert q.tier == TIER_OBSERVED


# ── R1b: 지분 보유·변동 신고서 (filer 유무 무관) ──────────────
def test_r1b_demotes_third_party_report_without_filer_field():
    q = _one("주식등의대량보유상황보고서(약식)", [SHAREHOLDER], None)
    assert q.tier == TIER_PROCEDURAL
    assert "지분" in q.reason


def test_r1b_demotes_insider_holding_report():
    q = _one("임원ㆍ주요주주특정증권등소유상황보고서", [SHAREHOLDER], None)
    assert q.tier == TIER_PROCEDURAL


def test_r1b_demotes_company_filed_ownership_report():
    """라이브 실측 — '최대주주등소유주식변동신고서'는 회사가 직접 낸다.

    flr_nm == corp_name이라 R1으로는 걸리지 않는다. 그래도 회사가 한 일이
    아니라 지분 현황의 정례 보고이므로 R1b가 filer 유무와 무관하게 잡아야
    한다. filer 가드를 두면 이 규칙이 실환경에서 죽는다.
    """
    q = _one(
        "최대주주등소유주식변동신고서", [SHAREHOLDER],
        {"corp_name": "삼성전자", "flr_nm": "삼성전자"},
    )
    assert q.tier == TIER_PROCEDURAL


def test_r1_reason_wins_over_r1b_when_filer_differs():
    """둘 다 해당하면 제출인을 명시하는 R1 사유가 더 구체적이라 우선한다."""
    q = _one(
        "주식등의대량보유상황보고서(일반)", [SHAREHOLDER],
        {"corp_name": "삼성전자", "flr_nm": "삼성물산"},
    )
    assert "삼성물산" in q.reason


# ── R2: 사후·해제 국면 ───────────────────────────────────────
def test_r2_demotes_result_report():
    q = _one("자기주식취득결과보고서", [TREASURY])
    assert q.tier == TIER_PROCEDURAL
    assert "결과" in q.reason


def test_r2_demotes_cancellation():
    q = _one("최대주주변경을수반하는주식담보제공계약해제ㆍ취소등", [SHAREHOLDER])
    assert q.tier == TIER_PROCEDURAL


def test_r2_keeps_trust_termination_decision():
    """과잉 강등 방지 — '해지'가 들어있어도 '결정'으로 끝나면 새 결정이다."""
    q = _one("주요사항보고서(자기주식취득신탁계약해지결정)", [TREASURY])
    assert q.tier == TIER_OBSERVED


# ── R3: 자회사·특수관계인 사안 ───────────────────────────────
def test_r3_demotes_subsidiary_matter():
    q = _one("유상증자결정(종속회사의주요경영사항)", [PCA3])
    assert q.tier == TIER_PROCEDURAL
    assert "자회사" in q.reason


def test_r3_demotes_related_party_participation():
    q = _one("특수관계인의유상증자참여", [PCA3])
    assert q.tier == TIER_PROCEDURAL


# ── R4: 해명·미확정 ─────────────────────────────────────────
def test_r4_demotes_company_denial():
    q = _one("풍문또는보도에대한해명(미확정)", [INQUIRY])
    assert q.tier == TIER_PROCEDURAL


def test_r4_keeps_exchange_inquiry_request():
    """과잉 강등 방지 — 거래소가 요구한 조회공시는 남는다."""
    q = _one("조회공시요구(풍문또는보도)(감사의견비적정설)", [INQUIRY])
    assert q.tier == TIER_OBSERVED


# ── R5: 정정·후속 꼬리표 ─────────────────────────────────────
def test_r5_demotes_attachment_amendment():
    q = _one("[첨부정정]주요사항보고서(유상증자결정)", [PCA3])
    assert q.tier == TIER_PROCEDURAL
    assert "첨부정정" in q.reason


def test_r5_demotes_issue_terms_confirmation():
    q = _one("[발행조건확정]주요사항보고서(전환사채권발행결정)", [CB_BW])
    assert q.tier == TIER_PROCEDURAL


def test_false_amendment_detects_regulatory_order():
    """[정정명령부과]는 정정공시가 아니라 규제기관 조치다."""
    assert is_false_amendment(parse_report_name("[정정명령부과]증권신고서")) is True
    assert is_false_amendment(parse_report_name("[기재정정]유상증자결정")) is False
    assert is_false_amendment(parse_report_name("유상증자결정")) is False


def test_r5_keeps_regulatory_order():
    q = _one("[정정명령부과]증권신고서", [CB_BW])
    assert q.tier == TIER_OBSERVED


# ── 우선순위: R5가 R2·R3보다 먼저 ────────────────────────────
def test_amendment_tag_wins_over_other_rules():
    q = _one("[기재정정]자기주식취득결과보고서", [TREASURY])
    assert "기재정정" in q.reason


# ── 문제 기업 신호 보존 (회귀 방지) ──────────────────────────
def test_problem_company_signals_survive():
    kept = [
        "최대주주변경",
        "최대주주변경을수반하는주식양수도계약체결",
        "금전대여결정",
        "타인에대한채무보증결정(자율공시)",
        "주요사항보고서(유형자산양수결정)",
        "주요사항보고서(전환사채권발행결정)",
        "주식병합결정",
        "회생절차개시결정",
        "주요사항보고서(회생절차개시신청)",
        "자본잠식50%이상또는매출액50억원미만사실발생",
        "타인에대한담보제공결정",
        "소송등의제기ㆍ신청(경영권분쟁소송)(주주총회소집허가)",
    ]
    for nm in kept:
        q = _one(nm, [SHAREHOLDER])
        assert q.tier == TIER_OBSERVED, f"{nm} 이 잘못 강등됨: {q.reason}"


# ── 안전성 ──────────────────────────────────────────────────
def test_empty_signals_returns_empty():
    assert qualify_signals([], parse_report_name("아무거나"), None) == []


def test_missing_filing_keys_do_not_raise():
    q = _one("최대주주변경", [SHAREHOLDER], {})
    assert q.tier == TIER_OBSERVED


# ── 라벨 보정 ───────────────────────────────────────────────
def test_label_softened_when_allocation_method_absent():
    """제목에 '제3자배정'이 없으면 그렇게 단정하지 않는다."""
    q = _one("주요사항보고서(유상증자결정)", [PCA3])
    assert q.label == "유상증자(배정방식 미상)"
    assert q.tier == TIER_OBSERVED


def test_label_kept_when_allocation_method_stated():
    q = _one("증권발행결과(자율공시)(제3자배정 유상증자)", [PCA3])
    assert q.label == "제3자배정유상증자"


def test_label_override_only_applies_to_3pca():
    q = _one("주요사항보고서(유상증자결정)", [CB_BW])
    assert q.label == "CB/BW발행"


# ── 사실 주석 ───────────────────────────────────────────────
def test_note_added_when_direction_is_reversed():
    q = _one("전환사채(해외전환사채포함)발행후만기전사채취득(제3회차)", [CB_BW])
    assert "취득" in q.note
    assert q.tier == TIER_OBSERVED   # 주석만 붙이고 강등하지 않는다


def test_note_added_for_bond_sale_decision():
    q = _one("주요사항보고서(자기전환사채매도결정)", [CB_BW])
    assert q.note != ""


def test_no_note_for_plain_issuance():
    q = _one("주요사항보고서(전환사채권발행결정)", [CB_BW])
    assert q.note == ""
