"""`get_shareholder_info`가 **기말 잔고**를 보여주는지 잠근다.

도구 출력을 원본 응답과 대조하다 찾았다(2026-08-30, 코아스).

    화면   백운조합 (본인): 54,745주 (0.48%)
    원본   백운조합 기말 2,003,260주 (**16.96%**)

옛 코드는 `bsis_posesn_stock_co`(**기초** 잔고)를 읽었다. 절 제목은 「주주
현황」이고 도구 이름도 현황인데 **기간 시작 시점의 값**을 보여 준 것이다.

## 얼마나 어긋났나

12개사 실측에서 **9곳**이 기초 ≠ 기말:

    코아스        0.66% → **20.42%**  (19.76%p)
    KR모터스     47.08% →  63.16%   (16.08%p)
    셀트리온     28.31% →  31.21%
    진원생명과학 10.35% →   8.92%
    두산         39.99% →  40.92%

⚠ 같은 응답(`hyslrSttus`)을 쓰는 `track_insider_trading`은 **이미
`trmend_…`(기말)를 쓰고 있었다** — 두 도구가 같은 회사에 다른 지분율을
냈다. 「core는 아는데 한 층만 모른다」의 또 한 사례.

기초는 버리지 않는다 — 달라졌으면 그 변화가 정보다. 기말을 본값으로 두고
「기초 X% 대비 ±Y%p」를 덧붙인다.

## 곁가지 둘

- 합계 행은 `relate`가 비어 「계 ()」로 나왔고, **두 줄**이라 왜 둘인지도
  알 수 없었다. 그 자리에 `stock_knd`가 있으니 쓴다 → 「계 (보통주)」·
  「계 (우선주)」.
- 머리글에 **기준 사업연도가 없었다**. 기말 잔고는 연도마다 크게 달라지는데
  (위 표) 시점을 말하지 않으면 읽는 사람이 알 수 없다.
"""
import pathlib
import re

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SRC = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")


def _fn() -> str:
    i = _SRC.index("def get_shareholder_info(")
    j = _SRC.index("\n@mcp.tool()", i)
    return _SRC[i:j]


def _code() -> str:
    keep = [l for l in _fn().splitlines() if not l.strip().startswith("#")]
    return "\n".join(keep)


def test_기말_잔고를_쓴다():
    body = _code()
    assert 'h.get("trmend_posesn_stock_co", "-")' in body
    assert 'h.get("trmend_posesn_stock_qota_rt", "-")' in body


def test_기초를_본값으로_쓰지_않는다():
    body = _code()
    assert 'stock_cnt = h.get("bsis_posesn_stock_co"' not in body
    assert 'ratio = h.get("bsis_posesn_stock_qota_rt"' not in body


def test_기초를_버리지도_않는다():
    """달라졌으면 그 변화가 정보다."""
    body = _code()
    assert 'h.get("bsis_posesn_stock_qota_rt")' in body
    assert "기초 {_b:.2f}% 대비 {_e - _b:+.2f}%p" in body


def test_차이가_없으면_말하지_않는다():
    body = _code()
    assert "if abs(_e - _b) >= 0.01:" in body


def test_파싱_실패를_삼키지_않고_비운다():
    body = _code()
    assert "except (TypeError, ValueError):" in body
    assert 'delta = ""' in body


def test_합계_행에_주식_종류를_쓴다():
    body = _code()
    assert 'h.get("relate") or h.get("stock_knd") or "-"' in body


def test_머리글이_사업연도를_밝힌다():
    body = _fn()
    assert "{_year} 사업연도 보고 기준" in body


def test_조회와_표기가_같은_연도를_쓴다():
    """기본값을 두 곳에서 따로 정하면 라벨과 데이터가 갈릴 수 있다."""
    body = _code()
    assert '_year = year or str(datetime.now().year - 1)' in body
    assert "fetch_shareholder_status(corp_code, _DART_API_KEY, _year)" in body


def test_insider와_같은_필드를_본다():
    """같은 응답을 쓰는 두 도구가 다른 지분율을 내면 안 된다."""
    i = _SRC.index("def track_insider_trading(")
    j = _SRC.index("\n@mcp.tool()", i)
    ins = _SRC[i:j]
    assert "trmend_posesn_stock_qota_rt" in ins or "trmend" in ins, (
        "insider 쪽이 기말을 안 쓴다 — 두 도구를 같은 기준으로 맞춰라"
    )


def test_대량보유_보고자_필드는_그대로다():
    """2026-08-26에 고친 `repror` 경로를 되돌리지 않았는지."""
    assert "repror" in _fn()
    assert not re.search(r'h\.get\("reprt_nm"', _fn()), "없는 필드로 되돌아갔다"


# ── 곁가지 셋 ──────────────────────────────────────────────────
def test_이름의_개행을_접는다():
    """실측 STX: 이름 가운데 개행이 있어 한 행이 두 줄로 찢어졌다.

    `report_resn`은 이미 접고 있었는데 **이름은 안 접고 있었다** —
    exec_comp의 `ofcps`(2026-08-26)와 같은 함정이다.
    """
    body = _code()
    assert '" ".join(str(h.get("nm") or "-").split())' in body
    assert '" ".join(str(h.get("repror") or "").split())' in body


def test_관계도_접는다():
    body = _code()
    assert 'str(h.get("relate") or h.get("stock_knd") or "-").split()' in body


def test_전부_미기재인_행을_뺀다():
    """DART가 종류별 자리만 채워 보낸 행 — 그리면 「계 (-): -주 (-%)」다."""
    body = _code()
    assert "_blank_rows += 1" in body
    assert '"trmend_posesn_stock_co",' in body


def test_뺀_건수를_밝힌다():
    """조용히 지우지 않는다."""
    body = _fn()
    assert "주식수·비율이 모두 미기재인 행 {_blank_rows}건은 뺐습니다" in body
    assert "if _blank_rows:" in _code(), "0건일 때도 말하면 소음이다"


def test_대량보유_상한을_밝힌다():
    """15명 상한은 이미 표기돼 있었다 — 되돌아가지 않는지."""
    body = _fn()
    assert "_rows[:15]" in body
    assert "외 {len(_rows) - 15}명" in body
