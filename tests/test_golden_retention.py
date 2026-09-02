"""골든이 무한히 쌓이지 않는지 잠근다.

## 무엇이 문제였나

`risk_check`·`doc`·`sections`·`view` 넷은 **그때의 최신 접수번호**를 파일명에
박는다. 그래서 전체 재생성 1회마다 회사당 4개씩 **새 파일**이 생기고 옛 것은
남는다 — 갱신되는 게 아니라 **쌓인다**.

실측(2026-09-02): **320건 중 rcept 계열이 136건(43%)**이고 그중 **116건(85%)이
낡았다**. 가장 오래된 것은 **4개월 전**(2026-04-26) 코드의 출력이다.

## 왜 지워도 되나 — 근거 셋

**① 특정 파일을 지목하는 소비처가 없다.** 골든은 diff 기준이 아니라
`test_golden_output_hygiene`·`test_no_internal_key_leak`·
`test_no_severity_derived_stats`·`test_golden_freshness`가 glob으로 훑는
**검사 코퍼스**다.

**② 옛 세트가 더하는 것의 84%가 공시 원문이다.** 고유 문구 2,888종 중
`doc`(1,481) + `view`(950) = **2,431종이 원문 덤프**이고, 도구 출력은
`sections` 344 + `risk_check` 113뿐이다. 세트를 늘려도 **우리가 만든 문구**의
검사 표면은 거의 넓어지지 않는다.

**③ 라이브 API 산출물이라 언제든 다시 만들 수 있다.** git 이력에도 남는다.

## 정한 기준 — **(회사, 도구)별 최신 2개**

⚠ **세트가 아니라 도구별로 센다.** 세트가 항상 넷씩 맞게 오지 않는다 — 실측에서
**6개 회사가 `sections`만 다른 rcept**를 쓴다(어느 회차의 재생성기가 도구마다
다른 공시를 골랐다). 세트로 묶으면 그 짝이 「파편」으로 보여 **온전한 것을 지우고
파편을 남기는** 일이 생긴다(실제로 첫 구현이 그랬다).

왜 1이 아닌가 — 재생성 사이의 연속성이 남아야 「이번에 무엇이 바뀌었나」를
비교할 근거가 있고, 서로 다른 공시 유형 2종이 남아 원문 서식 다양성이 최소한
유지된다.

정리 결과: **320 → 260건**(60개 삭제). `scripts/regen_goldens.py`의
`prune_rcept_goldens()`가 재생성 끝에 자동으로 돈다.
"""
import importlib.util
import pathlib
import re
from collections import defaultdict

import pytest

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_GOLD = _ROOT / "tests" / "fixtures" / "sample_outputs"
_TOOLS = ("risk_check", "doc", "sections", "view")
_RE = re.compile(r"^(?P<co>.+?)_(?P<tool>" + "|".join(_TOOLS) + r")_(\d{14})\.txt$")


def _groups():
    g = defaultdict(list)
    for f in _GOLD.glob("*.txt"):
        m = _RE.match(f.name)
        if m:
            g[(m.group("co"), m.group("tool"))].append(f.name)
    return g


def _regen_module():
    """`scripts/regen_goldens.py`는 import 시 API 키를 요구한다 — 없으면 건너뛴다."""
    spec = importlib.util.spec_from_file_location(
        "_regen", _ROOT / "scripts" / "regen_goldens.py")
    mod = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(mod)
    except SystemExit:
        pytest.skip("DART_API_KEY 없음 — 재생성 스크립트를 import할 수 없다")
    return mod


def test_회사_도구별로_두_개를_넘지_않는다():
    over = {k: sorted(v) for k, v in _groups().items() if len(v) > 2}
    assert not over, (
        f"rcept 계열 골든이 쌓였다({len(over)}조합) — "
        "`python scripts/regen_goldens.py`가 끝에 프루닝을 돌린다:\n"
        + "\n".join(f"  {co}/{tool}: {len(v)}개" for (co, tool), v in over.items()))


def test_프루닝이_재생성기에_배선돼_있다():
    """스크립트에 함수만 있고 호출되지 않으면 다시 쌓인다."""
    src = (_ROOT / "scripts" / "regen_goldens.py").read_text(encoding="utf-8")
    assert "def prune_rcept_goldens(" in src
    assert "prune_rcept_goldens()" in src, (
        "프루닝 함수가 정의만 되고 main에서 호출되지 않는다 — 다시 쌓인다")
    assert "[PRUNE]" in src, "조용히 지우면 안 된다 — 몇 개를 지웠는지 밝힌다"


def test_상한값이_문서와_같다():
    mod = _regen_module()
    assert mod.KEEP_RCEPT_FILES == 2, (
        "상한을 바꿨으면 이 파일의 머리말과 CLAUDE.md도 함께 고쳐라")
    # ⚠ 121행의 `RCEPT_TOOLS`(도구 목록)를 덮어쓰면 `t[0]`이 첫 글자가 돼
    #    재생성 매트릭스가 조용히 깨진다. 실제로 한 번 겪었다.
    assert [t[0] for t in mod.RCEPT_TOOLS] == list(_TOOLS), (
        "RCEPT_TOOLS(도구 목록)가 덮어써졌다 — 프루닝 상수는 "
        "`_RCEPT_GOLD_TOOLS`라는 다른 이름을 쓴다")


def test_프루닝은_최신을_남긴다():
    """접수번호는 앞 8자리가 접수일이라 문자열 정렬이 곧 시간순이다."""
    for (co, tool), names in _groups().items():
        rcepts = sorted(_RE.match(n).group(3) for n in names)
        assert len(rcepts) <= 2
        if len(rcepts) == 2:
            # 남은 둘이 서로 다른 접수번호여야 한다(같으면 중복 파일이다)
            assert rcepts[0] != rcepts[1], f"{co}/{tool}에 같은 rcept가 둘"


def test_비_rcept_골든은_회사당_하나다():
    """대조 — 나머지 도구는 파일명에 rcept가 없어 매번 덮어써진다.

    이 관례가 깨지면(다른 도구도 rcept를 파일명에 박기 시작하면) 같은 누적이
    다시 생긴다.
    """
    counts = defaultdict(int)
    for f in _GOLD.glob("*.txt"):
        if _RE.match(f.name):
            continue
        m = re.match(r"^(.+?)_(analyze|timeline|capital|turnover|anomaly)\.txt$", f.name)
        if m:
            counts[m.group(2)] += 1
    for tool, n in counts.items():
        assert n <= 12, f"{tool} 골든이 {n}개 — 회사 수(10)를 크게 넘는다"
