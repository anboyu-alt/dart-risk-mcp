"""패턴 카드가 taxonomy 라벨만 적어 **없던 사실을 말하지** 않는지 잠근다.

#293에서 보류한 `CB_BW→1.1`을 실제로 파 보고 찾았다(2026-08-25).

    1.1 한글 라벨 = 「전환가액 하향조정(**리픽싱**)」

그런데 `CB_BW`가 1.1을 켜는 제목은 대부분 **발행결정**이다. 1년 전수에서
`fund_diversion_chain`이 뜬 **132곳**의 1.1 근거를 분해하니:

    신규 발행 결정          121
    리픽싱(전환가액조정)     106
    매수선택권 행사 계열      28

    1.1이 **리픽싱만**인 회사   15곳
    1.1에 리픽싱이 **없는** 회사 **67곳**   ← 절반이다

즉 67곳의 카드가 「전환가액 하향조정(리픽싱) 관찰됨」이라 적었는데
**그 회사에 리픽싱 공시가 없다.**

## taxonomy 매핑은 건드리지 않았다

1.1은 `fund_diversion_chain`(1년 최다 발화)의 요구 신호이고, 패턴은 1.1을
"CB 조달"의 뜻으로 쓴다 — 이름과 용법이 어긋나는 것이지 매핑이 틀린 게
아니다. 개명·신설은 카탈로그 277건 매핑과 뷰어에 연쇄로 걸린다
(CLAUDE.md 「매핑 근거 감사」).

**표기만** 사실에 맞췄다 — `taxonomy_owners`(#289)로 이미 넘어오는 정보라
추가 조회가 없다.

    관찰됨: 채권 전환을 통한 최대주주 변경(3.1) ← 최대주주변경 ·
            감사의견 비적정·거절(4.4) ← 감사의견

부수: 「외 N개 패턴이 **2개 이상** 겹칩니다」는 v1.20.13에서 임계가 패턴
크기에 비례하게 바뀐 뒤로 **낡은 문구**다.
"""
import pathlib

from dart_risk_mcp.core.signals import SIGNAL_LABELS, SIGNAL_TYPES
from dart_risk_mcp.server import _matched_label

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_SERVER = (_ROOT / "dart_risk_mcp" / "server.py").read_text(encoding="utf-8")
_HTML = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")


def test_켠_신호를_함께_적는다():
    got = _matched_label("1.1", {"1.1": {"CB_BW"}})
    assert "(1.1)" in got
    assert "←" in got
    assert SIGNAL_LABELS["CB_BW"] in got


def test_소유_정보가_없으면_라벨만():
    assert _matched_label("1.1", None) == _matched_label("1.1", {})
    assert "←" not in _matched_label("1.1", {})


def test_여럿이_켜면_줄여_적는다():
    got = _matched_label("5.3", {"5.3": {"ASSET_TRANSFER", "FUND_DIVERSION",
                                         "DECISION_OVERSIZED"}})
    assert got.count("·") >= 1
    assert got.endswith("…"), got


def test_라벨_맵이_신호_전부를_덮는다():
    assert set(SIGNAL_LABELS) == {s["key"] for s in SIGNAL_TYPES}
    assert all(v for v in SIGNAL_LABELS.values())


def test_카드가_헬퍼를_쓴다():
    assert "_matched_label(t, taxonomy_owners)" in _SERVER
    assert 'f"{taxonomy_label_ko(t)}({t})" for t in ov["matched"]' not in _SERVER


def test_낡은_임계_문구가_없다():
    assert "2개 이상 겹칩니다" not in _SERVER
    assert "2개 이상 겹칩니다" not in _HTML
    assert "표시 기준을 넘겨 겹칩니다" in _SERVER
    assert "표시 기준을 넘겨 겹칩니다" in _HTML


def test_뷰어도_같은_표기를_한다():
    assert "function patternOverlapLinesHTML(p, taxOwners)" in _HTML
    assert "DATA.signal_labels" in _HTML
    assert "patternOverlapLinesHTML(p, CUR.taxOwners)" in _HTML
    assert "patterns, taxOwners," in _HTML, "CUR에 owners가 실리지 않는다"


def test_export가_신호_라벨을_내보낸다():
    import json

    data = json.loads((_ROOT / "docs" / "tool" / "signals-data.json")
                      .read_text(encoding="utf-8"))
    assert data["signal_labels"] == dict(SIGNAL_LABELS)


def test_안_보임에는_켠_신호를_붙이지_않는다():
    """관찰되지 않은 것에 '켠 신호'를 적으면 없는 사실을 만든다."""
    assert 'fmt(unseen, false)' in _HTML
    assert 'fmt(matched, true)' in _HTML


# ── 실물을 읽다 찾은 후속 결함 (2026-08-25) ─────────────────────
#
# #295가 넣은 「← 켠 신호」의 구분자가 **바깥 목록과 같았다**. 진원생명과학
# 리포트 실물:
#
#     구성 신호 **2개** 중 2개가 이 기간 공시에서 관찰됐습니다
#     관찰됨: 자본 이벤트 과다 반복(2.7) ← 자본 이벤트 과다 반복 ·
#             공시·보고 의무 위반(4.3) ← 공시의무위반 · 자금사용내역 미기재
#
# 바깥 join도 " · "라 **셋으로 읽힌다**. 그리고 2.7은 taxonomy 라벨과 신호
# 라벨이 같아 「X ← X」가 되어 아무것도 더하지 않았다.


def test_안쪽_구분자가_바깥과_다르다():
    got = _matched_label("4.3", {"4.3": {"DISCLOSURE_VIOL", "FUND_UNREPORTED"}})
    assert "," in got, got
    assert " · " not in got, f"바깥 목록과 같은 구분자다: {got}"


def test_같은_이름이면_붙이지_않는다():
    """2.7은 taxonomy 라벨과 신호 라벨이 같다 — 「X ← X」는 정보가 0이다."""
    got = _matched_label("2.7", {"2.7": {"CAPITAL_CHURN"}})
    assert "←" not in got, got


def test_다른_이름은_그대로_붙는다():
    got = _matched_label("1.1", {"1.1": {"CB_BW"}})
    assert "←" in got and SIGNAL_LABELS["CB_BW"] in got


def test_카드_한_줄에서_개수를_셀_수_있다():
    """바깥 ' · ' 개수 + 1 == 관찰된 taxonomy 수여야 읽는 사람이 안 헷갈린다."""
    from dart_risk_mcp.server import _matched_label as ml

    owners = {"2.7": {"CAPITAL_CHURN"},
              "4.3": {"DISCLOSURE_VIOL", "FUND_UNREPORTED"}}
    line = " · ".join(ml(t, owners) for t in ("2.7", "4.3"))
    assert line.count(" · ") == 1, line


def test_뷰어도_같은_규칙이다():
    html = (_ROOT / "docs" / "tool" / "index.html").read_text(encoding="utf-8")
    assert 'names.join(", ")' in html
    assert '.filter((n) => n !== label)' in html
