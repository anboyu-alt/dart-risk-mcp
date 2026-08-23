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
DISCLOSURE_VIOL = {"key": "DISCLOSURE_VIOL", "label": "공시의무위반"}
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


def test_r3_keeps_related_party_participation():
    """「특수관계인의유상증자참여」는 강등하지 않는다 (2026-08-23 정정).

    옛 테스트는 이 제목을 R3로 강등하는 동작을 고정하고 있었다. 원문 13건을
    전수로 열어 보니 뜻이 반대였다 — 특수관계인이 한 일이 아니라 **이 회사가
    유상증자를 했고 그 신주를 계열회사가 인수한 건**이다(참여자 관계
    계열회사 13/13, 공정거래법 제26조 13/13).

    같은 법의 형제 공시(자금차입·자금대여·출자·받은담보·담보제공)는 전부
    관찰이라 이것만 강등하는 것도 어긋났다.
    """
    q = _one("특수관계인의유상증자참여", [PCA3])
    assert q.tier == TIER_OBSERVED
    assert not q.reason


# ── R4: 해명·미확정 ─────────────────────────────────────────
def test_r4_demotes_company_denial():
    q = _one("풍문또는보도에대한해명(미확정)", [INQUIRY])
    assert q.tier == TIER_PROCEDURAL


def test_r4_keeps_exchange_inquiry_request():
    """과잉 강등 방지 — 거래소가 요구한 조회공시는 남는다.

    filing을 반드시 함께 넘긴다. 실환경(/list.json)에서는 flr_nm이 항상
    채워져 오고 거래소 공시면 그 값이 시장본부라, filing=None으로 두면
    R1을 통과하는 프로덕션 경로를 전혀 검증하지 못한다(리뷰 C1).
    실측 근거: 조회공시요구(현저한시황변동) / 금호전기 / 유가증권시장본부
    (20260813801194).
    """
    q = _one(
        "조회공시요구(풍문또는보도)(감사의견비적정설)", [INQUIRY],
        {"corp_name": "제이스코홀딩스", "flr_nm": "코스닥시장본부"},
    )
    assert q.tier == TIER_OBSERVED
    assert q.reason == ""


def test_r1_keeps_exchange_filed_disclosure_violation():
    """불성실공시법인지정 — 실측: 스코넥 / 코스닥시장본부 (20260812900993)."""
    q = _one(
        "불성실공시법인지정(공시번복)", [DISCLOSURE_VIOL],
        {"corp_name": "스코넥", "flr_nm": "코스닥시장본부"},
    )
    assert q.tier == TIER_OBSERVED


def test_r1_keeps_exchange_filed_trading_halt():
    """주권매매거래정지 — 실측: 에이비온 / 코스닥시장본부 (20260814901573)."""
    q = _one(
        "주권매매거래정지(조회공시답변)", [INQUIRY],
        {"corp_name": "에이비온", "flr_nm": "코스닥시장본부"},
    )
    assert q.tier == TIER_OBSERVED


def test_r1_keeps_kospi_bureau_filer():
    """유가증권시장본부 — 실측: 금호전기 / 20260813801194."""
    q = _one(
        "조회공시요구(현저한시황변동)", [INQUIRY],
        {"corp_name": "금호전기", "flr_nm": "유가증권시장본부"},
    )
    assert q.tier == TIER_OBSERVED


def test_r1_keeps_konex_bureau_filer():
    """코넥스만 '본부'가 붙지 않는다 — 실측: 퓨쳐메디신 / 코넥스시장
    (20260812600521). '시장본부'로 거르면 이 건이 통째로 사라진다."""
    q = _one(
        "주권매매거래정지(지정자문인선임계약해지)", [INQUIRY],
        {"corp_name": "퓨쳐메디신", "flr_nm": "코넥스시장"},
    )
    assert q.tier == TIER_OBSERVED


def test_r1_still_demotes_non_exchange_third_party_filer():
    """거래소 예외가 R1 자체를 무력화하지 않는다."""
    q = _one(
        "주식등의대량보유상황보고서(일반)", [SHAREHOLDER],
        {"corp_name": "삼성전자", "flr_nm": "국민연금공단"},
    )
    assert q.tier == TIER_PROCEDURAL


def test_exchange_filer_exception_does_not_bypass_other_rules():
    """거래소 제출이어도 R5(정정 꼬리표)는 그대로 강등한다 — 실측:
    '[기재정정]불성실공시법인지정예고(공시불이행)' 형태가 존재한다."""
    q = _one(
        "[기재정정]불성실공시법인지정예고(공시불이행)", [DISCLOSURE_VIOL],
        {"corp_name": "스코넥", "flr_nm": "코스닥시장본부"},
    )
    assert q.tier == TIER_PROCEDURAL
    assert "기재정정" in q.reason


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


from dart_risk_mcp.core.qualifiers import pick_headline  # noqa: E402
from dart_risk_mcp.core.signals import (  # noqa: E402
    AMBIGUOUS_SIGNAL_KEYS,
    SIGNAL_TYPES,
)

_ORDER = [s["key"] for s in sorted(SIGNAL_TYPES, key=lambda x: -x["score"])]


def _q(key, label, tier=TIER_OBSERVED):
    from dart_risk_mcp.core.qualifiers import Qualified
    return Qualified(key=key, label=label, tier=tier, reason="", note="")


def test_ambiguous_keys_are_all_real_signal_keys():
    known = {s["key"] for s in SIGNAL_TYPES}
    assert AMBIGUOUS_SIGNAL_KEYS <= known


def test_ambiguous_keys_contents():
    # ASSET_TRANSFER 추가(2026-08-22) — 자산 처분·양도도 정상적인 자산 교체가
    # 대다수라 상대방·가액 확인 전에는 헤드라인으로 올릴 근거가 없다.
    # 3차(2026-08-22): RELATED_PARTY(계열사 자금 지원은 일상)·EARNINGS_SHOCK
    # (증가일 수도 감소일 수도 있다) 추가 — 원문 확인 전에는 헤드라인 근거가 없다.
    assert AMBIGUOUS_SIGNAL_KEYS == frozenset(
        {"TREASURY", "TREASURY_TRUST", "FUND_OUTFLOW", "ACQ_REVIEW",
         "ASSET_TRANSFER", "RELATED_PARTY", "EARNINGS_SHOCK"}
    )


def test_headline_is_none_when_all_observed_are_ambiguous():
    """삼성전자 케이스 — observed가 자사주뿐이면 헤드라인이 없다."""
    qs = [_q("TREASURY", "자사주매입/처분"), _q("TREASURY", "자사주매입/처분")]
    assert pick_headline(qs, _ORDER) is None


def test_headline_picks_non_ambiguous_even_if_lower_priority():
    """셀트리온 케이스 — 자사주 9건 + 경영권분쟁 1건이면 후자가 헤드라인."""
    qs = [_q("TREASURY", "자사주매입/처분"), _q("MGMT_DISPUTE", "경영권분쟁")]
    head = pick_headline(qs, _ORDER)
    assert head is not None and head.key == "MGMT_DISPUTE"


def test_headline_ignores_procedural():
    qs = [_q("CB_BW", "CB/BW발행", tier=TIER_PROCEDURAL)]
    assert pick_headline(qs, _ORDER) is None


def test_headline_respects_priority_order_among_candidates():
    qs = [_q("EXEC", "임원변동"), _q("CB_BW", "CB/BW발행")]
    head = pick_headline(qs, _ORDER)
    expected = min({"EXEC", "CB_BW"}, key=_ORDER.index)
    assert head.key == expected


def test_headline_empty_input():
    assert pick_headline([], _ORDER) is None
