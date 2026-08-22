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
        if l.rstrip().endswith("];") or l.rstrip().endswith("/i;"):
            break
    return "\n".join(out)


def _viewer(texts):
    html = _HTML.read_text(encoding="utf-8")
    # parseAcquisitionDetail은 splitIssuerNation·ACQ_CORP_FORM_RE에 의존한다
    form_re = _cut_const(html, "const ACQ_CORP_FORM_RE")
    nation_tokens = _cut_const(html, "const ACQ_NATION_TOKENS")
    js = (form_re + "\n"
          + nation_tokens + "\n"
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
