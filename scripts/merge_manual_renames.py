# -*- coding: utf-8 -*-
"""수동 개명 시드(manual_renames.json) 검증 + sightings corp_renames 병합.

'상호변경안내' 공시 백필(backfill_renames.py)은 사실상 코스닥 전용이라
(corp_renames 610사 시장 분포 K 354 vs Y 2, 2026-08-03 실측) 유가증권(KOSPI)
개명은 자동으로 못 잡는다 — 실례: 에이프로젠KIC → 에이프로젠(00152385,
정관변경은 정기주총 의결이라 '상호변경안내' 공시가 없음). 이 스크립트는
운영자가 근거 rcept_no와 함께 등재한 시드를 DART와 대조 검증한 뒤 병합한다.

검증 2단계 (신규 event만, sightings에 이미 병합된 rcept_no는 건너뜀):
  1. 연결(치명): rcept_no 접수일의 해당 corp_code 공시 목록에 그 rcept_no가
     실재하는가 — 다른 회사 공시를 근거로 삼는 것을 기계적으로 차단.
  2. 표기(경고): 공시 원문에 시드의 옛 사명이 fold 수렴 기준으로 등장하는가 —
     '에이프로젠 KIC'(라틴)와 '에이프로젠케이아이씨'(음차)는 같은 fold.

시드 위치: SIGHTINGS_PATH 옆 manual_renames.json (private sightings repo에
커밋 — 법인명은 공개 사실이지만 sightings와 같은 운영 경로로 관리).
daily cron(discover_actors.main)도 같은 파일을 자동 반영하므로, 이 스크립트는
"지금 즉시 + 검증하며" 반영하고 싶을 때 쓴다.

실행: python scripts/merge_manual_renames.py [--seed 경로] [--dry-run] [--no-verify]
"""
import argparse
import json
import os
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from dart_risk_mcp.core.dart_client import (  # noqa: E402
    _retry,
    fetch_document_text,
)
from dart_risk_mcp.core.known_actors import fold_name  # noqa: E402
import scripts.discover_actors as da  # noqa: E402
from scripts.backfill_renames import merge_renames  # noqa: E402

_LIST_URL = "https://opendart.fss.or.kr/api/list.json"


def _fetch_day_list(corp_code: str, day: str, api_key: str) -> list:
    """해당 corp_code가 day(YYYYMMDD)에 접수한 공시의 rcept_no 목록."""
    r = _retry("get", _LIST_URL, params={
        "crtfc_key": api_key, "corp_code": corp_code,
        "bgn_de": day, "end_de": day, "page_count": 100})
    if r is None:
        return []
    try:
        return [it.get("rcept_no", "") for it in (r.json().get("list") or [])]
    except Exception:
        return []


def verify_manual_renames(renames: dict, api_key: str,
                          existing: dict | None = None) -> "tuple[list, list]":
    """시드 event를 DART와 대조 → (치명 오류, 경고) 목록.

    existing(현 sightings의 corp_renames)에 이미 든 rcept_no는 과거 실행에서
    병합·검증을 마친 것이라 API 호출 없이 건너뛴다.
    """
    errors: list = []
    warnings: list = []
    for cc, ent in renames.items():
        seen = {e.get("rcept_no")
                for e in ((existing or {}).get(cc) or {}).get("events", [])}
        folds = {fold_name(n) for n in ent.get("names", [])}
        folds.discard("")
        for ev in ent.get("events", []):
            rn = str(ev.get("rcept_no", ""))
            if rn in seen:
                continue
            day_rcepts = _fetch_day_list(cc, rn[:8], api_key)
            if rn not in day_rcepts:
                errors.append(
                    f"{cc}: rcept {rn}이 해당 corp_code의 {rn[:8]} 접수 목록에"
                    f" 없음 — 근거 공시가 이 회사 것이 아님")
                continue
            txt = fetch_document_text(rn, api_key, max_chars=20000) or ""
            folded_doc = fold_name(txt)
            if not any(f in folded_doc for f in folds):
                warnings.append(
                    f"{cc}: rcept {rn} 원문(앞 20,000자)에 시드의 옛 사명"
                    f" 표기가 보이지 않음 — 원문 직접 확인 권장")
    return errors, warnings


def _api_key() -> str:
    key = os.environ.get("DART_API_KEY", "")
    if key:
        return key
    p = Path(__file__).resolve().parent.parent / "tmp" / "_apikey.txt"
    return p.read_text(encoding="utf-8").strip() if p.exists() else ""


def main():
    ap = argparse.ArgumentParser(description="수동 개명 시드 검증·병합")
    ap.add_argument("--seed", default="",
                    help="manual_renames.json 경로 (기본: sightings 옆)")
    ap.add_argument("--dry-run", action="store_true",
                    help="저장 없이 검증·병합 결과만 출력")
    ap.add_argument("--no-verify", action="store_true",
                    help="DART 대조 검증 생략 (스키마 검증은 항상 수행)")
    args = ap.parse_args()

    sightings_path = Path(os.environ.get("SIGHTINGS_PATH") or da._DEFAULT_SIGHTINGS)
    seed_path = Path(args.seed) if args.seed else (
        sightings_path.parent / da._MANUAL_RENAMES_NAME)

    renames, errors = da.load_manual_renames(seed_path)
    for e in errors:
        print(f"[스키마 오류] {e}")
    if errors:
        raise SystemExit("시드 스키마 오류 — 수정 후 재실행 (rcept_no 없는"
                         " entry는 등재할 수 없습니다)")
    if not renames:
        print(f"시드 없음 또는 빈 시드: {seed_path}")
        return

    sdata = da._load(sightings_path, {"version": 1, "sightings": {}})

    if not args.no_verify:
        key = _api_key()
        if not key:
            raise SystemExit("DART_API_KEY 또는 tmp/_apikey.txt 필요"
                             " (--no-verify로 생략 가능)")
        v_errors, v_warnings = verify_manual_renames(
            renames, key, existing=sdata.get("corp_renames"))
        for w in v_warnings:
            print(f"[경고] {w}")
        for e in v_errors:
            print(f"[검증 실패] {e}")
        if v_errors:
            raise SystemExit("DART 대조 검증 실패 — 근거 rcept_no를 확인하세요")

    changed = merge_renames(sdata, renames)
    n_before = len(sdata.get("sightings", {}))
    if da.reconcile_corp_renames(sdata, da._corp_name_index(_api_key()),
                                 da._combined_legacy_index(sdata)):
        changed = True
    merged = n_before - len(sdata.get("sightings", {}))
    print(f"시드 {len(renames)}개 회사 병합, 소급 병합된 행위자 키: {merged}건")

    if args.dry_run:
        print("[dry-run] 저장 생략")
        return
    if changed:
        sightings_path.parent.mkdir(parents=True, exist_ok=True)
        sdata["updated"] = datetime.now().strftime("%Y-%m-%d")
        da._atomic_write_json(sightings_path, sdata, indent=0)
        print(f"저장: {sightings_path}")
    else:
        print("변경 없음")


if __name__ == "__main__":
    main()
