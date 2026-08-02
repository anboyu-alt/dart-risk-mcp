"""tool_server.corp.handle_corp — 공개 뷰어 기업 검색 폴백 몸통의 단위 테스트.

DART 호출(_load_corp_codes)은 dc._corp_cache를 직접 주입해 우회한다
(tests/test_corp_aliases.py의 전역 주입 관행과 동일). load_corp_aliases는
모킹한다.
"""
import pytest

import tool_server.corp as corp_mod
from dart_risk_mcp.core import dart_client as dc
from tool_server.corp import MAX_RESULTS, MIN_QUERY_LEN, handle_corp, search_corp_candidates


@pytest.fixture(autouse=True)
def _corp_cache_fixture(monkeypatch):
    """corp_cache에 상장·비상장 혼합 + 동명 충돌 없는 데이터를 주입."""
    cache = {
        "앤로보틱스": {"corp_code": "00808068", "stock_code": "138360"},
        "삼성전자": {"corp_code": "00126380", "stock_code": "005930"},
        "삼성바이오로직스": {"corp_code": "00877059", "stock_code": "207940"},
        "제이스코홀딩스": {"corp_code": "00164529", "stock_code": ""},  # 비상장
    }
    monkeypatch.setattr(dc, "_corp_cache", cache)
    monkeypatch.setattr(dc, "load_corp_aliases", lambda: {
        "협진": {"corp_code": "00808068", "stock_code": "138360", "current": "앤로보틱스"},
    })
    yield cache


class TestSearchCorpCandidatesPure:
    def test_exact_match_first(self):
        out = search_corp_candidates("앤로보틱스", dc._corp_cache, {})
        assert out[0] == {
            "name": "앤로보틱스", "corp_code": "00808068", "stock_code": "138360",
            "listed": True, "alias_of": None,
        }

    def test_stock_code_exact_match(self):
        out = search_corp_candidates("138360", dc._corp_cache, {})
        assert out[0]["name"] == "앤로보틱스"
        assert out[0]["corp_code"] == "00808068"

    def test_stock_code_no_match_returns_empty(self):
        assert search_corp_candidates("999999", dc._corp_cache, {}) == []

    def test_unlisted_candidate_marked_not_listed(self):
        out = search_corp_candidates("제이스코홀딩스", dc._corp_cache, {})
        assert out[0]["listed"] is False
        assert out[0]["stock_code"] == ""

    def test_alias_exact_match_resolves_to_current_name(self):
        aliases = {"협진": {"corp_code": "00808068", "stock_code": "138360", "current": "앤로보틱스"}}
        out = search_corp_candidates("협진", dc._corp_cache, aliases)
        assert out[0]["name"] == "앤로보틱스"
        assert out[0]["alias_of"] == "협진"
        assert out[0]["corp_code"] == "00808068"

    def test_partial_match_sorted_by_shorter_name_first(self):
        out = search_corp_candidates("삼성", dc._corp_cache, {})
        names = [c["name"] for c in out]
        assert names.index("삼성전자") < names.index("삼성바이오로직스")

    def test_no_match_returns_empty(self):
        assert search_corp_candidates("존재하지않는회사이름", dc._corp_cache, {}) == []

    def test_max_results_capped_at_8(self):
        cache = {f"테스트회사{i}": {"corp_code": f"c{i}", "stock_code": f"{100000+i}"} for i in range(20)}
        out = search_corp_candidates("테스트회사", cache, {})
        assert len(out) == MAX_RESULTS

    def test_empty_query_returns_empty(self):
        assert search_corp_candidates("", dc._corp_cache, {}) == []

    def test_exact_and_partial_no_duplicate_by_corp_code(self):
        # "앤로보틱스" 정확 일치 + 부분 일치 후보 목록에도 자기 자신이 다시
        # 걸릴 수 있는 상황(query in name)에서 corp_code 기준 중복 제거 확인.
        out = search_corp_candidates("앤로보틱스", dc._corp_cache, {})
        codes = [c["corp_code"] for c in out]
        assert len(codes) == len(set(codes))


class TestHandleCorp:
    def test_missing_api_key_returns_400(self):
        status, body = handle_corp({"q": "앤로보틱스"}, "")
        assert status == 400
        assert "X-DART-Key" in body["error"]

    @pytest.mark.parametrize("bad_q", ["", "a"])
    def test_query_too_short_returns_400(self, bad_q):
        status, body = handle_corp({"q": bad_q}, "key")
        assert status == 400
        assert "q" in body["error"]

    def test_success_returns_candidates(self):
        status, body = handle_corp({"q": "앤로보틱스"}, "key")
        assert status == 200
        assert body["query"] == "앤로보틱스"
        assert body["candidates"][0]["corp_code"] == "00808068"

    def test_alias_query_resolves_through_handle_corp(self):
        status, body = handle_corp({"q": "협진"}, "key")
        assert status == 200
        assert body["candidates"][0]["name"] == "앤로보틱스"
        assert body["candidates"][0]["alias_of"] == "협진"

    def test_empty_corp_cache_triggers_load_and_502_on_failure(self, monkeypatch):
        monkeypatch.setattr(dc, "_corp_cache", {})
        monkeypatch.setattr(dc, "_load_corp_codes", lambda key: None)  # 로드해도 여전히 빈 채로
        status, body = handle_corp({"q": "앤로보틱스"}, "key")
        assert status == 502

    def test_load_corp_codes_exception_returns_502(self, monkeypatch):
        monkeypatch.setattr(dc, "_corp_cache", {})

        def boom(key):
            raise RuntimeError("network")
        monkeypatch.setattr(dc, "_load_corp_codes", boom)
        status, body = handle_corp({"q": "앤로보틱스"}, "key")
        assert status == 502

    def test_no_judgement_wording_in_bodies(self):
        """무판정 원칙 — 서버 응답에 판정성 어휘가 섞이지 않는다."""
        for query, key in [({"q": "앤로보틱스"}, "key"), ({"q": "a"}, "key"), ({"q": "앤로보틱스"}, "")]:
            _, body = handle_corp(query, key)
            flat = str(body)
            for banned in ("위험도", "등급", "점수"):
                assert banned not in flat


def test_min_query_len_constant_is_two():
    assert MIN_QUERY_LEN == 2
