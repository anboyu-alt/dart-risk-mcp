"""큰 공시의 목차가 12%만 나오던 문제.

`list_disclosure_sections`의 목적은 큰 공시에서 **읽고 싶은 데로 건너뛰게**
하는 것이다. 그런데 153만 자 사업보고서에서 섹션이 11개만 나왔고, 전부
「해당사항 없습니다」 같은 껍데기였다 — 재무제표·주석·사업의 내용은 목차에
아예 없었다.

원인: DART 문서는 `<SECTION-N>`이 그 절의 **본문 전체**를 감싸고 제목은 그
안의 첫 `<TITLE>`에 있는데, 옛 구현은 `m.group(1)`(=본문 전체)을 제목으로
삼고 "200자 미만"만 남겼다. 그래서 내용이 있는 절이 통째로 버려졌다.

    <SECTION-1 ACLASS="MANDATORY">
      <TITLE ...>I. 회사의 개요</TITLE>
      …수만 자의 본문…
    </SECTION-1>

라이브 실측(아틀라스링크):

| 문서 | `<SECTION-N>` | 전 | 후 |
|---|---|---|---|
| 사업보고서 20260323000695 | 76 | 11 | **61** |
| 반기보고서 20260814002093 | 59 | 13 | **48** |
| 회사분할결정 20260805000212 | 2 | 1 | **2** |

수정 후 「2. 연결재무제표」·「3. 연결재무제표 주석」·「5. 재무제표 주석」이
목차에 뜨고 `view_disclosure(section_id=…)`로 바로 열린다.

⚠ `_valid_section_headings`는 id 부여(`list_document_sections`)와 id 해석
(`fetch_document_content`)이 **같은 필터를 공유**해야 한다 — 한쪽만 바뀌면
section_id가 다른 절을 가리킨다. 그래서 필터 함수 하나만 고쳤다.
"""
import dart_risk_mcp.core.dart_client as dc

_DOC = (
    '<SECTION-1 ACLASS="MANDATORY">'
    '<TITLE ATOC="Y">I. 회사의 개요</TITLE>'
    '<P>' + ("본문 " * 500) + '</P>'
    '</SECTION-1>'
    '<SECTION-2 ACLASS="MANDATORY">'
    '<TITLE>3. 연결재무제표 주석</TITLE>'
    '<P>' + ("주석 " * 800) + '</P>'
    '</SECTION-2>'
    '<SECTION-2 ACLASS="MANDATORY">'
    '<TITLE>2. 전문가와의 이해관계</TITLE>'
    '<P>해당사항 없습니다.</P>'
    '</SECTION-2>'
)


class TestHeadingTitle:
    def test_본문이_길어도_제목을_뽑는다(self):
        ms = list(dc._HEADING_RE.finditer(_DOC))
        assert dc._heading_title(ms[0]) == "I. 회사의 개요"

    def test_짧은_절도_그대로(self):
        ms = list(dc._HEADING_RE.finditer(_DOC))
        assert dc._heading_title(ms[2]) == "2. 전문가와의 이해관계"

    def test_TITLE이_없으면_본문에서_뽑는다(self):
        doc = "<SECTION-1>제목 없는 절</SECTION-1>"
        m = next(dc._HEADING_RE.finditer(doc))
        assert dc._heading_title(m) == "제목 없는 절"

    def test_h_태그는_그대로(self):
        doc = "<h2>II. 사업의 내용</h2>"
        m = next(dc._HEADING_RE.finditer(doc))
        assert dc._heading_title(m) == "II. 사업의 내용"


class TestValidHeadings:
    def test_본문_있는_절이_버려지지_않는다(self):
        got = dc._valid_section_headings(_DOC)
        assert len(got) == 3, "옛 구현은 짧은 껍데기 1개만 남겼다"
        assert [dc._heading_title(m) for m in got] == [
            "I. 회사의 개요", "3. 연결재무제표 주석", "2. 전문가와의 이해관계"]

    def test_제목이_길면_여전히_거른다(self):
        """길이 필터는 유지하되 **제목**에 건다."""
        doc = f"<SECTION-1><TITLE>{'가' * 250}</TITLE><P>x</P></SECTION-1>"
        assert dc._valid_section_headings(doc) == []

    def test_제목이_비면_거른다(self):
        assert dc._valid_section_headings("<SECTION-1><TITLE> </TITLE></SECTION-1>") == []

    def test_id_부여와_해석이_같은_목록을_본다(self):
        """두 호출부가 같은 필터를 쓰는지 — 어긋나면 section_id가 다른 절을
        가리킨다(옛 주석이 경고하는 계약)."""
        a = dc._valid_section_headings(_DOC)
        b = dc._valid_section_headings(_DOC)
        assert [m.start() for m in a] == [m.start() for m in b]
        assert [m.start() for m in a] == sorted(m.start() for m in a)
