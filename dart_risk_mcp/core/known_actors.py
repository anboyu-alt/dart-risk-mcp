"""공개기록 행위자 레지스트리 (Notion opt-in + 동봉 fallback, 순수 표준+requests).

레지스트리 데이터는 배포물에 싣지 않는다 — 제작자의 비공개 Notion DB가
원본이며, 접근 권한(NOTION_TOKEN + DB_KNOWN_ACTORS)을 부여받은 사용자만
opt-in으로 조회한다. 동봉 JSON은 빈 스켈레톤이다.

로드 우선순위: DART_KNOWN_ACTORS_PATH(로컬 JSON) > 신선한 파일 캐시(24h) >
주입 캐시(se_server 등이 set_registry_cache로 주입, 선택) > Notion > 동봉.
"""

# PEP 604(`X | None`) 표기를 쓰므로 이 import가 없으면 Python 3.10 미만에서
# **import 시점에** TypeError로 죽는다. 애노테이션을 문자열로 지연 평가해
# 구버전에서도 모듈이 로드되게 한다(3.11+에서는 동작 차이 없음).
from __future__ import annotations
import html
import json
import logging
import os
import re
import time
from importlib import resources
from pathlib import Path

import requests

log = logging.getLogger(__name__)

_CACHE_FILE = Path.home() / ".cache" / "dart-risk-mcp" / "known_actors_notion.json"
_CACHE_TTL = 24 * 3600


# ── 선택적 레지스트리 캐시 시임 ───────────────────────────────
# dart_client.py:48~59의 _http_cache/set_http_cache/get_http_cache와 동일한
# 패턴. se_server 등 외부 소비자가 Notion 레지스트리 캐시(예: Supabase)를
# 주입하는 유일한 지점이다. 기본값 None이면 캐시 없이 지금과 완전히 동일하게
# 동작한다(MCP 서버·CLI는 이 시임을 쓰지 않는다).
#
# 주입 객체는 아래 두 메서드만 제공하면 된다(CacheBackend 전체가 아니다 —
# core가 se_server 타입을 알 필요가 없다):
#   get_json(key) -> dict | None
#   put_json(key, value, ttl_seconds) -> None
#
# 캐시 키는 이 모듈이 고정 문자열 하나로 계산한다(레지스트리는 전역 단일
# 자산이라 회사·인물별로 나눌 필요가 없다). NOTION_TOKEN 등 자격증명은
# 키에도 값에도 들어가지 않는다.
_registry_cache = None
_REGISTRY_CACHE_KEY = "known_actors_registry"


def set_registry_cache(cache) -> None:
    """레지스트리 캐시를 주입한다. None이면 캐시를 사용하지 않는다(기본값)."""
    global _registry_cache
    _registry_cache = cache


def get_registry_cache():
    """현재 주입된 레지스트리 캐시를 반환한다 (미설정 시 None)."""
    return _registry_cache

_NOTION_BASE = "https://api.notion.com/v1"
_NOTION_VERSION = "2022-06-28"

_WS_RE = re.compile(r"\s+")

# 역할·자격 수식 괄호 — DART 인수자명에 붙는 '지위·신탁업자·업무집행' 등
# 자격 표기. 한 증권사가 수십 개 펀드의 신탁업자로 등장하며 괄호 내용만
# 달라 같은 실체가 수십 노드로 쪼개진다. 괄호 안에 역할 키워드가 있을
# 때만 제거해 법인 접사 '(주)'·역할 없는 괄호는 보존한다. ASCII·전각 모두.
_ROLE_QUALIFIER_KW = (
    r"지위|신탁|수탁|업무집행|운용|관리|대리|보관|위탁|사무|관리인|청산인"
)
# 괄호 내용 조각 — 다른 괄호는 삼키지 않되(별개 괄호 2개 동시 제거 방지),
# 역할 괄호 안에 중첩되는 법인 접사 '(주)'·㈜만 예외로 허용한다. 예:
# '(업무집행조합원 : (주)코오롱인베스트먼트)'에서 내부 '(주)'에 끊겨 stray ')'가
# 남던 문제를 없앤다.
_ROLE_PAREN_INNER = r"(?:[^()（）]|\(주\)|㈜)*"
_ROLE_PAREN_RE = re.compile(
    r"[(（]" + _ROLE_PAREN_INNER + r"(?:" + _ROLE_QUALIFIER_KW + r")"
    + _ROLE_PAREN_INNER + r"[)）]")

# 대괄호 역할 수식 — 괄호판과 동일한 역할 키워드 게이트로 '[…]'·'［…］'
# 구간을 제거한다. 예: '케이비스마트스케일업펀드[업무집행조합원: …]' →
# '케이비스마트스케일업펀드'. 역할 키워드 없는 대괄호(예: 상품 분류)는 보존.
# 내부에 '(주)'·㈜ 접사가 중첩돼도 대괄호 전체를 삼킨다.
_ROLE_BRACKET_INNER = r"(?:[^\[\]［］]|\(주\)|㈜)*"
_ROLE_BRACKET_RE = re.compile(
    r"[\[［]" + _ROLE_BRACKET_INNER + r"(?:" + _ROLE_QUALIFIER_KW + r")"
    + _ROLE_BRACKET_INNER + r"[\]］]")


def _drop_unbalanced(s: str, opens: str, closes: str) -> str:
    """짝 없는 여닫이 문자 제거 — 균형 잡힌 쌍('(주)'·'[분류]' 등)은 보존.

    역할 수식 제거 후 남을 수 있는 고아 여는/닫는 괄호·대괄호를 정리한다.
    스택으로 매칭되지 않는 여는/닫는 문자만 골라 삭제해 짝이 맞는 쌍은
    그대로 둔다. opens/closes: 여는·닫는 문자 집합(예: '(（'/')）', '[［'/']］').
    """
    out: list = []
    stack: list = []
    for ch in s:
        if ch in opens:
            stack.append(len(out))
            out.append(ch)
        elif ch in closes:
            if stack:
                stack.pop()
                out.append(ch)
            # 짝 없는 닫는 문자는 버림
        else:
            out.append(ch)
    for idx in stack:      # 짝 없는 여는 문자도 버림
        out[idx] = None
    return "".join(c for c in out if c is not None)


def strip_role_qualifier(name: str) -> str:
    """이름 정제 단일 관문 — HTML 엔티티 제거 + 역할·자격 수식 괄호/대괄호 제거.

    처리 순서(엔티티를 먼저 없애 이후 수식 정규식이 깨끗한 문자열에 적용):
    1) HTML 엔티티 — 비표준 '&CR;'를 명시적으로 제거하고 표준·숫자 엔티티는
       html.unescape로 디코드. 순수 '&'(예: 'S&T중공업'·'R&D')는 ';'가 없어
       unescape가 건드리지 않으므로 보존된다.
    2) 괄호 역할 수식 — 내용에 역할 키워드(지위·신탁·수탁·업무집행 등)가 있는
       구간만 제거. 법인 접사 '(주)'·역할 키워드 없는 괄호는 보존.
    3) 대괄호 역할 수식 — 동일 게이트로 '[…]'·'［…］' 구간 제거.
    4) 짝 없는 괄호·대괄호 정리 후 공백 단일화.

    예) '신한금융투자 주식회사 (본건 펀드7의 신탁업자 지위에서)' → '신한금융투자 주식회사',
    '한국산업은행(첨단전략산업기금의 관리,운용기관)' → '한국산업은행',
    '코오롱 투자조합(업무집행조합원 : (주)코오롱인베스트먼트)' → '코오롱 투자조합',
    '미래에셋대우 주식회사&CR;' → '미래에셋대우 주식회사',
    '케이비펀드[업무집행조합원: 케이비인베스트먼트 주식회사]' → '케이비펀드',
    'S&T중공업' → 'S&T중공업'(불변), '(주)베이트리' → '(주)베이트리'(불변),
    '홍길동' → '홍길동'.
    """
    if not name:
        return ""
    s = name.replace("&CR;", " ")   # 비표준 엔티티 — unescape가 못 건드림
    s = html.unescape(s)            # 표준·숫자 엔티티 디코드 (순수 '&'는 불변)
    s = _ROLE_PAREN_RE.sub(" ", s)
    s = _ROLE_BRACKET_RE.sub(" ", s)
    if ")" in s or "）" in s or "(" in s or "（" in s:
        s = _drop_unbalanced(s, "(（", ")）")
    if "]" in s or "］" in s or "[" in s or "［" in s:
        s = _drop_unbalanced(s, "[［", "]］")
    return _WS_RE.sub(" ", s).strip()


def normalize_name(name: str) -> str:
    """인물명 표기 정규화 — 역할 괄호 제거 + 공백 단일화 + 라틴 표기 대문자 통일.

    'Liu Huan'/'LIU HUAN'처럼 표기만 다른 동일 인물, 그리고 '증권사 (…신탁업자
    지위에서)'처럼 역할 괄호만 다른 동일 실체가 sightings 병합·레지스트리
    매칭에서 분리되지 않도록 한다(한글은 대소문자가 없어 대문자화 영향 없음).
    """
    return _WS_RE.sub(" ", strip_role_qualifier(name)).upper()


# ── 행위자 분류 ──────────────────────────────────────────────────
# 작전 추적 관점의 관심도별 분류. 조합(투자조합·사모펀드류)은 CB 작전의
# 대표 비히클이라 개인과 동급으로 추적하고, 일반 법인도 추적한다.
# 제도권 기관(증권사·은행·연기금 등)은 정상적으로 수십 개사 딜에 등장해
# '반복 등장' 신호가 무의미하므로 수집에서 제외한다.

# 문장 조각(추출 오류) 판정 — 원문 파싱이 이름 대신 보일러플레이트를
# 긁어온 경우. 공백 분리 토큰 중 순수 문법 조사·연결어가 있으면 조각.
# (실명·조합·법인명은 이런 표준 조사를 토큰으로 갖지 않는다.)
_FRAGMENT_TOKENS = {
    "으로서", "으로", "로서", "및", "등의", "등을", "에", "해당하는",
    "이며", "이고", "하며", "되어", "하여", "위해", "위한", "관련",
    "통해", "따라", "의한", "대한",
}


def _is_name_fragment(name: str) -> bool:
    """추출 오류로 인한 문장 조각 여부. 2토큰 이상 + 문법 조사 포함."""
    toks = name.split()
    return len(toks) >= 2 and any(t in _FRAGMENT_TOKENS for t in toks)


# 표(表) 파싱 아티팩트 — 인수자 명단 표의 헤더·합계행·조각이 이름으로 잘못
# 추출된 경우. 공백 제거·대문자 정규화 후 '정확히' 이 목록과 같으면 노이즈.
# (실명·조합·법인명이 이 값과 정확히 일치할 일은 없다.)
_NOISE_NAMES = {
    "합계", "소계", "총계", "중계", "계", "기타", "합", "소 계", "총 계",
    "비고", "구분", "순번", "번호", "성명", "주주명", "주주", "이름", "명", "주",
    "으로", "으로서", "및", "등", "등의", "합 계",
}
# 주의: 실명과 정확히 겹칠 수 있는 값은 넣지 않는다. 예) '이상'(李箱)은 실명
# 이므로 제외 — 표의 '5% 이상' 같은 조각이라도 실명 오탐·오삭제 위험이 크다.
_NOISE_NOSPACE = {_WS_RE.sub("", n).upper() for n in _NOISE_NAMES}


def _is_noise_name(name: str) -> bool:
    """표 헤더·합계행 등 파싱 아티팩트 여부(공백 제거 후 정확 일치)."""
    return _WS_RE.sub("", (name or "").strip()).upper() in _NOISE_NOSPACE


def canonical_name(name: str, aliases: dict | None = None) -> str:
    """정규화 + 별칭 정본화. 같은 인물의 여러 표기를 한 정본 키로 합친다.

    aliases: {정규화된 별칭: 정규화된 정본}. 한 인물이 공시에 여러 표기(가명·
    로마자·오기 등)로 등장할 때 한 행위자로 합쳐 추적하기 위함. 실제 별칭 매핑은
    투자 대상 식별 정보이므로 비공개 sightings 저장소의 aliases 맵에만 둔다.
    """
    n = normalize_name(name)
    return aliases.get(n, n) if aliases else n


# 라틴 문자 → 한글 음차 (금융권 관행 표기: DB↔디비, HLB↔에이치엘비 등)
_LATIN_PHON = {
    "A": "에이", "B": "비", "C": "씨", "D": "디", "E": "이", "F": "에프",
    "G": "지", "H": "에이치", "I": "아이", "J": "제이", "K": "케이", "L": "엘",
    "M": "엠", "N": "엔", "O": "오", "P": "피", "Q": "큐", "R": "알",
    "S": "에스", "T": "티", "U": "유", "V": "브이", "W": "더블유",
    "X": "엑스", "Y": "와이", "Z": "지",
}
_CORP_SUFFIX_RE = re.compile(r"(주식회사|유한회사|유한책임회사|\(주\)|㈜)")
# 영문 법인 접사 — 이름 '꼬리'의 토큰만 제거('CBI USA, INC.' ↔ 'CBI USA').
# 앞에 구분자([\s,.]+)를 요구해 이름 중간·선두의 CO 등은 보존한다.
_EN_LEGAL_SUFFIX_RE = re.compile(
    r"(?:[\s,\.，．]+(?:CO|LTD|INC|CORP|CORPORATION|LLC|LLP|LIMITED)\.?)+[\s,\.，．]*$",
    re.IGNORECASE)
_FOLD_STRIP_RE = re.compile(r"[\s·\-\.,，．]+")


def fold_name(name: str) -> str:
    """표기 변형 비교용 폴딩 — 같은 주체의 다른 표기가 한 값으로 수렴한다.

    법인 접사((주)·㈜·주식회사·꼬리의 Co/Ltd/Inc 등) 제거, 공백·중점·하이픈·
    쉼표·마침표 제거, 라틴 문자를 한글 음차로 변환. 예) '(주)베이트리'·
    '주식회사 베이트리'·'베이트리', 'DB금융투자 주식회사'·'디비금융투자',
    'LIM, CHARLES'·'LIM CHARLES', 'CBI USA, INC.'·'CBI USA'가 각각 동일
    폴딩. 한글 '컴퍼니'는 실명 일부('컴퍼니케이파트너스')일 수 있어 접사로
    취급하지 않는다. 비교 전용 — 표시·저장 키는 normalize_name/정본 그대로.
    """
    s = _CORP_SUFFIX_RE.sub("", (name or ""))
    s = _EN_LEGAL_SUFFIX_RE.sub("", s.strip())
    s = _FOLD_STRIP_RE.sub("", s).upper()
    return "".join(_LATIN_PHON.get(ch, ch) for ch in s)


# 한글(로마자) 병기 — '정소영(DING SHAO YING)'처럼 한 공시가 두 표기를 함께
# 쓴 경우. 괄호 안은 라틴 문자로 시작해야 하므로 한글 괄호에는 매칭 안 됨.
_BILINGUAL_RE = re.compile(
    r"^(?P<base>[가-힣][가-힣\s\d]*?)\s*[(（](?P<latin>[A-Za-z][A-Za-z\s\.,'\-]*)[)）]$")
# 구명칭 병기 — '(구. 옛이름)' / '[舊 (주)옛이름]'. 개명 전 표기와 같은 실체.
_FORMER_PAREN_RE = re.compile(r"[(（]\s*(?:구|舊)\s*[\.．]?\s*(?P<old>[^()（）]+?)\s*[)）]")
_FORMER_BRACKET_RE = re.compile(r"[\[［]\s*(?:구|舊)\s*[\.．]?\s*(?P<old>[^\[\]［］]+?)\s*[\]］]")


def fold_variants(name: str) -> list:
    """fold_name + 병기 표기가 만드는 대체 폴드 목록 (첫 원소 = 기본 폴드).

    한글(로마자) 병기·구명칭 병기는 한 문자열이 두 실체 표기를 담고 있어
    글자 단위 폴딩만으로는 단독 표기('DING SHAO YING'·'센시오2호투자조합')와
    수렴하지 않는다. 각 구성 표기의 폴드를 변형으로 추가해 sightings 병합이
    같은 실체로 접게 한다. 1글자 구성 표기('김(K)')는 오병합 위험이 커 제외.
    """
    primary = fold_name(name)
    out = [primary]
    parts = []
    m = _BILINGUAL_RE.match((name or "").strip())
    if m:
        parts += [m.group("base"), m.group("latin")]
    for rx in (_FORMER_PAREN_RE, _FORMER_BRACKET_RE):
        fm = rx.search(name or "")
        if fm:
            parts.append(fm.group("old"))       # 옛 이름 단독 표기
            parts.append(rx.sub(" ", name))     # 병기 제거한 현재명 단독 표기
    for p in parts:
        f = fold_name(p)
        if len(p.strip()) >= 2 and len(f) >= 2 and f not in out:
            out.append(f)
    return out


# 조합·사모 비히클 (기관 패턴보다 먼저 판정 — '일반사모투자신탁'류 포섭)
_FUND_PAT = re.compile(r"조합|합자회사|사모투자|사모펀드|사모 펀드")

# 제도권 기관 — 반복 등장이 정상인 주체
_INSTITUTION_PAT = re.compile(
    r"은행|증권|금융투자|보험|공제회|연기금|연금공단|공단|공사|금고|저축은행|종합금융|종금|"
    r"캐피탈|카드|자산운용|투자신탁|한국거래소|예탁결제원|"
    # 증권사이나 사명에 '증권/금융투자'가 없어 위 패턴에 안 걸리는 실체를
    # 리터럴로 명시(관측된 오기 '미래애셋대우' 포함). 지배적 오탐 허브였음.
    # ⚠ 'S&T중공업 대우'류·'대우건설'·'박대우(인물)' 오제외 방지 위해 접두
    # 'bare 대우'는 넣지 않는다 — 반드시 리터럴 두 개만.
    r"미래에셋대우|미래애셋대우|"
    r"bank\b|securities|insurance",
    re.IGNORECASE,
)

# 법인·기관성 패턴 (개인이 아님을 판정)
_ORG_PAT = re.compile(
    r"조합|투자|신탁|펀드|주식회사|\(주\)|㈜|유한|법인|파트너스|캐피탈|자산운용|"
    r"벤처|컴퍼니|코프|홀딩스|그룹|은행|공사|기금|시스템|"
    r"\b(?:co|ltd|llc|inc|corp)\b\.?|"
    r"limited|holdings|investment|bank|fund|trust|partners|capital|company",
    re.IGNORECASE,
)

# 개인명치고 지나치게 많은 공백 분리 토큰 — 프로그램/기관명 설명구 필터
_MAX_PERSON_TOKENS = 4


def classify_actor(name: str) -> str:
    """인수자명 분류: "person" | "fund" | "corp" | "institution" | "noise".

    - person: 개인명 (추적 대상)
    - fund: 조합·사모 비히클 (추적 대상 — CB 작전 대표 창구)
    - corp: 일반·외국 법인 (추적 대상)
    - institution: 제도권 기관 (수집 제외 — 반복 등장이 정상)
    - noise: 빈 문자열 등
    """
    if not name or not name.strip():
        return "noise"
    name = strip_role_qualifier(name)   # 기저 실체로 분류 (역할 괄호 제거)
    if not name:
        return "noise"
    if _is_noise_name(name):
        return "noise"  # 표 헤더·합계행 등 (예: "합계", "기타", "으로") 차단
    if _is_name_fragment(name):
        return "noise"  # 원문 파싱 조각 (예: "으로서 결성 및") 차단
    if _FUND_PAT.search(name):
        return "fund"
    if _INSTITUTION_PAT.search(name):
        return "institution"
    if re.search(r"\d", name) or _ORG_PAT.search(name) \
            or len(re.split(r"\s+", name.strip())) > _MAX_PERSON_TOKENS:
        return "corp"
    return "person"


# classify_actor kind → 레지스트리 구분(select) 표기
KIND_LABELS = {"person": "개인", "fund": "조합", "corp": "법인"}


# ── 섹터 구분 (증권·은행 제외 / 기타 기관 태깅) ──────────────────────
# 증권사·은행은 신탁·커스터디 역할로 대부분의 딜에 정상 등장해 신호가
# 무의미하므로 수집 자체를 하지 않는다. 반면 자산운용·보험·연기금·캐피탈
# 등 기타 제도권 기관과 자문·PE·VC 성 법인은 수집하되 그래프에서 기본
# 숨김(토글 노출) 처리한다. 이를 위한 섹터 판별 헬퍼.
_SECURITIES_PAT = re.compile(r"증권|투자증권|금융투자|미래에셋대우|미래애셋대우")
_BANK_PAT = re.compile(r"은행")
# 자문·PE·VC 성 법인(현재 classify_actor=="corp") — 사명 키워드로 식별.
_ADVISORY_PAT = re.compile(
    r"투자자문|자문|파트너스|인베스트먼트|인베스트|벤처투자|프라이빗에쿼티|에쿼티")


def sector_of(name: str) -> str | None:
    """행위자 섹터 구분: "증권" | "은행" | "기타기관" | None.

    strip_role_qualifier로 역할 괄호를 벗긴 기저 실체명 기준으로 판정한다.
    - 증권: 증권·투자증권·금융투자·미래에셋대우(관측 오기 포함)
    - 은행: 은행
    - 기타기관: 위 둘을 제외한 제도권 기관(classify_actor=="institution",
      예 자산운용·보험·연기금·캐피탈·종금·공공기관) + 자문·PE·VC 성 법인
      (투자자문·파트너스·인베스트먼트·벤처투자·에쿼티 등, classify=="corp")
    - None: 개인·조합·일반법인 등 정상 추적 대상(항상 표시)

    ※ 조합(fund)은 CB 작전의 핵심 추적 대상이라 사명에 '파트너스' 등이
      섞여도 기타기관으로 강등하지 않는다(항상 표시 원칙 보존).
    """
    base = strip_role_qualifier(name)
    if not base:
        return None
    if _SECURITIES_PAT.search(base):
        return "증권"
    if _BANK_PAT.search(base):
        return "은행"
    k = classify_actor(base)
    if k == "institution":
        return "기타기관"
    # 자문·PE·VC 사명 키워드는 개인·조합과 겹치지 않는 불명확 없는 법인 표지라
    # kind와 무관하게 기타기관으로 본다. 단, 조합(fund)은 CB 작전의 핵심
    # 추적 대상이므로 강등하지 않는다(항상 표시 원칙).
    if k != "fund" and _ADVISORY_PAT.search(base):
        return "기타기관"
    return None


def should_store(name: str) -> bool:
    """수집(저장) 대상 여부 — 증권·은행·노이즈만 버리고 기타 기관은 보존.

    - person·fund·corp: 항상 저장(추적 대상)
    - institution: 기타기관(증권·은행 제외한 제도권 기관)만 저장, 증권·은행 제외
    - noise: 저장 안 함
    """
    k = classify_actor(name)
    if k in ("person", "fund", "corp"):
        return True
    if k == "institution":
        return sector_of(name) == "기타기관"
    return False


def _valid(data) -> bool:
    return isinstance(data, dict) and isinstance(data.get("actors"), dict)


def _bundled() -> dict:
    try:
        text = (resources.files("dart_risk_mcp") / "data" / "known_actors.json").read_text(
            encoding="utf-8")
        data = json.loads(text)
        return data if _valid(data) else {"version": 1, "actors": {}}
    except Exception:
        return {"version": 1, "actors": {}}


# ── Notion 레지스트리 I/O ────────────────────────────────────────

def _notion_env() -> tuple[str, str]:
    tok = os.environ.get("NOTION_TOKEN", "")
    db = os.environ.get("DB_KNOWN_ACTORS", "")
    return (tok, db) if tok and db else ("", "")


def _notion_headers(token: str) -> dict:
    return {
        "Authorization": f"Bearer {token}",
        "Notion-Version": _NOTION_VERSION,
        "Content-Type": "application/json",
    }


def _plain(prop_items) -> str:
    """Notion rich_text/title 배열 → 평문."""
    return "".join(t.get("plain_text", "") for t in (prop_items or []))


_DART_VIEWER = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo="


def disclosure_url(rcept_no: str) -> str:
    """접수번호 → DART 공시 뷰어 URL. 빈 값이면 빈 문자열."""
    return f"{_DART_VIEWER}{rcept_no}" if rcept_no else ""


def _evidence_rich_text(text: str, company_url: dict | None) -> list:
    """evidence 평문에서 회사명 구간을 해당 공시 링크로 감싼 Notion rich_text.

    company_url: {회사명: 공시URL}. 없으면 전체 평문 단일 span.
    회사명이 서로 부분 문자열일 수 있어 긴 이름부터 매칭(비겹침).
    """
    text = (text or "")[:1900]
    urls = {k: v for k, v in (company_url or {}).items() if k and v}
    if not urls:
        return [{"type": "text", "text": {"content": text}}]
    names = sorted(urls, key=len, reverse=True)
    pat = re.compile("|".join(re.escape(n) for n in names))
    out, pos = [], 0
    for m in pat.finditer(text):
        if m.start() > pos:
            out.append({"type": "text", "text": {"content": text[pos:m.start()]}})
        nm = m.group(0)
        out.append({"type": "text",
                    "text": {"content": nm, "link": {"url": urls[nm]}}})
        pos = m.end()
    if pos < len(text):
        out.append({"type": "text", "text": {"content": text[pos:]}})
    return out or [{"type": "text", "text": {"content": text}}]


def _page_to_record(page: dict) -> tuple[str, dict]:
    """Notion 페이지 → (인물명, 기록 dict). JSON 레지스트리 스키마와 동일 형태."""
    p = page.get("properties", {})
    name = _plain(p.get("인물명", {}).get("title"))
    rec = {
        "source": _plain(p.get("source", {}).get("rich_text")),
        "status": (p.get("status", {}).get("select") or {}).get("name", ""),
        "evidence": _plain(p.get("evidence", {}).get("rich_text")),
        "url": p.get("url", {}).get("url") or "",
        "date": _plain(p.get("date", {}).get("rich_text")),
        "tags": [t.get("name", "") for t in p.get("tags", {}).get("multi_select", [])],
        "companies": [t.get("name", "") for t in p.get("관련기업", {}).get("multi_select", [])],
        "kind": (p.get("구분", {}).get("select") or {}).get("name", ""),
    }
    rcept = _plain(p.get("rcept_no", {}).get("rich_text"))
    if rcept:
        rec["rcept_no"] = rcept
    return name, rec


def fetch_registry_from_notion(token: str = "", db_id: str = "") -> dict | None:
    """Notion 레지스트리 DB 전체를 {version, actors} 형태로 조회.

    env(NOTION_TOKEN/DB_KNOWN_ACTORS) 미설정 또는 조회 실패 시 None —
    호출측이 동봉 데이터로 graceful fallback 한다.
    """
    if not (token and db_id):
        token, db_id = _notion_env()
    if not (token and db_id):
        return None
    actors: dict = {}
    payload: dict = {"page_size": 100}
    try:
        while True:
            resp = requests.post(
                f"{_NOTION_BASE}/databases/{db_id}/query",
                headers=_notion_headers(token), json=payload, timeout=15)
            if resp.status_code != 200:
                return None
            data = resp.json()
            for page in data.get("results", []):
                name, rec = _page_to_record(page)
                if name:
                    actors.setdefault(name, []).append(rec)
            if not data.get("has_more"):
                break
            payload["start_cursor"] = data.get("next_cursor")
    except Exception:
        return None
    return {"version": 1, "actors": actors}


def add_registry_record(name: str, record: dict, token: str = "", db_id: str = "") -> bool:
    """레지스트리 DB에 기록 행 추가. env 미설정/실패 시 False (graceful skip).

    record에 "companies"(list[str])가 있으면 관련기업 multi_select로 태깅해
    Notion에서 회사별로 필터링·추적 가능하게 한다. 이름 100자·목록 20개 상한
    (Notion multi_select 옵션 제약).
    """
    if not (token and db_id):
        token, db_id = _notion_env()
    if not (token and db_id):
        return False
    props: dict = {
        "인물명": {"title": [{"text": {"content": name}}]},
        "status": {"select": {"name": record.get("status") or "auto_matched"}},
        "source": {"rich_text": [{"text": {"content": record.get("source", "")}}]},
        "evidence": {"rich_text": _evidence_rich_text(
            record.get("evidence"), record.get("company_links"))},
        "date": {"rich_text": [{"text": {"content": record.get("date", "")}}]},
        "tags": {"multi_select": [{"name": t} for t in record.get("tags", []) if t]},
    }
    companies = [c[:100] for c in (record.get("companies") or []) if c][:20]
    if companies:
        props["관련기업"] = {"multi_select": [{"name": c} for c in companies]}
    if record.get("kind"):
        props["구분"] = {"select": {"name": record["kind"]}}
    if record.get("url"):
        props["url"] = {"url": record["url"]}
    if record.get("rcept_no"):
        props["rcept_no"] = {"rich_text": [{"text": {"content": record["rcept_no"]}}]}
    try:
        resp = requests.post(
            f"{_NOTION_BASE}/pages", headers=_notion_headers(token),
            json={"parent": {"database_id": db_id}, "properties": props}, timeout=15)
        return resp.status_code == 200
    except Exception:
        return False


def ensure_registry_schema(token: str = "", db_id: str = "") -> bool:
    """레지스트리 DB에 신규 속성(관련기업·구분)이 없으면 추가. 있으면 no-op.

    PATCH는 속성을 병합(추가)하는 방식이라 기존 속성·데이터를 건드리지 않는다.
    스키마가 진화할 때마다 이 함수에 속성을 추가하고 셋업 워크플로우를 재실행.
    """
    if not (token and db_id):
        token, db_id = _notion_env()
    if not (token and db_id):
        return False
    wanted = {
        "관련기업": {"multi_select": {}},
        "구분": {"select": {"options": [
            {"name": "개인", "color": "default"},
            {"name": "조합", "color": "orange"},
            {"name": "법인", "color": "purple"},
        ]}},
    }
    try:
        # 이미 존재하는 속성은 절대 재PATCH하지 않는다 — 동일 속성 재PATCH가
        # 전체 행의 값을 소거하는 사고가 있었음 (2026-07-04). 누락분만 추가.
        cur = requests.get(
            f"{_NOTION_BASE}/databases/{db_id}",
            headers=_notion_headers(token), timeout=15)
        if cur.status_code != 200:
            return False
        existing = set((cur.json().get("properties") or {}).keys())
        missing = {k: v for k, v in wanted.items() if k not in existing}
        if not missing:
            return True  # 전부 존재 — no-op
        resp = requests.patch(
            f"{_NOTION_BASE}/databases/{db_id}", headers=_notion_headers(token),
            json={"properties": missing}, timeout=15)
        return resp.status_code == 200
    except Exception:
        return False


# ── 로더 ─────────────────────────────────────────────────────────

# 근거 강도 3단계. 이 밖의 값(빈 문자열·None·오타 등)은 전부 가장 약한
# auto_matched로 강등한다. Notion 파서가 status select 비어있으면 키는 있고
# 값이 ""인 레코드를 만드는데, `== "auto_matched"`로 판정하면 그 빈 문자열이
# 화이트리스트 밖인 "사람이 넣은 것"으로 잘못 분류돼 기관 필터·렌더 양쪽에서
# 미검증 실명이 검증된 것처럼 새어나간다. 모르면 기계 등재로 보는 쪽(보수적)
# 으로 강등해야 안전하다.
_VALID_ACTOR_STATUSES = frozenset({"verified", "maintainer_seed", "auto_matched"})


def actor_status(rec: dict) -> str:
    """기록에서 status를 뽑아 화이트리스트로 검증(비문자열·미지값은 auto_matched).

    **이 판정의 유일한 소스** (SE-5b 리뷰). 전에는 이 로직이 세 곳에
    독립 구현돼 있었다 — `_filter_institutions`가 쓰던 이 함수의 옛 사설
    버전(`_record_status`), `se_server/api/handlers.py::_actor_status`,
    그리고 `server.py`의 `st == "auto_matched"` 인라인 동등비교 3곳
    (`_registry_company_section`·`lookup_known_actor`·`find_actor_overlap`).
    인라인 동등비교는 이 함수가 정확히 막으려는 결함 그 자체다 — Notion
    행에 빈 status가 오면 `== "auto_matched"`는 False가 되어 "동명이인
    미확인" 경고 없이 미검증 실명이 검증된 것처럼 렌더된다. 세 구현을
    이 함수 하나로 합치고 나머지는 여기서 import해 쓴다
    (`se_server/api/handlers.py`, `dart_risk_mcp/server.py`).
    """
    value = (rec or {}).get("status")
    return value if isinstance(value, str) and value in _VALID_ACTOR_STATUSES \
        else "auto_matched"


def _filter_institutions(data: dict) -> dict:
    """읽기 단계 기관 필터 — should_store가 거부하고 전 기록이 기계 등재인
    인물만 로드 결과에서 제외한다.

    실측(2026-07-29): should_store를 레지스트리 1,270명에 재적용하면 12명이
    거부되는데, 그 12명(전부 증권사/신탁업자 표기, 기록 95건 전부
    auto_matched)이 "등장 회사 수" 상위를 독점해 진짜 추적 대상(시너지파트너스
    등)을 가린다. should_store 자체는 정상 동작하는데 읽기 경로가 안 쓰고
    있었던 것이 결함이었다 — 여기서만 적용하고 should_store/classify_actor는
    재구현하지 않는다.

    verified·maintainer_seed 기록이 하나라도 있으면 제작자가 직접 판단해
    등재한 것이므로 무조건 남긴다(실측 0건이지만 미래 등재를 위한 방어).
    Notion·캐시·동봉 데이터 자체는 건드리지 않고 이 함수가 반환하는 사본에만
    적용한다.

    손글씨 `DART_KNOWN_ACTORS_PATH` JSON이 `{"actors": {"이름": null}}`처럼
    기록 목록 자리에 리스트가 아닌 값을 담고 있어도 죽지 않는다 — 레지스트리
    로딩은 예외를 전파하지 않는다는 이 저장소의 원칙(파일이 없을 때와
    동일하게 조용히 저하)에 따라, 리스트가 아닌 값은 빈 목록으로 취급한다.
    `_valid`는 최상위 {version, actors} 형태만 검사하고 각 인물 항목의
    형태까지는 보지 않으므로, 여기서 한 번 정규화해 두면 이 함수를 거치는
    `lookup_actor`·`lookup_actors_by_company`도 같은 malformed 값을 다시
    만나 죽지 않는다(정규화의 단일 관문).
    """
    if not _valid(data):
        return data
    actors = data.get("actors", {})
    filtered = {
        name: (recs if isinstance(recs, list) else [])
        for name, recs in actors.items()
        if should_store(name)
        or any(actor_status(r) != "auto_matched"
               for r in (recs if isinstance(recs, list) else []))
    }
    return {**data, "actors": filtered}


def _load_raw() -> dict:
    """레지스트리 원본 로드(필터 적용 전). 우선순위: 환경변수 경로 > 신선한
    Notion 캐시 > Notion > 동봉.

    Notion 실패 시 동봉 데이터로 graceful fallback(예외 비전파).
    """
    override = os.environ.get("DART_KNOWN_ACTORS_PATH")
    if override:
        try:
            with open(override, encoding="utf-8") as f:
                data = json.load(f)
            return data if _valid(data) else {"version": 1, "actors": {}}
        except Exception:
            return {"version": 1, "actors": {}}

    # Notion 미설정이면 캐시·조회 없이 동봉 데이터로 (opt-in)
    if not all(_notion_env()):
        return _bundled()

    # 24h 신선 캐시
    try:
        if _CACHE_FILE.exists() and (time.time() - _CACHE_FILE.stat().st_mtime) < _CACHE_TTL:
            data = json.loads(_CACHE_FILE.read_text(encoding="utf-8"))
            if _valid(data):
                return data
    except Exception:
        pass

    # 주입 캐시(예: se_server의 Supabase) — 파일시스템이 휘발성인 서버리스
    # 환경(Vercel)에서 위 파일 캐시가 매 콜드 인보케이션마다 미스가 나
    # Notion 15회 왕복(15초)을 매번 무는 문제의 시임. 저장은 이 함수 아래
    # (필터 적용 전 원본) — 이유는 모듈 상단 주석·테스트 참고.
    # get_json 실패(예외·깨진 형태)는 미스로 간주하고 Notion으로 진행한다.
    if _registry_cache is not None:
        try:
            cached = _registry_cache.get_json(_REGISTRY_CACHE_KEY)
            if _valid(cached):
                return cached
        except Exception:
            log.warning("레지스트리 캐시 조회 실패, Notion으로 폴백", exc_info=True)

    data = fetch_registry_from_notion()
    if data is not None:
        try:
            _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        if _registry_cache is not None:
            try:
                _registry_cache.put_json(_REGISTRY_CACHE_KEY, data, _CACHE_TTL)
            except Exception:
                log.warning("레지스트리 캐시 저장 실패, 로드는 정상 반환", exc_info=True)
        return data

    return _bundled()


def load_known_actors() -> dict:
    """레지스트리 로드(`_load_raw`) + 읽기 단계 기관 필터(`_filter_institutions`).

    Notion·캐시·동봉 데이터의 내용은 다시 쓰지 않는다 — 필터는 여기서 반환하는
    사본에만 적용된다. `lookup_actor`·`lookup_actors_by_company`가 모두 이
    함수를 거치므로 두 경로 모두 자동으로 필터가 적용된다.
    """
    return _filter_institutions(_load_raw())


def _record_fingerprint(rec: dict) -> str:
    """중복 판정용 지문 — 레코드의 필드 전체(값 포함)가 같아야 중복으로 본다.

    rcept_no만 다르고 evidence 문구가 같은 두 기록은 서로 다른 공시에서 나온
    별개 근거이므로 중복이 아니다. 반대로 파싱 원문에 `&CR;`가 섞여 같은
    실체가 두 키('삼성전자 주식회사' / '삼성전자 &CR;주식회사')로 저장된
    경우, 두 키의 기록을 합칠 때 완전히 동일한 필드 조합(예: 같은 rcept_no
    +evidence)만 한 번으로 접는다. dict는 unhashable하므로 정렬된 JSON
    문자열을 지문으로 쓴다.
    """
    return json.dumps(rec, ensure_ascii=False, sort_keys=True)


def lookup_actor(name: str) -> list[dict]:
    """인물명 매칭 → 기록 리스트(없으면 []).

    표기 정규화(공백·대소문자·역할 괄호·HTML 엔티티) 일치 + 폴딩 변형
    (fold_variants — 법인 접사·구두점 제거, 라틴 음차) 일치를 **모두** 합쳐
    반환한다. 레지스트리 키가 'LIU HUAN'일 때 'Liu Huan' 조회, '주식회사
    액션' 등재일 때 '(주)액션' 조회, '정소영 (DING SHAO YING)' 등재일 때
    'DING SHAO YING' 조회가 각각 매칭된다.

    매칭은 fold_variants 교집합 **하나**로 계산한다(SE-5b Part A, 최종
    리뷰 Finding 5로 단순화). 예전에는 "정규화 일치 키(norm_keys)"와
    "폴딩 일치 키(fold_keys)"를 따로 구해 합집합으로 냈는데, 그건 죽은
    이중 계산이었다 — `normalize_name(key) == want`이면 `fold_variants`는
    같은 입력에 같은 값을 내는 순수 함수이므로
    `fold_variants(normalize_name(key)) == fold_variants(want)`가 되고,
    자기 자신과의 교집합은 `fold_variants`가 항상 최소 1개 원소(기본 폴드)를
    반환하므로 절대 비지 않는다. 즉 정규화 일치는 반드시 폴딩 일치를
    함축한다(norm_keys ⊆ fold_keys, 늘 성립) — 그래서 폴딩 교집합 하나만
    구하면 두 티어를 합친 것과 정확히 같은 결과가 나온다.

    이 단일 폴딩 비교로 실측 사고(2026-07-29)의 두 사례를 모두 잡는다:
    '삼성전자 주식회사'/'삼성전자 &CR;주식회사'(엔티티만 다름 — 정규화
    단계에서 이미 같은 값)와 '(주)베이트리'/'주식회사 베이트리'(법인 접사
    표기만 다름 — 정규화 단계에서는 다른 값이지만 폴딩에서 수렴)가 각각
    같은 실체로 병합된다. 반대로 완전히 다른 실체를 잘못 합치는 위험은
    fold_name이 법인 접사·공백·구두점 제거와 라틴 음차만 하고 그 외
    글자는 그대로 두는 '문자열 전체 일치' 비교라 낮다 — 접사를 떼도 나머지
    글자가 다른 두 실체는 교집합이 생기지 않는다(예: '베이트리' ≠
    '베이트리무역', 테스트로 고정).

    매칭 키가 여럿이면(예: 파싱 오류로 같은 실체가 '삼성전자 주식회사'·
    '삼성전자 &CR;주식회사' 두 키로 저장된 경우) 첫 매칭에서 끊지 않고
    **모든 키의 기록을 합쳐** 반환한다 — 조회 표기에 따라 답이 달라지는
    것을 막는다. 정렬 후 순회해 반환 순서를 결정적으로 유지한다
    (lookup_actors_by_company가 같은 이유로 정렬하는 것과 동일한 이유).
    """
    if not name or not name.strip():
        return []
    actors = load_known_actors().get("actors", {})

    wf = set(fold_variants(normalize_name(name)))
    all_keys = {key for key in actors if wf & set(fold_variants(normalize_name(key)))}

    if not all_keys:
        return []

    seen: set = set()
    out: list[dict] = []
    for key in sorted(all_keys):
        for rec in actors[key]:
            fp = _record_fingerprint(rec)
            if fp not in seen:
                seen.add(fp)
                out.append(rec)
    return out


def lookup_actors_by_company(company_name: str) -> list[tuple[str, dict]]:
    """회사명 역방향 조회 → [(인물명, 기록)] (없으면 []).

    각 기록의 companies(레지스트리 '관련기업' 태그)와 정규화 + 폴딩 변형
    비교한다 — 태그가 '(주)베이트리'일 때 '주식회사 베이트리' 조회도 매칭.
    반환은 인물명 오름차순 — 렌더 결정성(테스트 안정성) 보장.
    """
    if not company_name or not company_name.strip():
        return []
    want = normalize_name(company_name)
    wf = set(fold_variants(want))
    actors = load_known_actors().get("actors", {})
    hits: list[tuple[str, dict]] = []
    for name in sorted(actors.keys()):
        for rec in actors[name]:
            comps = rec.get("companies") or []
            if any(normalize_name(c) == want
                   or wf & set(fold_variants(normalize_name(c)))
                   for c in comps):
                hits.append((name, rec))
    return hits
