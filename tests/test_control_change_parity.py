"""최대주주변경 원문 파서를 core ↔ 뷰어로 대조한다.

쌍둥이 함수 45쌍을 훑다 **이 쌍만 어느 테스트에도 이름이 없는 것**을 찾았다
(2026-08-30). 위험도가 가장 높은 자리였다.

    core    `parse_control_change_detail`  — 평문 정규식
    뷰어    `parseControlChangeDetail`     — `|`·개행 셀 분할 + `valueAfter` 인덱스 탐색

**구현 전략이 아예 다르다.** 반환 키도 `prev_holder` ↔ `prevHolder`로 갈려
있어 대조하려면 키 매핑이 필요했고, 그래서 아무도 안 썼던 것으로 보인다.
여기서 나오는 값이 「🔁 최대주주 변경 상세」 블록의 전부다 — 신규 최대주주
명칭·지분율·인수자금(자기자금/차입금/차입처/담보내역). 어긋나면 같은 회사에
MCP와 뷰어가 다른 사실을 낸다.

## 대조 결과: 어긋나지 않았다

CLAUDE.md가 라이브 매칭으로 기록한 **표기 변형 4건 전부**에서 9개 필드가 모두
일치했다. 결함은 없었고 **잠금이 없었을 뿐**이다.

    control_change_oein       20260709900615  아틀라스링크  「외 1인」(공백형)
    control_change_oenmyeong  20260728900445  졸스          「외N명」(붙임형)
    control_change_plain      20260728900521  제이케이시냅스 접미 없음 · (주) 접미
    control_change_person     20260727900769  선광          개인명 · 「외 22」 단위 생략

## 각자 받는 표현을 먹인다

core는 `fetch_document_text`(평문)를, 뷰어는 `/api/doc`(마크다운 표)을 받는다.
같은 문자열을 양쪽에 먹이면 **파서 차이가 아니라 입력 차이**를 재게 된다
(`test_viewer_markdown_input.py` 참고 — 그 실수를 실제로 한 적이 있다).
픽스처는 두 표현을 따로 저장한다.

⚠ **덮지 못한 경로**: 4건 모두 `borrowed_fund == 0`이다. 금감원 무자본 M&A
합동점검이 지목한 **주식담보대출(차입금>0)** 경로는 양쪽 다 라이브 사례가 없어
여전히 미검증이다(CLAUDE.md 라이브 검증 매트릭스에도 같은 한계가 적혀 있다).
사례를 찾으면 픽스처에 추가할 것.
"""
import json
import os
import pathlib
import shutil
import subprocess
import tempfile

import pytest

from dart_risk_mcp.core.dart_client import parse_control_change_detail

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")
_FX = json.loads(
    (_ROOT / "tests" / "fixtures" / "viewer" / "doc_representations.json")
    .read_text(encoding="utf-8"))

_TAGS = ["control_change_oein", "control_change_oenmyeong",
         "control_change_plain", "control_change_person"]

pytestmark = pytest.mark.skipif(
    shutil.which("node") is None, reason="node가 없으면 뷰어 쪽을 돌릴 수 없다")


def _cut(name: str) -> str:
    """중괄호 균형으로 함수 하나를 떼어낸다(문자열 안의 괄호는 세지 않는다)."""
    i = _HTML.index(f"function {name}(")
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
    raise AssertionError(name)


def _const(name: str) -> str:
    lines = _HTML.splitlines()
    i = next(k for k, l in enumerate(lines) if l.startswith(f"const {name} "))
    buf = []
    for l in lines[i:]:
        buf.append(l)
        if l.rstrip().endswith(";"):
            break
    return "\n".join(buf)


def _run_viewer(text: str) -> dict:
    src = _const("AMENDED_DOC_MARKERS")
    for fn in ("mdToPlain", "isAmendedDocument", "_ctrlAmountToInt",
               "_ctrlDashToEmpty", "parseControlChangeDetail"):
        src += "\n" + _cut(fn)
    src += (f"\nconst T={json.dumps(text, ensure_ascii=False)};"
            "\nconsole.log(JSON.stringify(parseControlChangeDetail(T)));")
    tf = tempfile.NamedTemporaryFile("w", suffix=".js", delete=False, encoding="utf-8")
    tf.write(src)
    tf.close()
    try:
        r = subprocess.run([shutil.which("node"), tf.name],
                           capture_output=True, text=True, encoding="utf-8")
        assert r.returncode == 0, f"node 실패:\n{(r.stderr or '')[:1200]}"
        return json.loads(r.stdout)
    finally:
        os.unlink(tf.name)


def _snake(key: str) -> str:
    return "".join(("_" + c.lower()) if c.isupper() else c for c in key)


def test_픽스처가_두_표현을_모두_담고_있다():
    for tag in _TAGS:
        fx = _FX[tag]
        assert fx["plain"] and fx["md"]
        assert fx["md"] != fx["plain"], "같은 문자열이면 입력 차이를 못 잰다"
        assert "|" in fx["md"], "마크다운 표가 아니다"


@pytest.mark.parametrize("tag", _TAGS)
def test_아홉_필드가_모두_일치한다(tag):
    fx = _FX[tag]
    core = parse_control_change_detail(fx["plain"])
    view = {_snake(k): v for k, v in _run_viewer(fx["md"]).items()}
    assert core, "core가 아무것도 못 읽었다 — 픽스처가 깨졌다"
    diff = {k: (core.get(k), view.get(k))
            for k in set(core) | set(view) if core.get(k) != view.get(k)}
    assert not diff, f"{tag}에서 갈렸다: {diff}"


@pytest.mark.parametrize("tag", _TAGS)
def test_핵심_값이_비어_있지_않다(tag):
    """전부 공란이면 위 대조는 통과해도 아무것도 확인하지 못한다."""
    core = parse_control_change_detail(_FX[tag]["plain"])
    assert core.get("new_holder"), "신규 최대주주 명칭을 못 읽었다"
    assert core.get("prev_holder"), "변경 전 최대주주를 못 읽었다"
    assert isinstance(core.get("new_ratio"), (int, float))
    assert core.get("new_ratio", 0) > 0
    assert core.get("self_fund", 0) > 0, "자기자금을 못 읽었다"


def test_네_표기_변형이_모두_들어_있다():
    """「외 N인」 표기가 갈리는 것이 이 파서의 알려진 난점이다."""
    got = {}
    for t in _TAGS:
        r = parse_control_change_detail(_FX[t]["plain"])
        got[t] = (r.get("prev_holder", ""), r.get("new_holder", ""))
    # 실측값(2026-08-30) — 「인/명」 단위도, 앞 공백 유무도, 단위 생략도 다 다르다
    assert got["control_change_oein"][0] == "신정관 외 1인"
    assert got["control_change_oenmyeong"][0] == "(주)바른손이앤에이 외 2명"
    # ⚠ 붙임형은 **신규 최대주주** 쪽에 나온다 — 「지피클럽외 1명」(외 앞 공백 없음)
    assert got["control_change_oenmyeong"][1] == "(주)지피클럽외 1명"
    assert got["control_change_person"][0] == "심충식 외 22", "단위 생략형"
    assert "외" not in got["control_change_plain"][0], "접미 없는 사례"


def test_차입금_경로는_아직_덮이지_않았다():
    """⚠ 덮이지 않은 것을 **덮인 척하지 않기 위한** 표시.

    금감원이 지목한 주식담보대출(차입금>0) 경로는 라이브 사례가 없다.
    사례를 찾으면 픽스처를 추가하고 이 테스트를 바꿔라.
    """
    borrowed = [parse_control_change_detail(_FX[t]["plain"]).get("borrowed_fund", 0)
                for t in _TAGS]
    assert all(b == 0 for b in borrowed), (
        "차입금>0 사례가 픽스처에 들어왔다 — 이제 그 경로도 대조하도록 고쳐라"
    )
