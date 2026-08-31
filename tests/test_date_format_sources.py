"""날짜 표기가 **어디서 왔는지**를 고정한다.

위험 목록 3번을 제작자 승인으로 처리한 결과(2026-08-30).

## 무엇이 문제라고 적혀 있었나

「한 리포트 안에 `20260709` · `2026.07.09` · `2026-07-09` · `26.07.09`가 섞여
나온다 — 각 블록이 원문 표기를 따르거나 자체 포맷을 쓴다.」

## 재 보니 전제가 달랐다

골든 전수에서 겹침을 없애고(1차 측정은 `YYYY-MM` 정규식이 `YYYY-MM-DD`의
앞부분을 겹쳐 세 두 수가 항상 같았다) 원문 인용 골든을 분리해 세었다.

    도구 생성  5,580   YYYYMMDD 5,123(92%) · YYYY.MM.DD 314 · YYYY-MM-DD 134 · YYYY-MM 9
    원문 인용    394

**우리가 만드는 표기는 `_fmt_date8` 하나뿐이고, 그것은 일관되게
`YYYY.MM.DD`다.** `YYYYMMDD`가 아닌 것은 전부 **값의 출처**가 그 표기다:

    YYYY.MM.DD   affiliates 최초취득일 152 · fund_usage 납입일 123 — DART가 그 표기로 준다
    YYYY-MM-DD   금감원 카탈로그 보도자료 날짜 61 · majorstock의 rcept_dt 23 · 산문 10
    YYYY-MM      고정 문장 「무자본 M&A 합동점검(2019-12)」 9

즉 선택지 (a)「우리가 만드는 줄만 통일」은 **이미 참**이고, 남은 혼재를
없애려면 DART가 준 문자열을 다시 써야 한다 — 그러면 「DART가 준 값」과
「우리가 만든 값」의 구분이 사라진다(항목이 스스로 경고한 위험).

## 잠복 위험 하나

`majorstock.json`의 `rcept_dt`는 **`2026-06-08`**로 온다 — 같은 이름의 필드가
`list.json`에서는 `20260608`이다. 렌더가 `len(dt) == 8`로 갈라 대시 표기를
그대로 통과시키는데, 이걸 「버그」로 보고 `dt[:8]`로 자르면 **`2026-06-`**가
된다. 이 테스트가 그 자리를 잠근다.
"""
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SERVER = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
_GOLD = _ROOT / "tests" / "fixtures" / "sample_outputs"


def test_우리가_만드는_날짜_포맷은_하나다():
    """`_fmt_date8` 말고 다른 조립식이 생기면 표기가 갈린다."""
    assert 'return f"{d[:4]}.{d[4:6]}.{d[6:]}" if len(d) == 8 else d' in _SERVER, (
        "_fmt_date8의 본문이 바뀌었다 — 표기를 바꾸려면 골든 전부를 함께 본다")
    # 헬퍼를 거치지 않고 손으로 조립한 8자리 날짜가 있는지.
    # ⚠ 이 테스트를 처음 돌렸을 때 `search_market_disclosures`의 window_label이
    #   같은 포맷을 손으로 한 번 더 조립하고 있었다(출력은 같았지만 8자리가
    #   아니면 쓰레기가 나온다). 헬퍼 호출로 바꿨다.
    hand = [v for v in
            re.findall(r"\{(\w+)\[:4\]\}[.\-]\{\1\[4:6\]\}[.\-]\{\1\[6:", _SERVER)
            if v != "d"]      # "d"는 헬퍼 자신의 본문
    assert not hand, (
        f"_fmt_date8을 안 거치고 조립한 자리: {hand} — 한 곳에서만 만든다")


def test_majorstock_대시_표기를_자르지_않는다():
    """`dt[:8]`이면 「2026-06-」가 된다 — 날짜가 아니라 잘린 문자열이다."""
    i = _SERVER.index("# 응답은 '현재 보유자'가 아니라")
    block = _SERVER[i:i + 2200]
    assert '_fmt_date8(dt) if len(dt) == 8 else dt' in block, (
        "8자리일 때만 포맷하는 가드가 사라졌다 — majorstock은 대시로 준다")
    assert "dt[:8]" not in block, "대시 표기를 잘랐다 → 「2026-06-」"


def test_골든에_대시_표기가_실제로_남아_있다():
    """가드가 실제로 발화한다는 증거 — 없어지면 위 테스트가 공허해진다."""
    hits = 0
    for f in _GOLD.glob("*_shareholder.txt"):
        hits += len(re.findall(r"· 20\d{2}-\d{2}-\d{2}$",
                               f.read_text(encoding="utf-8"), re.M))
    assert hits > 0, (
        "5% 대량보유 줄에서 대시 날짜가 사라졌다 — DART 표기가 바뀌었거나 "
        "누군가 정규화했다. 어느 쪽인지 확인하고 위 테스트를 함께 고쳐라")


def test_원문_인용_골든은_섞여_있는_게_정상이다():
    """`doc_`·`view_` 골든은 공시 원문이다 — 표기를 손대면 원문이 아니게 된다."""
    mixed = 0
    for f in _GOLD.glob("*.txt"):
        tool = f.stem.split("_", 1)[1] if "_" in f.stem else f.stem
        if not tool.startswith(("doc_", "view_")):
            continue
        t = f.read_text(encoding="utf-8", errors="replace")
        kinds = sum(bool(re.search(p, t)) for p in (
            r"(?<![\d.\-])20\d{2}\.\d{2}\.\d{2}(?![\d.])",
            r"(?<![\d\-])20\d{2}-\d{2}-\d{2}(?![\d\-])",
            r"(?<![\d.])\d{2}\.\d{2}\.\d{2}(?![\d.])"))
        mixed += 1 if kinds > 1 else 0
    assert mixed > 0, "원문 골든에 표기 혼재가 없다 — 표본이 바뀌었는지 확인"
