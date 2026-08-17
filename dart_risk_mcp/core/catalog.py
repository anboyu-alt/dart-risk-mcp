"""주가조작 MD 카탈로그 로더

dart-monitor의 knowledge/manipulation_catalog/*.md를 읽어
도구 응답에 관련 선례를 첨부한다.

카탈로그 파일이 없어도 빈 문자열을 반환해 graceful degradation.
"""

from __future__ import annotations

import re
from pathlib import Path

from .explain import category_prose
from .taxonomy import TAXONOMY

# v0.7.5: MD 본문이 한글화되면서(제목·정의·위험 신호) 카탈로그 발췌 시 사용자에게
# 보여줘도 좋은 맥락 정보가 됐다. 남은 '내부 지표'는 영문 메타 라벨 3종(`Severity`,
# `Base Score`, `Crisis Timeline`)뿐이어서 이 3줄만 핀포인트로 제거한다.
# 헤더(`## N.M: 제목`), `### 정의`, `### 탐지 키워드`, `### 위험 신호`는 보존한다.
_TAXONOMY_META_LINE = re.compile(
    r"^- \*\*(?:Severity|Base Score|Crisis Timeline)\*\*:.*(?:\r?\n|$)",
    re.MULTILINE,
)


def _strip_taxonomy_metadata(md: str) -> str:
    """카탈로그 MD에서 내부용 메타 라벨(Severity / Base Score / Crisis Timeline)만 제거한다.

    제거 대상: `- **Severity**: ...`, `- **Base Score**: ...`, `- **Crisis Timeline**: ...`
    세 줄만 핀포인트로 제거.
    남기는 대상: 한글화된 제목·정의·탐지 키워드·위험 신호 섹션 + 적발 사례·법조·기존 기사 인용.
    """
    return _TAXONOMY_META_LINE.sub("", md)

_CATALOG_DIR = Path(__file__).parent.parent / "knowledge" / "manipulation_catalog"

_CATEGORY_TO_FILE: dict[str, str] = {
    "Convertible Bond & Debt Manipulation": "01_cb_debt.md",
    "Capital Structure Manipulation": "02_capital_structure.md",
    "Ownership & Control": "03_ownership_control.md",
    "Governance & Disclosure": "04_governance.md",
    "Corporate Action Manipulation": "05_corporate_action.md",
    "Accounting & Financial Reporting": "06_accounting.md",
    "Market Manipulation & Trading": "07_market_manipulation.md",
    "Crisis & Distress Signals": "08_crisis_distress.md",
}


def _taxonomy_sort_key(tid: str) -> tuple:
    """taxonomy ID("5.1" 등)를 숫자 오름차순으로 정렬하는 키.

    호출부들이 taxonomy ID 목록을 set 순회(`list({...})`)로 만들어 넘기므로,
    여기서 정렬하지 않으면 발췌 섹션 순서가 PYTHONHASHSEED에 따라 실행마다
    달라진다(2026-08-03 골드 재생성 중 실측). 숫자가 아닌 키(패턴 키 등)는
    어차피 아래 루프에서 스킵되므로 맨 뒤로 보내기만 한다.
    """
    parts = tid.split(".")
    try:
        return (0, [int(p) for p in parts])
    except ValueError:
        return (1, [tid])


# 카탈로그 MD의 유형 헤더: `## {tid}: {한글 제목}`. 다음 헤더 직전까지가 그
# 유형의 블록이다(`### 정의`/`### 탐지 키워드`/`### 위험 신호`/`### 금감원·
# 금융위 적발 사례`/`### 적발 기법 종합`/`### 인용 법조`/`### 기존 현장 기사
# 인용` 하위 섹션 포함).
_ANY_HEADER_RE = re.compile(r"^## \S+: .*$", re.MULTILINE)

# 사례 개수 제한(SE-13 후속, 2026-08-16 실측): 사례 목록이 발췌 예산을 다 먹어
# 그 뒤 `### 적발 기법 종합`/`### 인용 법조`(130건 등 유형 전체를 집계한 값)가
# 통째로 잘리는 문제를 막기 위해, `### 금감원·금융위 적발 사례` 섹션 안의 사례
# 항목 개수를 `max_cases`로 제한한다. 사례는 `scripts/catalog/build_md.py`의
# `group_cases`가 이미 date 내림차순으로 정렬해 두므로 여기서는 재정렬하지 않고
# 앞에서(=최신순으로) `max_cases`개만 취한다.
_CASES_HEADER_RE = re.compile(r"^### 금감원·금융위 적발 사례.*$", re.MULTILINE)
_SUBSECTION_HEADER_RE = re.compile(r"^### .*$", re.MULTILINE)
_CASE_ITEM_RE = re.compile(
    r"^- \*\*\d{4}-\d{2}-\d{2} / .*?(?=^- \*\*\d{4}-\d{2}-\d{2} / |\Z)",
    re.MULTILINE | re.DOTALL,
)
_CASE_PLACEHOLDER_MARK = "적발 사례 없음"


def _limit_case_entries(block: str, max_cases: int) -> str:
    """taxonomy 블록의 `### 금감원·금융위 적발 사례` 섹션에서 사례 항목을
    최대 `max_cases`개로 제한하고, 잘려나간 게 있으면 잔여 건수를 사실
    한 줄로 덧붙인다.

    - 사례 섹션을 못 찾으면 블록을 그대로 반환(방어적 — 정상 카탈로그 MD라면
      항상 존재).
    - 사례가 0건(자리표시자 문장 "적발 사례 없음 — …")이면 그대로 둔다.
    - 사례 개수가 `max_cases` 이하면 자를 게 없으므로 그대로 둔다.
    - 재정렬하지 않는다 — 입력이 이미 최신순이라 앞에서부터 취하면 최신 사례가
      남는다.
    """
    header_match = _CASES_HEADER_RE.search(block)
    if not header_match:
        return block

    section_start = header_match.end()
    next_header = _SUBSECTION_HEADER_RE.search(block, section_start)
    section_end = next_header.start() if next_header else len(block)
    section = block[section_start:section_end]

    if _CASE_PLACEHOLDER_MARK in section:
        return block

    items = _CASE_ITEM_RE.findall(section)
    total = len(items)
    if total <= max_cases:
        return block

    kept = items[:max_cases]
    remaining = total - max_cases
    note = (
        f"- …외 {remaining}건 (이 유형의 적발 사례 총 {total}건). "
        f"아래 '적발 기법 종합'·'인용 법조'는 {total}건 전체를 집계한 것입니다."
    )
    body = ("".join(kept).rstrip("\n") + "\n" + note) if kept else note
    new_section = "\n\n" + body + "\n\n"

    return block[:section_start] + new_section + block[section_end:]


def _extract_taxonomy_block(content: str, tid: str) -> str | None:
    """content에서 `## {tid}: ...` 헤더로 시작하는 블록 하나만 뽑아 반환한다.

    블록 범위는 그 헤더 줄부터 다음 `## ` 헤더 직전까지(파일 끝이면 끝까지).
    헤더를 찾지 못하면 None — 호출부가 폴백(파일 앞부분 절단)을 결정한다.
    """
    header_re = re.compile(rf"^## {re.escape(tid)}: .*$", re.MULTILINE)
    match = header_re.search(content)
    if not match:
        return None
    start = match.start()
    next_match = _ANY_HEADER_RE.search(content, match.end())
    end = next_match.start() if next_match else len(content)
    block = content[start:end]
    # 다음 헤더 직전(또는 파일 끝)의 구분선("---")과 그 앞뒤 공백을 정리한다.
    block = re.sub(r"\n+-{3,}\s*\Z", "", block)
    return block.strip()


def load_catalog_excerpt(taxonomy_ids: list[str], max_chars: int = 2600, max_cases: int = 2) -> str:
    """taxonomy ID 목록에 해당하는 카탈로그 MD 발췌를 반환한다.

    중복 카테고리는 한 번만 로드. 파일 부재·읽기 오류 시 해당 카테고리 건너뜀.
    섹션 순서는 입력 순서와 무관하게 taxonomy ID 숫자 오름차순(카테고리 1~8 순)
    으로 고정된다 — 입력이 set에서 왔더라도 출력은 결정적이다.

    `max_chars`=2600 / `max_cases`=2 근거(2026-08-16 전수 실측, 317건 기준):
    사례 1건은 중앙값 506자(평균 543자, 최대 1,577자). 사례를 뺀 고정 섹션
    (정의·탐지 키워드·위험 신호·적발 기법 종합·인용 법조·기존 기사 인용) 합계는
    사례가 많은 유형에서 최대 약 1,573자. 즉 `max_cases=2`로 제한하면
    `1,573 + 2×506 ≈ 2,585자`로 고정 섹션(특히 사례 전체를 집계한 '적발 기법
    종합'·'인용 법조')이 잘리지 않고 전부 들어간다. 이전 기본값 1500자는 사례
    목록만으로 예산을 다 써 그 뒤 섹션이 통째로 잘리는 문제가 있었다(taxonomy
    4.3: 보유 사례 130건 중 발췌 노출 3건, 88% 절단).

    ⚠ **함정(SE-13 Task 1에서 실사고 발생)**: 인자는 반드시 `TAXONOMY`(taxonomy.py)의
    키인 taxonomy ID 문자열(예: `"5.1"`, `"7.1"`)이어야 한다. `CROSS_SIGNAL_PATTERNS`의
    패턴 키(예: `"zombie_ma"`, `"fake_new_biz"`)를 넘기면 아래 `TAXONOMY.get(tid)`가
    조용히 `None`을 반환해 전부 스킵되고, 예외 없이 **빈 문자열**만 돌아온다 — 호출은
    정상적으로 "성공"한 것처럼 보이기 때문에 이 실수는 로그·예외로 드러나지 않는다.
    패턴 키로 발췌를 뽑고 싶다면 `CROSS_SIGNAL_PATTERNS[key]["signal_sequence"]`
    (taxonomy ID 목록)를 먼저 꺼내 이 함수에 넘길 것. 호출부를 추가/수정할 때는
    "인자가 진짜 taxonomy ID인지" 를 확인하고, 회귀 테스트는 반드시 반환값이
    비어있지 않음을 assert할 것 — 호출 여부만 확인하는 테스트는 이 버그를 잡지 못한다
    (실제로 8번째 죽은 배선 사례가 이렇게 놓쳤다. `server.py`의 `track_fund_usage` 참고).
    """
    # {category: [tid, ...]} — taxonomy ID 숫자 오름차순으로 먼저 정렬한 뒤 묶으므로,
    # 카테고리 등장 순서(dict 삽입 순서)도 같은 오름차순을 그대로 따른다. 패턴 키 등
    # taxonomy ID가 아닌 키는 여기서 조용히 스킵된다(위 docstring 경고 참고).
    ids_by_category: dict[str, list[str]] = {}
    for tid in sorted(taxonomy_ids, key=_taxonomy_sort_key):
        signal = TAXONOMY.get(tid)
        if not signal:
            continue
        category = signal.get("category", "")
        ids_by_category.setdefault(category, []).append(tid)

    excerpts: list[str] = []

    for category, ids in ids_by_category.items():
        filename = _CATEGORY_TO_FILE.get(category)
        if not filename:
            continue

        md_path = _CATALOG_DIR / filename
        if not md_path.exists():
            continue

        try:
            content = md_path.read_text(encoding="utf-8")
        except OSError:
            continue

        content = _strip_taxonomy_metadata(content)

        # 요청받은 id들의 블록만 모은다(같은 카테고리 여러 id면 오름차순으로 이어붙임).
        # 블록별로 사례 항목 개수를 max_cases로 제한(사례가 예산을 다 먹어 뒤의
        # 집계 섹션이 통째로 잘리는 문제 방지 — 위 docstring 근거 참고).
        blocks = []
        for tid in ids:
            b = _extract_taxonomy_block(content, tid)
            if b is None:
                continue
            blocks.append(_limit_case_entries(b, max_cases))

        if blocks:
            section_body = "\n\n---\n\n".join(blocks)
        else:
            # 폴백: 요청한 id의 헤더를 하나도 못 찾음 — 빈 문자열로 퇴화시키느니
            # 기존 동작(파일 앞부분 절단)으로 최소한의 맥락이라도 남긴다.
            section_body = content.strip()

        # 연속 빈 줄 정리 (메타 블록 제거·블록 이어붙이기 후 공백이 과다하게 남는 것을 방지)
        section_body = re.sub(r"\n{3,}", "\n\n", section_body).strip() + "\n"

        truncated = section_body[:max_chars]
        if len(section_body) > max_chars:
            truncated += "\n…(이하 생략)"

        header = f"━━ 카탈로그 선례: {category} ━━"
        prose = category_prose(category)
        if prose:
            excerpts.append(f"{header}\n이 카테고리가 뭔가요 — {prose}\n\n{truncated}")
        else:
            excerpts.append(f"{header}\n{truncated}")

    return "\n\n".join(excerpts)
