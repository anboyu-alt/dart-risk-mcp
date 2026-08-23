"""횡령·배임 공시가 혼자 `founder_fade` 임계를 채우지 못한다.

`EMBEZZLE`은 5.3("장외 자산 이전 — 특수관계인에게 공정가 대비 15% 이상 할인
매각")과 8.1("인위적 부실화")을 함께 켰다. 5.3은 **특정 거래**를 요구하는데
「횡령ㆍ배임혐의발생」류 제목은 그 거래를 말하지 않는다 — 조건이 어긋나는
자리에 밀어 넣은 것이라 INQUIRY 실사고(조회공시가 4.3 공시의무위반을 켜서
패턴 카드 3개를 띄운 건)와 같은 종류다.

이중 매핑은 그 자체로 위험하다. 신호 하나가 taxonomy 2개를 켜면 공시
**한 건**이 패턴의 부분 겹침 임계(min_overlap=2)를 혼자 채운다. 1년
코퍼스에서 82건(혐의진행사항 33·혐의발생 30·사실확인 19)이 그렇게
`founder_fade`를 2/5로 띄우고 있었다.

축소의 기준은 **고아를 만들지 않는 것**이다 — 5.3은 ASSET_TRANSFER·
FUND_DIVERSION·DECISION_OVERSIZED가 계속 켠다.
"""
import pytest

from dart_risk_mcp.core.qualifiers import parse_report_name, qualify_signals
from dart_risk_mcp.core.signals import SIGNAL_KEY_TO_TAXONOMY, match_signals
from dart_risk_mcp.core.taxonomy import CROSS_SIGNAL_PATTERNS


def _taxonomies(nm):
    q = qualify_signals(match_signals(nm), parse_report_name(nm),
                        {"flr_nm": "", "corp_name": ""})
    tax = set()
    for x in q:
        if x.tier != "observed":
            continue
        v = SIGNAL_KEY_TO_TAXONOMY.get(x.key)
        tax |= set(v if isinstance(v, (list, tuple)) else [v] if v else [])
    return tax


class TestEmbezzleSingleTaxonomy:
    TITLES = ["횡령ㆍ배임혐의발생", "횡령ㆍ배임혐의진행사항", "횡령ㆍ배임사실확인"]

    def test_EMBEZZLE은_8_1만_켠다(self):
        assert SIGNAL_KEY_TO_TAXONOMY["EMBEZZLE"] == ["8.1"]

    @pytest.mark.parametrize("nm", TITLES)
    def test_신호_자체는_그대로_발화한다(self, nm):
        assert "EMBEZZLE" in {s["key"] for s in match_signals(nm)}, nm

    @pytest.mark.parametrize("nm", TITLES)
    def test_횡령배임_제목은_혼자_패턴을_못_채운다(self, nm):
        seq = set(CROSS_SIGNAL_PATTERNS["founder_fade"]["signal_sequence"])
        assert len(_taxonomies(nm) & seq) < 2, nm

    def test_5_3은_다른_신호가_계속_켠다(self):
        """고아를 만들지 않는 선에서만 좁힌다 — 이게 축소의 기준이다."""
        others = {k for k, v in SIGNAL_KEY_TO_TAXONOMY.items()
                  if "5.3" in (v if isinstance(v, (list, tuple)) else [v])}
        assert others, "5.3을 켜는 신호가 하나도 없으면 taxonomy가 죽는다"
        assert "EMBEZZLE" not in others

    def test_SHAREHOLDER는_좁히지_않았다(self):
        """3.2를 빼면 그걸 켜는 신호가 0개가 되어 taxonomy가 통째로 사라지고,
        founder_fade·related_party_hollowing에 발화 불가 id가 하나씩 더
        늘어난다(이미 4.1·2.5가 그 상태다). 같은 구조지만 기준에 걸려
        손대지 않았음을 고정한다."""
        assert SIGNAL_KEY_TO_TAXONOMY["SHAREHOLDER"] == ["3.1", "3.2"]
        lighting = {k for k, v in SIGNAL_KEY_TO_TAXONOMY.items()
                    if "3.2" in (v if isinstance(v, (list, tuple)) else [v])}
        assert lighting == {"SHAREHOLDER"}
