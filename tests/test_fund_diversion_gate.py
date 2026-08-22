"""fund_diversion_chain 내용 확인 게이트 (v1.13.0).

이 패턴은 요구 신호가 1.1(CB/BW)+5.8(타법인 취득) 둘뿐이라 겹침 2개면 곧
전부 일치이고, ACQ_REVIEW 재현율 수정 후 1년 기준 **142개사**에서 발화한다 —
제목만으로는 정상적인 사업 확장 M&A와 구분되지 않는다.

`capital_backflow`와 같은 구조로, 취득 대상이 **계열·특수관계로 확인될 때만**
패턴을 표시하고 그 외에는 확인된 사실만 블록으로 남긴다.
"""
import pytest

from dart_risk_mcp.core.dart_client import (
    classify_target_listing,
    parse_acquisition_detail,
)
from dart_risk_mcp.server import (
    _fund_diversion_gate,
    _render_acquisition_confirmations,
    _render_pattern_watch_block,
)


def _row(relation, classification, issuer="테스트법인", ratio=10.0, listing="unlisted"):
    return {
        "rcept_dt": "20260101", "report_nm": "타법인주식및출자증권취득결정",
        "rcept_no": "20260101000001", "issuer": issuer, "relation": relation,
        "classification": classification, "amount": 1_000_000_000,
        "equity_ratio": ratio, "nation": "", "listing": listing,
    }


class TestGateDecision:
    def test_계열이면서_비상장이면_통과(self):
        """금감원 근거는 '유용 최대 경로가 비상장주식 취득(55%)' — 두 축이
        함께 서야 이 패턴의 근거와 맞는다(2026-08-22 강화)."""
        g = _fund_diversion_gate([_row("계열회사", "affiliated", listing="unlisted")])
        assert g["pass"] is True
        assert g["fact_lines"] == []

    @pytest.mark.parametrize("relation,cls", [
        ("-", "external"),
        ("종속회사", "subsidiary"),
    ])
    def test_외부_종속회사만이면_차단(self, relation, cls):
        """모회사가 자회사 지분을 늘리는 것은 정상적인 지배구조 정리다 —
        capital_backflow와 같은 판단."""
        g = _fund_diversion_gate([_row(relation, cls)])
        assert g["pass"] is False
        assert g["fact_lines"], "차단했으면 확인된 사실은 남겨야 한다"
        assert "계열·특수관계 취득은 미확인" in "\n".join(g["fact_lines"])

    def test_전부_미확인이면_원문_확인_안내(self):
        g = _fund_diversion_gate([_row("", "unknown")])
        assert g["pass"] is False
        assert "원문 확인 필요" in "\n".join(g["fact_lines"])

    def test_확인_자체가_없으면_사실_블록도_없다(self):
        """5.8이 관찰되지 않아 원문을 열지 않은 경우 — 호출 예산 0."""
        g = _fund_diversion_gate([])
        assert g["pass"] is False
        assert g["fact_lines"] == []

    def test_한_건이라도_계열이면_통과(self):
        g = _fund_diversion_gate([
            _row("-", "external"), _row("계열회사", "affiliated"),
        ])
        assert g["pass"] is True


class TestRenderedBlock:
    def test_게이트가_막으면_패턴이_목록에서_빠진다(self):
        lines, fact_lines, filtered = _render_pattern_watch_block(
            ["1.1", "5.8"], [], True, {},
            acq_confirmations=[_row("-", "external", "무관법인")],
        )
        assert not any(f["pattern_id"] == "fund_diversion_chain" for f in filtered)
        assert "조달-유용 체인" not in "\n".join(lines)
        assert "타법인 취득 대상 확인" in "\n".join(fact_lines)
        assert "무관법인" in "\n".join(fact_lines)

    def test_게이트를_통과하면_패턴이_표시된다(self):
        lines, fact_lines, filtered = _render_pattern_watch_block(
            ["1.1", "5.8"], [], True, {},
            acq_confirmations=[_row("계열회사", "affiliated")],
        )
        assert any(f["pattern_id"] == "fund_diversion_chain" for f in filtered)
        assert "조달-유용 체인" in "\n".join(lines)
        assert fact_lines == []

    def test_확인이_없으면_기존_동작_유지(self):
        """acq_confirmations 미전달 = 하위 호환. 다만 게이트 입력이 없으므로
        패턴은 표시되지 않는다(원문 확인 없이 CRITICAL 카드를 띄우지 않는다)."""
        lines, _, filtered = _render_pattern_watch_block(["1.1", "5.8"], [], True, {})
        assert not any(f["pattern_id"] == "fund_diversion_chain" for f in filtered)

    def test_두_게이트의_사실_블록이_섞이지_않는다(self):
        """자금유출 상대방과 타법인 취득 대상은 성격이 달라 각자 헤더를 단다."""
        outflow = [{
            "rcept_dt": "20260201", "report_nm": "타인에대한채무보증결정",
            "rcept_no": "2", "counterparty": "유출상대", "relation": "종속회사",
            "classification": "subsidiary", "amount": 100,
        }]
        _, fact_lines, _ = _render_pattern_watch_block(
            ["3.1", "5.7", "1.1", "5.8"], outflow, True, {},
            acq_confirmations=[_row("-", "external", "취득대상")],
        )
        joined = "\n".join(fact_lines)
        assert "━━ 자금유출·자산이전 상대방 확인 ━━" in joined
        assert "━━ 타법인 취득 대상 확인 ━━" in joined
        assert joined.index("자금유출·자산이전") < joined.index("타법인 취득 대상")


class TestParser:
    """원문 파서 — 두 서식(취득결정 자율공시 / 양수결정 법정)을 모두 읽는다."""

    ACQ = ("코아스/타법인주식및출자증권취득결정/(2026.05.06)타법인주식및출자증권취득결정 "
           "타법인 주식 및 출자증권 취득결정 1. 발행회사 회사명 해성옵틱스 국적 대한민국 "
           "대표자 조철 자본금(원) 24,183,874 회사와 관계 - 발행주식총수(주) 48,367,748 "
           "주요사업 광학 렌즈모듈 2. 취득내역 취득주식수(주) 2,000,000 취득금액(원) "
           "5,000,000,000 자기자본(원) 34,717,783,264 자기자본대비(%) 14.40 "
           "4. 취득방법 전환사채 전환권 행사 5. 취득목적 유동성을 제고하고자 함 "
           "6. 취득예정일자 2026-05-07")

    TRF = ("타법인 주식 및 출자증권 양수결정 1. 발행회사 회사명 이화전기공업 주식회사 국적 "
           "대한민국 대표자 백성현 자본금(원) 43,789,728,000 회사와 관계 - "
           "발행주식총수(주) 218,948,640 주요사업 UPS 2. 양수내역 양수주식수(주) 54,142,221 "
           "양수금액(원)(A) 10,853,546,458 총자산(원)(B) 81,110,226,850 총자산대비(%)(A/B) 13.38 "
           "자기자본(원)(C) 2,426,341,781 자기자본대비(%)(A/C) 447.32 "
           "4. 양수목적 대상회사에 대한 경영지배 목적 5. 양수예정일자 2025년 09월 03일 "
           "6. 거래상대방 회사명(성명) - 8. 외부평가에 관한 사항 외부평가 여부 미해당")

    def test_취득결정_서식(self):
        d = parse_acquisition_detail(self.ACQ)
        assert d["issuer"] == "해성옵틱스"
        assert d["relation"] == "-"
        assert d["amount"] == 5_000_000_000
        assert d["equity_ratio"] == pytest.approx(14.40)
        assert "전환사채" in d["method"]

    def test_양수결정_서식(self):
        d = parse_acquisition_detail(self.TRF)
        assert d["issuer"] == "이화전기공업 주식회사"
        assert d["amount"] == 10_853_546_458
        assert d["equity_ratio"] == pytest.approx(447.32)
        assert d["extval"] == "미해당"

    def test_무관한_원문은_빈_dict(self):
        assert parse_acquisition_detail("기업설명회(IR) 개최 1. 일시")["issuer"] == ""
        assert parse_acquisition_detail("")["issuer"] == ""

    def test_렌더에_자기자본_대비가_표기된다(self):
        lines = _render_acquisition_confirmations([_row("-", "external", "대상사", 447.3)])
        assert "자기자본 대비 447.3%" in "\n".join(lines)


class TestParserFormVariants:
    """2026-08-22 실측 — 서식이 두 가지인데 하나만 보고 있었다.

    70건 표본에서 issuer **60%**·relation **19%**가 실패했다. 원인:
      ① 「발행회사 회사명(국적) <이름> 대표이사 …」 (37/70) — 옛 정규식이
         바로 뒤 "(국적)"의 여는 괄호까지만 잡아 issuer가 "(" 하나가 됐다
      ② 「회사와**의**관계」 변형 (3/70) — "회사와 관계"만 보고 있었다
    수정 후 둘 다 실패 7%이며, 남은 7%는 발행회사 블록이 없는 「영업양수」다.
    """

    PAREN_FORM = (
        "타법인 주식 및 출자증권 취득결정 발행회사 회사명(국적) 주식회사 대현 (대한민국) "
        "대표이사 홍길동 자본금(원) 1,000,000 회사와 관계 계열회사 발행주식총수(주) 100 "
        "2. 취득내역 취득금액(원) 5,000,000,000 자기자본대비(%) 12.30"
    )
    PLAIN_FORM = (
        "타법인 주식 및 출자증권 취득결정 발행회사 회사명 해성옵틱스 국적 대한민국 "
        "대표자 조철 자본금(원) 24,183,874 회사와 관계 - 발행주식총수(주) 48,367,748 "
        "2. 취득내역 취득금액(원) 5,000,000,000 자기자본대비(%) 14.40"
    )
    NO_SPACE_RELATION = (
        "타법인 주식 및 출자증권 취득결정 발행회사 회사명(국적) (주)원픽이앤씨 "
        "대표이사 김수현 자본금(원) 150,000,000 회사와의관계 - 발행주식총수(주) 30,000"
    )
    FOREIGN = (
        "타법인 주식 및 출자증권 취득결정 발행회사 회사명(국적) VERISMO THERAPEUTICS, INC.(미국) "
        "대표이사 KIM 자본금(원) 4,645,902 회사와 관계 종속회사 발행주식총수(주) 31,753,714"
    )

    def test_괄호형_서식에서_이름과_국적을_분리한다(self):
        d = parse_acquisition_detail(self.PAREN_FORM)
        assert d["issuer"] == "주식회사 대현"
        assert d["nation"] == "대한민국"
        assert d["relation"] == "계열회사"

    def test_평문형_서식도_그대로_읽는다(self):
        d = parse_acquisition_detail(self.PLAIN_FORM)
        assert d["issuer"] == "해성옵틱스"
        assert d["relation"] == "-"

    def test_회사와의관계_변형을_읽는다(self):
        d = parse_acquisition_detail(self.NO_SPACE_RELATION)
        assert d["issuer"] == "(주)원픽이앤씨"
        assert d["relation"] == "-"

    def test_법인형태_괄호는_이름에서_떼지_않는다(self):
        """'비에스지(주)'의 '(주)'는 이름의 일부다."""
        d = parse_acquisition_detail(
            "타법인 주식 및 출자증권 취득결정 발행회사 회사명 비에스지(주) 국적 대한민국 "
            "대표자 김 자본금(원) 1 회사와 관계 - 발행주식총수(주) 1"
        )
        assert d["issuer"] == "비에스지(주)"

    def test_해외법인_국적을_읽는다(self):
        d = parse_acquisition_detail(self.FOREIGN)
        assert "VERISMO" in d["issuer"]
        assert d["nation"] == "미국"


class TestTargetListing:
    """취득 대상의 국내 상장 여부 — 금감원 '유용 최대 경로는 비상장주식 취득(55%)' 축.

    2026-08-22 실측으로 판정률을 **28% → 93%**로 올렸다. corpCode.xml은
    상장·비상장을 모두 담은 공시대상 법인 명부(11만여 건)라, 거기서 못 찾는
    것은 국내 상장사가 아니라는 강한 근거다.
    """

    def test_이름이_없으면_추측하지_않는다(self):
        assert classify_target_listing("") == "unknown"
        assert classify_target_listing("   ") == "unknown"

    def test_해외법인은_국내_비상장이다(self):
        assert classify_target_listing("VERISMO THERAPEUTICS, INC.", "미국") == "unlisted"
        assert classify_target_listing("CAR TECH, LLC", "USA") == "unlisted"

    def test_국내_표기는_명부로_판정한다(self):
        cache = {
            "이화전기공업": {"corp_code": "1", "stock_code": "024810"},
            "다이나맥": {"corp_code": "2", "stock_code": ""},
        }
        assert classify_target_listing("이화전기공업 주식회사", "대한민국", cache) == "listed"
        assert classify_target_listing("주식회사 다이나맥", "대한민국", cache) == "unlisted"

    def test_명부에_없으면_비상장으로_본다(self):
        """조합·펀드·SPC는 애초에 국내 상장사가 아니다."""
        cache = {"아무회사": {"corp_code": "1", "stock_code": "000000"}}
        assert classify_target_listing("더베스트조합", "", cache) == "unlisted"
        assert classify_target_listing("아크조합 제1호", "", cache) == "unlisted"

    def test_명부가_비면_판정하지_않는다(self):
        assert classify_target_listing("아무회사", "", {}) == "unknown"

    def test_상장_여부는_게이트_통과_조건이_아니다(self):
        """비상장 자회사 편입도 대부분 비상장이라 통과 조건으로 쓰지 않는다 —
        사실 표기 전용이다."""
        row = _row("-", "external")
        row["listing"] = "unlisted"
        assert _fund_diversion_gate([row])["pass"] is False


class TestUnlistedRequirement:
    """2026-08-22 강화 — 계열·특수관계 **이면서 비상장**일 때만 통과.

    70건 실측: 계열 확인 10건 중 8건이 비상장이었고, 빠지는 2건은 **지주회사가
    상장 계열사 지분을 취득한 건**이었다(녹십자홀딩스→녹십자웰빙,
    사토시홀딩스→한국첨단소재) — 정상적인 그룹 내 거래라 조준이 정확하다.
    """

    def test_계열이지만_상장사면_차단(self):
        g = _fund_diversion_gate([_row("계열회사", "affiliated", listing="listed")])
        assert g["pass"] is False
        joined = "\n".join(g["fact_lines"])
        assert "계열·특수관계 취득 1건이 확인됐으나" in joined
        assert "상장사" in joined
        assert "비상장주식 취득 경로와는 다릅니다" in joined

    def test_계열이지만_상장여부_미확인이면_차단(self):
        """비상장이라는 것을 확인하지 못한 것이다 — CRITICAL 카드는 확인된
        사실 위에서만 띄운다."""
        g = _fund_diversion_gate([_row("계열회사", "affiliated", listing="unknown")])
        assert g["pass"] is False
        assert "상장 여부를 원문에서 확인하지 못했습니다" in "\n".join(g["fact_lines"])

    def test_한_건이라도_계열_비상장이면_통과(self):
        g = _fund_diversion_gate([
            _row("계열회사", "affiliated", "상장계열사", listing="listed"),
            _row("계열회사", "affiliated", "비상장계열사", listing="unlisted"),
        ])
        assert g["pass"] is True
        assert [c["issuer"] for c in g["affiliated"]] == ["비상장계열사"]

    def test_비상장이어도_외부면_통과하지_않는다(self):
        """비상장 단독은 조건이 아니다 — 정상적인 비상장 자회사 편입도
        대부분 비상장이기 때문."""
        g = _fund_diversion_gate([_row("-", "external", listing="unlisted")])
        assert g["pass"] is False

    def test_차단해도_확인된_사실은_남는다(self):
        g = _fund_diversion_gate([
            _row("계열회사", "affiliated", "녹십자웰빙", ratio=8.5, listing="listed")
        ])
        joined = "\n".join(g["fact_lines"])
        assert "녹십자웰빙" in joined
        assert "(상장)" in joined
        assert "자기자본 대비 8.5%" in joined

    def test_렌더_블록에서도_동일하게_막힌다(self):
        lines, fact_lines, filtered = _render_pattern_watch_block(
            ["1.1", "5.8"], [], True, {},
            acq_confirmations=[_row("계열회사", "affiliated", "상장계열사", listing="listed")],
        )
        assert not any(f["pattern_id"] == "fund_diversion_chain" for f in filtered)
        assert "조달-유용 체인" not in "\n".join(lines)
        assert "상장사" in "\n".join(fact_lines)


class TestNationDetection:
    """괄호 안이 국적인지 영문 병기·부기인지 가른다 (2026-08-22).

    실측 70건 중 6건이 국적이 아니었다 — 「JIANGSU QICHENG NEW MATERIALS
    CO.,LTD.」(영문명)·「가칭」·「예정」·「Dunamu Inc.」. 이걸 국적으로 보면
    `classify_target_listing`이 "국내가 아님 → 비상장" 지름길을 잘못 타서,
    영문 병기가 붙은 **상장사**가 비상장으로 뒤집힐 수 있다.
    """

    def _issuer(self, tail):
        return parse_acquisition_detail(
            "타법인 주식 및 출자증권 취득결정 발행회사 회사명(국적) " + tail
            + " 대표이사 X 자본금(원) 1 회사와 관계 - 발행주식총수(주) 1"
        )

    @pytest.mark.parametrize("tail,name,nation", [
        ("주식회사 대현 (대한민국)", "주식회사 대현", "대한민국"),
        ("VERISMO THERAPEUTICS, INC.(미국)", "VERISMO THERAPEUTICS, INC.", "미국"),
        ("CAR TECH, LLC(USA)", "CAR TECH, LLC", "USA"),
    ])
    def test_진짜_국적은_국적으로_읽는다(self, tail, name, nation):
        d = self._issuer(tail)
        assert d["issuer"] == name
        assert d["nation"] == nation

    @pytest.mark.parametrize("tail,name", [
        ("주식회사 라프텔 (Laftel)", "주식회사 라프텔"),
        ("두나무(주) (Dunamu Inc.)", "두나무(주)"),
        ("에이치엠지퓨처콤플렉스 주식회사 (예정)", "에이치엠지퓨처콤플렉스 주식회사"),
        ("Hyundai Steel USA (가칭)", "Hyundai Steel USA"),
    ])
    def test_영문병기_부기는_국적이_아니다(self, tail, name):
        d = self._issuer(tail)
        assert d["issuer"] == name, "이름에서는 떼어낸다"
        assert d["nation"] == "", f"국적으로 쓰면 안 된다: {d['nation']!r}"

    def test_국적이_아니면_명부로_판정한다(self):
        """영문 병기가 붙은 상장사가 해외로 오인돼 비상장이 되면 안 된다."""
        cache = {"이화전기공업": {"corp_code": "1", "stock_code": "024810"}}
        assert classify_target_listing("이화전기공업", "", cache) == "listed"
        # 국적이 실제로 해외면 명부를 보지 않고 비상장
        assert classify_target_listing("이화전기공업", "미국", cache) == "unlisted"
