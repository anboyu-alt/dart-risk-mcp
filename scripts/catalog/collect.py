"""Phase A — 금감원 보도자료 게시판 목록 수집 + 규칙 필터 → JSONL.

오픈API 대신 게시판 웹페이지를 쓴다. API는 일일 30회 한도가 실증됐고
(resultCode 033), 2010~2026 백필은 약 200청크라 7~8일이 걸린다. 게시판은
키도 한도도 없고 목록에 제목·담당부서·등록일·nttId가 모두 들어 있다.

필터 설계(600건 표본 실측, 2026-08-16): 금감원 보도자료는 은행·보험·서민금융·
교육이 대부분이라 전부 열면 낭비다. 담당부서로 1차, 제목 키워드로 2차,
일반안내 패턴으로 3차를 거르면 24.5%로 좁혀진다. 남은 판단(정기 통계 vs 적발
조치)은 규칙으로 자르면 핵심 건까지 놓치므로 Phase C의 LLM 스크리닝에 맡긴다.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date
from pathlib import Path

import requests

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts._console import use_utf8_stdout  # noqa: E402
from scripts.catalog.extract import decode_page  # noqa: E402

LIST_URL = "https://www.fss.or.kr/fss/bbs/B0000188/list.do?menuNo=200218"
VIEW_URL = "https://www.fss.or.kr/fss/bbs/B0000188/view.do?nttId={id}&menuNo=200218"
OUT_PATH = _REPO_ROOT / "data" / "catalog" / "catalog_sources.jsonl"
STATE_PATH = _REPO_ROOT / "data" / "catalog" / "collect_state.json"
_HEADERS = {"User-Agent": "dart-risk-mcp catalog builder"}
_TIMEOUT = 30
_SLEEP = 0.25          # 서버 예의. 1,200페이지 순회 시 약 5분의 대기가 된다.
_MAX_PAGES = 200       # 연도당 안전 상한(실측 최대 85페이지)

# 담당부서 — 조직 개편이 잦아(회계감독1국 → 회계감리1국 → 회계심사국) 부분일치로 잡는다.
# '조사1국'은 '조사국'을 포함하지 않으므로 번호 붙은 조사국을 개별 등재한다.
DEPT_IN: list[str] = [
    "자본시장", "공시", "회계", "금융투자", "자산운용", "감사인감리",
    "조사1국", "조사2국", "조사3국", "조사기획", "특별조사", "공매도", "가상자산조사",
    "불공정",
]
# '보험조사국'(보험사기)·'보험감리실'이 위 패턴에 딸려 오는 것을 막는다.
DEPT_OUT: list[str] = ["보험"]

TITLE_KW: list[str] = [
    "불공정거래", "주가조작", "시세조종", "미공개", "부정거래", "선행매매", "리딩방",
    "전환사채", "신주인수권", "유상증자", "무상감자", "최대주주", "무자본", "우회상장",
    "횡령", "배임", "분식", "회계처리기준", "감사의견", "감리", "상장폐지", "관리종목",
    "증권선물위원회", "증선위", "공시위반", "자기주식", "공매도", "테마주", "작전",
    "코스닥", "코스피", "상장사", "상장기업", "증권신고서", "사업보고서", "주가",
]
# 부서·키워드가 맞아도 적발/조치 성격이 아닌 것 — 발간물·행사·인사.
TITLE_OUT: list[str] = [
    "가이드북", "공모전", "수상작", "설명회", "발간", "배포", "채용", "인가 의결",
    "예비인가", "교육", "홍보", "포상금 지급실적", "우수사례", "모범사례",
    "세미나", "워크숍", "기고", "임명", "위촉", "업무협약", "핸드북", "사례집",
]

_ROW = re.compile(
    r'<td class="num">\s*(\d*)\s*</td>\s*'
    r'<td class="title"><a href="[^"]*nttId=(\d+)[^"]*">([\s\S]*?)</a></td>\s*'
    r"<td>([\s\S]*?)</td>\s*<td>\s*(\d{4}-\d{2}-\d{2})"
)
_TAG = re.compile(r"<[^>]+>")
_ENTITIES = {
    "&amp;": "&", "&lsquo;": "'", "&rsquo;": "'", "&#39;": "'", "&middot;": "·",
    "&quot;": '"', "&nbsp;": " ", "&lt;": "<", "&gt;": ">",
}


def _clean(text: str) -> str:
    text = _TAG.sub(" ", text)
    for entity, char in _ENTITIES.items():
        text = text.replace(entity, char)
    return " ".join(text.split())


def parse_list_rows(html: str) -> list[dict]:
    """게시판 목록 HTML에서 행을 뽑는다. 매칭 실패는 빈 리스트(호출부가 종료 판단)."""
    return [
        {"id": m.group(2), "title": _clean(m.group(3)),
         "dept": _clean(m.group(4)), "date": m.group(5)}
        for m in _ROW.finditer(html)
    ]


def dept_hit(dept: str) -> bool:
    """담당부서가 자본시장 계열인가. '/' 구분 다중 부서는 하나라도 맞으면 통과."""
    for part in (p.strip() for p in (dept or "").split("/")):
        if not part or any(x in part for x in DEPT_OUT):
            continue
        if any(k in part for k in DEPT_IN):
            return True
    return False


def title_keywords(title: str) -> list[str]:
    return [k for k in TITLE_KW if k in (title or "")]


def is_general_notice(title: str) -> bool:
    """발간물·행사·인사 등 적발/조치가 아닌 일반 안내인가."""
    return any(x in (title or "") for x in TITLE_OUT)


def passes_filter(row: dict) -> bool:
    """(부서 OR 제목 키워드) AND NOT 일반안내."""
    if is_general_notice(row.get("title", "")):
        return False
    return dept_hit(row.get("dept", "")) or bool(title_keywords(row.get("title", "")))


def to_record(row: dict) -> dict:
    """목록 행 → 표준 레코드(Phase B·C가 소비)."""
    return {
        "source": "fss",
        "id": row["id"],
        "title": row.get("title", ""),
        "dept": row.get("dept", ""),
        "date": row.get("date", ""),
        "url": VIEW_URL.format(id=row["id"]),
        "matched_keywords": title_keywords(row.get("title", "")),
        "matched_dept": dept_hit(row.get("dept", "")),
    }


def page_key(year: int, page: int) -> str:
    return f"{year}:{page}"


def load_state(path: Path) -> dict:
    if not path.exists():
        return {"done_pages": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"done_pages": []}
    return data if isinstance(data, dict) and "done_pages" in data else {"done_pages": []}


def save_state(path: Path, state: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(state, ensure_ascii=False, indent=1), encoding="utf-8")


def fetch_list_page(year: int, page: int, fetch=None) -> str:
    """연도·페이지의 목록 HTML. 실패·오염 시 빈 문자열(호출부가 종료 판단)."""
    url = f"{LIST_URL}&sdate={year}0101&edate={year}1231&pageIndex={page}"
    try:
        raw = fetch(url) if fetch else _default_fetch(url)
    except Exception as exc:
        print(f"[COLLECT] {year} p{page} 요청 실패: {type(exc).__name__} {exc}")
        return ""
    html, trusted = decode_page(raw)
    if not trusted:
        print(f"[COLLECT] {year} p{page} 디코딩 신뢰 불가 — 건너뜀")
        return ""
    return html


def _default_fetch(url: str) -> bytes:
    resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.content


def main() -> None:
    use_utf8_stdout()
    parser = argparse.ArgumentParser(description="FSS 보도자료 목록 수집 → catalog_sources.jsonl")
    parser.add_argument("--from-year", type=int, default=2010)
    parser.add_argument("--to-year", type=int, default=date.today().year)
    parser.add_argument("--out", default=str(OUT_PATH))
    parser.add_argument("--state", default=str(STATE_PATH))
    parser.add_argument("--resume", action="store_true", help="이미 수집한 페이지를 건너뛴다")
    parser.add_argument("--dry-run", action="store_true", help="저장 없이 통과 건수만 출력")
    args = parser.parse_args()

    out_path, state_path = Path(args.out), Path(args.state)
    state = load_state(state_path) if args.resume else {"done_pages": []}
    done = set(state.get("done_pages") or [])

    seen: set[str] = set()
    if args.resume and out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                seen.add(str(json.loads(line).get("id", "")))
        print(f"[COLLECT] resume — 기존 {len(seen)}건 / 완료 페이지 {len(done)}개")

    if not args.dry_run:
        out_path.parent.mkdir(parents=True, exist_ok=True)
    fh = None if args.dry_run else out_path.open("a", encoding="utf-8")

    total = kept = 0
    try:
        for year in range(args.from_year, args.to_year + 1):
            year_total = year_kept = 0
            for page in range(1, _MAX_PAGES + 1):
                key = page_key(year, page)
                if key in done:
                    continue
                html = fetch_list_page(year, page)
                rows = parse_list_rows(html)
                if not rows:
                    break                      # 해당 연도의 마지막 페이지
                year_total += len(rows)
                for row in rows:
                    if row["id"] in seen or not passes_filter(row):
                        continue
                    seen.add(row["id"])
                    year_kept += 1
                    if fh:
                        fh.write(json.dumps(to_record(row), ensure_ascii=False) + "\n")
                if fh:
                    fh.flush()
                done.add(key)
                if not args.dry_run:
                    save_state(state_path, {"done_pages": sorted(done)})
                time.sleep(_SLEEP)
            total += year_total
            kept += year_kept
            rate = (year_kept / year_total * 100) if year_total else 0.0
            print(f"[COLLECT] {year}: 원본 {year_total}건 → 통과 {year_kept}건 ({rate:.1f}%)")
    finally:
        if fh:
            fh.close()

    rate = (kept / total * 100) if total else 0.0
    print(f"[COLLECT] 완료: 원본 {total}건 → 필터 통과 {kept}건 ({rate:.1f}%)")
    if not args.dry_run:
        print(f"[COLLECT] 저장 → {out_path}")


if __name__ == "__main__":
    main()
