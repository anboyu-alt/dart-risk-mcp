"""문제 회사 기반 행위자 자동 발굴.

매일 시장 '문제 회사'(자금조달 + 불안정 신호 동반)의 개인 인수자를 sightings로
누적(private repo, 12개월 윈도우)하고, 서로 다른 문제 회사 N=2곳+ 에 반복 등장하는
인물을 known_actors(public)에 auto_matched로 자동 등재한다. 임원·조합명은 제외.

사용: python scripts/discover_actors.py
환경: DART_API_KEY, SIGHTINGS_PATH(private repo의 sightings.json), MAIL_*(선택).
"""
import json
import os
import re
from datetime import datetime, timedelta
from pathlib import Path

from dart_risk_mcp.core.dart_client import fetch_market_disclosures, fetch_company_disclosures
from dart_risk_mcp.core.cb_extractor import extract_cb_investors
from dart_risk_mcp.core.investor_extractor import extract_rights_offering_investors
from dart_risk_mcp.core.signals import match_signals, is_amendment_disclosure
from scripts.refresh_known_actors import send_mail, _api_key

FUNDING_KEYS = {"CB_BW", "EB", "3PCA", "RIGHTS_UNDER", "RCPS"}
INSTABILITY_KEYS = {"SHAREHOLDER", "REVERSE_SPLIT", "GAMJA_MERGE", "INQUIRY",
                    "AUDIT", "MGMT_DISPUTE", "DISCLOSURE_VIOL"}
WINDOW_DAYS = 2
MAX_PAGES = 5
WINDOW_MONTHS = 12
N_THRESHOLD = 2

KNOWN_PATH = Path(__file__).resolve().parents[1] / "dart_risk_mcp" / "data" / "known_actors.json"
_DEFAULT_SIGHTINGS = Path(__file__).resolve().parents[1] / "tmp" / "sightings.json"

# 개인명이 아닌(법인·조합) 패턴
_ORG_PAT = re.compile(
    r"조합|투자|신탁|펀드|주식회사|\(주\)|㈜|유한|법인|파트너스|캐피탈|자산운용|"
    r"벤처|컴퍼니|코프|홀딩스|그룹|Co\.|Ltd|LLC|Inc")


def company_signal_keys(corp_code: str, api_key: str, lookback_days: int = 180) -> set:
    """회사 최근 공시의 신호 키 집합(정정 제외)."""
    keys = set()
    for d in (fetch_company_disclosures(corp_code, api_key, lookback_days) or []):
        rnm = d.get("report_nm", "")
        if is_amendment_disclosure(rnm):
            continue
        for s in (match_signals(rnm) or []):
            keys.add(s["key"])
    return keys


def is_problem_company(signal_keys) -> bool:
    """자금조달 신호 AND 불안정 신호가 함께 있으면 문제 회사."""
    ks = set(signal_keys)
    return bool(ks & FUNDING_KEYS) and bool(ks & INSTABILITY_KEYS)


def _is_person(name: str) -> bool:
    """개인명 여부(법인·조합 패턴 제외)."""
    if not name or not name.strip():
        return False
    return not _ORG_PAT.search(name)
