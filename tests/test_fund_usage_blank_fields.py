"""자금사용 응답의 **미기재(`"-"`)를 값으로 읽지 않는지** 잠근다.

DART `pssrpCptalUseDtls`/`prvsrpCptalUseDtls`는 빈 칸을 `"-"`로 준다.
파이썬에서 `"-"`는 참이고 `_to_int_safe("-")`는 0이라, 그대로 두면 화면이
**없는 사실을 말한다**:

    납입 0원          ← 0원이 납입된 게 아니라 그 칸이 비어 있다
    차이사유: -       ← 사유가 「-」인 게 아니라 안 적혀 있다
    계획: (공란) (0원)  ← 행 전체가 빈 껍데기

실측(2026-08-28, 6개사 937건 · 응답 39행 전수):

    pay_amount 미기재        937 / 937  (100%)
    「차이사유: -」 출력      KB금융 3년 499줄
    행 전체가 빈 껍데기      아틀라스링크 36건 중 20건 · KB금융 12건

⚠ **`tests/test_no_dead_fields.py`는 이 부류를 못 잡는다.** 그 검사는 "읽기만
하고 아무도 안 넣는 키"를 찾는데 `pay_amount`는 응답에 **있다**(값이 `"-"`일
뿐). 「키는 있는데 값이 늘 비어 있는」 것은 다른 부류다.
"""
import pathlib
import re

import pytest

from dart_risk_mcp.core.dart_client import _fund_text

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SERVER = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")


@pytest.mark.parametrize("raw", ["-", "–", "—", "", "  -  ", None,
                                 "해당사항없음", "해당사항 없음"])
def test_미기재_표기는_빈_값이_된다(raw):
    assert _fund_text(raw) == ""


@pytest.mark.parametrize("raw,expect", [
    ("운영자금", "운영자금"),
    ("  시설자금  ", "시설자금"),
    ("채무상환자금(회사채 등)", "채무상환자금(회사채 등)"),
    ("A-B 사업", "A-B 사업"),          # 값 안의 하이픈은 살린다
])
def test_실제_값은_보존된다(raw, expect):
    assert _fund_text(raw) == expect


def test_납입금액이_없으면_0원이라_적지_않는다():
    """DART가 `pay_amount`를 늘 미기재로 준다 — 「납입 0원」은 거짓이다."""
    i = _SERVER.index("for rec in _shown:")
    body = _SERVER[i:i + 1400]
    assert 'if rec.get("pay_amount"):' in body, "금액 유무를 가르지 않는다"
    assert 'elif rec.get("pay_de"):' in body, "대신 쓸 납입일 경로가 없다"
    assert re.search(r'f"납입 \{rec\[.pay_amount.\]:,\}원"\s*\n\s*\)', body) is None, (
        "무조건 「납입 N원」을 찍는 옛 형태가 남아 있다"
    )


def test_빈_껍데기_행은_목록에서_빠지고_건수가_밝혀진다():
    i = _SERVER.index("def _is_blank_record(")
    body = _SERVER[i:i + 700]
    for field in ("plan_useprps", "real_dtls_cn", "dffrnc_resn", "pay_de",
                  "plan_amount", "real_dtls_amount", "flags"):
        assert field in body, f"{field}를 빈 판정에 넣지 않았다"
    assert "계획·실제가 모두 미기재인" in _SERVER, "제외 건수를 밝히지 않는다"


def test_총_건수는_빈_행_제외와_무관하다():
    """조회된 것은 조회된 것이다 — 집계를 목록 기준으로 바꾸면 안 된다."""
    i = _SERVER.index("def track_fund_usage(")
    body = _SERVER[i:i + 9000]
    assert re.search(r"총 \{len\(records\)\}건 조회", body)
    assert "len(_usable)}건 조회" not in body
    assert "len(_shown)}건 조회" not in body


def test_플래그가_있으면_빈_행으로_보지_않는다():
    """플래그가 붙었다면 판정에 쓰인 값이 있었다는 뜻이다."""
    i = _SERVER.index("def _is_blank_record(")
    assert 'r.get("flags")' in _SERVER[i:i + 700]


# ── 뷰어 쌍둥이 ──────────────────────────────────────────────────────────
#
# 뷰어는 core보다 **나쁘게** 틀렸다 — core는 `"-"`를 그대로 보여줘 사용자가
# 미기재임을 알 수 있었지만, 뷰어는 그것을 「집행 차이 사유 보고 있음」이라는
# **판단 문장**으로 바꾼다(`hasDiff = entry.uses.some(u => u.diff_reason)`).

import json
import os
import shutil
import subprocess
import tempfile

_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")


def _cut(head: str) -> str:
    i = _HTML.index(head)
    depth, j, in_s, q = 0, i, False, ""
    while j < len(_HTML):
        c = _HTML[j]
        if in_s:
            if c == "\\":
                j += 2
                continue
            if c == q:
                in_s = False
        elif c in "\"'`":
            in_s, q = True, c
        elif c == "{":
            depth += 1
        elif c == "}":
            depth -= 1
            if depth == 0:
                return _HTML[i:j + 1]
        j += 1
    raise AssertionError(head)


@pytest.mark.skipif(shutil.which("node") is None, reason="node 없음")
def test_뷰어_정규화가_core와_같은_값을_낸다():
    tokens = [l for l in _HTML.splitlines()
              if l.startswith("const FUND_BLANK_TOKENS")]
    assert tokens, "뷰어에 미기재 목록이 없다"
    src = tokens[0] + "\n" + _cut("function fundText(")
    cases = ["-", "", "  -  ", "운영자금", "A-B 사업", "해당사항없음", "–", "—"]
    js = (src + "\nconst C = " + json.dumps(cases, ensure_ascii=False) +
          ";\nconsole.log(JSON.stringify(C.map(fundText)));")
    tf = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    tf.write(js)
    tf.close()
    try:
        r = subprocess.run([shutil.which("node"), tf.name],
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, r.stderr[:800]
        got = json.loads(r.stdout)
    finally:
        os.unlink(tf.name)
    assert got == [_fund_text(c) for c in cases]


def test_뷰어가_대시를_그대로_두지_않는다():
    i = _HTML.index("function normalizeFundUsageItem(")
    body = _HTML[i:i + 1400]
    assert "fundText(item.dffrnc_occrrnc_resn)" in body, (
        "차이사유가 정규화를 안 거친다 — 「-」가 참이라 「사유 보고 있음」이 거짓으로 뜬다"
    )
    assert '(item.dffrnc_occrrnc_resn || "").trim()' not in body, "옛 형태가 남아 있다"
    assert "fundText(item.pay_de)" in body
