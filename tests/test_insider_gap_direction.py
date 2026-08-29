"""내부자 매도 ↔ 부정 공시의 **방향**과 보고자 **묶음**을 잠근다.

워크트리 코드로 `track_insider_trading`을 직접 돌려 출력을 읽다 찾았다
(2026-08-30, 제이스코홀딩스).

## 1. 「N일 후」인데 공시가 먼저였다

    • (주)캐디언스시스템  매도일 20250331  →  13일 후 DISCLOSURE_VIOL 공시 (20250318)

20250318은 20250331보다 **13일 전**이다. `detect_insider_pre_disclosure`가
`gap = abs((disc_date - sell_date).days)`로 **부호를 버렸고** 렌더는 「N일 후」를
고정으로 붙였다. 라이브 4건이 **전부** 공시가 먼저인데 전부 「후」였다.

⚠ 방향이 뒤집히면 뜻이 정반대다 — 「악재 공시 **전에** 팔았다」(정보 우위 의심)와
「악재 뒤에 팔았다」(손절)는 다른 사실이다. 헤더는 「정보 우위 매도 가능성
검토」라 적고 있었으니 화면이 데이터와 반대를 말했다.

창은 ±30일 **양방향**이 의도다(CLAUDE.md: 사실 표기·무점수). 그래서 걸리는
범위는 그대로 두고 **방향을 밝히고** 헤더에서 단정을 뺐다.

부수 수정: 창 안에 부정 공시가 여럿이면 옛 코드는 리스트 **첫 번째**를 잡고
`break`했다 — 가장 가까운 것이 아니라 임의의 것이었다. 방향과 일수를 화면에
적게 됐으므로 **가장 가까운 것**을 고른다(동률이면 이른 날짜, 결정적).

## 2. 같은 법인이 두 시계열로 갈렸다

    ▶ ㈜캐디언스시스템    20241231 6.94 → 20250630 5.52 (Δ-1.42)
    ▶ (주)캐디언스시스템  20240930 7.75 → 20250331 6.14 (Δ-1.61)

표기만 다른 같은 법인이다. 갈리면 **Δ가 분기를 건너뛴다** — 실제 시계열은
7.75 → 6.94 → 6.14 → 5.52이고 분기 변동은 -0.81 · -0.80 · -0.62인데, 화면의
-1.61 · -1.42는 그 **두 배**다. 이 Δ는 매수·매도 클러스터(0.5%p/30일)와
위 플래그의 입력이라 판정까지 오염된다.

`_holder_key`는 이미 **공백 변형**을 접는 같은 부류의 수정을 거쳤는데(20개사
9건) 법인 표기만 빠져 있었다. 빈도 실측: 12개사 중 **1곳**. 드물지만 걸리면
그 회사의 Δ가 전부 거짓이다 — 「묶음 축」 결함의 세 번째다(앞의 둘은 주식
종류·날짜).
"""
import pathlib

import pytest

from dart_risk_mcp.core.dart_client import detect_insider_pre_disclosure
from dart_risk_mcp.server import _gap_phrase, _holder_key

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SRC = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")


def _code() -> str:
    """주석을 뺀 코드만."""
    keep = [l for l in _SRC.splitlines() if not l.strip().startswith("#")]
    return chr(10).join(keep)


def _flag(sell: str, disc: str, key: str = "AUDIT"):
    flags = detect_insider_pre_disclosure(
        [{"holder": "홍길동", "rcept_dt": sell, "delta_pct": -1.0}],
        [{"key": key, "rcept_dt": disc, "report_nm": "테스트"}],
    )
    assert len(flags) == 1
    return flags[0]


# ── 1. 방향 ────────────────────────────────────────────────────
def test_공시가_나중이면_양수다():
    f = _flag("20250410", "20250420")
    assert f["gap_signed"] == 10
    assert f["days_gap"] == 10


def test_공시가_먼저면_음수다():
    """라이브에서 실제로 나온 방향 — 옛 코드가 「후」라 적던 자리."""
    f = _flag("20250331", "20250318", key="DISCLOSURE_VIOL")
    assert f["gap_signed"] == -13
    assert f["days_gap"] == 13


def test_문구가_방향을_뒤집지_않는다():
    assert _gap_phrase({"days_gap": 10, "gap_signed": 10}) == "매도 10일 후"
    assert _gap_phrase({"days_gap": 13, "gap_signed": -13}) == "매도 13일 전"
    assert _gap_phrase({"days_gap": 0, "gap_signed": 0}) == "같은 날"


def test_방향을_모르면_말하지_않는다():
    """옛 호출자 호환 — 없는 사실을 지어내지 않는다."""
    assert _gap_phrase({"days_gap": 7}) == "7일 간격"


def test_렌더가_고정_문구를_쓰지_않는다():
    assert "일 후 {f['disclosure_key']}" not in _SRC, "「N일 후」가 하드코딩돼 있다"
    assert "_gap_phrase(f)" in _SRC


def test_헤더가_정보_우위를_단정하지_않는다():
    """±30일 양방향이라 공시가 먼저인 건도 들어온다 — 그때는 정보 우위가 아니다."""
    # ⚠ 두 함정을 피한다. ① 근거 주석이 옛 문구를 인용한다 ② **매도 클러스터**
    #    블록에도 같은 표현이 있다(「30일 이내 0.5%p 이상 보유 감소 — 정보 우위
    #    매도 가능성 검토 권장」). 그쪽은 공시와 무관한 별개 기능이고 제 데이터와
    #    모순되지도 않아 건드리지 않았다. 이 블록만 본다.
    i = _SRC.index("INSIDER_PRE_DISCLOSURE 패턴 탐지")
    block = chr(10).join(
        l for l in _SRC[i:i + 2000].splitlines() if not l.strip().startswith("#"))
    assert "정보 우위 매도 가능성 검토" not in block
    assert "매도 ±30일 안에 부정 공시가 관찰됩니다" in block


def test_매도_클러스터_문구는_건드리지_않았다():
    """별개 기능이다 — 이 수정의 범위 밖이라는 것을 못 박는다."""
    assert "30일 이내 0.5%p 이상 보유 감소 — 정보 우위 매도 가능성 검토 권장" in _SRC


# ── 2. 가장 가까운 공시 ────────────────────────────────────────
def test_창_안에_여럿이면_가장_가까운_것을_고른다():
    flags = detect_insider_pre_disclosure(
        [{"holder": "홍길동", "rcept_dt": "20250410", "delta_pct": -1.0}],
        [  # 리스트 **순서상 먼저**인 것이 더 먼 쪽
            {"key": "AUDIT", "rcept_dt": "20250330", "report_nm": "먼 쪽"},
            {"key": "INSOLVENCY", "rcept_dt": "20250412", "report_nm": "가까운 쪽"},
        ],
    )
    assert len(flags) == 1
    assert flags[0]["disclosure_date"] == "20250412", "리스트 첫 번째를 잡고 있다"
    assert flags[0]["days_gap"] == 2


def test_동률이면_이른_날짜를_고른다():
    """결정적이어야 한다 — 같은 입력에 같은 출력."""
    flags = detect_insider_pre_disclosure(
        [{"holder": "홍길동", "rcept_dt": "20250410", "delta_pct": -1.0}],
        [{"key": "AUDIT", "rcept_dt": "20250415"},
         {"key": "INSOLVENCY", "rcept_dt": "20250405"}],
    )
    assert flags[0]["disclosure_date"] == "20250405"


def test_한_매도에_한_건만_남는다():
    flags = detect_insider_pre_disclosure(
        [{"holder": "홍길동", "rcept_dt": "20250410", "delta_pct": -1.0}],
        [{"key": "AUDIT", "rcept_dt": "20250411"},
         {"key": "INSOLVENCY", "rcept_dt": "20250412"},
         {"key": "EMBEZZLE", "rcept_dt": "20250413"}],
    )
    assert len(flags) == 1


def test_창_밖은_여전히_안_걸린다():
    assert detect_insider_pre_disclosure(
        [{"holder": "홍길동", "rcept_dt": "20250410", "delta_pct": -1.0}],
        [{"key": "AUDIT", "rcept_dt": "20250601"}],
    ) == []


# ── 3. 보고자 묶음 ─────────────────────────────────────────────
@pytest.mark.parametrize("a,b", [
    ("㈜캐디언스시스템", "(주)캐디언스시스템"),      # 라이브 실측
    ("주식회사 한국파일", "(주)한국파일"),
    ("유한회사 가나", "가나"),
    ("㈜ 다라", "다라주식회사"),
])
def test_법인_표기_차이를_접는다(a, b):
    assert _holder_key(a) == _holder_key(b), f"{a} ≠ {b}"


def test_공백_접기는_그대로다():
    """앞선 라운드(20개사 9건)의 수정을 되돌리지 않았는지."""
    assert _holder_key("최용석 (주1)") == _holder_key("최용석(주1)")
    assert _holder_key("Citadel Multi-Asset") == _holder_key("CitadelMulti-Asset")


def test_다른_이름을_합치지_않는다():
    assert _holder_key("캐디언스시스템") != _holder_key("캐디언스")
    assert _holder_key("홍길동") != _holder_key("홍길순")


def test_묶음_키가_주식_종류를_유지한다():
    """종류를 섞으면 Δ가 거짓이 된다(두산 실측) — 그 수정을 깨지 않았는지."""
    assert "_hk = (_holder_key(holder), kind)" in _SRC


def test_접사_집합이_core와_같다():
    from dart_risk_mcp.core import dart_client as dc
    assert dc._AFFIL_CORP_SUFFIX_RE.pattern in _SRC, (
        "두 곳이 갈리면 같은 이름을 한쪽만 접는다"
    )


# ── 4. 접힌 줄의 마지막 날짜 ───────────────────────────────────
#
# 보고자를 병합하자 드러났다(두산에너빌리티). 인접 중복 dedup이 **처음
# 관측일만** 남겨, 「20240930 30.39%」만 보이고 그 지분이 **20260630
# 보고에서도 그대로였다**는 사실이 사라졌다. 읽는 사람은 자료가 2년 묵은
# 줄로 오해한다 — 화면이 아는 것보다 적게 말하는 부류다.
#
# 값·Δ·순서는 그대로 두고 「(~YYYYMMDD 동일)」만 덧붙인다.

def test_dedup이_마지막_날짜를_보존한다():
    i = _SRC.index("인접 중복 dedup")
    body = _SRC[i:i + 700]
    assert "deduped[-1][3] = date" in body, "접힌 마지막 날짜를 버린다"
    assert "deduped.append([ratio, date, src_lbl, date])" in body


def test_같은_값이_이어지면_그_사실을_적는다():
    i = _SRC.index("same_str =")
    body = _SRC[i:i + 300]
    assert 'f" (~{last_date} 동일)" if last_date != date else ""' in body


def test_접힌_구간이_없으면_아무_말도_하지_않는다():
    """한 번만 관측된 줄에 「(~같은날 동일)」이 붙으면 소음이다."""
    assert "if last_date != date else \"\"" in _SRC


def test_Δ와_순서는_건드리지_않았다():
    """표기만 더한 것이다 — 판정 입력(Δ)이 달라지면 안 된다."""
    i = _SRC.index("same_str =")
    body = _SRC[i - 400:i + 400]
    assert "delta = ratio - prev_ratio if prev_ratio is not None else 0.0" in body
    assert "rows_sorted = sorted(rows, key=lambda r: r[1])" in _SRC
