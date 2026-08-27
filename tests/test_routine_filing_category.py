"""「정기 보고」 범주가 export만 되고 **뷰어에 배선돼 있지 않던** 것을 잠근다.

`scripts/export_tool_data.py`는 `routine_filing_keywords`와
`categories["9"] = "정기 보고"`를 진작 내보내고 있었고, 그 주석은 이렇게
적고 있었다 —

    뷰어의 classifyDisclosureCategory가 위험 신호 키워드 매칭에 전부
    실패한 뒤에만 이 번호를 반환한다.

**그런 함수가 없다.** 뷰어는 신호가 붙은 행에서만 카테고리를 그렸고, 신호가
없는 행은 전부 「—」였다. 데이터는 실려 나가는데 기능은 존재하지 않았다
(2026-08-27 — `DATA.*` 접근을 export 키와 대조하다 찾았다).

그래서 사업보고서·분기보고서가 「—」로만 보였다. 「기타」(모른다)가 아니라
**「정기 보고」(안다, 위험 신호가 아니다)**라는 별도 사실 범주다 — export
쪽 실측: 삼성전자 「기타」 982건 중 **924건**이 목록 첫 항목 하나였다.

⚠ **`--c9` 색이 CSS에 없었다** — 배선했어도 점이 투명하게 찍혔을 것이다.
"""
import json
import pathlib
import re
import shutil
import subprocess

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")
_DATA = json.loads((_ROOT / "docs" / "tool" / "signals-data.json")
                   .read_text(encoding="utf-8"))
_NODE = shutil.which("node")


def _fn():
    i = _HTML.index("function routineCategory(reportNm) {")
    j = _HTML.index("\n}", i)
    return _HTML[i:j + 2]


def _run(title, kws=None):
    data = {"routine_filing_keywords":
            kws if kws is not None else _DATA["routine_filing_keywords"]}
    script = (f"const DATA = {json.dumps(data, ensure_ascii=False)};\n{_fn()}\n"
              f"process.stdout.write(String(routineCategory("
              f"{json.dumps(title, ensure_ascii=False)})));")
    out = subprocess.run([_NODE, "-e", script], capture_output=True, text=True,
                         encoding="utf-8")
    assert out.returncode == 0, out.stderr
    return out.stdout


@pytest.mark.skipif(not _NODE, reason="node가 없어 뷰어 함수를 실행할 수 없습니다")
@pytest.mark.parametrize("title", [
    "사업보고서 (2024.12)",
    "분기보고서 (2025.03)",
    "주주총회소집공고",
    "임원ㆍ주요주주특정증권등소유상황보고서",
])
def test_정기_보고를_알아본다(title):
    assert _run(title) == "9"


@pytest.mark.skipif(not _NODE, reason="node가 없어 뷰어 함수를 실행할 수 없습니다")
@pytest.mark.parametrize("title", [
    "주요사항보고서(유상증자결정)", "최대주주변경", "", "증권신고서(합병)",
])
def test_그_밖은_범주를_주지_않는다(title):
    assert _run(title) == "null"


@pytest.mark.skipif(not _NODE, reason="node가 없어 뷰어 함수를 실행할 수 없습니다")
def test_목록이_비면_아무것도_주지_않는다():
    assert _run("사업보고서", kws=[]) == "null"


def test_export가_실제로_그_키를_낸다():
    assert _DATA["routine_filing_keywords"], "키워드 목록이 비었다"
    assert _DATA["categories"]["9"] == "정기 보고"


def test_색이_정의돼_있다():
    """배선만 하고 색이 없으면 점이 투명하게 찍힌다."""
    assert re.search(r"--c9:\s*#", _HTML), "--c9 색이 없다"


def test_피드가_그_함수를_쓴다():
    """헬퍼만 있고 아무도 안 부르면 예전과 같다."""
    assert _HTML.count("routineCategory(") >= 2
