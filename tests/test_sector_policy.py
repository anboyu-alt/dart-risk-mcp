"""sector_policy 정적 맵 + 감사인명 정규화 + 계정 별칭 테스트 (kreports 이식분)."""
import pytest

from dart_risk_mcp.core.sector_policy import (
    SECTOR_POLICY_MAP,
    DEFAULT_POLICY_ITEMS,
    KSIC_TO_SECTOR,
    get_sector_for_induty_code,
    get_induty_name,
    get_critical_items,
)
from dart_risk_mcp.core.dart_client import (
    _AUDITOR_ALIASES,
    _normalize_auditor,
    _FS_ALIASES,
    _pick_account,
)


# ---------------------------------------------------------------------------
# 업종별 회계정책 맵
# ---------------------------------------------------------------------------

class TestSectorPolicy:
    def test_manufacturing_maps_to_c(self):
        # 전자부품 제조(26) → 제조업 C
        assert get_sector_for_induty_code("26410") == "C"

    def test_bio_maps_to_m(self):
        # 연구개발(70) → 전문·과학·기술 M (바이오 포함)
        assert get_sector_for_induty_code("70113") == "M"

    def test_unknown_code_returns_none(self):
        assert get_sector_for_induty_code("99") is None
        assert get_sector_for_induty_code(None) is None
        assert get_sector_for_induty_code("") is None

    def test_induty_name(self):
        assert get_induty_name("26410") == "전자부품·컴퓨터·통신장비 제조"
        assert get_induty_name(None) == "미분류"
        assert get_induty_name("99999") == "업종코드 99999"

    def test_critical_items_manufacturing(self):
        items = get_critical_items("26410")
        keys = [it[0] for it in items]
        # 제조업 핵심: 재고자산 평가 + 감가상각
        assert "inventory_valuation" in keys
        assert "depreciation" in keys
        # 공통 항목도 중복 없이 병합
        assert "employee_benefits" in keys
        assert "foreign_currency" in keys

    def test_critical_items_no_duplicates(self):
        for code in ("26410", "41000", "64110", "70113"):
            items = get_critical_items(code)
            # (item_key, 표시명) 조합 중복 없음
            pairs = [(it[0], it[1]) for it in items]
            assert len(pairs) == len(set(pairs)), f"중복: {code}"

    def test_critical_items_unknown_returns_defaults(self):
        items = get_critical_items(None)
        assert items == DEFAULT_POLICY_ITEMS

    def test_item_tuple_shape(self):
        # 모든 항목이 4-tuple(key, 표시명, priority, 설명)
        all_items = list(DEFAULT_POLICY_ITEMS)
        for sector in SECTOR_POLICY_MAP.values():
            all_items.extend(sector["critical_items"])
        for it in all_items:
            assert len(it) == 4
            assert it[2] in ("high", "medium")

    def test_ksic_map_targets_exist(self):
        # KSIC_TO_SECTOR가 가리키는 대분류가 전부 SECTOR_POLICY_MAP에 존재
        for sector in set(KSIC_TO_SECTOR.values()):
            assert sector in SECTOR_POLICY_MAP

    def test_no_forbidden_grade_words(self):
        # v0.8.5: 등급 명칭이 표시 텍스트에 유입되지 않아야 함
        import re
        forbidden = re.compile(r"매우위험|고위험|중위험|저위험|위험\s*등급")
        for sector in SECTOR_POLICY_MAP.values():
            for it in sector["critical_items"]:
                assert not forbidden.search(it[1] + it[3])


# ---------------------------------------------------------------------------
# 감사인명 정규화
# ---------------------------------------------------------------------------

class TestNormalizeAuditor:
    @pytest.mark.parametrize("raw,expected", [
        ("삼정", "삼정회계법인"),
        ("삼정KPMG", "삼정회계법인"),
        ("삼일", "삼일회계법인"),
        ("EY한영", "한영회계법인"),
        ("딜로이트안진", "안진회계법인"),
        ("삼일회계법인", "삼일회계법인"),   # 이미 표준명이면 그대로
        ("태평양회계법인", "태평양회계법인"),  # 미등록 이름은 원형 유지
    ])
    def test_alias_normalization(self, raw, expected):
        assert _normalize_auditor(raw) == expected

    def test_whitespace_and_entities_stripped(self):
        assert _normalize_auditor("삼정 KPMG") == "삼정회계법인"
        assert _normalize_auditor("삼일&nbsp;") == "삼일회계법인"

    def test_alias_values_are_canonical(self):
        # 별칭의 표준명이 다시 별칭 키가 되면 무한 정규화 여지 — 방지 확인
        for canonical in _AUDITOR_ALIASES.values():
            assert canonical.lower() not in _AUDITOR_ALIASES


# ---------------------------------------------------------------------------
# 계정 별칭 확장
# ---------------------------------------------------------------------------

class TestFsAliases:
    def test_revenue_variants_resolve(self):
        for nm in ("매출액", "영업수익", "수익(매출액)", "수입금액"):
            assert _pick_account({nm: 100}, _FS_ALIASES["매출"]) == 100

    def test_exact_name_has_priority(self):
        # 정확명("매출액")이 느슨한 별칭("수익")보다 우선
        fs = {"수익": 1, "매출액": 2}
        assert _pick_account(fs, _FS_ALIASES["매출"]) == 2

    def test_quarterly_net_income_resolves(self):
        assert _pick_account({"분기순이익": 42}, _FS_ALIASES["당기순이익"]) == 42
        assert _pick_account({"반기순이익": 43}, _FS_ALIASES["당기순이익"]) == 43

    def test_equity_variants(self):
        assert _pick_account({"자본합계": 7}, _FS_ALIASES["자본총계"]) == 7
