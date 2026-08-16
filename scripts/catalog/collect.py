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
_MAX_CONSECUTIVE_FAILURES = 3  # 이 값을 넘으면 사이트 장애로 간주해 그 연도를 중단

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


def should_stop_year(consecutive_failures: int) -> bool:
    """연속 실패 횟수가 임계값을 넘으면 그 연도 순회를 중단할지 판정한다.

    한 페이지 실패로 연도 전체를 버리지 않기 위해, 실패는 우선 건너뛰고
    다음 페이지로 계속한다. 다만 연속 실패가 임계값을 넘으면 일시적 흔들림이
    아니라 사이트 장애로 보고 그 연도를 중단한다(무한정 재시도하며 시간을
    낭비하지 않기 위함).
    """
    return consecutive_failures >= _MAX_CONSECUTIVE_FAILURES


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


def fetch_list_page(year: int, page: int, fetch=None) -> tuple[str, bool]:
    """연도·페이지의 목록 HTML. 반환: (html, ok).

    ok=False는 요청 실패·디코딩 신뢰불가를 뜻한다. 정상 응답인데 행이 없는
    경우(연도의 끝)와 반드시 구분해야 한다 — 둘을 같은 빈 문자열로 뭉개면
    일시적 실패가 연도 종료로 오인돼 나머지 페이지가 조용히 누락된다.
    """
    url = f"{LIST_URL}&sdate={year}0101&edate={year}1231&pageIndex={page}"
    try:
        raw = fetch(url) if fetch else _default_fetch(url)
    except Exception as exc:
        print(f"[COLLECT] {year} p{page} 요청 실패: {type(exc).__name__} {exc}")
        return "", False
    html, trusted = decode_page(raw)
    if not trusted:
        print(f"[COLLECT] {year} p{page} 디코딩 신뢰 불가 — 건너뜀")
        return "", False
    return html, True


def _default_fetch(url: str) -> bytes:
    resp = requests.get(url, headers=_HEADERS, timeout=_TIMEOUT)
    resp.raise_for_status()
    return resp.content


def check_output_conflict(out_path: Path, *, resume: bool, overwrite: bool, dry_run: bool) -> None:
    """`--resume`·`--overwrite` 없이 기존 출력을 덮어쓰려는 실행을 막는다.

    출력 파일을 항상 append 모드로 열기 때문에, 플래그 없이 두 번 실행하면
    같은 레코드가 그대로 두 벌 쌓인다. dry-run은 아무것도 쓰지 않으므로
    대상이 아니다. 충돌 시 SystemExit로 알린다(main()의 argparse 관례와 동일).
    """
    if dry_run or not out_path.exists() or resume or overwrite:
        return
    existing = sum(1 for line in out_path.read_text(encoding="utf-8").splitlines() if line.strip())
    raise SystemExit(
        f"출력 파일에 이미 {existing}건이 있습니다: {out_path}\n"
        "  이어서 수집하려면 --resume, 처음부터 다시 만들려면 --overwrite 를 쓰세요."
    )


def reset_for_overwrite(out_path: Path, state_path: Path, *, overwrite: bool, dry_run: bool) -> None:
    """`--overwrite` 지정 시 기존 출력·상태 파일을 모두 지운다.

    출력만 지우고 state를 남기면 이미 끝난 페이지로 기록된 것들이 건너뛰어져
    빈 결과가 된다 — 반드시 둘 다 지워야 처음부터 다시 수집된다.
    """
    if not overwrite or dry_run:
        return
    out_path.unlink(missing_ok=True)
    state_path.unlink(missing_ok=True)


def main() -> None:
    use_utf8_stdout()
    parser = argparse.ArgumentParser(description="FSS 보도자료 목록 수집 → catalog_sources.jsonl")
    parser.add_argument("--from-year", type=int, default=2010)
    parser.add_argument("--to-year", type=int, default=date.today().year)
    parser.add_argument("--out", default=str(OUT_PATH))
    parser.add_argument("--state", default=str(STATE_PATH))
    parser.add_argument("--resume", action="store_true", help="이미 수집한 페이지를 건너뛴다")
    parser.add_argument("--overwrite", action="store_true", help="기존 출력·상태를 지우고 처음부터 다시 수집한다")
    parser.add_argument("--dry-run", action="store_true", help="저장 없이 통과 건수만 출력")
    args = parser.parse_args()

    out_path, state_path = Path(args.out), Path(args.state)

    check_output_conflict(out_path, resume=args.resume, overwrite=args.overwrite, dry_run=args.dry_run)
    reset_for_overwrite(out_path, state_path, overwrite=args.overwrite, dry_run=args.dry_run)

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
    failed_pages: list[str] = []
    try:
        for year in range(args.from_year, args.to_year + 1):
            year_total = year_kept = 0
            consecutive_failures = 0
            for page in range(1, _MAX_PAGES + 1):
                key = page_key(year, page)
                if key in done:
                    continue
                html, ok = fetch_list_page(year, page)
                if not ok:
                    consecutive_failures += 1
                    failed_pages.append(key)
                    if should_stop_year(consecutive_failures):
                        print(
                            f"[COLLECT] {year}: 연속 {consecutive_failures}회 요청 실패 — "
                            "사이트 장애로 간주해 이 연도 수집을 중단합니다"
                        )
                        break
                    time.sleep(_SLEEP)
                    continue                  # 이 페이지만 건너뛰고 다음 페이지로 계속(done에는 넣지 않음)
                consecutive_failures = 0
                rows = parse_list_rows(html)
                if not rows:
                    break                      # 정상 응답인데 행이 없음 — 해당 연도의 마지막 페이지
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

    if failed_pages:
        shown = ", ".join(failed_pages[:20])
        more = len(failed_pages) - 20
        suffix = f" ... 외 {more}개" if more > 0 else ""
        print(f"[COLLECT] ⚠ 수집 실패 페이지 {len(failed_pages)}개: {shown}{suffix}")
        print("[COLLECT]   이 페이지들은 저장되지 않았습니다. 다음 명령으로 재시도하세요:")
        print(
            f"[COLLECT]   python scripts/catalog/collect.py "
            f"--from-year {args.from_year} --to-year {args.to_year} --resume"
        )


if __name__ == "__main__":
    main()
