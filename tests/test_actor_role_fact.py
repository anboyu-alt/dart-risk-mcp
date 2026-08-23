"""겸직 임원의 직위를 사실로 병기한다 — 동명이인을 눈으로 가릴 수 있게.

`find_actor_overlap`은 임원 **이름만** 보고 겸직을 판정했다. 그래서 대조군
(삼성전자·셀트리온)에서 「이혁재」가 ⚠️ 공통 행위자로 떴다. 원본을 열어 보면
서로 다른 사람이다(2026-08-23 라이브 실측).

    삼성전자 이혁재   직위 이사 · 등기 사외이사
    셀트리온 이혁재   직위 수석부사장 · 등기 미등기

반대로 문서화된 진짜 사례는 직위까지 같다.

    CG인바이츠 신용규  회장/사내이사      헬스커넥트 신용규  사내이사
    CG인바이츠 이호영  공동 대표이사/사내이사  헬스커넥트 이호영  사내이사

`fetch_executive_roster_detail`은 이미 이 필드를 담고 있었는데
`find_actor_overlap`이 이름만 쓰는 `fetch_executive_roster`를 부르고 있었다.
같은 엔드포인트·같은 연도 루프라 호출 예산은 그대로다.

**거르지 않는다** — 사외이사라고 세력이 아니라는 보장이 없고, 이 레포는
판정을 하지 않는다(v0.8.5). 표기만 늘린다.
"""
import dart_risk_mcp.server as srv


class TestExecRoleLabel:
    def test_직위와_등기여부를_함께_적는다(self):
        assert srv._exec_role_label(
            {"ofcps": "이사", "rgist_exctv_at": "사외이사"}) == "이사/사외이사"

    def test_같은_값이면_한_번만_적는다(self):
        """실측: 헬스커넥트는 직위·등기 모두 '사내이사'다."""
        assert srv._exec_role_label(
            {"ofcps": "사내이사", "rgist_exctv_at": "사내이사"}) == "사내이사"

    def test_원문_개행을_한_줄로_편다(self):
        """실측: 삼성전자 응답에 「등기\n임원」이 온다."""
        assert srv._exec_role_label(
            {"ofcps": "등기\n임원", "rgist_exctv_at": ""}) == "등기 임원"

    def test_한쪽만_있으면_그것만(self):
        assert srv._exec_role_label(
            {"ofcps": "", "rgist_exctv_at": "미등기"}) == "미등기"

    def test_비어_있으면_빈_문자열(self):
        """호출부가 라벨 없이 기존 형태로 렌더한다."""
        assert srv._exec_role_label({}) == ""
        assert srv._exec_role_label({"ofcps": "  ", "rgist_exctv_at": None}) == ""

    def test_판정하지_않는다(self):
        """사외이사를 거르거나 등급을 매기지 않는다 — 원문 표기 그대로."""
        out = srv._exec_role_label({"ofcps": "사외이사", "rgist_exctv_at": "사외이사"})
        assert out == "사외이사"
        for banned in ("위험", "정상", "의심", "점수"):
            assert banned not in out
