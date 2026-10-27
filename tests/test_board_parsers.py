"""core/board.py 순수 파서 5종 — SKAI(357880) 실공시 픽스처 기준."""
import json
import re
from pathlib import Path

import pytest

from dart_risk_mcp.core.board import (
    extract_board_section,
    find_resolution_rows,
    match_director_overlap,
    parse_board_resolutions,
    parse_decision_parties,
    summarize_board_conflict,
)

FIX = Path(__file__).parent / "fixtures" / "board"


def _txt(name: str) -> str:
    return (FIX / name).read_text(encoding="utf-8")


@pytest.fixture(scope="module")
def skai_text() -> str:
    return _txt("20251219000418_text.txt")


@pytest.fixture(scope="module")
def control_text() -> str:
    return _txt("control_20261023000221_text.txt")


@pytest.fixture(scope="module")
def board_md() -> str:
    return _txt("20260323001292_board_section.md")


@pytest.fixture(scope="module")
def roster() -> list[dict]:
    return json.loads(_txt("exctvSttus_01381984_2025_11011.json"))


@pytest.fixture(scope="module")
def skai_parties(skai_text) -> dict:
    return parse_decision_parties(skai_text)


@pytest.fixture(scope="module")
def parsed(board_md) -> dict:
    return parse_board_resolutions(extract_board_section(board_md))


# ── parse_decision_parties ─────────────────────────────────────────────────

class TestDecisionParties:
    def test_skai_정확한_반환(self, skai_parties):
        assert skai_parties == {
            "counterparty": {
                "name": "주식회사 디렉터스컴퍼니",
                "rep": "신재혁",
                "relation": "최대주주",
            },
            "target": {
                "name": "(주)스카이인텔리전스",
                "rep": "이재철",
                "relation": "최대주주의 특수관계인",
            },
            "resolution_date8": "20251219",
            "outside_directors_present": "2",
            "related_party": True,
        }

    def test_대조군_개인_상대방(self, control_text):
        p = parse_decision_parties(control_text)
        assert p["counterparty"]["name"] == "김상곤 외 2인"
        assert p["counterparty"]["rep"] == ""  # 개인이라 대표이사 행이 없다
        assert p["counterparty"]["relation"] == "-"
        assert p["target"]["name"] == "(주)지아이티아카데미"
        assert p["target"]["rep"] == "김상곤"
        assert p["target"]["relation"] == "-"
        assert p["resolution_date8"] == "20261023"
        assert p["outside_directors_present"] == "2"
        assert p["related_party"] is False

    def test_CRLF_개행이_섞여도_같다(self, skai_text, skai_parties):
        crlf = skai_text.replace(" 6. 거래상대방", "\r\n6. 거래상대방")
        assert parse_decision_parties(crlf) == skai_parties

    def test_정정_원문은_빈_값(self, skai_text):
        amended = "정정신고(보고) " + skai_text
        p = parse_decision_parties(amended)
        assert p["counterparty"] == {"name": "", "rep": "", "relation": ""}
        assert p["target"] == {"name": "", "rep": "", "relation": ""}
        assert p["resolution_date8"] == ""
        assert p["outside_directors_present"] == ""
        assert p["related_party"] is False

    @pytest.mark.parametrize("bad", ["", "   ", None, "관련 없는 문장입니다."])
    def test_빈_입력은_예외없이_빈_값(self, bad):
        p = parse_decision_parties(bad)
        assert p["counterparty"]["name"] == ""
        assert p["target"]["name"] == ""
        assert p["related_party"] is False

    def test_관계_라벨_변형을_모두_받는다(self):
        text = (
            "1. 발행회사 회사명 가나다 주식회사 국적 대한민국 대표자 홍길동 "
            "자본금(원) 100 회사와의관계 계열회사 발행주식총수(주) 10 "
            "6. 거래상대방 회사명(성명) 라마바 주식회사 자본금(원) 5 "
            "회사와 관계 특수관계인 7. 거래대금지급 "
            "9. 이사회결의일(결정일) 2025.12.19 - 사외이사참석여부 참석(명) 1 불참(명) 0"
        )
        p = parse_decision_parties(text)
        assert p["target"]["relation"] == "계열회사"
        assert p["counterparty"]["relation"] == "특수관계인"
        assert p["target"]["rep"] == "홍길동"
        assert p["resolution_date8"] == "20251219"
        assert p["related_party"] is True

    def test_부정_관계표기는_관련당사자가_아니다(self):
        text = (
            "1. 발행회사 회사명 가나다 국적 대한민국 대표자 홍길동 자본금(원) 1 "
            "회사와 관계 특수관계 없음 발행주식총수(주) 1 "
            "6. 거래상대방 회사명(성명) 라마바 자본금(원) 5 회사와의 관계 최대주주 아님 7. 거래대금"
        )
        p = parse_decision_parties(text)
        assert p["related_party"] is False

    def test_더러운_대표자_값은_버린다(self):
        text = (
            "1. 발행회사 회사명 가나다 국적 대한민국 대표자 홍길동은 신주를 취득합니다 "
            "자본금(원) 1 회사와 관계 - 발행주식총수(주) 1 "
            "6. 거래상대방 회사명(성명) 라마바 자본금(원) 5 회사와의 관계 - 7. 대금"
        )
        assert parse_decision_parties(text)["target"]["rep"] == ""


# ── extract_board_section ──────────────────────────────────────────────────

class TestExtractBoardSection:
    def test_제목줄부터_표_끝까지(self, board_md):
        sec = extract_board_section(board_md)
        first = sec.split("\n", 1)[0]
        assert "이사회의 주요 의결사항" in first
        assert "| 35 | 2025년 12월 19일 | 타법인 주식취득 계약의 건 |" in sec
        # 앞 절(내부회계 인력 표·이사회 운영 규정)은 들어오지 않는다
        assert "내부회계담당인력수" not in sec
        assert "제37조(이사회)" not in sec

    def test_다음_소제목에서_끊는다(self, board_md):
        sec = extract_board_section(board_md + "\n다. 이사회 내 위원회\n| 위원회 | 구성 |\n")
        assert "이사회 내 위원회" not in sec
        assert "| 35 |" in sec

    def test_공백_변형을_허용한다(self):
        md = "가. 개요\n(2) 이사회의주요  의결사항 등\n| a | b |\n|---|---|\n| 1 | 2 |\n나. 다음\n"
        sec = extract_board_section(md)
        assert sec.startswith("(2) 이사회의주요  의결사항 등")
        assert "| 1 | 2 |" in sec
        assert "다음" not in sec

    @pytest.mark.parametrize("src", ["", "의결사항이 없는 문서", None])
    def test_없으면_빈_문자열(self, src):
        assert extract_board_section(src) == ""


# ── parse_board_resolutions ────────────────────────────────────────────────

class TestBoardResolutions:
    def test_이사_명단_순서와_출석률(self, parsed):
        names = [d["name"] for d in parsed["directors"]]
        assert names == [
            "신재혁", "이재철", "제갈완", "MAO, XUCHAO", "곽노준", "신기동", "홍영훈",
        ]
        att = {d["name"]: d["attendance"] for d in parsed["directors"]}
        assert att["신재혁"] == "100%"
        assert att["MAO, XUCHAO"] == "0%"

    def test_사내사외_구분은_추정하지_않는다(self, parsed):
        # 이름 줄에 사내/사외 표지가 없고 헤더의 병합 폭이 마크다운에 안 드러난다
        assert {d["group"] for d in parsed["directors"]} == {""}

    def test_행_수와_미파싱(self, parsed):
        assert len(parsed["rows"]) == 35
        # 회차·일자·안건이 모두 빈 마지막 행은 조용히 버리지 않고 센다
        assert parsed["unparsed"] == 1

    def test_35회차_찬반_원문_그대로(self, parsed):
        row = [r for r in parsed["rows"] if r["no"] == "35"][0]
        assert row["date8"] == "20251219"
        assert row["result"] == "가결"
        assert "타법인 주식취득" in row["agenda"]
        assert row["votes"] == {
            "신재혁": "찬성",
            "이재철": "찬성",
            "제갈완": "찬성",
            "MAO, XUCHAO": "-",
            "곽노준": "-",
            "신기동": "-",
            "홍영훈": "찬성",
        }

    def test_첫_행_날짜(self, parsed):
        assert parsed["rows"][0]["no"] == "1"
        assert parsed["rows"][0]["date8"] == "20250103"
        assert parsed["rows"][0]["agenda"] == "대표이사 선임"

    def test_CRLF에도_같은_결과(self, board_md, parsed):
        crlf = extract_board_section(board_md).replace("\n", "\r\n")
        assert parse_board_resolutions(crlf) == parsed

    def test_날짜_표기_변형(self):
        sec = (
            "| 회차 | 개최 일자 | 의안 내용 | 가결 여부 | 사내이사 등의 성명 | 사외이사 등의 성명 |\n"
            "|---|---|---|---|---|---|\n"
            "| 김갑(출석률: 100%) | 이을(출석률: 50%) |\n"
            "| 찬 반 여 부 |\n"
            "| 1 | 2025.12.19 | 가 | 가결 | 찬성 | 반대 |\n"
            "| 2 | 2025-01-05 | 나 | 부결 | 기권 | 찬성 |\n"
            "| 3 | 2025년 3월 7일 | 다 | 가결 | 찬성 | 비고 |\n"
        )
        p = parse_board_resolutions(sec)
        assert [r["date8"] for r in p["rows"]] == ["20251219", "20250105", "20250307"]
        assert p["rows"][1]["votes"] == {"김갑": "기권", "이을": "찬성"}
        assert p["rows"][2]["votes"]["이을"] == "비고"  # 원문 그대로, 변환 없음
        assert p["unparsed"] == 0

    def test_셀_수가_다른_행은_센다(self):
        sec = (
            "| 회차 | 개최 일자 | 의안 내용 | 가결 여부 | 사내이사 등의 성명 | 사외이사 등의 성명 |\n"
            "|---|---|---|---|---|---|\n"
            "| 김갑(출석률: 100%) | 이을(출석률: 50%) |\n"
            "| 찬 반 여 부 |\n"
            "| 1 | 2025.12.19 | 가 | 가결 | 찬성 | 반대 |\n"
            "| 2 | 2025.12.20 | 나 | 가결 | 찬성 |\n"
        )
        p = parse_board_resolutions(sec)
        assert len(p["rows"]) == 1
        assert p["unparsed"] == 1

    @pytest.mark.parametrize(
        "src",
        [
            "",
            None,
            "| 구분 | 내용 |\n|---|---|\n| 제37조 | 이사회는 이사로 구성한다. |\n",
            "| 회차 | 개최 일자 | 의안 내용 | 가결 여부 |\n|---|---|---|---|\n| 1 | 2025.1.1 | 가 | 가결 |\n",
        ],
    )
    def test_2단_헤더가_아니면_빈_결과(self, src):
        assert parse_board_resolutions(src) == {"directors": [], "rows": [], "unparsed": 0}


# ── find_resolution_rows ───────────────────────────────────────────────────

class TestFindResolutionRows:
    def test_SKAI_20251219(self, parsed):
        rows = find_resolution_rows(parsed, "20251219", "타법인 주식취득")
        assert [r["no"] for r in rows] == ["35"]

    def test_안건_힌트가_든_행을_앞에(self):
        parsed = {
            "directors": [],
            "unparsed": 0,
            "rows": [
                {"no": "1", "date8": "20250101", "agenda": "정관 변경의 건", "result": "가결", "votes": {}},
                {"no": "2", "date8": "20250101", "agenda": "타법인 주식 양수의 건", "result": "가결", "votes": {}},
                {"no": "3", "date8": "20250102", "agenda": "타법인 주식 양수의 건", "result": "가결", "votes": {}},
            ],
        }
        assert [r["no"] for r in find_resolution_rows(parsed, "20250101", "타법인주식양수")] == ["2", "1"]
        assert [r["no"] for r in find_resolution_rows(parsed, "20250101")] == ["1", "2"]
        assert find_resolution_rows(parsed, "20990101") == []

    @pytest.mark.parametrize("p", [None, {}, {"rows": []}])
    def test_빈_입력(self, p):
        assert find_resolution_rows(p, "20251219") == []


# ── match_director_overlap ─────────────────────────────────────────────────

def _by_key(rows):
    return {(r["name"], r["side"]): r for r in rows}


class TestDirectorOverlap:
    def test_SKAI_겸직_사람_집합(self, roster, skai_parties):
        ov = match_director_overlap(roster, skai_parties)
        # MAO, XUCHAO는 주요경력에 대상회사(스카이인텔리전스)가 직접 적혀 있다
        assert {r["name"] for r in ov} == {"신재혁", "이재철", "제갈완", "MAO, XUCHAO"}

    def test_근거와_역할(self, roster, skai_parties):
        k = _by_key(match_director_overlap(roster, skai_parties))
        sh = k[("신재혁", "counterparty")]
        assert sh["role_at_issuer"] == "대표이사/사내이사"
        assert sh["other_name"] == "주식회사 디렉터스컴퍼니"
        assert sh["evidence"][0] == "공시 거래상대방 대표자 일치"
        assert any(e.startswith("임원현황 주요경력: 「") and "디렉터스컴퍼니" in e for e in sh["evidence"])
        assert sh["role_at_other"] == "대표자(공시 기재)"
        assert sh["mxmm_shrholdr_relate"] == "특수관계인"
        assert sh["birth_match"] is None
        assert ("신재혁", "target") not in k

        # 이재철: 대상회사 대표자(①+②) · 상대방 임원 경력(②) — 같은 사람이라 행 둘
        jc_t = k[("이재철", "target")]
        assert jc_t["evidence"][0] == "공시 발행회사 대표자 일치"
        assert len(jc_t["evidence"]) == 2
        jc_c = k[("이재철", "counterparty")]
        assert len(jc_c["evidence"]) == 1 and jc_c["evidence"][0].startswith("임원현황 주요경력")
        assert jc_c["role_at_other"].count("디렉터스컴퍼니") == 1
        assert "COO" in jc_c["role_at_other"]
        assert jc_c["role_at_issuer"] == "부대표/사내이사"

        # 제갈완: 경력 근거만
        jw = k[("제갈완", "counterparty")]
        assert len(jw["evidence"]) == 1 and jw["evidence"][0].startswith("임원현황 주요경력")
        assert "CFO" in jw["role_at_other"]
        assert all(r["birth_match"] is None for r in k.values())
        assert k[("MAO, XUCHAO", "target")]["role_at_issuer"] == "사내이사"  # 직위=구분이면 한 번만

    def test_경력_인용은_20자_이내로_한_줄(self, roster, skai_parties):
        for r in match_director_overlap(roster, skai_parties):
            if r["role_at_other"] != "대표자(공시 기재)":
                assert "\n" not in r["role_at_other"]
                assert len(r["role_at_other"]) <= 20 + 10 + 20  # 앞 20 + 회사명 + 뒤 20

    def test_이름_정규화_각주_공백_개행(self, roster, skai_parties):
        names = {r["name"] for r in match_director_overlap(roster, skai_parties)}
        assert "이재철" in names and "이재철(1)" not in names
        assert "제갈완" in names and "제갈완 " not in names
        assert "MAO, XUCHAO" in names  # 개행은 공백 하나로

    def test_상대방_명부_이름_일치와_생년월(self, skai_parties):
        issuer = [{"nm": "홍길동", "birth_ym": "1970년 01월", "ofcps": "사외이사",
                   "rgist_exctv_at": "사외이사", "main_career": "", "mxmm_shrholdr_relate": "-"}]
        other_same = [{"nm": "홍 길동", "birth_ym": "1970년 01월", "ofcps": "이사", "rgist_exctv_at": "사내이사"}]
        other_diff = [{"nm": "홍길동", "birth_ym": "1985년 05월", "ofcps": "이사", "rgist_exctv_at": "사내이사"}]
        other_nobirth = [{"nm": "홍길동", "birth_ym": "", "ofcps": "이사", "rgist_exctv_at": "사내이사"}]
        r = match_director_overlap(issuer, skai_parties, other_same)
        assert len(r) == 1 and r[0]["birth_match"] is True
        assert r[0]["evidence"] == ["상대방 임원현황 이름 일치"]
        assert r[0]["side"] == "counterparty"
        assert r[0]["role_at_other"] == "이사/사내이사"
        assert match_director_overlap(issuer, skai_parties, other_diff)[0]["birth_match"] is False
        assert match_director_overlap(issuer, skai_parties, other_nobirth)[0]["birth_match"] is None
        assert match_director_overlap(issuer, skai_parties, [])  == []

    def test_합계_빈_이름은_건너뛴다(self, skai_parties):
        rows = [
            {"nm": "계", "main_career": "디렉터스컴퍼니"},
            {"nm": "합계", "main_career": "디렉터스컴퍼니"},
            {"nm": "", "main_career": "디렉터스컴퍼니"},
        ]
        assert match_director_overlap(rows, skai_parties) == []

    def test_대조군은_겸직_없음(self, roster, control_text):
        assert match_director_overlap(roster, parse_decision_parties(control_text)) == []

    @pytest.mark.parametrize("r", [None, []])
    def test_빈_명부(self, r, skai_parties):
        assert match_director_overlap(r, skai_parties) == []

    def test_파티가_비어도_예외없음(self, roster):
        assert match_director_overlap(roster, {}) == []
        assert match_director_overlap(roster, parse_decision_parties("")) == []


# ── summarize_board_conflict ───────────────────────────────────────────────

_FORBIDDEN = re.compile(r"위험|제척 없음|심각|의심|위반|문제")


class TestSummarize:
    def test_SKAI(self, parsed, roster, skai_parties):
        ov = match_director_overlap(roster, skai_parties)
        row = find_resolution_rows(parsed, skai_parties["resolution_date8"], "타법인 주식")[0]
        s = summarize_board_conflict(parsed["directors"], ov, row)
        assert "\n" not in s
        assert "이사 7인 중 4인이 상대방·대상회사 임원 겸직" in s
        assert "겸직 이사 결의 표기: 찬성 3 · 「-」 1" in s  # 신재혁·이재철·제갈완 찬성 / MAO '-'
        assert "전체 이사 결의 표기: 찬성 4 · 「-」 3" in s
        assert not _FORBIDDEN.search(s)

    def test_의결표_없음(self, parsed, roster, skai_parties):
        ov = match_director_overlap(roster, skai_parties)
        s = summarize_board_conflict(parsed["directors"], ov, None)
        assert s.endswith("의결표 없음")
        assert "이사 7인 중 4인" in s

    def test_이사_수_확인_불가(self):
        s = summarize_board_conflict([], [], None)
        assert "이사 수 확인 불가" in s
        assert not _FORBIDDEN.search(s)

    def test_겸직_0인(self, parsed):
        row = parsed["rows"][-2]
        s = summarize_board_conflict(parsed["directors"], [], row)
        assert "이사 7인 중 0인이" in s
        assert "찬성" in s

    def test_의결표에_이름이_없는_겸직자는_표기한다(self, parsed):
        ov = [{"name": "없는사람", "side": "counterparty"}]
        row = parsed["rows"][-2]
        s = summarize_board_conflict(parsed["directors"], ov, row)
        assert "표에 없음 1" in s
