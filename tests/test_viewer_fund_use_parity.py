"""뷰어의 용도 묶음 분류가 core `classify_fund_use`와 같은지 잠근다.

core를 고칠 때 뷰어가 안 따라오는 것이 이 저장소의 되풀이되는 결함이다
(`classifyOutflowRelation` 드리프트 v1.14.0, 페이지 예산 #318). 이번에는
뷰어가 **실제 집행 문구 자체를 가져오지 않고** 있었다 —
`normalizeFundUsageItem`이 `real_cptal_use_dtls_amount`(금액)만 담고
`..._cn`(문구)은 버렸다. 비교할 재료가 없으니 이탈을 볼 수도 없었다.

⚠ **소스 문자열 검색으로 확인하지 않는다.** node로 두 구현에 **같은 입력**을
넣어 결과를 맞춘다.
"""
import json
import pathlib
import shutil
import subprocess

import pytest

from dart_risk_mcp.core.dart_client import _FUND_USE_CATEGORIES, classify_fund_use

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")
_NODE = shutil.which("node")

# 30개사 2,877건 실측에서 실제로 나온 표기 + 경계 사례
_CASES = [
    "운영자금", "운영 자금", "운전자금", "시설자금", "채무상환", "채무상환자금",
    "타법인증권취득자금", "타법인 증권 취득 자금", "지분취득", "차입금상환",
    "자산취득", "본사 부동산 추가 취득", "R&D 센터 인프라 투자",
    "원재료 매입채무 결제", "운영자금\n(게임개발)", "신규사업 발굴/투자, 사업확장",
    "전환사채 상환(주)", "제5회EB조기상환", "기타", "-", "", "운영자금 및 시설자금",
]


def _js(fn_src, expr):
    out = subprocess.run([_NODE, "-e", fn_src + "\n" + expr],
                         capture_output=True, text=True, encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return out.stdout


def _viewer_src():
    def grab(start, end):
        i = _HTML.index(start)
        j = _HTML.index("\n" + end, i)
        return _HTML[i:j + len(end) + 1]

    return "\n".join([
        grab("const FUND_USE_CATEGORIES = [", "];"),
        grab("function classifyFundUse(text) {", "}"),
        grab("function fundUseShift(planText, realText) {", "}"),
    ])


@pytest.mark.skipif(not _NODE, reason="node가 없어 뷰어 함수를 실행할 수 없습니다")
def test_분류_결과가_core와_같다():
    payload = json.dumps(_CASES, ensure_ascii=False)
    got = _js(_viewer_src(),
              f"process.stdout.write(JSON.stringify({payload}.map(classifyFundUse)))")
    viewer = [sorted(x) for x in json.loads(got)]
    core = [sorted(classify_fund_use(c)) for c in _CASES]
    for c, v, k in zip(_CASES, viewer, core):
        assert v == k, f"{c!r}: 뷰어 {v} ≠ core {k}"


@pytest.mark.skipif(not _NODE, reason="node가 없어 뷰어 함수를 실행할 수 없습니다")
def test_묶음_개수가_같다():
    got = _js(_viewer_src(),
              "process.stdout.write(String(FUND_USE_CATEGORIES.length))")
    assert int(got) == len(_FUND_USE_CATEGORIES) == 4


@pytest.mark.skipif(not _NODE, reason="node가 없어 뷰어 함수를 실행할 수 없습니다")
@pytest.mark.parametrize("plan,real,shift", [
    ("운영자금", "타법인증권취득자금", True),
    ("운영자금", "운영자금", False),
    ("운영자금 및 시설자금", "시설자금", False),
    ("원재료 매입채무 결제", "운영자금", False),
    ("", "채무상환자금", False),
    ("기타", "기타", False),
])
def test_이탈_판정이_core와_같다(plan, real, shift):
    from dart_risk_mcp.core.dart_client import _detect_fund_anomaly

    rec = {"plan_useprps": plan, "real_dtls_cn": real, "plan_amount": 10,
           "real_dtls_amount": 10, "dffrnc_resn": "",
           "plan_cats": sorted(classify_fund_use(plan)),
           "real_cats": sorted(classify_fund_use(real))}
    assert ("FUND_DIVERSION" in _detect_fund_anomaly(rec)) is shift

    got = _js(_viewer_src(),
              "process.stdout.write(String(fundUseShift("
              f"{json.dumps(plan, ensure_ascii=False)}, "
              f"{json.dumps(real, ensure_ascii=False)}) !== null))")
    assert (got == "true") is shift


def test_뷰어가_실제_집행_문구를_담는다():
    """금액만 담던 것이 이 결함의 뿌리였다."""
    assert "real_dtls_cn:" in _HTML
    assert "real_cptal_use_dtls_cn" in _HTML
