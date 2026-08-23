"""변동이 없는 보고자가 시계열을 뒤덮던 문제.

`track_insider_trading`이 말하는 것은 "지분 **변동** 시계열"이다. 그런데
관측이 1건뿐이고 비율이 0.00%인 보고자는 변동을 담지 않는데, 회사가 클수록
그 줄이 출력을 뒤덮어 정작 Δ가 붙은 줄이 묻혔다.

라이브 실측(2026-08-23, 2년 조회) — Δ는 하나도 잃지 않는다:

| 회사 | 전 | 후 | Δ 있는 줄 |
|---|---|---|---|
| 삼성전자 | 40,464자 (3,311줄) | **3,144자** (114줄) | 70 → 70 |
| 셀트리온 | 6,581자 | 4,074자 | 71 → 71 |
| 두산에너빌리티 | 3,376자 | 699자 | 1 → 1 |
| 제이스코홀딩스 | 582자 | 620자 | 7 → 7 |

지우는 게 아니라 **접는다** — 인원수와 예시를 사실로 남긴다. 목록에서
빠졌다는 것과 존재하지 않는다는 것이 같은 화면이 되면 안 된다.

규모 푸터도 이 도구에만 빠져 있어 함께 붙였다(다른 다년 도구와 같은 관례).
"""
from unittest.mock import patch

import dart_risk_mcp.core.dart_client as dc
import dart_risk_mcp.server as srv


def _rec(holder, rate, date, source="elestock"):
    return {
        "repror": holder, "corp_name": "테스트", "corp_code": "00000001",
        "sp_stock_lmp_rate": rate, "sp_stock_lmp_cnt": "1000",
        "rcept_dt": date, "rcept_no": "2026" + date[4:] + "000001",
        "source": source, "isu_exctv_ofcps": "", "isu_exctv_rgist_at": "",
        "isu_main_shrholdr": "",
    }


def _run(records):
    with patch.object(srv, "_DART_API_KEY", "k"), \
         patch.object(srv, "resolve_corp",
                      return_value=("테스트", {"corp_code": "00000001",
                                             "stock_code": "000001"})), \
         patch.object(srv, "fetch_insider_timeline", return_value=records), \
         patch.object(srv, "fetch_company_disclosures", return_value=[]), \
         patch.object(dc, "_retry", side_effect=AssertionError("네트워크 금지")):
        return srv.track_insider_trading("테스트", lookback_years=2)


class TestFlatReportersFolded:
    def test_관측_1건_0퍼센트는_접는다(self):
        out = _run([_rec("김영", "0.00", "20250301"),
                    _rec("이수", "0.00", "20250401")])
        assert "▶ 김영" not in out and "▶ 이수" not in out
        assert "보고자 2명은 위 목록에서 접었습니다" in out
        assert "김영" in out and "이수" in out, "인원수만 남기고 지우면 안 된다"

    def test_같은_0퍼센트가_두_번이어도_접는다(self):
        """기존 dedup(0.005%p 미만 차이는 동일 데이터)이 먼저 접어 관측 1건이
        되고, 그 뒤 이 규칙이 적용된다. 두 시점 모두 0.00%면 실제로 변동이
        없으므로 맞는 동작이다 — 처음엔 "관측 2건이면 남긴다"로 적었다가
        테스트가 이 상호작용을 드러냈다."""
        out = _run([_rec("김영", "0.00", "20250301"),
                    _rec("김영", "0.00", "20250601")])
        assert "▶ 김영" not in out
        assert "접었습니다" in out

    def test_0퍼센트에서_움직이면_남긴다(self):
        """dedup을 넘는 차이가 있으면 변동이므로 그대로 표기한다."""
        out = _run([_rec("김영", "0.00", "20250301"),
                    _rec("김영", "0.40", "20250601")])
        assert "▶ 김영" in out
        assert "Δ+0.40%" in out

    def test_비율이_0이_아니면_접지_않는다(self):
        out = _run([_rec("박대주", "5.10", "20250301")])
        assert "▶ 박대주" in out
        assert "접었습니다" not in out

    def test_델타가_있는_보고자는_그대로_남는다(self):
        """이 수정의 목적은 Δ를 살리는 것이다 — 하나도 잃으면 안 된다."""
        out = _run([_rec("최주주", "5.00", "20250301"),
                    _rec("최주주", "3.00", "20250601"),
                    _rec("김영", "0.00", "20250401")])
        assert "▶ 최주주" in out
        assert "Δ-2.00%" in out
        assert "▶ 김영" not in out

    def test_접을_게_없으면_안내를_붙이지_않는다(self):
        out = _run([_rec("박대주", "5.10", "20250301")])
        assert "접었습니다" not in out


class TestSizeFooter:
    def test_다년_조회에_규모_푸터가_붙는다(self):
        out = _run([_rec("박대주", "5.10", "20250301")])
        assert "예상 출력 규모" in out

    def test_1년_조회에는_붙지_않는다(self):
        """다른 다년 도구와 같은 관례 — lookback_years<=1이면 생략."""
        with patch.object(srv, "_DART_API_KEY", "k"), \
             patch.object(srv, "resolve_corp",
                          return_value=("테스트", {"corp_code": "00000001",
                                                 "stock_code": "000001"})), \
             patch.object(srv, "fetch_insider_timeline",
                          return_value=[_rec("박대주", "5.10", "20250301")]), \
             patch.object(srv, "fetch_company_disclosures", return_value=[]):
            out = srv.track_insider_trading("테스트", lookback_years=1)
        assert "예상 출력 규모" not in out
