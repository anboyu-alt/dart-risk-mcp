# -*- coding: utf-8 -*-
"""신호 한정층 — 공시 제목 구조 파싱 + 신호 표시 계층 판정.

match_signals(signals.py)는 제목에 키워드가 들어있는지만 본다. 그래서
부정("해제"·"철회")·방향(발행/취득)·주체(회사/제3자)·수식어(제3자배정/일반공모)를
구분할 수단이 없고, 정상 공시가 위험 신호로 잡힌다.

이 모듈은 match_signals '이후'에 동작한다. 신호를 지우지 않고 tier만 붙인다:
- observed:   회사가 낸, 해당 사건 자체의 공시
- procedural: 제3자 제출 / 사후 보고 / 철회·해제 / 해명 / 정정

순수 함수만 둔다 — 네트워크 호출 없음.
"""
import re
from dataclasses import dataclass

from .dart_client import _fold_corp_name
from .signals import AMBIGUOUS_SIGNAL_KEYS

# 본체 어미 후보. 긴 것이 먼저 매칭돼야 하므로 _tail_of가 길이순으로 검사한다.
# 'ㆍ'(U+318D)는 DART 실제 표기라 그대로 둔다.
TAILS: tuple[str, ...] = (
    "해제ㆍ취소등", "결과보고서", "계약체결", "보고서", "결정", "해제",
    "취소", "철회", "해지", "중단", "해명", "신청", "확정", "변경",
    "발생", "요구", "취득", "매도",
)

_TAG_RE = re.compile(r"^\[([^\]]*)\]\s*")
_PAREN_RE = re.compile(r"\(([^()]*)\)")
_WS_RE = re.compile(r"\s+")


@dataclass(frozen=True)
class ParsedName:
    """공시 제목을 구조 조각으로 나눈 결과.

    tags:      대괄호 접두 태그 — ("첨부정정",)
    body:      태그·괄호를 뺀 본체 (공백 제거)
    subtitles: 괄호 내용 (공백 제거)
    tail:      본체의 마지막 어미 토큰. 본체가 '~보고서' 껍데기이고 괄호가
               어미를 가지면 괄호 쪽 어미를 쓴다.
    compact:   태그를 뺀 전체 문자열 (공백 제거) — 부분 검사용
    """

    tags: tuple[str, ...]
    body: str
    subtitles: tuple[str, ...]
    tail: str
    compact: str


def _tail_of(text: str) -> str:
    """text가 TAILS 중 하나로 끝나면 그 어미를 반환. 긴 것 우선."""
    for cand in sorted(TAILS, key=len, reverse=True):
        if text.endswith(cand):
            return cand
    return ""


def parse_report_name(report_nm: str) -> ParsedName:
    """공시 제목을 {태그, 본체, 괄호부제, 어미}로 나눈다.

    공백은 전부 제거한다 — DART 표기가 '자회사의 주요경영사항'과
    '종속회사의주요경영사항'처럼 띄어쓰기가 섞여 오기 때문이다.
    """
    rest = (report_nm or "").strip()
    tags: list[str] = []
    while True:
        m = _TAG_RE.match(rest)
        if not m:
            break
        tags.append(m.group(1).strip())
        rest = rest[m.end():]

    compact = _WS_RE.sub("", rest)
    subtitles = tuple(s for s in _PAREN_RE.findall(compact) if s)
    body = _PAREN_RE.sub("", compact)

    tail = _tail_of(body)
    # '주요사항보고서(자기주식취득결정)'처럼 본체가 껍데기면 괄호 쪽을 본다.
    if tail == "보고서" and subtitles:
        inner = _tail_of(subtitles[-1])
        tail = inner or tail

    return ParsedName(
        tags=tuple(tags),
        body=body,
        subtitles=subtitles,
        tail=tail,
        compact=compact,
    )


TIER_OBSERVED = "observed"
TIER_PROCEDURAL = "procedural"

# R1 예외 — 제출인이 거래소 시장본부인 공시.
#
# 거래소가 회사에 대해 내는 조치·요구(조회공시요구·불성실공시법인지정·
# 주권매매거래정지)는 flr_nm이 회사가 아니라 시장본부라 R1(제출인≠회사)에
# 그대로 걸린다. 그런데 이것들은 회사가 낸 해명·정정이 아니라 관찰해야 할
# 사건 그 자체다(설계 §195-196, §445 — "거래소가 요구한 조회공시는 남는다").
# 강등되면 INQUIRY·DISCLOSURE_VIOL이 관찰 집계·헤드라인·패턴 매칭에서
# 통째로 빠져 탈출기 서사와 capital_churn_anomaly가 무너진다.
#
# 라이브 실측(2026-08-14, /list.json pblntf_ty=I, 20260701~20260814 6,341행
# 전수 — corp_name과 다른 flr_nm을 전부 수집해 도출):
#   코스닥시장본부   389행  예) 불성실공시법인지정(공시번복) / 스코넥 / 20260812900993
#   유가증권시장본부  71행  예) 조회공시요구(현저한시황변동) / 금호전기 / 20260813801194
#   코넥스시장       13행  예) 주권매매거래정지(지정자문인 선임계약 해지) / 퓨쳐메디신 / 20260812600521
# 코넥스만 '본부'가 붙지 않는다 — '시장본부'로 거르면 코넥스 조치가 통째로
# 사라진다. 세 값이 관측된 전부이며 '시장감시위원회'·'거래소' 표기는 없었다.
#
# 회사 자신이 낸 조회공시 답변('조회공시요구에대한답변(미확정)')은 flr_nm이
# 회사라 애초에 R1 대상이 아니고, R4(미확정)가 그대로 강등한다.
EXCHANGE_FILERS: tuple[str, ...] = (
    "코스닥시장본부",
    "유가증권시장본부",
    "코넥스시장",
)


def is_exchange_filer(filer: str) -> bool:
    """제출인 표기가 거래소 시장본부인지. 부분 일치로 본다.

    '한국거래소 코스닥시장본부'처럼 앞에 기관명이 붙어 와도 걸리도록
    포함 검사를 쓴다. 오판해도 방향이 안전하다 — 강등하지 않고 기존
    동작(observed)으로 남기는 쪽이다.
    """
    f = (filer or "").strip()
    return bool(f) and any(m in f for m in EXCHANGE_FILERS)

# R1b — 제3자가 회사에 대해 제출하는 보고서. 본체가 이것으로 시작하면
# 회사의 행위가 아니다(제출인은 국민연금·블랙록·개인 임원 등).
THIRD_PARTY_TITLES: tuple[str, ...] = (
    "주식등의대량보유상황보고서",
    "임원ㆍ주요주주특정증권등소유상황보고서",
    "최대주주등소유주식변동신고서",
)

# R2 — 이미 실행됐거나 되돌린 국면. 어미가 이것이면 새 사건이 아니다.
PHASE_TAILS: tuple[str, ...] = (
    "결과보고서", "해제ㆍ취소등", "해제", "취소", "철회", "해지", "중단",
)

# R2 예외 — 어미는 '해제'지만 국면이 끝난 게 아니라 **다음 단계로 넘어간** 경우.
# 「주권매매거래정지해제(상장폐지에 따른 정리매매 개시)」는 매매정지가 풀려 정상으로
# 돌아왔다는 뜻이 아니라, 상장폐지가 확정돼 정리매매(상장폐지 전 마지막 매매)가
# 시작된다는 뜻이다 — 거래소 퇴출 절차에서 가장 무거운 국면인데 어미만 보면 해소로
# 읽힌다. 이 예외가 없으면 그 공시가 "체결이 아니라 해제입니다"로 강등돼 집계·
# 헤드라인에서 전부 빠진다.
#
# 실측(2026-05-24~08-22, 90일·고유 공시 48,646건): 상장폐지 절차 계열 177건 중
# R2가 강등한 23건을 전수 확인한 결과 두 갈래였다 —
#   · 21건: 정리매매 개시(20)·재개(1) → **강등이 틀렸다**(국면 상승)
#   ·  2건: 「상장폐지사유 미해당」·「상장적격성 실질심사 대상 제외 결정」
#           → **강등이 옳다**(실제로 해소된 건)
# 그래서 어미가 아니라 **괄호 부제**로 가른다. 부제에 아래 표현이 있으면 R2를
# 건너뛴다. 두 해소 건은 부제가 달라 그대로 강등된다.
# R2 보강 — 본체가 사건을 담지 않는 **포장 제목**은 괄호 부제가 실제 사건이다.
# 「기타주요경영사항(제3자배정유상증자결정철회)」의 tail은 본체 '기타주요경영사항'
# 에서 뽑히므로 PHASE_TAILS에 걸리지 않아, 증자를 **철회**한 건이 관찰 신호
# '제3자배정유상증자'로 그대로 표시됐다. 같은 사건이 「제3자배정유상증자결정철회」
# 라는 단독 제목이면 tail='철회'로 강등되는데, 포장지가 씌워지면 강등되지 않는
# 비일관이다.
#
# 아래 목록은 실측(2026-05-24~08-22, 90일)에서 부제가 PHASE_TAILS로 끝나는 제목의
# body 분포를 전수로 보고 고른 것이다. 「소송등의제기ㆍ신청(경영권분쟁소송)
# (주주총회결의취소)」는 **넣지 않았다** — body가 '제기·신청'이라는 행위 자체를
# 담고 있고 '주주총회결의취소'는 소송의 청구 취지이지 소송 철회가 아니다.
WRAPPER_BODIES: tuple[str, ...] = (
    "기타주요경영사항",
    "기타경영사항",
    "투자판단관련주요경영사항",
)

# R2c — 본체 자체가 **결과 보고**인 제목. 어미(괄호)가 '자율공시'라 PHASE_TAILS에
# 걸리지 않는다.
#
# 실사고(2026-08-24, SK하이닉스 실물): 「주요사항보고서(유상증자결정)」(20260624)과
# 「유상증자또는주식관련사채등의발행결과(자율공시)」(20260715)가 **둘 다 관찰
# 신호**로 잡혀 헤드라인이 「유상증자 ×2」였다. 증자는 한 번이다.
#
# core는 이 표기를 이미 사후 보고로 알고 있었다 — `CHURN_RESULT_MARKS`
# (v1.20.10)가 자본 이벤트 집계에서 같은 이유로 뺀다. **두 층이 서로 다른
# 답을 내고 있었다.**
#
# 1년 코퍼스 실측: 발행결과 391건(3PCA 371·RCPS 17·CB_BW 3) + 청약결과 123건
# (전부 3PCA) = **514건이 전부 관찰**이었다(강등 0). 반면 같은 뜻의 어미
# '결과보고서'는 946건이 이미 강등돼 있다 — **표기가 달라서 갈렸을 뿐이다**.
#
# body가 '결과'로 끝나는 표기는 1년 전수에서 위 셋뿐이라 오탐 여지가 없다.
# 회사 단위 영향(90일 시장 전수, 증자·메자닌 관찰 505개사): 결과보고를 가진
# 73개사 중 **63개사(86%)는 결정도 같은 창에 있어** 순수한 중복 제거이고,
# 나머지 10개사는 결정이 창 밖이라 관찰이 0이 된다 — 다만 강등은 삭제가
# 아니라 「절차·사후 보고」 절로의 이동이므로 사실 자체는 계속 보인다.
RESULT_BODY_MARKS: tuple[str, ...] = ("발행결과", "청약결과")

ESCALATION_SUBTITLES: tuple[str, ...] = (
    "정리매매개시", "정리매매재개",
    # 2026-08-23 — 1년 코퍼스로 R2 강등을 **전수**(38행 / 1,105건) 재검토해
    # 찾은 둘. v1.12.2가 90일 창에서 23건을 훑어 정리매매를 갈라낸 것과 같은
    # 작업이며, 창을 넓히니 두 종류가 더 나왔다.
    #
    #   「매매거래정지및정지해제(풍문등조회공시)」 10건
    #     본체가 정지와 해제를 **함께** 알리는데 어미만 보면 '해제'다. 사건은
    #     풍문에 대한 조회공시이고, 형제 제목 「조회공시요구(풍문또는보도)」
    #     28건은 관찰이다 — 같은 사건이 어미 때문에 갈렸다.
    #
    #   「주권매매거래정지해제(회생절차개시결정)」 1건
    #     법원이 회생절차를 **개시**해서 정지가 풀린 것이다. 같은 부제의
    #     「주권매매거래정지기간변경(회생절차 개시결정)」 11건은 관찰인데
    #     이것만 강등됐다. 부제가 같으면 판정도 같아야 한다.
    #     (부분 문자열이라 「'회생절차개시결정의 취소결정'에 대한 재항고
    #      취하…」 1건도 함께 관찰로 올라간다 — 회생 취소를 다투는 국면이라
    #      GOING_CONCERN 관찰이 맞고, 옛 사유 "체결이 아니라 해제입니다"는
    #      그 제목에도 사실이 아니었다.)
    #
    # 나머지 36행은 전부 정당한 강등이었다 — 결과보고서 946 · 계약해제ㆍ취소
    # 102 · 각종 철회 · 「상장폐지 사유 해소」 · 「실질심사 대상 제외 결정」.
    "풍문등조회공시",
    "회생절차개시결정",
)

# R3 — 공시 주체가 이 회사가 아닌 경우. 공백 제거 후 비교한다.
SUBSIDIARY_SUBTITLES: tuple[str, ...] = (
    "종속회사의주요경영사항",
    "자회사의주요경영사항",
    "관계회사의주요경영사항",
)
# R3에는 「특수관계인의」 접두 규칙이 있었다. 뜻이 반대라 2026-08-23에 뺐다.
#
# 그 규칙이 1년 코퍼스에서 실제로 잡던 제목은 **한 종류뿐**이었다 —
# 「특수관계인의유상증자참여」 275건. 그런데 원문 13건을 전수로 열어 보니
# 이 공시는 "특수관계인이 한 일"이 아니라 **이 회사가 유상증자를 했고 그
# 신주를 계열회사가 인수한 건**이었다(참여자 관계 계열회사 13/13,
# 공정거래법 제26조 13/13). 강등 사유로 "회사가 아니라 특수관계인의
# 행위입니다"를 띄우고 있었으니 사용자에게 사실과 반대인 설명을 준 셈이다.
#
# 형제 공시와도 어긋났다. 같은 공정거래법 제26조 대규모내부거래 공시인데
# 판정이 이것만 달랐다(2026-08 시장 실측):
#   특수관계인으로부터자금차입 63건 관찰 · 특수관계인에대한자금대여 37건 관찰
#   특수관계인에대한출자 20건 관찰 · 특수관계인으로부터받은담보 13건 관찰
#   특수관계인에대한담보제공  9건 관찰 · **특수관계인의유상증자참여 13건 강등**
#
# 신호는 3PCA로 두고 tier만 형제와 맞춘다. 배정방식은 제목에 없으므로
# LABEL_OVERRIDES가 "유상증자(배정방식 미상)"으로 표기한다 — 실제로 원문
# 표본의 배정방식은 주주배정이었다(확인된 5건 전부).

# R1c — 집합투자증권(펀드) 서류. 회사가 낸 사건 공시가 아니라 자산운용사가
# 내는 상품 등록·판매 서류이고, **제목에 상품명이 통째로 들어가** 회사 사건
# 키워드와 부딪힌다.
#
# 이 함정은 이 레포에서 이미 두 번 우연히 발견됐다(둘 다 코드 주석에 남아 있다).
#   `"미달"` ← 「미(美)달러」 · `"지연"` ← 「글로벌클린에너지연금증권」
# 세 번째를 기다리는 대신 문서 종류로 가른다.
#
# 1년 코퍼스 실측(2026-08-23): 「집합투자증권」이 든 제목 중 신호가 붙는 것은
# 6종 6건이고 **전부 상품명 때문**이었다.
#   자사주매입고배당주…투자신탁      → TREASURY  (3건)
#   글로벌4차산업전환사채증권…투자신탁 → CB_BW     (2건)
#   지속가능글로벌테마주증권투자신탁   → THEME_STOCK(1건)
# 본체는 일괄신고서·증권발행실적보고서·투자설명서뿐이고, 이 마커가 회사
# 사건을 삼키는 사례는 **0건**이다.
#
# ⚠ 관측된 마커만 넣는다. 다른 상품 계열(파생결합증권 등)이 신호를 켜는
# 사례는 이번 코퍼스에 없었다 — 나오면 그때 근거와 함께 넓힌다.
FUND_PRODUCT_MARKS: tuple[str, ...] = (
    "집합투자증권",
)

# R5 — 기존 공시의 정정·후속. '[정정명령부과]'는 규제기관 조치라 여기 없다.
AMENDMENT_TAGS: tuple[str, ...] = (
    "기재정정", "첨부정정", "첨부추가", "정정", "발행조건확정", "연장결정",
)


def _wrapper_phase_tail(parsed) -> str:
    """포장 제목의 괄호 부제가 사후·해제 국면을 가리키면 그 어미를 돌려준다.

    본체가 `WRAPPER_BODIES`일 때만 본다. 국면 상승 예외(`_is_escalation`)가
    걸리면 빈 문자열(강등하지 않는다).
    """
    if parsed.body not in WRAPPER_BODIES or _is_escalation(parsed):
        return ""
    for sub in parsed.subtitles:
        for tail in PHASE_TAILS:
            if sub.endswith(tail):
                return tail
    return ""


def _is_escalation(parsed) -> bool:
    """어미가 해제·취소류여도 국면이 다음 단계로 넘어간 제목인가.

    괄호 부제에 `ESCALATION_SUBTITLES`가 하나라도 들어 있으면 참. 부제는
    `parse_report_name`이 이미 공백을 제거해 두므로 부분 문자열로 본다.
    """
    return any(
        esc in sub
        for sub in parsed.subtitles
        for esc in ESCALATION_SUBTITLES
    )


def _is_amendment_tag(tag: str) -> bool:
    """R5 태그 판정 — 완전 일치 또는 '정정'으로 끝남.

    '정정명령부과'는 '정정'으로 시작할 뿐 끝나지 않으므로 걸리지 않는다.
    """
    t = (tag or "").strip()
    return t in AMENDMENT_TAGS or t.endswith("정정")


def is_false_amendment(parsed: ParsedName) -> bool:
    """_AMENDMENT_RE에는 걸리지만 실제 정정공시가 아닌 경우.

    match_signals는 '[정정명령부과]증권신고서'를 정정공시로 오판해 신호를
    통째로 삭제한다. 호출부는 이 함수가 True일 때만 접두를 벗겨 재매칭한다 —
    진짜 정정공시([기재정정] 등)의 기존 동작은 바뀌지 않는다.
    """
    if not parsed.tags:
        return False
    return not any(_is_amendment_tag(t) for t in parsed.tags)


def supports_pattern(event: "dict") -> bool:
    """이 관찰 이벤트가 복합 패턴의 taxonomy 근거로 설 수 있는가.

    **방향 안내가 붙은 이벤트는 설 수 없다.** `DIRECTION_NOTES`가 붙었다는 것은
    "제목이 켠 신호 이름과 실제 방향·종류가 다르다"는 뜻이고, 패턴의
    `signal_sequence`는 **이름 쪽 방향**을 요구한다.

    실사고(2026-08-24, 사용자 제보 — SK하이닉스): 「부채 악순환」(CRITICAL)
    카드가 떴는데 근거 1.3은 *"Exchange Bond (EB) **Issuance**"*인 반면 실제
    공시는 「자기교환사채**만기전취득**결정」이었다. **사채를 갚은 건이
    부채가 늘어나는 패턴의 근거로 세어졌다** — 방향이 정반대다. 한정층은
    이미 "발행이 아니라 사채 취득·매도·소각 건입니다"라고 적고 있었고,
    자본 이벤트 집계도 `CHURN_NON_DILUTIVE_MARKS`로 같은 판단을 한다.
    **패턴 층만 그 판단을 버리고 있었다.**

    `DIRECTION_NOTES` 7종 전부에 같은 논리가 성립한다 —

        CB_BW·EB   되사기·소각  ↔ 1.1/1.3/1.5는 **발행**을 요구
        RCPS       소각        ↔ 1.4는 **발행**
        TREASURY   신탁 체결·해지 ↔ 2.6은 **직접 취득·재매각**
        RELATED_PARTY  회사가 **준** 출자 ↔ 4.2는 회사로 흘러드는 거래
        DEBT_RESTR 회사가 **해 준** 면제 ↔ 8.2는 회사가 받는 출자전환
        GOING_CONCERN  회생 **종결**  ↔ 8.4는 개시·폐지(부실 진입)

    ⚠ 신호를 지우지 않는다 — 관찰 목록·타임라인·집계에는 그대로 남고
    **패턴 근거로만** 서지 못한다. 방향 안내는 사용자에게 계속 보인다.
    """
    if not isinstance(event, dict):
        return False
    if event.get("tier", TIER_OBSERVED) != TIER_OBSERVED:
        return False
    if event.get("is_amendment"):
        return False
    return not (event.get("note") or "").strip()


@dataclass(frozen=True)
class Qualified:
    """한정된 신호 하나.

    key/label: 표시용. label은 보정될 수 있다(Task 4).
    tier:      TIER_OBSERVED | TIER_PROCEDURAL
    reason:    강등 사유 (사실 문장). observed면 "".
    note:      사실 주석 (방향 불일치 등). 없으면 "".
    """

    key: str
    label: str
    tier: str
    reason: str
    note: str


# R4 예외 — 거래소가 물었다는 사실은 답변의 확정 여부와 무관하다.
#
# R4는 "회사가 아직 정해진 게 없다고 답했다"를 근거로 강등한다. 그 논리가
# 맞는 신호도 있지만 `INQUIRY`에는 맞지 않는다 — taxonomy 7.1은 "공시 전
# 이상 거래(주가·거래량 급변)"이고, 거래소는 **그 이상 거래를 봤기 때문에**
# 물었다. 답변이 미확정이라고 해서 이미 일어난 시황 변동이 사라지지 않는다.
#
# 1년 코퍼스 실측(2026-08-23)에서 드러난 비일관:
#   조회공시요구(현저한시황변동)                        observed  77건
#   조회공시요구(풍문또는보도)에대한답변(부인)             observed   6건
#   조회공시요구(풍문또는보도)에대한답변(중요공시예정)      observed  42건
#   조회공시요구(현저한시황변동)에대한답변(미확정)          강등     76건  ←
# 부인(회사가 아니라고 함)은 관찰인데 미확정(확인해주지 않음)만 강등됐다.
# 같은 요구에 대한 답변인데 판정이 갈린다.
#
# 「풍문또는보도에대한해명」(353건)은 **고치지 않는다** — 거래소 요구에 따른
# 것인지 회사의 자발적 해명인지 제목만으로 알 수 없고, 판정 불가면 보수적
# 쪽에 두는 것이 이 레포의 관례다(제목 수준 vs 내용 확인 감사표 참고).
# 제목에 요구가 **적혀 있는** 149건만 되돌린다.
#
# R4가 1년 코퍼스에서 강등하는 502건은 전부 INQUIRY 단독이라, 이 예외가
# 다른 신호의 tier를 건드리지 않는다(실측).
INQUIRY_DEMAND_MARK = "조회공시요구"


def _demotion_reason(parsed: ParsedName, filing: "dict | None") -> str:
    """강등 사유를 반환. 강등 대상이 아니면 빈 문자열.

    평가 순서 R1 → R1b → R1c → R5 → R2 → R2b → R2c → R3 → R4,
    첫 매칭에서 멈춘다.
    R5를 앞에 두는 이유: 정정본은 내용과 무관하게 정정이다.
    """
    filing = filing or {}

    # R1 — 제출인이 회사가 아님. 단 거래소 시장본부 제출은 예외다
    # (EXCHANGE_FILERS 주석 참고 — 거래소 조치는 사건 자체다).
    filer = (filing.get("flr_nm") or "").strip()
    corp = (filing.get("corp_name") or "").strip()
    if (
        filer and corp
        and not is_exchange_filer(filer)
        and _fold_corp_name(filer) != _fold_corp_name(corp)
    ):
        return f"회사가 낸 공시가 아닙니다 (제출인: {filer})"

    # R1b — 지분 보유·변동 신고서. filer 유무와 무관하게 평가한다.
    #
    # 라이브 실측(2026-08-14, 삼성전자 20260410~0425): '최대주주등소유주식변동
    # 신고서'는 flr_nm이 회사 자신("삼성전자")이라 R1으로는 걸리지 않는다.
    # 세 유형 모두 '회사가 한 일'이 아니라 지분 현황의 정례 보고이므로,
    # 누가 제출했든 사건 공시가 아니다. filer 가드를 두면 flr_nm이 존재하는
    # 실환경에서 이 규칙이 통째로 죽는다.
    for title in THIRD_PARTY_TITLES:
        if parsed.body.startswith(title):
            return "지분 보유·변동 신고서입니다 (회사의 사건 공시가 아님)"

    # R1c — 집합투자증권(펀드) 서류 (위 FUND_PRODUCT_MARKS 주석 참고)
    for mark in FUND_PRODUCT_MARKS:
        if mark in parsed.compact:
            return "집합투자증권(펀드) 서류입니다 (회사의 사건 공시가 아님)"

    # R5 — 정정·후속 꼬리표
    for tag in parsed.tags:
        if _is_amendment_tag(tag):
            return f"기존 공시의 정정·후속 보고입니다 ({tag})"

    # R2 — 사후·해제 국면 (단, 국면이 상승한 경우는 제외 — 위 주석 참고)
    if parsed.tail in PHASE_TAILS and not _is_escalation(parsed):
        if parsed.tail == "결과보고서":
            return "이미 실행된 건의 결과 보고입니다"
        return f"체결이 아니라 {parsed.tail}입니다"
    # R2b — 포장 제목(기타주요경영사항 등)의 부제가 사후·해제 국면인 경우
    _wtail = _wrapper_phase_tail(parsed)
    if _wtail:
        return f"체결이 아니라 {_wtail}입니다"
    # R2c — 본체가 결과 보고인 제목 (어미가 '자율공시'라 R2에 안 걸린다)
    if any(mk in parsed.body for mk in RESULT_BODY_MARKS):
        return "이미 실행된 건의 결과 보고입니다"

    # R3 — 자회사·특수관계인 사안
    if any(s in SUBSIDIARY_SUBTITLES for s in parsed.subtitles):
        return "이 회사가 아니라 자회사 사안입니다"

    # R4 — 해명·미확정. 단 제목에 「조회공시요구」가 명시된 답변은 제외한다
    # (아래 INQUIRY_DEMAND_MARK 주석 참고).
    if (
        (parsed.tail == "해명" or "미확정" in parsed.subtitles)
        and INQUIRY_DEMAND_MARK not in parsed.compact
    ):
        return "회사가 미확정으로 답한 해명 공시입니다"

    return ""


# 라벨 보정 — 제목이 확정해주지 못하는 수식어는 라벨에서 뺀다.
# 3PCA 키워드에 '유상증자'가 통째로 있어 일반공모·소액공모까지 '제3자배정'으로
# 표기되던 것을 막는다(셀트리온 헤드라인 오탐의 직접 원인).
#
# missing_marker: 라벨 보정 여부를 가르는 유일한 기준(_adjusted_label). 바뀌면
#   Task 4의 42개 단위 테스트가 검증하는 강등 동작이 그대로 바뀐다 — 손대지 않는다.
# confirm_markers: 라벨이 보정된 뒤, 뷰어가 원문을 펼쳐 실제 배정 방식을
#   확인할 때 찾는 후보 문구 전체(missing_marker 포함). 라벨을 보정할지
#   말지에는 관여하지 않는다 — 순수하게 "원문에서 어떤 배정 방식이
#   적혔는지" 사용자에게 보여주기 위한 확인 대상 목록이다(Task 10 후속).
LABEL_OVERRIDES: dict = {
    "3PCA": {
        "missing_marker": "제3자배정",
        "label": "유상증자(배정방식 미상)",
        "confirm_markers": ("제3자배정", "주주배정", "일반공모", "주주우선공모"),
    },
}

# 사실 주석 — tier는 바꾸지 않고 사실만 덧붙인다. 신호 재배정은 하지 않는다.
# 제목이 신호 라벨과 **반대 방향**을 가리킬 때 붙는 사실 안내. 라벨·tier는
# 바꾸지 않고 한 줄을 덧붙인다(강등이 아니다 — 되사기·소각도 관찰 대상이다).
#
# 2026-08-22 실측 확장(90일·고유 공시 48,646건): 기존 마커 2종은 되사기·소각
# 제목 208건 중 **122건(59%)**만 잡았다. 나머지 86건은 「주요사항보고서(자기
# 전환사채만기전취득결정)」 61건처럼 '사채취득'이 붙어 있지 않은 표기여서,
# 라벨 그대로 "CB/BW **발행**입니다"로 표시됐다 — 회사가 사채를 되사거나
# 소각하는 건인데 발행으로 읽히면 방향이 정반대다. 마커를 넓혀 207/208(100%)로
# 올렸다(미커버 1건: 「자기신주인수권부사채재매각결정」).
#
# `EB`·`RCPS`는 아예 항목이 없어 되사기 14건·1건이 전부 발행으로 표시됐다.
#
# ⚠ RCPS의 마커에 "상환"을 넣으면 안 된다 — 상품명 자체가 '**상환**전환우선주'라
# 모든 RCPS 공시에 안내가 붙는다. 소각만 본다.
DIRECTION_NOTES: dict = {
    "CB_BW": {
        "markers": ("사채취득", "사채매도", "만기전취득", "소각", "재매각", "사채매입"),
        "note": "발행이 아니라 사채 취득·매도·소각 건입니다",
    },
    "EB": {
        "markers": ("사채취득", "사채매도", "만기전취득", "소각", "재매각", "사채매입"),
        "note": "발행이 아니라 사채 취득·매도·소각 건입니다",
    },
    "RCPS": {
        "markers": ("소각",),
        "note": "발행이 아니라 소각 건입니다",
    },
    # 자사주: 키워드 「자기주식취득」이 **부분 문자열**이라 신탁계약 체결·해지
    # 제목까지 가져온다(1년 실측 1,532건 중 526건 = 34%).
    #   체결 292 · 해지 234 — 특히 **해지는 매입 프로그램을 끝내는 것**이라
    #   "자사주 취득·처분" 해설과 방향이 어긋난다(우리금융지주 리포트에서 발견).
    # 신호는 지우지 않는다 — 신탁을 통한 우회 취득도 관찰 대상이고, 구조화
    # 경로(`fetch_treasury_decisions`)에서는 이미 `TREASURY_TRUST`로 따로 센다.
    # 제목 경로에서는 방향만 사실로 덧붙인다.
    "TREASURY": {
        "markers": ("신탁계약체결", "신탁계약해지"),
        "note": "직접 취득·처분이 아니라 신탁계약 체결·해지 건입니다",
    },
    # 방향 대립 전수(2026-08-24)에서 남은 둘. 해설이 이미 양쪽을 설명하지만,
    # 해설은 신호 유형당 한 번 나오고 **안내는 그 줄에 붙는다** — 어느 쪽인지
    # 바로 옆에서 말해 주는 편이 낫다.
    #
    #   RELATED_PARTY  으로부터 자금차입·받은담보 1,772 ↔ 에대한출자 221
    #   DEBT_RESTR     으로부터받은채무면제 10 ↔ 에대한채무면제 6
    #
    # 소수 쪽(나가는 방향)에만 붙인다 — 다수 쪽은 라벨·해설과 방향이 같다.
    "RELATED_PARTY": {
        "markers": ("에대한출자",),
        "note": "받아온 것이 아니라 회사가 특수관계인에게 출자한 건입니다",
    },
    "DEBT_RESTR": {
        "markers": ("에대한채무면제",),
        "note": "면제받은 것이 아니라 회사가 채무를 면제해 준 건입니다",
    },
    # 회생절차는 국면에 따라 뜻이 정반대다(2026-08-23 1년 실측, 발화 107건):
    #   개시 83건 — 회사 존속이 법정 절차로 넘어갔다
    #   폐지 12건 — 회생이 **실패**해 절차가 종료된다(파산으로 간다). 더 나쁘다
    #   종결  5건 — 회생이 **성공**해 정상화됐다. 위험 신호가 아니다
    # 종결만 방향이 반대인데 라벨은 셋 다 "계속기업불확실"이라 같은 무게로
    # 보인다. 신호를 지우지는 않는다 — 회생을 거친 이력 자체는 관찰 대상이라
    # 목록에서 빼면 그 사실이 사라진다. 방향만 사실로 덧붙인다.
    # ⚠ "폐지"는 넣지 않는다 — 절차가 끝난다는 점은 같지만 결과가 정반대다.
    "GOING_CONCERN": {
        "markers": ("종결",),
        "note": "회생절차가 종결된 건입니다 (폐지·개시와 방향이 다릅니다)",
    },
}


def _adjusted_label(sig: dict, parsed: ParsedName) -> str:
    """제목이 뒷받침하지 못하는 수식어를 뺀 표시 라벨."""
    label = sig.get("label", "")
    rule = LABEL_OVERRIDES.get(sig.get("key", ""))
    if rule and rule["missing_marker"] not in parsed.compact:
        return rule["label"]
    return label


def _direction_note(sig: dict, parsed: ParsedName) -> str:
    """방향이 신호 라벨과 어긋날 때의 사실 주석."""
    rule = DIRECTION_NOTES.get(sig.get("key", ""))
    if not rule:
        return ""
    if any(m in parsed.compact for m in rule["markers"]):
        return rule["note"]
    return ""


def qualify_signals(
    signals: list,
    parsed: ParsedName,
    filing: "dict | None" = None,
) -> "list[Qualified]":
    """match_signals 결과에 표시 계층(tier)과 사유를 붙인다.

    신호를 제거하지 않는다 — tier만 붙는다. 판단 불가하면 observed(기존
    동작)로 남긴다. 예외를 던지지 않는다.
    """
    reason = _demotion_reason(parsed, filing)
    tier = TIER_PROCEDURAL if reason else TIER_OBSERVED
    return [
        Qualified(
            key=sig.get("key", ""),
            label=_adjusted_label(sig, parsed),
            tier=tier,
            reason=reason,
            note=_direction_note(sig, parsed),
        )
        for sig in (signals or [])
    ]


def pick_headline(
    qualified: "list[Qualified]",
    order: "list[str] | None" = None,
) -> "Qualified | None":
    """헤드라인이 될 신호를 고른다. 없으면 None.

    후보 = observed 신호 중 AMBIGUOUS_SIGNAL_KEYS를 뺀 것.
    후보가 비면 None을 반환하고, 호출부는 중립 표기로 대체한다.

    ambiguous를 후보로 되돌리는 별도 조건은 두지 않는다 — non-ambiguous가
    하나라도 있으면 그것이 헤드라인이 되고, 없으면 중립 표기이므로
    ambiguous가 헤드라인이 되어야 할 경우가 존재하지 않는다.
    """
    candidates = [
        q for q in (qualified or [])
        if q.tier == TIER_OBSERVED and q.key not in AMBIGUOUS_SIGNAL_KEYS
    ]
    if not candidates:
        return None
    if not order:
        return candidates[0]
    rank = {k: i for i, k in enumerate(order)}
    return min(candidates, key=lambda q: rank.get(q.key, len(rank)))
