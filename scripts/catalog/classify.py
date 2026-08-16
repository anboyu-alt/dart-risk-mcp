"""Phase C — 2단계 분류.

1차 스크리닝: 제목+담당부서+일자만으로 등재 가치를 판정. 네트워크를 쓰지 않는다
              — Phase A의 게시판 목록이 이미 이 셋을 갖고 있다.
2차 정밀:     1차 통과분만 extract_light(상세 페이지)로 요약을 받고, 이어서
              extract_full(PDF 전문)을 시도해 taxonomy 45개에 매핑한다.

상세 조회와 PDF 다운로드를 1차 통과분에만 거는 것이 이 설계의 핵심이다. 규칙 필터
통과분은 약 3,000건이지만 1차를 통과하는 것은 수백 건이라, 순서를 바꾸는 것만으로
네트워크 요청이 한 자릿수 배 줄어든다.

anthropic SDK를 쓰지 않고 requests로 직접 호출한다 — 이 레포는 Notion API도
같은 방식으로 다루며, 런타임/배치 모두 서드파티 의존성을 늘리지 않는 원칙이다.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from pathlib import Path

import requests

_REPO_ROOT = Path(__file__).resolve().parents[2]
if str(_REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(_REPO_ROOT))

from scripts._console import use_utf8_stdout  # noqa: E402
from scripts.catalog.extract import extract_full, extract_light  # noqa: E402

API_URL = "https://api.anthropic.com/v1/messages"
MODEL = "claude-haiku-4-5-20251001"
_TIMEOUT = 120
_SLEEP = 0.2
# Phase A(collect.py)의 출력을 바로 받는다 — 중간 산출물 catalog_bodies.jsonl은 없다.
IN_PATH = _REPO_ROOT / "data" / "catalog" / "catalog_sources.jsonl"
OUT_PATH = _REPO_ROOT / "data" / "catalog" / "catalog_classified.jsonl"

_JSON_BLOCK = re.compile(r"\{[\s\S]*\}")


def build_taxonomy_prompt(taxonomy: dict[str, dict]) -> str:
    """45개 유형 정의를 시스템 프롬프트로 만든다(프롬프트 캐싱 대상)."""
    lines = [
        "너는 한국 금융감독원·금융위원회 보도자료를 불공정거래 유형으로 분류하는 분석기다.",
        "아래는 분류 체계다. 각 항목은 'ID | 명칭 | 설명 | 키워드' 형식이다.",
        "",
    ]
    for tid in sorted(taxonomy, key=lambda t: [int(x) for x in t.split(".")]):
        e = taxonomy[tid]
        kws = ", ".join(e.get("keywords") or [])
        lines.append(f"{tid} | {e.get('name','')} | {e.get('description','')} | {kws}")
    lines += [
        "",
        "규칙:",
        "- 보도자료가 위 유형 중 어디에도 해당하지 않으면 taxonomy_ids를 빈 배열로 둔다.",
        "- 억지로 끼워 맞추지 마라. 확신이 없으면 confidence를 low로 하고 빈 배열을 낸다.",
        "- 반드시 JSON 객체 하나만 출력한다. 설명 문장을 덧붙이지 마라.",
    ]
    return "\n".join(lines)


def call_anthropic(system: str, user: str, api_key: str, model: str = MODEL) -> str:
    """Anthropic Messages API 호출. 시스템 프롬프트에 캐시 제어를 건다."""
    payload = {
        "model": model,
        "max_tokens": 1500,
        "system": [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}],
        "messages": [{"role": "user", "content": user}],
    }
    headers = {
        "x-api-key": api_key,
        "anthropic-version": "2023-06-01",
        "content-type": "application/json",
    }
    resp = requests.post(API_URL, headers=headers, json=payload, timeout=_TIMEOUT)
    resp.raise_for_status()
    blocks = resp.json().get("content") or []
    return "".join(b.get("text", "") for b in blocks if b.get("type") == "text")


def _extract_json(text: str) -> dict:
    match = _JSON_BLOCK.search(text or "")
    if not match:
        return {}
    try:
        parsed = json.loads(match.group(0))
        return parsed if isinstance(parsed, dict) else {}
    except json.JSONDecodeError:
        return {}


def parse_screen_response(text: str) -> dict:
    """1차 스크리닝 응답 파싱. 파싱 실패는 보수적으로 keep=False."""
    data = _extract_json(text)
    return {"keep": bool(data.get("keep")), "category_hint": str(data.get("category_hint", ""))}


def parse_classify_response(text: str) -> dict:
    """2차 정밀 응답 파싱. 존재하지 않는 taxonomy id는 버린다."""
    from dart_risk_mcp.core.taxonomy import TAXONOMY

    data = _extract_json(text)

    def _strlist(key: str) -> list[str]:
        vals = data.get(key)
        return [str(v).strip() for v in vals if str(v).strip()] if isinstance(vals, list) else []

    return {
        "taxonomy_ids": [t for t in _strlist("taxonomy_ids") if t in TAXONOMY],
        "techniques": _strlist("techniques"),
        "sanctions": _strlist("sanctions"),
        "laws": _strlist("laws"),
        "summary": str(data.get("summary", "")).strip(),
        "confidence": str(data.get("confidence", "low")).strip() or "low",
    }


_SCREEN_SYSTEM = (
    "너는 한국 금융감독원 보도자료를 선별하는 분류기다. "
    "주가조작·불공정거래·회계부정·지배구조 남용 등 상장기업 투자자 보호와 직접 관련된 "
    "자료면 keep=true, 채용·행사·일반 정책 홍보면 keep=false로 판정한다. "
    'JSON 객체 하나만 출력한다: {"keep": true/false, "category_hint": "1~8 중 하나 또는 빈 문자열"}'
)


def main() -> None:
    use_utf8_stdout()
    parser = argparse.ArgumentParser(description="보도자료 2단계 분류")
    parser.add_argument("--in", dest="in_path", default=str(IN_PATH))
    parser.add_argument("--out", default=str(OUT_PATH))
    parser.add_argument("--model", default=MODEL)
    parser.add_argument("--limit", type=int, default=0, help="상위 N건만 처리(비용 통제)")
    parser.add_argument("--resume", action="store_true", help="출력에 있는 id는 건너뜀")
    args = parser.parse_args()

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("ANTHROPIC_API_KEY 환경변수가 필요합니다")

    from dart_risk_mcp.core.taxonomy import TAXONOMY

    records = [json.loads(l) for l in Path(args.in_path).read_text(encoding="utf-8").splitlines() if l.strip()]
    out_path = Path(args.out)
    done: set[str] = set()
    if args.resume and out_path.exists():
        for line in out_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                done.add(str(json.loads(line).get("id", "")))
        print(f"[CLASSIFY] resume — 완료 {len(done)}건 건너뜀")

    todo = [r for r in records if str(r.get("id", "")) not in done]
    if args.limit:
        todo = todo[: args.limit]

    system_full = build_taxonomy_prompt(TAXONOMY)
    kept = mapped = 0
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("a", encoding="utf-8") as fh:
        for i, rec in enumerate(todo, 1):
            # 1차: 목록에서 이미 확보한 제목·부서·일자만 본다. 네트워크 호출 없음.
            head = (f"제목: {rec.get('title','')}\n"
                    f"담당부서: {rec.get('dept','')}\n"
                    f"일자: {rec.get('date','')}")
            try:
                screen = parse_screen_response(call_anthropic(_SCREEN_SYSTEM, head, api_key, args.model))
            except Exception as exc:
                print(f"[CLASSIFY] 스크리닝 실패 {rec.get('id')}: {type(exc).__name__}")
                continue
            if not screen["keep"]:
                continue
            kept += 1

            # 2차: 여기서 처음 네트워크로 본문을 확보한다(상세 페이지 → PDF 순).
            rec = extract_light(rec)
            full = extract_full(rec)
            body = full or rec.get("body", "")
            source = "pdf" if full else rec.get("body_source", "title_only")
            user = f"제목: {rec.get('title','')}\n일자: {rec.get('date','')}\n본문:\n{body[:20000]}"
            try:
                result = parse_classify_response(call_anthropic(system_full, user, api_key, args.model))
            except Exception as exc:
                print(f"[CLASSIFY] 정밀 실패 {rec.get('id')}: {type(exc).__name__}")
                continue

            out = {
                "id": rec.get("id", ""),
                "date": rec.get("date", ""),
                "agency": "금융감독원" if rec.get("source") == "fss" else "금융위원회",
                "title": rec.get("title", ""),
                "url": rec.get("url", ""),
                "body_source": source,
                **result,
            }
            if out["taxonomy_ids"]:
                mapped += 1
            fh.write(json.dumps(out, ensure_ascii=False) + "\n")
            fh.flush()
            if i % 25 == 0:
                print(f"[CLASSIFY] {i}/{len(todo)} — 통과 {kept} / 매핑 {mapped}")
            time.sleep(_SLEEP)

    print(f"[CLASSIFY] 완료: 후보 {len(todo)} → 스크리닝 통과 {kept} → 유형 매핑 {mapped}")


if __name__ == "__main__":
    main()
