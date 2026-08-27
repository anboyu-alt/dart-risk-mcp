"""취득 대상의 상장 여부를 **이름이 아니라 명부**로 판단하는지 잠근다.

`dart_client.py`에 「조합·펀드·투자신탁·리츠 같은 이름은 unlisted로 본다」는
`_NON_CORP_MARKERS` 목록이 **정의만 된 채** 있었다(2026-08-27 제거).
쓰이지 않은 것이 다행이다 — 명부 실측(110,911건)에서 **그 마커를 가진 채
진짜 상장 종목코드를 달고 있는 법인이 40곳**이었다.

    395400 SK리츠 · 396690 미래에셋글로벌리츠 · 365550 ESR켄달스퀘어리츠
    012420 메리츠종합금융증권 · 073530 코크렙제3호CR리츠 · …

상장 리츠·위탁관리부동산투자회사는 실재하는 코스피·코스닥 종목이다.
그 지름길을 켰다면 40곳을 unlisted로 뒤집었을 것이고,
`fund_diversion_chain`은 **unlisted일 때 발화**하므로 게이트가 느슨해져
없는 패턴이 떴을 것이다.

**이름은 실체를 말해 주지 않는다 — 명부를 본다.**
"""
import pytest

from dart_risk_mcp.core.dart_client import classify_target_listing

# 실측에서 뽑은, 마커를 가졌지만 **상장사**인 이름들
_LISTED = {
    "SK리츠": {"stock_code": "395400", "corp_code": "1"},
    "미래에셋글로벌리츠": {"stock_code": "396690", "corp_code": "2"},
    "ESR켄달스퀘어리츠": {"stock_code": "365550", "corp_code": "3"},
    "메리츠종합금융증권": {"stock_code": "012420", "corp_code": "4"},
    "코크렙제3호CR리츠": {"stock_code": "073530", "corp_code": "5"},
    # 같은 마커를 가졌지만 비상장인 것도 명부에 있다
    "테스트투자조합제1호": {"stock_code": "", "corp_code": "6"},
}


@pytest.mark.parametrize("name", [
    "SK리츠", "미래에셋글로벌리츠", "ESR켄달스퀘어리츠",
    "메리츠종합금융증권", "코크렙제3호CR리츠",
])
def test_이름에_마커가_있어도_명부가_상장이면_listed(name):
    assert classify_target_listing(name, "대한민국", _LISTED) == "listed"


def test_같은_마커라도_종목코드가_없으면_unlisted():
    assert classify_target_listing("테스트투자조합제1호", "대한민국",
                                   _LISTED) == "unlisted"


def test_명부에_없으면_unlisted():
    """명부는 비상장까지 담으므로, 없다는 것은 국내 상장사가 아니라는 근거다."""
    assert classify_target_listing("없는회사명", "대한민국", _LISTED) == "unlisted"


def test_이름이_비면_추측하지_않는다():
    assert classify_target_listing("", "대한민국", _LISTED) == "unknown"


def test_이름_기반_지름길이_없다():
    """`_NON_CORP_MARKERS`가 되살아나면 상장 리츠 40곳이 뒤집힌다."""
    import pathlib

    from dart_risk_mcp.core import dart_client as dc

    src = pathlib.Path(dc.__file__).read_text(encoding="utf-8")
    code = "\n".join(ln for ln in src.splitlines()
                     if not ln.lstrip().startswith("#"))
    assert "_NON_CORP_MARKERS" not in code
