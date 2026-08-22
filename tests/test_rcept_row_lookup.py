"""접수번호 → list.json 행 역해석 (2026-08-22).

옛 구현은 하루 1,200건(12페이지)까지만 훑었다. 1년 코퍼스 실측으로 재 보니
그 상한은 **영업일의 77%만 커버**했고, 못 찾은 이유를 구분하지 않아 호출부가
"이 공시에서 의심 신호가 탐지되지 않았습니다"로 퇴화했다 — **정말 신호가
없는 공시와 조회에 실패한 공시가 같은 화면으로 보였다.**

| 상한 | 커버 영업일 (244일 기준) |
|---|---|
| 1,200건(12p) | 188일 (77.0%) |
| 5,000건(50p) | 242일 (99.2%) |
"""
import json
import pathlib
import statistics
from unittest.mock import patch

import pytest

import dart_risk_mcp.core.dart_client as dc


@pytest.fixture(autouse=True)
def _clear_cache():
    dc._rcept_row_cache.clear()
    yield
    dc._rcept_row_cache.clear()


def _resp(rows, total_page=1, status="000"):
    class R:
        def json(self):
            return {"status": status, "total_page": total_page, "list": rows}
    return R()


def _row(rcept_no, nm="테스트공시"):
    return {"rcept_no": rcept_no, "report_nm": nm,
            "corp_name": "테스트", "flr_nm": "테스트", "rcept_dt": rcept_no[:8]}


class TestStatus:
    def test_찾으면_found(self):
        with patch.object(dc, "_retry", return_value=_resp([_row("20260814900829")])):
            row, st = dc.resolve_disclosure_row_with_status("20260814900829", "k")
        assert st == dc.ROW_FOUND
        assert row["report_nm"] == "테스트공시"

    def test_전_페이지를_훑고_없으면_not_found(self):
        with patch.object(dc, "_retry", return_value=_resp([_row("20260814000001")])):
            row, st = dc.resolve_disclosure_row_with_status("20260814900829", "k")
        assert (row, st) == (None, dc.ROW_NOT_FOUND)

    def test_상한에_걸리면_scan_limit(self):
        """부재가 아니라 '못 봤다' — 이 구분이 이 변경의 핵심이다."""
        with patch.object(dc, "_retry", return_value=_resp([_row("20260814000001")],
                                                          total_page=99)):
            row, st = dc.resolve_disclosure_row_with_status(
                "20260814900829", "k", max_pages=3)
        assert (row, st) == (None, dc.ROW_SCAN_LIMIT)

    def test_status_013은_오류가_아니라_부재다(self):
        """휴장일 등 — '일시적이니 재시도하세요'라고 안내하면 안 된다."""
        with patch.object(dc, "_retry", return_value=_resp([], status="013")):
            row, st = dc.resolve_disclosure_row_with_status("20260101999999", "k")
        assert (row, st) == (None, dc.ROW_NOT_FOUND)

    def test_비정상_status는_error(self):
        with patch.object(dc, "_retry", return_value=_resp([], status="020")):
            row, st = dc.resolve_disclosure_row_with_status("20260814900829", "k")
        assert (row, st) == (None, dc.ROW_ERROR)

    def test_네트워크_오류는_error(self):
        with patch.object(dc, "_retry", side_effect=RuntimeError("boom")):
            row, st = dc.resolve_disclosure_row_with_status("20260814900829", "k")
        assert (row, st) == (None, dc.ROW_ERROR)

    @pytest.mark.parametrize("bad", ["", "abc", "1234", "2026081490082X",
                                     "202608149008290"])
    def test_형식_오류는_호출하지_않는다(self, bad):
        with patch.object(dc, "_retry", side_effect=AssertionError("호출되면 안 된다")):
            row, st = dc.resolve_disclosure_row_with_status(bad, "k")
        assert (row, st) == (None, dc.ROW_NOT_FOUND)


class TestPaging:
    def test_뒷페이지에_있어도_찾는다(self):
        """list.json은 접수번호 순이 아니라 전수를 훑어야 한다.

        20260331 실측: page 1에 …000015와 …604216이 함께 온다.
        """
        target = "20260814900829"
        calls = []

        def fake(method, url, **kw):
            pg = kw["params"]["page_no"]
            calls.append(pg)
            rows = [_row(target)] if pg == 7 else [_row(f"202608140000{pg:02d}")]
            return _resp(rows, total_page=10)

        with patch.object(dc, "_retry", side_effect=fake), \
             patch.object(dc.time, "sleep"):
            row, st = dc.resolve_disclosure_row_with_status(target, "k")
        assert st == dc.ROW_FOUND
        assert 7 in calls

    def test_찾으면_남은_배치를_돌지_않는다(self):
        target = "20260814900829"
        calls = []

        def fake(method, url, **kw):
            pg = kw["params"]["page_no"]
            calls.append(pg)
            rows = [_row(target)] if pg == 2 else [_row(f"202608140000{pg:02d}")]
            return _resp(rows, total_page=50)

        with patch.object(dc, "_retry", side_effect=fake), \
             patch.object(dc.time, "sleep"):
            _, st = dc.resolve_disclosure_row_with_status(target, "k")
        assert st == dc.ROW_FOUND
        # 첫 배치(2~5)까지만 — 50페이지를 다 돌면 안 된다
        assert max(calls) <= 1 + dc._ROW_LOOKUP_CONCURRENCY

    def test_total_page가_1이면_한_번만_호출한다(self):
        calls = []

        def fake(method, url, **kw):
            calls.append(kw["params"]["page_no"])
            return _resp([_row("20260814000001")], total_page=1)

        with patch.object(dc, "_retry", side_effect=fake):
            _, st = dc.resolve_disclosure_row_with_status("20260814900829", "k")
        assert calls == [1]
        assert st == dc.ROW_NOT_FOUND


class TestCache:
    def test_성공을_캐시한다(self):
        calls = []

        def fake(method, url, **kw):
            calls.append(1)
            return _resp([_row("20260814900829")])

        with patch.object(dc, "_retry", side_effect=fake):
            dc.resolve_disclosure_row_with_status("20260814900829", "k")
            dc.resolve_disclosure_row_with_status("20260814900829", "k")
        assert len(calls) == 1

    def test_부재도_캐시한다(self):
        """실패가 캐시되지 않으면 재조회가 매번 50페이지를 다시 쓴다."""
        calls = []

        def fake(method, url, **kw):
            calls.append(1)
            return _resp([_row("20260814000001")], total_page=1)

        with patch.object(dc, "_retry", side_effect=fake):
            dc.resolve_disclosure_row_with_status("20260814900829", "k")
            _, st = dc.resolve_disclosure_row_with_status("20260814900829", "k")
        assert len(calls) == 1
        assert st == dc.ROW_NOT_FOUND

    def test_scan_limit도_캐시하되_상태를_유지한다(self):
        calls = []

        def fake(method, url, **kw):
            calls.append(1)
            return _resp([_row("20260814000001")], total_page=99)

        with patch.object(dc, "_retry", side_effect=fake), \
             patch.object(dc.time, "sleep"):
            dc.resolve_disclosure_row_with_status("20260814900829", "k", max_pages=2)
            _, st = dc.resolve_disclosure_row_with_status("20260814900829", "k",
                                                          max_pages=2)
        assert st == dc.ROW_SCAN_LIMIT
        assert len(calls) == 2      # 첫 호출의 2페이지만, 재조회는 캐시

    def test_error는_캐시하지_않는다(self):
        """네트워크 오류는 일시적일 수 있다 — 재시도 기회를 막지 않는다."""
        calls = []

        def fake(method, url, **kw):
            calls.append(1)
            raise RuntimeError("boom")

        with patch.object(dc, "_retry", side_effect=fake):
            dc.resolve_disclosure_row_with_status("20260814900829", "k")
            dc.resolve_disclosure_row_with_status("20260814900829", "k")
        assert len(calls) == 2


class TestBackwardCompat:
    def test_옛_함수는_행만_돌려준다(self):
        with patch.object(dc, "_retry", return_value=_resp([_row("20260814900829")])):
            row = dc.resolve_disclosure_row_from_rcept_no("20260814900829", "k")
        assert row["report_nm"] == "테스트공시"

    def test_옛_함수는_실패에_None을_돌려준다(self):
        with patch.object(dc, "_retry", return_value=_resp([], status="013")):
            assert dc.resolve_disclosure_row_from_rcept_no("20260814900829", "k") is None


class TestLimitRationale:
    def test_상한이_1년_실측_분포를_덮는다(self):
        """기본 상한 50페이지(5,000건)의 근거를 코퍼스로 고정한다.

        코퍼스가 갱신돼 하루 공시량이 크게 늘면 이 테스트가 알려 준다.
        """
        corpus = (pathlib.Path(__file__).parent / "fixtures" / "corpus"
                  / "signal_titles_365d.json")
        scanned = json.loads(corpus.read_text(encoding="utf-8"))["n_disclosures_scanned"]
        # 244 영업일 기준 하루 평균 — 상한의 4분의 1을 넘으면 재검토 신호
        daily_avg = scanned / 244
        assert daily_avg < 5000 / 4, (
            f"하루 평균 {daily_avg:.0f}건 — 기본 max_pages(50) 재검토"
        )

    def test_기본값이_50페이지다(self):
        import inspect
        sig = inspect.signature(dc.resolve_disclosure_row_with_status)
        assert sig.parameters["max_pages"].default == 50


class TestToolMessage:
    """도구 출력에서 '신호 없음'과 '확인 못 함'이 구분되는지."""

    def _run(self, status, **kw):
        import dart_risk_mcp.server as srv
        with patch.object(srv, "resolve_disclosure_row_with_status",
                          return_value=(None, status)), \
             patch.object(srv, "_DART_API_KEY", "k"):
            return srv.check_disclosure_risk(rcept_no="20260814900829", **kw)

    def test_scan_limit이면_신호_없음이라_말하지_않는다(self):
        out = self._run(dc.ROW_SCAN_LIMIT)
        assert "신호가 없다는 뜻이 아닙니다" in out
        assert "의심 신호가 탐지되지 않았습니다" not in out
        assert "조회 범위" in out

    def test_error면_재시도를_안내한다(self):
        out = self._run(dc.ROW_ERROR)
        assert "신호가 없다는 뜻이 아닙니다" in out
        assert "다시 시도" in out

    def test_not_found면_접수번호를_확인하라고_한다(self):
        out = self._run(dc.ROW_NOT_FOUND)
        assert "찾지 못했습니다" in out
        assert "의심 신호가 탐지되지 않았습니다" not in out

    def test_제목을_직접_넘기면_조회_실패를_말하지_않는다(self):
        """제목이 있으면 분석이 가능하므로 실패 안내가 불필요하다."""
        out = self._run(dc.ROW_SCAN_LIMIT, report_name="주주명부폐쇄기간또는기준일설정")
        assert "조회 범위" not in out
        assert "의심 신호가 탐지되지 않았습니다" in out


class TestThrottleGuard:
    """DART 분당 스로틀(status 020)은 HTTP 200으로 온다 — _retry가 못 잡는다.

    이 함수는 페이지를 동시 4개씩 버스트로 던지므로 정확히 그 조건을 만든다.
    같은 종류의 사고가 이미 기록돼 있다(SE-4h: fnlttSinglIndx 12콜 버스트에서
    한 호출이 020으로 죽어 그 해가 통째로 빠진 채 '추이'가 그려졌다).
    """

    def test_020은_재시도해서_살린다(self):
        seq = [_resp([], status="020"),
               _resp([_row("20260814900829")])]

        with patch.object(dc, "_retry", side_effect=seq), \
             patch.object(dc.time, "sleep"):
            row, st = dc.resolve_disclosure_row_with_status("20260814900829", "k")
        assert st == dc.ROW_FOUND, "스로틀 한 번에 조회가 통째로 죽으면 안 된다"

    def test_800도_재시도한다(self):
        seq = [_resp([], status="800"),
               _resp([_row("20260814900829")])]
        with patch.object(dc, "_retry", side_effect=seq), \
             patch.object(dc.time, "sleep"):
            _, st = dc.resolve_disclosure_row_with_status("20260814900829", "k")
        assert st == dc.ROW_FOUND

    def test_재시도를_소진하면_error다(self):
        with patch.object(dc, "_retry", return_value=_resp([], status="020")) as m, \
             patch.object(dc.time, "sleep"):
            _, st = dc.resolve_disclosure_row_with_status("20260814900829", "k")
        assert st == dc.ROW_ERROR
        assert m.call_count == dc._ROW_STATUS_RETRIES

    def test_013은_재시도하지_않는다(self):
        """'그 조건에 자료가 없다'는 확정 답변이다."""
        with patch.object(dc, "_retry", return_value=_resp([], status="013")) as m:
            _, st = dc.resolve_disclosure_row_with_status("20260814900829", "k")
        assert st == dc.ROW_NOT_FOUND
        assert m.call_count == 1

    def test_900은_재시도하지_않는다(self):
        """키 오류는 다시 물어도 같은 답이다."""
        with patch.object(dc, "_retry", return_value=_resp([], status="900")) as m:
            _, st = dc.resolve_disclosure_row_with_status("20260814900829", "k")
        assert st == dc.ROW_ERROR
        assert m.call_count == 1

    def test_정상_응답은_한_번만_호출한다(self):
        with patch.object(dc, "_retry",
                          return_value=_resp([_row("20260814900829")])) as m:
            _, st = dc.resolve_disclosure_row_with_status("20260814900829", "k")
        assert st == dc.ROW_FOUND
        assert m.call_count == 1
