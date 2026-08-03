# -*- coding: utf-8 -*-
"""섹션 id 정합성 — list_document_sections ↔ fetch_document_content.

list_document_sections는 빈 제목·200자 이상 헤딩을 건너뛰며 id(fNsM)를
매기는데, fetch_document_content는 원시 헤딩 목록을 s_idx로 인덱싱해
스킵된 헤딩이 있으면 view_disclosure(section_id=…)가 **다른 섹션**을
반환했다(2026-08-04 정적 감사 E-1). 두 함수는 같은 필터 규칙의 헤딩
목록을 공유해야 한다.
"""
import io
import unittest
import zipfile
from unittest.mock import patch

from dart_risk_mcp.core import dart_client as dc

HTML = (
    "<html><title>테스트문서</title><body>"
    "<h1>첫 섹션</h1><p>첫 내용</p>"
    "<h2></h2><p>빈 제목 헤딩 뒤 내용</p>"          # 스킵 대상(빈 제목)
    "<h2>" + "가" * 250 + "</h2><p>본문 오인 헤딩</p>"  # 스킵 대상(200자+)
    "<h1>둘째 섹션</h1><p>둘째 내용</p>"
    "<h1>셋째 섹션</h1><p>셋째 내용</p>"
    "</body></html>"
)


def _zip_with(html: str):
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("doc.html", html.encode("utf-8"))
    buf.seek(0)
    return zipfile.ZipFile(buf)


class TestSectionIdAlignment(unittest.TestCase):
    def test_ids_resolve_to_listed_titles(self):
        with patch.object(dc, "_fetch_document_zip",
                          side_effect=lambda *a, **k: _zip_with(HTML)):
            listed = dc.list_document_sections("20260101000001", "key")
            sections = listed[0]["sections"]
            self.assertEqual([s["title"] for s in sections],
                             ["첫 섹션", "둘째 섹션", "셋째 섹션"])
            # 각 id로 원문을 조회하면 그 id의 제목 섹션 내용이 나와야 한다
            out1 = dc.fetch_document_content(
                "20260101000001", "key", section_id="f0s1")
            self.assertIn("둘째 내용", out1["content"])
            self.assertNotIn("빈 제목 헤딩 뒤 내용", out1["content"])
            out2 = dc.fetch_document_content(
                "20260101000001", "key", section_id="f0s2")
            self.assertIn("셋째 내용", out2["content"])


if __name__ == "__main__":
    unittest.main()
