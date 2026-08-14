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
