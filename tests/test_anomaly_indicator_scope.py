"""`check_disclosure_anomaly`의 지표가 **설명과 같은 것을 세는지** 잠근다.

도구 출력을 읽다 찾았다(2026-08-30, 제이스코홀딩스).

    **④ 자본 스트레스** (2건)
        • 증권발행결과(자율공시) (제3자배정 유상증자)
        • 주요사항보고서(유상증자결정)

**한 사건을 두 번 센다** — 뒤가 증자 결정이고 앞은 그 결과 보고다. 원인은
이 도구만 **한정층을 쓰지 않는 것**이었다(다른 넷은 쓴다).

## ②③④ — 한정층을 적용한다

12개사 365일 실측:

    ② 감사의견      3건 · 강등 0건  (영향 없음)
    ③ 공시의무 위반  7건 · 강등 0건  (영향 없음)
    ④ 자본 스트레스 27건 · 강등 **16건(59%)**

강등된 것: 「유상증자또는주식관련사채등의**발행결과**」 10 · 「유상증자결정
(**종속회사**의주요경영사항)」 2 · 「…**청약결과**」 1 · 「증권발행결과」 1 ·
정정 2. 전부 **이미 센 사건의 결과 보고**이거나 **이 회사의 행위가 아니다**.

## ⑤ — 한정층을 그대로 쓰면 **반대 방향으로 틀린다**

여기서 한 번 잘못 고쳤다. 한정층을 그대로 걸었더니 두산 5→0 · 삼성전자 2→0 ·
셀트리온 2→0 · KR모터스 2→0으로, 실제로 있었던 조회 대응이 지워졌다.

조회공시 계열은 **세 형태**로 기록된다(실측):

    조회공시요구(풍문또는보도)                      거래소가 낸 요구
    조회공시요구(풍문또는보도)에대한답변(부인/미확정)   회사의 답변
    풍문또는보도에대한해명(미확정)                    회사가 낸 해명(요구 기록 없음)

한정층은 뒤 둘을 R4로 강등한다 — **신호·패턴에서는 옳다**(해명은 사건이 아니라
답변이다). 그런데 이 지표는 「조회 사건 수」라, 회사 쪽 기록만 남는 회사에서
0이 된다(7곳 중 **4곳**).

반대로 원자료를 그대로 세면 **요구+답변이 한 사건인데 둘로** 잡힌다
(진원생명과학 20260617 요구 → 20260618 답변 · 코아스 20250922 → 0923).

그래서 **날짜 근접 병합**(3일)으로 사건을 센다. 실측 답변은 전부 요구 다음
날이라 3일이면 충분하고, 넓히면 서로 다른 조회를 합칠 위험이 커진다.

검산(7곳): 진원 3 · 코아스 1 · KR모터스 2 · 두산 5 · 삼성 2 · 셀트리온 2 ·
제이스코 1 — 원자료(중복)와 한정층 단순 적용(누락) 어느 쪽과도 다르다.
"""
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SRC = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")


def _fn() -> str:
    i = _SRC.index("def check_disclosure_anomaly(")
    j = _SRC.index("\n@mcp.tool()", i)
    return _SRC[i:j]


def _code() -> str:
    keep = [l for l in _fn().splitlines() if not l.strip().startswith("#")]
    return "\n".join(keep)


def test_한정층을_쓴다():
    body = _code()
    assert "qualify_signals(sigs, parse_report_name(nm), d)" in body
    assert "if q.tier == TIER_OBSERVED" in body


def test_지표_2_3_4는_관찰_신호만_센다():
    body = _code()
    for key in ('"AUDIT" in keys', '"DISCLOSURE_VIOL" in keys',
                "keys & _CAPITAL_STRESS"):
        assert key in body, f"{key}가 사라졌다"
    # `keys`는 observed만 담는다
    assert 'keys = {s["key"] for s, q in zip(sigs, quals) if q.tier == TIER_OBSERVED}' in body


def test_지표_5는_강등과_무관하게_모은다():
    """회사 쪽 기록만 있는 회사에서 0이 되면 안 된다."""
    body = _code()
    assert 'if any(s["key"] == "INQUIRY" for s in sigs):' in body
    assert 'inquiry_rows.append((d.get("rcept_dt", ""), nm))' in body
    assert '"INQUIRY" in keys' not in body, "관찰 신호로만 세던 옛 경로가 남아 있다"


def test_지표_5가_날짜로_사건을_병합한다():
    body = _code()
    assert "_INQUIRY_EVENT_GAP_DAYS = 3" in body
    assert "<= _INQUIRY_EVENT_GAP_DAYS" in body
    assert "inquiry_rows.sort(key=lambda r: r[0])" in body, "정렬 없이 병합하면 비결정적"


def test_병합_창이_넓어지지_않는다():
    """넓히면 서로 다른 조회가 한 건으로 합쳐진다 — 실측 답변은 요구 다음날."""
    m = re.search(r"_INQUIRY_EVENT_GAP_DAYS = (\d+)", _fn())
    assert m and int(m.group(1)) <= 3


def test_제외_건수를_밝힌다():
    body = _fn()
    assert "절차·사후 보고 {len(procedural_hits)}건을 " in body
    assert "지표 ②~④에서" in body, "⑤는 따로 세므로 범위에 넣으면 두 번 말한다"


def test_제외_집계에_INQUIRY가_빠져_있다():
    body = _code()
    i = body.index("procedural_hits.append(nm)")
    seg = body[i - 400:i]
    assert '{"AUDIT", "DISCLOSURE_VIOL"} | _CAPITAL_STRESS' in seg
    assert '"INQUIRY"} | _CAPITAL_STRESS' not in seg


def test_예시_제목의_여백을_접는다():
    """DART 제목은 안쪽 여백이 길다 — 문장 안에 그대로 넣으면 읽히지 않는다."""
    # ⚠ 처음엔 `re.sub(r'\s+', ...)`로 썼다가 **이스케이프가 하나 더 붙어**
    #    리터럴 백슬래시를 찾는 정규식이 됐다(공백이 안 접혔다). `split()`은
    #    그 함정이 없다.
    assert "' '.join(procedural_hits[0].split())" in _fn()
    assert "re.sub(r'\\s+'" not in _fn(), "이스케이프가 두 번 들어간 형태"


def test_다른_네_도구도_한정층을_쓴다():
    """이 도구만 빠져 있었다는 사실을 고정 — 다시 갈리면 잡는다."""
    for fn_name in ("def analyze_company_risk(", "def build_event_timeline(",
                    "def check_disclosure_risk("):
        i = _SRC.index(fn_name)
        j = _SRC.index("\n@mcp.tool()", i)
        assert "qualify_signals" in _SRC[i:j], f"{fn_name}에서 한정층이 사라졌다"
