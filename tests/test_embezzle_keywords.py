"""EMBEZZLE 키워드 축소 회귀 가드 (2026-08-16).

시장 전체 실측(2026-07-17~2026-08-15, 30일·공시 15,555건)에서 "불공정거래"·
"주가조작"·"시세조종"·"미공개정보이용"·"미공개중요정보"·"선행매매"·"차명" 7개
키워드는 전부 0건이었다 — DART 공시 제목은 회사가 내는 공시라, 금융감독원
조사·제재의 결과인 이 7개 유형은 애초에 여기 등장하지 않는다. 반면 "횡령"·
"배임"은 실측 3건 매칭됐다. 상세 근거는
docs/catalog/gap-triage-2026-08-17.md 참고.

이 테스트는 (1) EMBEZZLE 키워드가 축소된 상태(횡령·배임 2개)로 유지되는지,
(2) 실제 매칭이 여전히 되는지, (3) 지워진 키워드가 되살아나지 않는지를 고정한다.
"""
import unittest

from dart_risk_mcp.core.signals import SIGNAL_TYPES, match_signals


def _embezzle_signal() -> dict:
    for sig in SIGNAL_TYPES:
        if sig["key"] == "EMBEZZLE":
            return sig
    raise AssertionError("EMBEZZLE not found in SIGNAL_TYPES")


class TestEmbezzleKeywordsReduced(unittest.TestCase):
    def test_embezzle_keywords_are_exactly_two(self):
        sig = _embezzle_signal()
        self.assertEqual(sig["keywords"], ["횡령", "배임"])

    def test_match_signals_still_catches_real_dart_title(self):
        # 실제 DART 제목 표기(가운뎃점은 U+318D "ㆍ", 일반 U+00B7 "·"가 아님).
        matched = match_signals("횡령ㆍ배임혐의발생")
        keys = {s["key"] for s in matched}
        self.assertIn("EMBEZZLE", keys)

    def test_match_signals_does_not_catch_removed_keywords(self):
        for title in ("주가조작 혐의 관련 조회공시", "시세조종 의혹 관련 조회공시"):
            matched = match_signals(title)
            keys = {s["key"] for s in matched}
            self.assertNotIn(
                "EMBEZZLE", keys,
                f"EMBEZZLE matched removed keyword title: {title!r}",
            )


if __name__ == "__main__":
    unittest.main()
