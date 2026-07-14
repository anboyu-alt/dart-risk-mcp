"""공개기록 행위자 레지스트리 (Notion opt-in + 동봉 fallback, 순수 표준+requests).

레지스트리 데이터는 배포물에 싣지 않는다 — 제작자의 비공개 Notion DB가
원본이며, 접근 권한(NOTION_TOKEN + DB_KNOWN_ACTORS)을 부여받은 사용자만
opt-in으로 조회한다. 동봉 JSON은 빈 스켈레톤이다.

로드 우선순위: DART_KNOWN_ACTORS_PATH(로컬 JSON) > Notion(24h 캐시) > 동봉.
"""
import html
import json
import os
import re
import time
from importlib import resources
from pathlib import Path

import requests

_CACHE_FILE = Path.home() / ".cache" / "dart-risk-mcp" / "known_actors_notion.json"
_CACHE_TTL = 24 * 3600

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
_FOLD_STRIP_RE = re.compile(r"[\s·\-\.]+")


def fold_name(name: str) -> str:
    """표기 변형 비교용 폴딩 — 같은 주체의 다른 표기가 한 값으로 수렴한다.

    법인 접사((주)·㈜·주식회사 등) 제거, 공백·중점·하이픈 제거, 라틴 문자를
    한글 음차로 변환. 예) '(주)베이트리'·'주식회사 베이트리'·'베이트리',
    'DB금융투자 주식회사'·'디비금융투자', '정 상 용'·'정상용'이 각각 동일
    폴딩. 비교 전용 — 표시·저장 키는 normalize_name/정본을 그대로 쓴다.
    """
    s = _CORP_SUFFIX_RE.sub("", (name or ""))
    s = _FOLD_STRIP_RE.sub("", s).upper()
    return "".join(_LATIN_PHON.get(ch, ch) for ch in s)


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

def load_known_actors() -> dict:
    """레지스트리 로드. 우선순위: 환경변수 경로 > 신선한 Notion 캐시 > Notion > 동봉.

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

    data = fetch_registry_from_notion()
    if data is not None:
        try:
            _CACHE_FILE.parent.mkdir(parents=True, exist_ok=True)
            _CACHE_FILE.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        except Exception:
            pass
        return data

    return _bundled()


def lookup_actor(name: str) -> list[dict]:
    """인물명 매칭 → 기록 리스트(없으면 []).

    정확 일치 우선, 실패 시 표기 정규화(공백·대소문자) 일치로 폴백 —
    레지스트리 키가 'LIU HUAN'일 때 'Liu Huan' 조회도 매칭된다.
    """
    if not name or not name.strip():
        return []
    actors = load_known_actors().get("actors", {})
    hit = actors.get(name.strip())
    if hit is not None:
        return list(hit)
    want = normalize_name(name)
    for key, recs in actors.items():
        if normalize_name(key) == want:
            return list(recs)
    return []


def lookup_actors_by_company(company_name: str) -> list[tuple[str, dict]]:
    """회사명 역방향 조회 → [(인물명, 기록)] (없으면 []).

    각 기록의 companies(레지스트리 '관련기업' 태그)와 정규화 비교한다.
    반환은 인물명 오름차순 — 렌더 결정성(테스트 안정성) 보장.
    """
    if not company_name or not company_name.strip():
        return []
    want = normalize_name(company_name)
    actors = load_known_actors().get("actors", {})
    hits: list[tuple[str, dict]] = []
    for name in sorted(actors.keys()):
        for rec in actors[name]:
            comps = rec.get("companies") or []
            if any(normalize_name(c) == want for c in comps):
                hits.append((name, rec))
    return hits
