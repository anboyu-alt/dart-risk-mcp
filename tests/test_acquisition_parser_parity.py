"""취득/양수 원문 파서 core ↔ 뷰어 동등성 (v1.13.0).

두 레이어가 각자 이식한 파서라 드리프트가 생긴다. 실제 DART 원문에서 뽑은
두 서식 픽스처로 같은 값을 내는지 확인한다.
"""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile

import pytest

from dart_risk_mcp.core.dart_client import parse_acquisition_detail

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = _ROOT / "docs" / "tool" / "index.html"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node가 없어 뷰어 JS를 실행할 수 없다"
)

# 실제 DART 원문(코아스 20260506800991 / 20250904000002)에서 발췌
ACQ = ("코아스/타법인주식및출자증권취득결정 타법인 주식 및 출자증권 취득결정 "
       "1. 발행회사 회사명 해성옵틱스 국적 대한민국 대표자 조철 자본금(원) 24,183,874 "
       "회사와 관계 - 발행주식총수(주) 48,367,748 주요사업 광학 렌즈모듈 "
       "2. 취득내역 취득주식수(주) 2,000,000 취득금액(원) 5,000,000,000 "
       "자기자본(원) 34,717,783,264 자기자본대비(%) 14.40")

TRF = ("타법인 주식 및 출자증권 양수결정 1. 발행회사 회사명 이화전기공업 주식회사 "
       "국적 대한민국 대표자 백성현 자본금(원) 43,789,728,000 회사와 관계 계열회사 "
       "발행주식총수(주) 218,948,640 주요사업 UPS 2. 양수내역 양수주식수(주) 54,142,221 "
       "양수금액(원)(A) 10,853,546,458 총자산(원)(B) 81,110,226,850 "
       "총자산대비(%)(A/B) 13.38 자기자본(원)(C) 2,426,341,781 자기자본대비(%)(A/C) 447.32")

IRRELEVANT = "기업설명회(IR) 개최 1. 일시 행사일 2026-04-15"

# 2026-08-22 실측으로 드러난 두 번째 서식(70건 중 37건) — 옛 파서는 여기서
# issuer가 "(" 하나로 잘렸다. 양쪽이 같이 고쳐졌는지 확인한다.
PAREN = ("타법인 주식 및 출자증권 취득결정 발행회사 회사명(국적) 주식회사 대현 (대한민국) "
         "대표이사 홍길동 자본금(원) 1,000,000 회사와 관계 계열회사 발행주식총수(주) 100 "
         "2. 취득내역 취득금액(원) 5,000,000,000 자기자본대비(%) 12.30")
# 「회사와의관계」(의 포함) 변형
NO_SPACE = ("타법인 주식 및 출자증권 취득결정 발행회사 회사명(국적) (주)원픽이앤씨 "
            "대표이사 김수현 자본금(원) 150,000,000 회사와의관계 - 발행주식총수(주) 30,000")


def _cut(html, marker):
    i = html.index(marker)
    b = html.index("{", i)
    d = 0
    for j in range(b, len(html)):
        if html[j] == "{":
            d += 1
        elif html[j] == "}":
            d -= 1
            if d == 0:
                return html[i:j + 1]
    raise AssertionError(marker)


def _cut_const(html, prefix):
    """여러 줄에 걸친 const 선언을 '];'로 끝나는 줄까지 잘라낸다."""
    lines = html.splitlines()
    i = next(n for n, l in enumerate(lines) if l.startswith(prefix))
    out = []
    for l in lines[i:]:
        out.append(l)
        if l.rstrip().endswith(";"):
            break
    return "\n".join(out)


def _viewer(texts):
    html = _HTML.read_text(encoding="utf-8")
    # parseAcquisitionDetail은 splitIssuerNation·ACQ_CORP_FORM_RE에 의존한다
    form_re = _cut_const(html, "const ACQ_CORP_FORM_RE")
    nation_tokens = _cut_const(html, "const ACQ_NATION_TOKENS")
    # 2026-09-11: `mdToPlain`(마크다운 표 → core가 보는 평문)과
    # `RELATION_LOOKS_DIRTY_RE`(관계가 주석 문장을 물면 버린다) 의존 추가.
    dirty_re = _cut_const(html, "const RELATION_LOOKS_DIRTY_RE")
    js = (form_re + "\n"
          + nation_tokens + "\n"
          + dirty_re + "\n"
          + _cut(html, "function mdToPlain(text)") + "\n"
          + _cut(html, "function looksLikeNation(text)") + "\n"
          + _cut(html, "function splitIssuerNation(raw)") + "\n"
          + _cut(html, "function parseAcquisitionDetail(text)") + "\n"
          + f"const T = {json.dumps(texts, ensure_ascii=False)};\n"
          "console.log(JSON.stringify(T.map(parseAcquisitionDetail)));\n")
    tf = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    tf.write(js)
    tf.close()
    try:
        r = subprocess.run([shutil.which("node"), tf.name],
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, r.stderr[:1500]
        return json.loads(r.stdout)
    finally:
        os.unlink(tf.name)


class TestParity:
    def test_두_서식과_무관_원문에서_같은_값을_낸다(self):
        texts = [ACQ, TRF, IRRELEVANT, PAREN, NO_SPACE]
        js = _viewer(texts)
        for t, j in zip(texts, js):
            py = parse_acquisition_detail(t)
            assert j["issuer"] == py["issuer"], t[:40]
            assert j["relation"] == py["relation"], t[:40]
            assert j["nation"] == py["nation"], t[:40]
            # 뷰어는 문자열, core는 숫자 — 값이 같은지만 본다
            assert (j["amount"].replace(",", "") or "0") == str(py["amount"] or 0), t[:40]
            assert (float(j["ratio"] or 0)) == pytest.approx(py["equity_ratio"]), t[:40]
            # ⚠ 2026-09-13 추가 — 이 셋을 **비교하지 않아서** 뷰어가 core가 읽는
            #   값을 통째로 버리는 것을 여기서 못 잡았다(실측 45일 20건에서
            #   취득목적 16/16 · 취득방법 14/16이 원문에 있는데 화면엔 0건).
            #   패리티 테스트는 비교하는 키만 지킨다.
            assert j["purpose"] == py["purpose"], t[:40]
            assert j["method"] == py["method"], t[:40]
            assert j["extval"] == py["extval"], t[:40]
            assert j["putOption"] == py["put_option"], t[:40]
            assert j["putOptionText"] == py["put_option_text"], t[:40]

    def test_괄호형_서식을_양쪽_다_읽는다(self):
        """실측 37/70이 이 서식이다 — 한쪽만 고치면 뷰어와 리포트가 갈린다."""
        py = parse_acquisition_detail(PAREN)
        js = _viewer([PAREN])[0]
        assert py["issuer"] == js["issuer"] == "주식회사 대현"
        assert py["nation"] == js["nation"] == "대한민국"
        assert py["relation"] == js["relation"] == "계열회사"

    def test_회사와의관계_변형을_양쪽_다_읽는다(self):
        py = parse_acquisition_detail(NO_SPACE)
        js = _viewer([NO_SPACE])[0]
        assert py["relation"] == js["relation"] == "-"
        assert py["issuer"] == js["issuer"] == "(주)원픽이앤씨"

    def test_계열회사_표기를_양쪽_다_읽는다(self):
        """게이트 통과 여부를 가르는 결정적 필드다."""
        assert parse_acquisition_detail(TRF)["relation"] == "계열회사"
        assert _viewer([TRF])[0]["relation"] == "계열회사"


# ── 풋옵션 「예」 실측 픽스처 (아이엘 20260910900252, 2026-09-10) ──────────
#
# 원문 표기가 **두 형태**다: 「풋옵션계약 등의 체결여부」(이 건)와
# 「풋옵션 등 계약 체결여부」(SGC에너지·HD현대 등). 한쪽만 보면 절반을 놓친다.
# 45일 20건 실측에서 값은 아니오 15 · **예 1** — 드물지만 걸리면 실질적이다.
PUT_YES = """아이엘/타법인주식및출자증권취득결정/(2026.09.10)타법인주식및출자증권취득결정 타법인 주식 및 출자증권 취득결정 1. 발행회사 회사명(국적) (주)리드엔지니어링 대표이사 김현호 자본금(원) 800,000,000 회사와 관계 - 발행주식총수(주) 1,000 주요사업 반도체 제조용 기계 제조업 -최근 6월 이내 제3자 배정에 의한 신주취득 여부 아니오 2. 취득내역 취득주식수(주) 800 취득금액(원) 12,800,000,000 자기자본(원) 45,504,478,457 자기자본대비(%) 28.13 대기업 여부 미해당 3. 취득후 소유주식수 및 지분비율 소유주식수(주) 800 지분비율(%) 80.0 4. 취득방법 현금, 대용납입 5. 취득목적 SiC 전력반도체 장비 사업 진출 및 사업 포트폴리오 확대를 통한 신성장동력 확보 6. 취득예정일자 2026-09-18 7. 자산양수의 주요사항보고서 제출대상 여부 아니오 -최근 사업연도말 자산총액(원) 154,697,625,359 취득가액/자산총액(%) 8.27 8. 우회상장 해당 여부 아니오 -향후 6월이내 제3자배정 증자 등 계획 아니오 9. 발행회사(타법인)의 우회상장 요건 충족여부 아니오 10. 이사회결의일(결정일) 2026-09-10 -사외이사 참석여부 참석(명) 1 불참(명) 1 -감사(감사위원) 참석여부 참석 11. 공정거래위원회 신고대상 여부 미해당 12. 풋옵션계약 등의 체결여부 예 -계약내용 - 매수인 또는 매수인이 지정하는 자는 잔여지분의 전부 또는 일부에 대하여 콜옵션을 가진다. - 콜옵션은 거래종결일로부터 1년이 되는 날부터 4년이 되는 날까지 매수인의 선택에 따라 전부 또는 일부 행사할 수 있다. 단, 매도인의 정당한 사유 없는 조기퇴사, 고의, 중대한 귀책사유로 인한 해임 시(매도인이 관련 법령 및 내부 규정, 본 계약 등에 위반하여 해임되는 경우를 의미함. 이하 같음)에는 위 기간 전이라도 즉시 행사할 수 있다. - 매도인은 거래종결일로부터 24개월이 되는 날 이후 매수인에 대하여 잔여지분의 전부 또는 일부의 매수를 청구할 수 있는 풋옵션을 가진다. 매수인은 행사통지 수령일로부터 10영업일 이내에 행사대금 전액을 현금으로 지급하며(상계 불가), 지급이 지연되는 경우 연 1할 5푼의 지연손해금을 가산한다. 13. 기타 투자판단에 참고할 사항 - 상기 자본금 및 발행주식총수는 공시제출일 현재 기준입니다. - 상기 2. 취득내역의 자기자본은 최근 사업연도말 연결 재무제표의 자기자본에서 공시제출일 현재까지의 자본금 및 자본잉여금의 증감액을 반영한 금액입니다. - 상기 4.의 취득 일정은 다음과 같습니다. 계약금: 2026년 09월 10일 - 5억원 (주식양수 목적 실사 보증금 상계처리) 잔금: 2029년 09월 18일 - 123억원 1) 제9회차 전환사채 대용납입: 78억원 2) 현금: 45억원 - 상기 6.의 취득예정일자는 잔금 지급일입니다. - 상기 7.의 최근 사업년도말 자산총액은 당사의 2025년말 연결재무제표 기준입니다. - 하기 발행회사의 요약 재무상황의 당해연도, 전년도, 전전년도는 2025년, 2024년, 2023년의 재무제표 기준으로 작성하였습니다. [발행회사의 요약 재무상황] (단위 : 백만원) 구분 자산총계 부채총계 자본총계 자본금 매출액 당기순이익 당해년도 14,562 3,119 11,443 800 10,334 1,018 전년도 18,717 8,292 10,425 800 22,659 1,273 전전년도 18,336 8,197 10,139 800 38,745 1,339 [상대방에 관한 사항] 1. 인적사항 - 기본사항 성명(명칭) 국적 주소(본점소재지)[읍ㆍ면ㆍ동까지만 기재] 생년월일(사업자등록번호 등) 주식회사 리드엔지니어링 대한민국 충북 청주시 청원구 오창읍 317-81-02152 직업(사업내용) 반도체 제조용 기계 제조업 - 최대주주ㆍ대표이사ㆍ대표집행임원 현황 및 재무상황 등(상대방이 법인인 경우) 구분 성명 주식수 지분율(%) 최대주주 김현호 1,000 100.0 대표이사 김현호 1,000 100.0 (단위 : 백만원) 해당 사업연도 2025 결산기 12월 자산총계 14,562 자본금 800 부채총계 3,119 매출액 10,334 자본총계 11,443 당기순손익 1,018 외부감사인 청설공인회계사감사반(제230호) 휴업 여부 아니오 감사의견 적정 폐업 여부 아니오 2. 상대방과의 관계 1. 회사와 상대방과의 관계 - 2. 회사의 최대주주ㆍ임원과 상대방과의 관계 성명 상대방과의 관계 - - - 3. 최근 3년간 거래내역(일상적 거래 제외) 구분 거래 내역 당해년도 - 전년도 - 전전년도 -"""

PUT_NO = (
    "타법인 주식 및 출자증권 취득결정 발행회사 회사명(국적) (주)가나 국적 대한민국 "
    "회사와의 관계 계열회사 발행주식총수(주) 100 취득금액(원) 1,000,000 "
    "자기자본대비(%) 1.5 취득방법 현금취득 3. 취득목적 사업 확대 4. 거래상대방 "
    "12. 풋옵션 등 계약 체결여부 아니오 -계약내용 - 13. 기타 투자판단과 관련한 사항"
)


class TestPutOption:
    def test_체결된_건은_내용까지_같다(self):
        py = parse_acquisition_detail(PUT_YES)
        js = _viewer([PUT_YES])[0]
        assert py["put_option"] is True and js["putOption"] is True
        assert py["put_option_text"] == js["putOptionText"]
        assert "콜옵션" in py["put_option_text"], "계약 내용을 읽지 못했다"

    def test_아니오는_False다(self):
        """늘 「아니오」인 줄은 배경이지 신호가 아니다 — True로 새면 안 된다."""
        py = parse_acquisition_detail(PUT_NO)
        js = _viewer([PUT_NO])[0]
        assert py["put_option"] is False and js["putOption"] is False
        assert py["put_option_text"] == js["putOptionText"] == ""

    def test_두_표기형을_모두_읽는다(self):
        """「풋옵션계약 등의 체결여부」와 「풋옵션 등 계약 체결여부」."""
        assert "풋옵션계약 등의 체결여부" in PUT_YES
        assert "풋옵션 등 계약 체결여부" in PUT_NO
        for t in (PUT_YES, PUT_NO):
            assert parse_acquisition_detail(t)["put_option"] == _viewer([t])[0]["putOption"]

    def test_취득목적과_방법이_양쪽_다_나온다(self):
        """원문에 있는데 화면에 안 닿던 값들(실측 16/16 · 14/16)."""
        py = parse_acquisition_detail(PUT_YES)
        js = _viewer([PUT_YES])[0]
        assert py["purpose"] and py["purpose"] == js["purpose"]
        assert py["method"] == js["method"]
