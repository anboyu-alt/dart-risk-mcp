"""core(Python) ↔ 뷰어(JS) 원문 파서 동등성 — 실측 원문 픽스처 전수 대조.

v1.13.4/v1.14.0에서 core에 들어간 원문 확인 계층 3종이 뷰어에 이식됐다.
두 레이어는 로직을 각자 이식하므로 드리프트가 생긴다 — 실제로 이 이식 과정에서
뷰어의 `classifyOutflowRelation`에 core의 2026-08-04 수정(부정 표기 우선 검사)이
빠져 있던 것을 발견했다("특수관계 없음"을 계열로 읽어 CRITICAL 패턴이 오발화).

픽스처는 실제 DART 원문의 특징 구간을 옮긴 것이며, 라이브 8건 대조는
별도로 수행했다(전부 일치). node가 없으면 건너뛴다.
"""
import json
import os
import pathlib
import re
import shutil
import subprocess
import tempfile

import pytest

from dart_risk_mcp.core.dart_client import (
    classify_outflow_relation,
    parse_asset_disposal_detail,
    parse_earnings_shock_detail,
    parse_related_party_detail,
)

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = _ROOT / "docs" / "tool" / "index.html"

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node가 없어 뷰어 JS를 실행할 수 없다"
)

_CONSTS = (
    "AMENDED_DOC_MARKERS", "AFFIL_DASH_VALUES",
    "DISPOSAL_COUNTERPARTY_RES", "DISPOSAL_RELATION_RE", "DISPOSAL_AMOUNT_RE",
    "DISPOSAL_AMOUNT_BARE_RE", "DISPOSAL_UNIT_MILLION_RE", "DISPOSAL_RATIO_RE",
    "DISPOSAL_BOOK_RE", "DISPOSAL_EXTVAL_RE", "RELATION_LOOKS_DIRTY_RE",
    "RP_COUNTERPARTY_RES", "RP_RELATION_RE", "RP_AMOUNT_RE", "RP_RATE_RE",
    "RP_EQUITY_RE", "RP_UNIT_MILLION_RE", "RP_UNIT_EOK_RE", "ES_ROW_RE",
    "ASSET_DISPOSAL_TITLE_MARKS", "OUTFLOW_SUBSIDIARY_KEYWORDS",
    "OUTFLOW_AFFILIATED_KEYWORDS", "OUTFLOW_EXTERNAL_VALUES",
    "OUTFLOW_NEGATION_MARKERS",
)
_FUNCS = (
    # `mdToPlain`은 뷰어가 받는 마크다운 표를 core가 보는 평문 모양으로
    # 맞춘다. 이 파일은 **평문을 양쪽에 먹이므로** 그 정규화가 무해한지도
    # 함께 검사하는 셈이다 — 표 표현 자체의 대조는
    # `test_viewer_markdown_input.py`가 맡는다.
    "mdToPlain",
    "isAmendedDocument", "affiliateInt", "affiliateRatio",
    "parseAssetDisposalDetail", "parseRelatedPartyDetail",
    "parseEarningsShockDetail", "isAssetDisposalTitle", "classifyOutflowRelation",
)

# 실측 원문의 특징 구간(서식별 1종 이상)
RP_DOCS = [
    # 백만원 단위 + 이자율 + 자기자본대비 (포승그린파워 20260812000839)
    "특수관계인으로부터 자금차입 (단위 : 백만 원) 1. 차입처 (주)엘엑스인터내셔널 "
    "회사와의 관계 계열회사 다. 차입기간 2026 라. 차입금액 120,000 "
    "- 직전사업연도말 자기자본 63,925 - 자기자본대비 (%) 187.72 마. 이자율 (%) 연 4.6",
    # 억원 단위 (삼성전자 20260730000505)
    "특수관계인에 대한 출자 (단위 : 억원) 1. 거래상대방 SVIC 83호 회사와의 관계 출자조합 "
    "2. 출자내역 다. 출자금액 2,970 라. 출자상대방 총출자액 3,000",
    # 담보 서식
    "특수관계인으로부터 받은 담보 (단위 : 백만 원) 1. 담보제공자 (주)엘엑스인터내셔널 "
    "회사와의 관계 계열회사 나. 담보금액 44,974",
    # 정정 원문 — 양쪽 다 읽지 않아야 한다
    "특수관계인으로부터 자금차입 정정신고(보고) 정정일자 2026-08-21 1. 차입처 (주)가나 "
    "회사와의 관계 계열회사 라. 차입금액 120,000",
    "",
]
AS_DOCS = [
    "유형자산 처분결정 거래상대방 한미반도체 주식회사 회사와의 관계 - "
    "2. 처분내역 처분금액 (원) 56,000,000,000 자산총액 대비 (%) 19.72",
    "특수관계인에 대한 자산양도 (단위 : 백만 원) 1. 거래상대방 (주)가나 회사와의 관계 "
    "계열회사 다. 양도가액 12,899",
    # 실측 서식(에스케이지오센트릭 20260804000488) — 관계 뒤에 항목 번호가 온다
    "특수관계인에 대한 자산양도 (단위 : 백만 원) 1. 거래상대방 에스케이하이퍼(주) "
    "회사와의 관계 계열회사 (편입 예정) 2. 자산양도 내역 다. 양도가액 103,431",
    # 종료 앵커를 못 만나 표를 삼킨 오염형 — 양쪽 다 관계를 버려야 한다
    "비유동자산 처분결정 양수법인 에이치에스효성첨단소재 - 회사와의 관계 계열회사 "
    "처분금액 (원) 264,300,000,000 자산총액 대비 (%) 455.63 외부평가 여부 예",
    "포커스에이아이/유형자산처분결정(자율공시) 정정신고(보고) 정정일자 2026-08-21 "
    "3. 정정사유 소유권을 매수자(거래상대방)에게 양도 예정함 4. 정정사항 정정항목 "
    "정정전 정정후 2.처분내역-처분금액(원) 2,697,773,850 3,064,686,070",
    "",
]
ES_DOCS = [
    "매출액또는손익구조 30% 이상 변동 손익구조 "
    "- 매출액 35,517,233,415 32,888,839,235 2,628,394,180 7.99 - "
    "- 영업이익 4,000,000,000 3,000,000,000 1,000,000,000 32.1 - "
    "- 당기순이익 -3,000,000,000 1,000,000,000 -4,000,000,000 -400.0 적자전환",
    "매출액또는손익구조 변동 손익구조 - 매출액 100 200 -100 - -",
    "매출액또는손익구조 변동 정정신고(보고) 정정일자 2026-01-01 손익구조 "
    "- 매출액 100 200 -100 -50.0 -",
    "",
]
REL_VALUES = ["계열회사", "종속회사", "자회사", "관계회사", "특수관계인",
              "특수관계 없음", "최대주주 아님", "해당없음", "타인", "-", "",
              "임원", "대표이사", "출자조합", "기타"]


def _cut(html: str, name: str) -> str:
    i = html.index("function " + name + "(")
    b = html.index("{", i)
    depth = 0
    for j in range(b, len(html)):
        if html[j] == "{":
            depth += 1
        elif html[j] == "}":
            depth -= 1
            if depth == 0:
                return html[i:j + 1]
    raise AssertionError("중괄호가 맞지 않는다: " + name)


def _cut_const(html: str, name: str) -> str:
    m = re.search(r"^const " + name + r"\s*=\s*[\s\S]*?;\s*$", html, re.M)
    assert m, "상수를 찾지 못했다: " + name
    return m.group(0)


def _run_viewer() -> dict:
    html = _HTML.read_text(encoding="utf-8")
    src = "\n".join(
        [_cut_const(html, c) for c in _CONSTS] + [_cut(html, f) for f in _FUNCS]
    )
    js = (
        src + "\n"
        + "const RP = " + json.dumps(RP_DOCS, ensure_ascii=False) + ";\n"
        + "const AS = " + json.dumps(AS_DOCS, ensure_ascii=False) + ";\n"
        + "const ES = " + json.dumps(ES_DOCS, ensure_ascii=False) + ";\n"
        + "const RV = " + json.dumps(REL_VALUES, ensure_ascii=False) + ";\n"
        + "console.log(JSON.stringify({\n"
        + "  rp: RP.map(parseRelatedPartyDetail),\n"
        + "  as: AS.map(parseAssetDisposalDetail),\n"
        + "  es: ES.map(parseEarningsShockDetail),\n"
        + "  rel: RV.map(classifyOutflowRelation),\n"
        + "}));\n"
    )
    tf = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    tf.write(js)
    tf.close()
    try:
        r = subprocess.run([shutil.which("node"), tf.name],
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, "node 실패:\n" + (r.stderr or "")[:2000]
        return json.loads(r.stdout)
    finally:
        os.unlink(tf.name)


@pytest.fixture(scope="module")
def viewer():
    return _run_viewer()


class TestParserParity:
    def test_특수관계인_자금거래_파서가_같은_값을_낸다(self, viewer):
        for doc, got in zip(RP_DOCS, viewer["rp"]):
            exp = parse_related_party_detail(doc)
            assert got["counterparty"] == exp["counterparty"], doc[:40]
            assert got["relation"] == exp["relation"], doc[:40]
            assert got["amount"] == exp["amount"], doc[:40]
            assert got["interestRate"] == exp["interest_rate"], doc[:40]
            assert got["equityRatio"] == exp["equity_ratio"], doc[:40]
            assert got["kind"] == exp["kind"], doc[:40]

    def test_자산처분_파서가_같은_값을_낸다(self, viewer):
        for doc, got in zip(AS_DOCS, viewer["as"]):
            exp = parse_asset_disposal_detail(doc)
            assert got["counterparty"] == exp["counterparty"], doc[:40]
            assert got["relation"] == exp["relation"], doc[:40]
            assert got["amount"] == exp["amount"], doc[:40]
            assert got["assetRatio"] == exp["asset_ratio"], doc[:40]
            assert got["bookValue"] == exp["book_value"], doc[:40]
            assert got["extval"] == exp["extval"], doc[:40]

    def test_손익구조_파서가_같은_값을_낸다(self, viewer):
        for doc, got in zip(ES_DOCS, viewer["es"]):
            exp = parse_earnings_shock_detail(doc)
            assert len(got["rows"]) == len(exp["rows"]), doc[:40]
            for g, e in zip(got["rows"], exp["rows"]):
                assert g["account"] == e["account"]
                assert g["current"] == e["current"]
                assert g["prior"] == e["prior"]
                assert g["change"] == e["change"]
                assert g["changePct"] == e["change_pct"]
                assert g["turn"] == e["turn"]
            assert got["turnedToLoss"] == exp["turned_to_loss"], doc[:40]

    def test_관계_분류가_같다(self, viewer):
        for val, got in zip(REL_VALUES, viewer["rel"]):
            assert got == classify_outflow_relation(val), val


class TestKnownRegressions:
    """이식 과정에서 실제로 발견한 결함들을 고정한다."""

    def test_부정_표기가_계열로_읽히지_않는다(self, viewer):
        """뷰어에 core 2026-08-04 수정이 빠져 있었다 — CRITICAL 패턴 오발화 원인."""
        for val in ("특수관계 없음", "최대주주 아님"):
            assert viewer["rel"][REL_VALUES.index(val)] == "external", val

    def test_관계_미추출은_external이_아니라_unknown이다(self, viewer):
        """옛 뷰어 코드는 모르는 값을 전부 external로 떨어뜨렸다."""
        assert viewer["rel"][REL_VALUES.index("")] == "unknown"
        assert viewer["rel"][REL_VALUES.index("기타")] == "unknown"

    def test_억원_단위를_원으로_오인하지_않는다(self, viewer):
        """놓치면 실제의 1억분의 1로 표기된다(삼성전자 2,970억원 → 2970)."""
        assert viewer["rp"][1]["amount"] == 297_000_000_000

    def test_정정_원문은_양쪽_다_읽지_않는다(self, viewer):
        assert viewer["rp"][3]["counterparty"] == ""
        assert viewer["as"][4]["counterparty"] == ""
        assert viewer["as"][4]["amount"] == 0

    def test_관계값이_표를_삼키면_미기재로_버린다(self, viewer):
        """40자로 자르면 "계열회사 처분금액 (원) 264,300,0…"가 화면에 남는다."""
        assert viewer["as"][3]["relation"] == ""
        assert viewer["as"][3]["counterparty"] == "에이치에스효성첨단소재"  # 상대는 유지
        assert viewer["as"][2]["relation"] == "계열회사 (편입 예정)"  # 실측형은 그대로
        assert viewer["es"][2]["rows"] == []


class TestOutflowBlockScope:
    """자금유출 상대방 블록이 두 계열을 모두 담는지 (v1.18.3).

    core는 `_confirm_outflow_counterparties`가 자산 처분(5.3)과 금전대여·
    채무보증·담보제공(5.7)을 함께 처리하고, v1.13.4에서 **게이트와 무관하게**
    렌더하도록 고쳤다 — 확인된 상대방은 패턴 주장이 아니라 사실이라,
    경영권 변경이 없어 capital_backflow가 성립하지 않는 회사에서도 남아야 한다.

    뷰어는 그 수정이 절반만 이식돼 있었다. 자산 처분은 독립 블록이 됐지만
    금전대여·담보제공은 패턴 카드 경로에만 실려 통째로 사라졌다.
    """

    def _html(self):
        return _HTML.read_text(encoding="utf-8")

    def test_두_신호를_모두_후보로_삼는다(self):
        src = _cut(self._html(), "loadAssetTransferCore")
        assert 'detailBlockHits("ASSET_TRANSFER"' in src
        assert 'detailBlockHits("FUND_OUTFLOW"' in src

    def test_제목으로_파서를_가른다(self):
        """자산 처분과 금전대여는 원문 서식이 다르다."""
        src = _cut(self._html(), "loadAssetTransferCore")
        assert "isAssetDisposalTitle" in src
        assert "parseAssetDisposalDetail" in src
        assert "parseOutflowDetail" in src

    def test_중복_접수번호를_거른다(self):
        src = _cut(self._html(), "loadAssetTransferCore")
        assert "seen.has" in src or "seen.add" in src

    def test_컨테이너가_두_신호_중_하나만_있어도_생긴다(self):
        html = self._html()
        i = html.index('id="atCore"')
        head = html[max(0, i - 400):i]
        assert "FUND_OUTFLOW" in head and "ASSET_TRANSFER" in head

    def test_관계_표기가_중복되지_않는다(self):
        """원문이 "종속회사"이고 분류도 "종속회사"면 한 번만 쓴다."""
        src = _cut(self._html(), "assetTransferCardHTML")
        assert "relRaw === clsLabel" in src


class TestViewerFairTradeFormat:
    """뷰어 `parseOutflowDetail`의 공정거래법 제26조 서식 (2026-08-23).

    core와 **입력이 다르다** — core는 태그를 지운 평문을, 뷰어는 `/api/doc`가
    만든 마크다운 표를 받는다. 그래서 구현도 다르지만, 같은 공백이 양쪽에
    있었다: 「거래상대방」 라벨을 몰라 공정위 서식(「특수관계인에대한자금대여」·
    「특수관계인에대한담보제공」, 1년 920건 이상)에서 상대방이 빈 값이었다.

    ⚠ 금액은 이 서식만 「(단위 : 백만 원)」이고 필드명에 "(원)"이 없다.
    그리고 뷰어의 `norm()`은 숫자 접두("2.")만 떼고 한글 항목 기호("바.")는
    남기므로 패턴이 그걸 허용해야 한다.
    """

    FT_COLLATERAL = (
        "\n| 관련법규 | 공정거래법 제26조 |\n|---|---|\n\n| (단위 : 백만 원) |\n|---|\n\n"
        "| 1. 거래상대방 | 아산배방개발(주) | 회사와의 관계 | 계열회사 |\n"
        "|---|---|---|---|\n| 바. 담보금액 | 305,800 |\n"
    )
    FT_LOAN = (
        "\n| 관련법규 | 공정거래법 제26조 |\n|---|---|\n\n"
        "| 1. 거래상대방 | 손제호 | 회사와의 관계 | 임원 |\n"
        "|---|---|---|---|\n| 나. 거래금액 | 4,900 |\n"
    )
    MSR_LOAN = (
        "\n| 1. 대여 상대 | (주)한국파일 |\n|---|---|\n"
        "| 회사와의 관계 | 종속회사 |\n| 대여금액(원) | 5,000,000,000 |\n"
    )
    MSR_GUARANTEE = (
        "\n| 1. 채무자 | 분양계약자 |\n|---|---|\n"
        "| 회사와의 관계 | - |\n| 채무보증금액(원) | 100,000,000,000 |\n"
    )

    def _parse(self, texts):
        html = _HTML.read_text(encoding="utf-8")
        import re as _re
        m = _re.search(r"^const AFFIL_DASH_VALUES\s*=\s*[\s\S]*?;\s*$", html, _re.M)
        src = ((m.group(0) if m else "") + "\n"
               + _cut(html, "affiliateInt") + "\n" + _cut(html, "parseOutflowDetail"))
        js = (src + "\nconst T=" + json.dumps(texts, ensure_ascii=False)
              + ";\nconsole.log(JSON.stringify(T.map(parseOutflowDetail)));")
        tf = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
        tf.write(js)
        tf.close()
        try:
            r = subprocess.run([shutil.which("node"), tf.name],
                               capture_output=True, text=True, encoding="utf-8")
            assert r.returncode == 0, r.stderr[:500]
            return json.loads(r.stdout)
        finally:
            os.unlink(tf.name)

    def test_공정위_서식_상대방과_관계를_읽는다(self):
        got = self._parse([self.FT_COLLATERAL, self.FT_LOAN])
        assert got[0]["counterparty"] == "아산배방개발(주)"
        assert got[0]["relation"] == "계열회사"
        assert got[1]["counterparty"] == "손제호"
        assert got[1]["relation"] == "임원"

    def test_공정위_금액을_원_단위로_환산한다(self):
        got = self._parse([self.FT_COLLATERAL, self.FT_LOAN])
        assert got[0]["amount"] == "305800000000"
        assert got[1]["amount"] == "4900000000"

    def test_기존_서식이_밀리지_않는다(self):
        got = self._parse([self.MSR_LOAN, self.MSR_GUARANTEE])
        assert got[0]["counterparty"] == "(주)한국파일"
        assert got[0]["relation"] == "종속회사"
        assert got[0]["amount"] == "5,000,000,000"
        assert got[1]["counterparty"] == "분양계약자"
        assert got[1]["amount"] == "100,000,000,000"


class TestViewerTangibleAcquisitionFormat:
    r"""유형자산 양수/양도 서식 — 값 자리에 **하위 라벨**이 온다.

    사용자 제보(2026-08-23): 아틀라스링크 1년 조회 OUTFLOW 패널에
    「상대: 회사명(성명) — 1원」이 떴다. 둘 다 값이 아니다.

        | 6. 거래상대방 | 회사명(성명) | ㈜ 로아앤코홀딩스 |
          ^라벨          ^하위 라벨      ^값
        | 2. 양수내역   | 양수금액(원)  | 17,400,000,000 |
        | 7. 거래대금지급 | 1. 지급형태 : 현금… |

    원인이 둘이었고 도입 시점도 다르다.

    | 증상 | 원인 | 도입 |
    |---|---|---|
    | 상대 「회사명(성명)」 | `isCpLabel`에 「거래상대방」을 넣어 다음 셀(=하위 라벨)을 값으로 받음 | **#218** |
    | 금액 「1」 | `거래대금[^\d]{0,10}([0-9,]+)`이 「거래대금지급 1. 지급형태」의 **열거번호**를 잡음 | dfbc580 |

    #218 이전에는 상대방이 「㈜ 로아앤코홀딩스」로 맞았다(금액은 그때도 1).
    26건 라이브 대조에서 기존 서식 11건은 불변, 15건은 빈 값 → 실제 값으로
    개선됐다.
    """

    TANGIBLE_ACQ = (
        "\n| 2. 양수내역 | 양수금액(원) | 17,400,000,000 |\n|---|---|---|\n"
        "| 자산총액(원) | 112,469,562,455 |\n| 자산총액대비(%) | 15.47 |\n"
        "| 6. 거래상대방 | 회사명(성명) | ㈜ 로아앤코홀딩스 |\n"
        "| 자본금(원) | 2,544,970,500 |\n| 주요사업 | 연예인 매니지먼트 |\n"
        "| 회사와의 관계 | 계열회사 |\n"
        "| 7. 거래대금지급 | 1. 지급형태 : 현금2. 지급조건 및 시기 : … |\n"
    )
    TANGIBLE_ACQ_NO_REL = (
        "\n| 2. 양수내역 | 양수금액(원) | 21,600,000,000 |\n|---|---|---|\n"
        "| 6. 거래상대방 | 회사명(성명) | 정은산업 주식회사 |\n"
        "| 회사와의 관계 | - |\n"
        "| 7. 거래대금지급 | 1. 지급형태: 현금2. 지급시기 및 조건:- 계약금 … |\n"
    )
    FAIRTRADE = (
        "\n| 관련법규 | 공정거래법 제26조 |\n|---|---|\n\n| (단위 : 백만 원) |\n|---|\n\n"
        "| 1. 거래상대방 | 아산배방개발(주) | 회사와의 관계 | 계열회사 |\n"
        "|---|---|---|---|\n| 바. 담보금액 | 305,800 |\n"
    )
    LOAN = (
        "\n| 1. 대여 상대 | (주)한국파일 |\n|---|---|\n"
        "| 회사와의 관계 | 종속회사 |\n| 대여금액(원) | 5,000,000,000 |\n"
    )

    def _parse(self, texts):
        html = _HTML.read_text(encoding="utf-8")
        import re as _re
        consts = "\n".join(
            ln for ln in html.split("\n")
            if ln.strip().startswith(("const AMENDED_DOC_MARKERS",
                                      "const AFFIL_DASH_VALUES")))
        src = consts + "\n" + "\n".join(
            _cut(html, f) for f in
            ("affiliateInt", "isAmendedDocument", "parseOutflowDetail"))
        js = (src + "\nconst T=" + json.dumps(texts, ensure_ascii=False)
              + ";\nconsole.log(JSON.stringify(T.map(parseOutflowDetail)));")
        tf = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False,
                                         encoding="utf-8")
        tf.write(js)
        tf.close()
        try:
            r = subprocess.run([shutil.which("node"), tf.name],
                               capture_output=True, text=True, encoding="utf-8")
            assert r.returncode == 0, r.stderr[:600]
            return json.loads(r.stdout)
        finally:
            os.unlink(tf.name)

    def test_하위_라벨을_상대방으로_받지_않는다(self):
        got = self._parse([self.TANGIBLE_ACQ, self.TANGIBLE_ACQ_NO_REL])
        assert got[0]["counterparty"] == "㈜ 로아앤코홀딩스"
        assert got[1]["counterparty"] == "정은산업 주식회사"
        for g in got:
            assert g["counterparty"] != "회사명(성명)"

    def test_양수금액을_읽는다(self):
        got = self._parse([self.TANGIBLE_ACQ, self.TANGIBLE_ACQ_NO_REL])
        assert got[0]["amount"] == "17,400,000,000"
        assert got[1]["amount"] == "21,600,000,000"

    def test_열거번호를_금액으로_잡지_않는다(self):
        """「7. 거래대금지급 | 1. 지급형태」의 1이 금액이 되면 안 된다."""
        only_enum = ("\n| 6. 거래상대방 | 회사명(성명) | 가나 주식회사 |\n|---|---|---|\n"
                     "| 7. 거래대금지급 | 1. 지급형태: 현금 |\n")
        assert self._parse([only_enum])[0]["amount"] == ""

    def test_관계는_그대로_읽는다(self):
        got = self._parse([self.TANGIBLE_ACQ, self.TANGIBLE_ACQ_NO_REL])
        assert got[0]["relation"] == "계열회사"
        assert got[1]["relation"] == "-"

    def test_공정위_서식이_깨지지_않는다(self):
        """#218이 고친 것 — 이번 수정이 되돌리면 안 된다."""
        got = self._parse([self.FAIRTRADE])[0]
        assert got["counterparty"] == "아산배방개발(주)"
        assert got["relation"] == "계열회사"
        assert got["amount"] == "305800000000"

    def test_기존_금전대여가_깨지지_않는다(self):
        got = self._parse([self.LOAN])[0]
        assert got["counterparty"] == "(주)한국파일"
        assert got["relation"] == "종속회사"
        assert got["amount"] == "5,000,000,000"
