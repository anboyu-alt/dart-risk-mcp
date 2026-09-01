"""신호→taxonomy 매핑이 **제목에 근거가 있는지** 코퍼스로 전수 감사한다.

`SHAREHOLDER→3.2`(#289)를 찾아낸 방법을 일반화했다. 각 매핑에 대해
**taxonomy 자체 키워드가 그 신호의 관찰 제목에 실제로 나타나는 비율**을 잰다.
0%면 "제목이 뒷받침하지 않는 주장"이라는 신호다 — 자동 결함은 아니지만
**근거를 적어 두지 않으면 안 되는 자리**다.

1년 코퍼스 실측(2026-08-25) 결과 0%인 매핑 15건을 전수 분류했다:

| 매핑 | 판단 |
|---|---|
| `EXEC→3.4` · `MGMT→3.4` | **제거** — `MGMT_DISPUTE`가 100% 근거로 소유 |
| `EXEC→3.3` | 유지 — 빼면 고아(다른 소유자 `ACTIVIST`는 absent) |
| `SHAREHOLDER→3.2` | 유지 — #289가 **세는 방법**으로 해결 |
| `ASSET_TRANSFER→5.3` | 유지 — v1.13.4가 키워드를 실제 표기로 교체했고 taxonomy 쪽 키워드만 옛 개념어로 남았다 |
| `RELATED_PARTY→4.2` | 유지 — v1.13.5가 "가격 괴리는 제목에 없다"고 기록하고 참고 강도로 둠 |
| `AUDIT→8.4` · `INQUIRY→7.1` | 유지 — 뜻이 맞다(자본잠식↔계속기업, 조회공시↔이상매매) |
| `EMBEZZLE→8.1` · `INSOLVENCY→8.1` | 유지 |
| 8.5 계열(`DELISTING_RISK`·`EARNINGS_SHOCK`·`WATCH_ISSUE`) | 유지 — 문서화된 의도적 매핑 |
| `CB_BW→1.1/1.5/1.6` | **보류** — 1.1은 `fund_diversion_chain`(1년 132장, 최다)의 요구 신호라 건드리면 파급이 크다. 아래 별도 테스트로 사실만 고정한다 |

⚠ **이 프록시는 약하다.** 후속 실측(2026-08-25)에서 `TAXONOMY[*].keywords`
자체가 **217개 중 166개(76%)가 죽어 있음**을 확인했다 — 0%가 나오는 주된
이유는 매핑이 틀려서가 아니라 **taxonomy 키워드 목록이 낡아서**다. 그래서
이 sweep은 "결함 탐지기"가 아니라 **"판단을 적었는지 묻는 장치"**로 쓴다.
실제 판정은 위 표처럼 사람이 제목을 보고 내렸다.

이 파일은 **비율을 고정하지 않는다**(코퍼스가 갱신되면 흔들린다).
대신 ① 위 판단이 뒤집히지 않았는지 ② 새 0% 매핑이 생기지 않았는지를 본다.
"""
import collections
import json
import pathlib

import pytest

from dart_risk_mcp.core.qualifiers import (
    TIER_OBSERVED, parse_report_name, qualify_signals,
)
from dart_risk_mcp.core.signals import SIGNAL_KEY_TO_TAXONOMY as SKT, match_signals
from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS, TAXONOMY

_ROOT = pathlib.Path(__file__).resolve().parents[1]
_CORPUS = json.loads((_ROOT / "tests" / "fixtures" / "corpus"
                      / "signal_titles_365d.json").read_text(encoding="utf-8"))

# 위 표에서 "유지/보류"로 판단한 것들 — 근거를 남긴 상태다.
_ACCEPTED = {
    ("EXEC", "3.3"), ("SHAREHOLDER", "3.2"), ("ASSET_TRANSFER", "5.3"),
    ("RELATED_PARTY", "4.2"), ("AUDIT", "8.4"), ("INQUIRY", "7.1"),
    ("EMBEZZLE", "8.1"), ("DELISTING_RISK", "8.5"), ("EARNINGS_SHOCK", "8.5"),
    # ("CB_BW", "1.1")은 2026-08-26에 **목록에서 빠졌다** — 0%였던 이유가
    # 매핑이 아니라 개념어의 조사 하나였다(「전환가액조정」 vs 실제 표기
    # 「전환가액**의**조정」 1년 338건). 실제 표기를 개념어에 더하니 28.7%다.
    ("WATCH_ISSUE", "8.5"), ("CB_BW", "1.5"), ("CB_BW", "1.6"),
    # ("MEZZ_EXERCISE", "1.8") — **taxonomy 자체 키워드가 비어 있어서** 0%다.
    # 매핑이 약해서가 아니라 스윕의 입력이 없는 것이다. `1.8`은 2026-09-02에
    # 신설했고(위험 목록 10번 B) 그 신호의 관찰 제목이 곧 정의 그 자체라
    # (「전환청구권행사」 = 메자닌 전환·행사) 개념어를 따로 둘 필요가 없다.
    # ⚠ 개념어를 넣고 싶어지면 먼저 `8.5`를 보라 — 같은 이유로 비어 있고
    #    같은 이유로 이 목록에 셋이 올라와 있다(DELISTING_RISK·EARNINGS_SHOCK·
    #    WATCH_ISSUE). 무점수 관찰 유형의 공통 성질이다.
    ("MEZZ_EXERCISE", "1.8"),
}


def _observed_titles():
    obs = collections.defaultdict(collections.Counter)
    for t in _CORPUS["titles"]:
        nm, n = t["nm"], t.get("n", 1)
        sigs = match_signals(nm)
        for m, q in zip(sigs, qualify_signals(sigs, parse_report_name(nm),
                                              {"report_nm": nm})):
            if q.tier == TIER_OBSERVED:
                obs[m["key"]][nm.replace(" ", "")] += n
    return obs


def test_근거_0퍼센트_매핑은_전부_기록돼_있다():
    obs = _observed_titles()
    unlisted = []
    for key, tids in SKT.items():
        titles = obs.get(key)
        if not titles:
            continue
        for tid in tids:
            kws = (TAXONOMY.get(tid) or {}).get("keywords") or []
            hit = sum(n for nm, n in titles.items()
                      if any(k.replace(" ", "") in nm for k in kws))
            if hit == 0 and (key, tid) not in _ACCEPTED:
                unlisted.append((key, tid, sum(titles.values())))
    assert not unlisted, (
        "제목이 뒷받침하지 않는 새 매핑 — 판단을 적고 _ACCEPTED에 넣으세요: "
        f"{unlisted}"
    )


def test_리픽싱_매핑은_이제_근거가_있다():
    """0%가 사라졌다는 사실을 **양방향으로** 고정한다.

    `_ACCEPTED`는 "0%인데 목록에 없으면 실패"만 본다 — 0%가 아니게 된 항목을
    목록에 남겨 둬도 아무도 안 잡는다. 그래서 기록이 조용히 낡는다.
    """
    obs = _observed_titles()
    titles = obs["CB_BW"]
    kws = [k.replace(" ", "") for k in TAXONOMY["1.1"]["keywords"]]
    hit = sum(n for nm, n in titles.items() if any(k in nm for k in kws))
    assert hit > 0, "1.1 근거가 다시 0이 됐다 — 개념어에서 실제 표기가 빠졌나?"
    assert "전환가액의조정" in TAXONOMY["1.1"]["keywords"]
    # 조사 없는 옛 표기도 남겨 둔다 — 다른 표기가 나타날 수 있다.
    assert "전환가액조정" in TAXONOMY["1.1"]["keywords"]


def test_근사_불일치는_이_한_건뿐이었다():
    """1년 전수에서 「조사 하나 차이」 후보가 더 있는지 — 없다는 사실을 남긴다.

    있으면 같은 종류의 침묵이 또 있다는 뜻이라 근거를 적고 고쳐야 한다.
    """
    import difflib

    obs = _observed_titles()
    near = []
    for key, tids in SKT.items():
        titles = obs.get(key)
        if not titles:
            continue
        for tid in tids:
            kws = [k.replace(" ", "") for k in
                   ((TAXONOMY.get(tid) or {}).get("keywords") or [])]
            if any(k in nm for nm in titles for k in kws):
                continue
            for k in kws:
                for nm in titles:
                    for i in range(max(1, len(nm) - len(k) - 2)):
                        frag = nm[i:i + len(k) + 2]
                        if difflib.SequenceMatcher(None, k, frag).ratio() >= 0.85:
                            near.append((key, tid, k, frag))
    assert not near, f"조사 하나 차이로 어긋난 개념어가 또 있다: {near[:5]}"


@pytest.mark.parametrize("key", ["EXEC", "MGMT"])
def test_승계_분쟁을_중복_주장하지_않는다(key):
    assert "3.4" not in SKT[key], f"{key}가 3.4를 다시 주장한다"


def test_삼점사는_경영권분쟁이_소유한다():
    owners = {k for k, v in SKT.items() if "3.4" in v}
    assert owners == {"MGMT_DISPUTE"}, owners


def test_고아를_만들지_않았다():
    """제거한 매핑의 taxonomy가 소유자를 잃지 않았는지."""
    for tid in ("3.4", "5.4", "3.3"):
        owners = {k for k, v in SKT.items() if tid in v}
        assert owners, f"{tid}가 고아가 됐다"


def test_삼점사_삼점삼은_어느_패턴에도_안_쓰인다():
    """패턴에 쓰였다면 이 정리가 카드 발화를 바꿨을 것이다."""
    used = {t for v in CROSS_SIGNAL_PATTERNS.values()
            for t in v["signal_sequence"]}
    assert "3.4" not in used and "3.3" not in used


def test_경영권분쟁_신호는_근거가_있다():
    """제거의 전제 — MGMT_DISPUTE는 실제로 3.4의 조건어를 담은 제목에 붙는다."""
    obs = _observed_titles()
    titles = obs.get("MGMT_DISPUTE") or {}
    kws = [k.replace(" ", "") for k in TAXONOMY["3.4"]["keywords"]]
    hit = sum(n for nm, n in titles.items() if any(k in nm for k in kws))
    assert hit > 0 and hit == sum(titles.values()), (
        f"MGMT_DISPUTE 근거율이 100%가 아니다: {hit}/{sum(titles.values())}"
    )
