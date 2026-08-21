# 복합 패턴에 순서·간격 축을 넣어야 하는가 — 실측과 판단 (2026-08-21)

**결론: 넣지 않는다.** 근거가 부족하다. 아래는 그 판단의 근거가 된 측정이다.

수치는 전부 실 DART API로 측정한 값이다. 판단 부분은 판단이라고 명시했다.

---

## 1. 질문

`CROSS_SIGNAL_PATTERNS`의 각 패턴에는 `signal_sequence`(taxonomy id 목록)와
`timeline_months`가 있다. 이름과 값이 **서사 순서**로 읽힌다:

```
founder_fade (창업주 퇴장) · timeline 18개월
  3.2 지배주주 저가 엑시트 → 3.1 채권 전환을 통한 최대주주 변경
  → 4.1 주주총회 절차 위반 → 5.3 장외 자산 이전 → 8.1 인위적 부실화
```

그런데 매칭은 순서를 보지 않는다. `find_pattern_match`는 부분집합 판정이고,
2026-08-17에 추가한 `find_pattern_overlaps`도 교집합 크기만 센다.
`timeline_months`는 **어디에서도 매칭에 쓰이지 않는다**(`capital_backflow`·
`capital_churn_anomaly`만 별도 게이트를 갖는다).

"무자본 M&A의 본질은 신호 종류가 아니라 순서(경영권 변경 → 자금유출 → 부실화)
아닌가"라는 문제 제기가 있었다. 그렇다면 순서·간격을 매칭 조건으로 넣어야 한다.

**넣기 전에 물어야 할 것: 실제 공시에서 그 순서가 지켜지는가?**

---

## 2. 방법

12개 회사 × 조회창 **1,095일(3년)**. 회사마다:

1. `fetch_company_disclosures`로 공시를 받고
2. `match_signals` → `qualify_signals`로 **observed 신호만** 남기고
3. 신호를 `SIGNAL_KEY_TO_TAXONOMY`로 taxonomy id에 매핑해
4. **id별 최초 관찰일**을 구한다.

패턴별로 매칭된 id가 2개 이상이면 관측 1건으로 삼고, 두 지표를 잰다:

- **순서 일치율** — 매칭된 id의 모든 쌍에 대해 `signal_sequence`상 앞선 id가
  실제로도 먼저(또는 같은 날) 관찰됐는지. 무작위면 50%.
- **기간** — 최초~최후 관찰일의 개월 수. `timeline_months`와 비교.

회사 구성은 신호가 많이 잡히는 곳(아이톡시·제이스코홀딩스·이엠티·아틀라스링크·
오르비텍·CG인바이츠·헬릭스미스·STX)과 대조군(나이스정보통신·두산·셀트리온·
삼성전자)을 섞었다. 스크립트 전문은 부록 A.

---

## 3. 실측 (관측 37건)

| 회사 | 패턴 | 매칭 | 순서 일치 | 기간(월) | timeline |
|---|---|---|---|---:|---:|
| 아이톡시 | founder_fade | 4/5 | 2/6 | 0 | 18 |
| 아이톡시 | related_party_hollowing | 2/5 | 1/1 | 0 | 15 |
| 아이톡시 | zombie_ma | 4/6 | 5/6 | 15 | 12 |
| 아이톡시 | audit_insider_dump | 2/3 | 0/1 | 15 | 6 |
| 아이톡시 | delisting_evasion | 3/6 | 3/3 | 7 | 9 |
| 아이톡시 | fake_new_biz | 2/4 | 1/1 | 8 | 6 |
| 제이스코홀딩스 | founder_fade | 3/5 | 3/3 | 32 | 18 |
| 제이스코홀딩스 | zombie_ma | 4/6 | 4/6 | 30 | 12 |
| 제이스코홀딩스 | audit_insider_dump | 2/3 | 0/1 | 27 | 6 |
| 제이스코홀딩스 | delisting_evasion | 3/6 | 0/3 | 35 | 9 |
| 제이스코홀딩스 | fake_new_biz | 2/4 | 1/1 | 30 | 6 |
| 제이스코홀딩스 | capital_backflow | 2/2 | 1/1 | 13 | 12 |
| 이엠티 | founder_fade | 2/5 | 1/1 | 0 | 18 |
| 이엠티 | zombie_ma | 3/6 | 3/3 | 3 | 12 |
| 이엠티 | audit_insider_dump | 2/3 | 0/1 | 3 | 6 |
| 이엠티 | fake_new_biz | 2/4 | 1/1 | 0 | 6 |
| 아틀라스링크 | founder_fade | 2/5 | 1/1 | 0 | 18 |
| 아틀라스링크 | debt_spiral | 2/5 | 1/1 | 18 | 12 |
| 아틀라스링크 | zombie_ma | 3/6 | 1/3 | 9 | 12 |
| 아틀라스링크 | audit_insider_dump | 2/3 | 1/1 | 9 | 6 |
| 아틀라스링크 | fake_new_biz | 3/4 | 1/3 | 12 | 6 |
| 아틀라스링크 | capital_backflow | 2/2 | 0/1 | 27 | 12 |
| 아틀라스링크 | fund_diversion_chain | 2/2 | 1/1 | 23 | 12 |
| 오르비텍 | founder_fade | 2/5 | 1/1 | 0 | 18 |
| 오르비텍 | zombie_ma | 2/6 | 0/1 | 20 | 12 |
| 오르비텍 | fund_diversion_chain | 2/2 | 1/1 | 0 | 12 |
| 헬릭스미스 | founder_fade | 2/5 | 1/1 | 0 | 18 |
| 헬릭스미스 | zombie_ma | 4/6 | 3/6 | 4 | 12 |
| 헬릭스미스 | audit_insider_dump | 2/3 | 0/1 | 2 | 6 |
| 헬릭스미스 | delisting_evasion | 2/6 | 0/1 | 2 | 9 |
| 헬릭스미스 | fake_new_biz | 2/4 | 1/1 | 4 | 6 |
| STX | zombie_ma | 3/6 | 3/3 | 21 | 12 |
| STX | audit_insider_dump | 2/3 | 0/1 | 13 | 6 |
| STX | delisting_evasion | 3/6 | 1/3 | 27 | 9 |
| STX | fake_new_biz | 2/4 | 1/1 | 6 | 6 |
| 나이스정보통신 | zombie_ma | 2/6 | 1/1 | 0 | 12 |
| 나이스정보통신 | fake_new_biz | 3/4 | 3/3 | 13 | 6 |

**집계**

| 지표 | 값 |
|---|---|
| 순서 일치율(쌍별) | **48/75 = 64%** (무작위 50%) |
| `timeline_months` 안에 들어온 관측 | **18/37 = 49%** |
| 실제 기간 | 중앙값 **9개월** · 최대 **35개월** |

대조군 중 두산·셀트리온·삼성전자는 매칭 2개 이상인 패턴이 없어 표에 나타나지
않는다(= 관측 0건). 이는 2026-08-17 부분 겹침 실측에서 대조군의 부분 일치가
0이었던 것과 같은 결과다.

---

## 4. 읽기

**순서 일치 64%는 제약으로 쓰기에 부족하다.** 무작위(50%)보다는 높지만
**셋 중 하나는 순서를 어긴다.** 제약으로 넣으면 그만큼을 떨어뜨린다.
같은 패턴이 회사마다 다르게 나타나는 것도 확인된다 — `zombie_ma`가 아이톡시는
5/6인데 아틀라스링크는 1/3, `delisting_evasion`이 아이톡시는 3/3인데
제이스코홀딩스는 0/3이다.

표본 한계도 분명하다: 회사 12곳, 쌍 75개이고 **한 회사 안의 쌍들은 독립이
아니다**(같은 공시 이력에서 나온다). 64%를 "약한 양의 신호"로 읽는 것 이상은
이 표본으로 할 수 없다.

**`timeline_months`는 데이터와 맞지 않는다.** 49%면 동전 던지기다.
제이스코홀딩스 `founder_fade`는 32개월(설정 18개월), STX `delisting_evasion`은
27개월(설정 9개월)이다. 이 값이 지금 매칭에 쓰이지 **않는 것이 오히려
안전했다.**

**왜 순서가 흐트러지는가 (판단).** 이 도구가 보는 것은 **회사가 낸 공시의
접수일**이지 사건의 발생 순서가 아니다. 정기보고서는 몇 달 뒤에 나오고,
감사의견은 연 1회 시점에 몰리며, 거래소 제재 공시는 조사가 끝난 뒤에 나온다.
같은 사건이라도 공시 유형에 따라 시차가 제각각이라, 사건 순서가 공시 순서로
그대로 보존되지 않는다.

---

## 5. 결정

1. **순서·간격을 매칭 제약으로 넣지 않는다.** 64%·49%로는 근거가 부족하고,
   넣으면 진짜 사례를 떨어뜨린다. 현재의 순서 무관 집합 판정을 유지한다.
2. **표시로는 가능하다(미구현).** 관찰된 신호를 시간순으로 늘어놓고 패턴이
   상정한 순서를 나란히 보여주는 것은 사실 표기라 무판정 원칙과 충돌하지
   않는다. 사용자가 직접 대조할 재료가 된다. 필요해지면 그때 만든다.
3. **`timeline_months`에 실측 주석을 단다.** 필드가 남아 있어 "매칭에 쓰이는
   줄" 오해를 부르는데 데이터와 맞지 않는다. 이 문서와 함께 `taxonomy.py`에
   주석을 남겼다.

---

## 6. 이 측정이 못 답한 것

- **금감원 사례로는 검증할 수 없다.** 카탈로그 277건 중 taxonomy id를 2개
  이상 가진 사례가 37건뿐이고 패턴 전체를 담은 사례는 0건이다(2026-08-17
  실측). 보도자료 한 건은 회사 하나의 사건이라 순서 검증의 표본이 되지 못한다.
- **"진짜 무자본 M&A"만 골라 재지 않았다.** 대상 회사는 신호가 많이 잡히는
  곳으로 골랐을 뿐, 실제로 그 패턴이 성립한 회사인지는 확인하지 않았다.
  적발 확정 사례 목록이 있다면 그 집합에서 다시 재는 것이 더 강한 검증이다.
- **표본이 작다.** 회사 12곳. 순서 일치율의 신뢰구간을 좁히려면 수백 개
  회사가 필요하다.

---

## 부록 A — 측정 스크립트

`DART_API_KEY` 환경변수가 필요하고 수 분 걸린다. 레포에 스크립트를 추가하지
않은 이유는 1회성 조사이고 실행에 실 API 키가 필요하기 때문이다.

```python
"""signal_sequence의 순서가 실제 공시에서 지켜지는지 실측."""
import collections, itertools, os, sys, statistics as st
from dart_risk_mcp.core.dart_client import fetch_company_disclosures, resolve_corp
from dart_risk_mcp.core.qualifiers import parse_report_name, qualify_signals
from dart_risk_mcp.core.signals import SIGNAL_KEY_TO_TAXONOMY, match_signals
from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS as P

KEY = os.environ["DART_API_KEY"]
DAYS = 1095
COMPANIES = ["아이톡시","제이스코홀딩스","이엠티","아틀라스링크","오르비텍","CG인바이츠",
             "헬릭스미스","STX","나이스정보통신","두산","셀트리온","삼성전자"]

def first_dates(corp):
    """taxonomy id -> 최초 관찰일(YYYYMMDD)"""
    out = {}
    for r in fetch_company_disclosures(corp, KEY, DAYS):
        nm, d = r.get("report_nm") or "", r.get("rcept_dt") or ""
        ms = match_signals(nm)
        if not ms or not d:
            continue
        for qi in qualify_signals(ms, parse_report_name(nm), filing=r):
            if getattr(qi, "tier", "observed") != "observed":
                continue
            for t in (SIGNAL_KEY_TO_TAXONOMY.get(qi.key) or []):
                if t not in out or d < out[t]:
                    out[t] = d
    return out

pairs_ok = pairs_tot = 0
spans = []
for name in COMPANIES:
    cn, info = resolve_corp(name, KEY)
    fd = first_dates(info["corp_code"])
    for k, p in P.items():
        seq = p["signal_sequence"]
        m = [t for t in seq if t in fd]
        if len(m) < 2:
            continue
        ok = sum(1 for a, b in itertools.combinations(m, 2) if fd[a] <= fd[b])
        pairs_ok += ok
        pairs_tot += len(list(itertools.combinations(m, 2)))
        ds = sorted(fd[t] for t in m)
        span = (int(ds[-1][:4]) * 12 + int(ds[-1][4:6])) - (int(ds[0][:4]) * 12 + int(ds[0][4:6]))
        spans.append((span, p.get("timeline_months")))

print(f"순서 일치율 {pairs_ok}/{pairs_tot} = {pairs_ok/pairs_tot:.1%}")
within = sum(1 for s, tl in spans if tl and s <= tl)
print(f"timeline 안: {within}/{len(spans)} = {within/len(spans):.0%}")
print(f"기간 중앙값 {st.median(s for s, _ in spans):.0f}개월 · 최대 {max(s for s, _ in spans)}개월")
```

---

## 관련 문서

- `docs/catalog/gap-triage-2026-08-17.md` — 갭 후보 분류. §4의 "유형을 추가하기
  전에 DART 제목에 실제로 등장하는지 먼저 재라"와 같은 절차를 따른 조사다.
