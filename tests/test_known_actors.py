import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


class TestKnownActors(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self._path = str(Path(self._tmp.name) / "ka.json")
        self._env = patch.dict("os.environ", {"DART_KNOWN_ACTORS_PATH": self._path})
        self._env.start()

    def tearDown(self):
        self._env.stop()
        self._tmp.cleanup()

    def _write(self, data):
        Path(self._path).write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")

    def test_lookup_returns_records(self):
        from dart_risk_mcp.core.known_actors import lookup_actor
        self._write({"version": 1, "actors": {
            "신승수": [{"source": "DART 임원현황", "evidence": "CG인바이츠 등기임원",
                       "url": "https://dart.fss.or.kr", "date": "2024", "tags": ["겸직"]}]
        }})
        recs = lookup_actor("신승수")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["source"], "DART 임원현황")

    def test_lookup_unknown_returns_empty(self):
        from dart_risk_mcp.core.known_actors import lookup_actor
        self._write({"version": 1, "actors": {}})
        self.assertEqual(lookup_actor("유령"), [])

    def test_lookup_strips_and_handles_blank(self):
        from dart_risk_mcp.core.known_actors import lookup_actor
        self._write({"version": 1, "actors": {"신승수": [{"source": "X", "evidence": "y"}]}})
        self.assertEqual(len(lookup_actor("  신승수  ")), 1)
        self.assertEqual(lookup_actor(""), [])

    def test_lookup_matches_case_variant(self):
        # 레지스트리 키 'LIU HUAN'(자동 발굴 정규화 표기)을 'Liu Huan'으로 조회해도 매칭
        from dart_risk_mcp.core.known_actors import lookup_actor
        self._write({"version": 1, "actors": {
            "LIU HUAN": [{"source": "자동 발굴", "evidence": "e"}]}})
        self.assertEqual(len(lookup_actor("Liu Huan")), 1)
        self.assertEqual(len(lookup_actor("liu  huan")), 1)

    def test_normalize_name(self):
        from dart_risk_mcp.core.known_actors import normalize_name
        self.assertEqual(normalize_name("  Liu   Huan "), "LIU HUAN")
        self.assertEqual(normalize_name("홍길동"), "홍길동")
        self.assertEqual(normalize_name(""), "")

    def test_strip_role_qualifier(self):
        from dart_risk_mcp.core.known_actors import strip_role_qualifier
        # 후행 역할 괄호 제거 (가공 예시)
        self.assertEqual(
            strip_role_qualifier("가나금융투자 주식회사 (본건 펀드7의 신탁업자 지위에서)"),
            "가나금융투자 주식회사")
        # 선행 역할 괄호 제거
        self.assertEqual(
            strip_role_qualifier("(본건 펀드3의 신탁업자 지위에서) 가나금융투자 주식회사"),
            "가나금융투자 주식회사")
        # 전각 괄호도 제거
        self.assertEqual(
            strip_role_qualifier("가나은행（첨단기금의 관리,운용기관）"), "가나은행")
        # ASCII 괄호 + 관리/운용 키워드
        self.assertEqual(
            strip_role_qualifier("가나은행(첨단전략산업기금의 관리,운용기관)"), "가나은행")
        # 법인 접사 '(주)'는 보존 (역할 키워드 없음)
        self.assertEqual(strip_role_qualifier("(주)베이트리"), "(주)베이트리")
        # 역할 괄호 안에 '(주)'가 중첩돼도 괄호 전체 제거 — stray ')' 잔여 없음
        self.assertEqual(
            strip_role_qualifier(
                "코오롱 2021 이노베이션 투자조합(업무집행조합원 : (주)코오롱인베스트먼트)"),
            "코오롱 2021 이노베이션 투자조합")
        self.assertEqual(
            strip_role_qualifier("가나조합(업무집행조합원 ㈜가나인베스트먼트)"), "가나조합")
        # 중첩 케이스 결과에 짝 없는 괄호가 남지 않는다
        for _probe in ("(", ")", "（", "）"):
            self.assertNotIn(
                _probe,
                strip_role_qualifier(
                    "코오롱 2021 이노베이션 투자조합(업무집행조합원 : (주)코오롱인베스트먼트)"))
        # 역할 키워드 없는 괄호는 보존
        self.assertEqual(
            strip_role_qualifier("BOLD (Business Opportunities)"),
            "BOLD (Business Opportunities)")
        # 개인명·빈값·None
        self.assertEqual(strip_role_qualifier("홍길동"), "홍길동")
        self.assertEqual(strip_role_qualifier(""), "")
        self.assertEqual(strip_role_qualifier(None), "")

    def test_normalize_name_strips_role_qualifier(self):
        from dart_risk_mcp.core.known_actors import normalize_name
        # 역할 괄호 제거 후 정규화 (선행·후행 변형이 동일 기저 키로 수렴)
        self.assertEqual(
            normalize_name("가나금융투자 주식회사 (본건 펀드7의 신탁업자 지위에서)"),
            normalize_name("가나금융투자 주식회사"))
        self.assertEqual(
            normalize_name("(본건 펀드3의 신탁업자 지위에서) 가나금융투자 주식회사"),
            normalize_name("가나금융투자 주식회사"))
        # 기존 동작 보존
        self.assertEqual(normalize_name("  Liu   Huan "), "LIU HUAN")
        self.assertEqual(normalize_name("(주)베이트리"), "(주)베이트리")

    def test_strip_role_qualifier_removes_html_entities(self):
        from dart_risk_mcp.core.known_actors import strip_role_qualifier
        # 비표준 '&CR;' 제거 — 후행·선행·중간 위치 불문
        self.assertEqual(strip_role_qualifier("가나실체&CR;"), "가나실체")
        self.assertEqual(strip_role_qualifier("&CR;가나실체"), "가나실체")
        self.assertEqual(
            strip_role_qualifier("가나에셋대우 주식회사&CR;"), "가나에셋대우 주식회사")
        # '&CR;' 제거가 대괄호 역할 수식 제거보다 먼저 — 엔티티가 정규식을 깨지 않음
        self.assertEqual(
            strip_role_qualifier("가나펀드&CR;[업무집행조합원: (주)나다인베스트먼트]"),
            "가나펀드")
        # 표준·숫자 엔티티는 html.unescape로 디코드
        self.assertEqual(strip_role_qualifier("&#28070;가나"), "润가나")
        self.assertEqual(strip_role_qualifier("가나 &amp; 나다"), "가나 & 나다")
        # ⚠ 순수 '&'(세미콜론 없음)는 보존 — 'S&T'·'R&D'
        self.assertEqual(strip_role_qualifier("S&T중공업"), "S&T중공업")
        self.assertEqual(strip_role_qualifier("R&D파트너스"), "R&D파트너스")

    def test_strip_role_qualifier_removes_bracket_qualifiers(self):
        from dart_risk_mcp.core.known_actors import strip_role_qualifier
        # 역할 키워드 있는 대괄호 제거 (ASCII·전각). 가공 예시.
        self.assertEqual(
            strip_role_qualifier("가나펀드[업무집행조합원: 나다인베스트먼트 주식회사]"),
            "가나펀드")
        self.assertEqual(
            strip_role_qualifier("가나증권 주식회사 [나다의 신탁업자 지위에서]"),
            "가나증권 주식회사")
        self.assertEqual(
            strip_role_qualifier("가나펀드［업무집행조합원: 나다인베스트먼트］"),
            "가나펀드")
        # 대괄호 안 '(주)' 중첩돼도 통째로 삼킴 — stray 괄호 잔여 없음
        r = strip_role_qualifier("가나펀드[업무집행조합원: (주)나다인베스트먼트]")
        self.assertEqual(r, "가나펀드")
        for _p in ("[", "]", "［", "］", "(", ")"):
            self.assertNotIn(_p, r)
        # 역할 키워드 없는 대괄호는 보존 (가공 분류 태그)
        self.assertEqual(strip_role_qualifier("가나상품[에너지]"), "가나상품[에너지]")

    def test_load_missing_file_returns_empty(self):
        from dart_risk_mcp.core.known_actors import load_known_actors
        # 파일 미생성 상태
        self.assertEqual(load_known_actors(), {"version": 1, "actors": {}})

    def test_load_corrupt_returns_empty(self):
        from dart_risk_mcp.core.known_actors import load_known_actors
        Path(self._path).write_text("{ broken", encoding="utf-8")
        self.assertEqual(load_known_actors(), {"version": 1, "actors": {}})

    def test_override_skips_notion(self):
        # DART_KNOWN_ACTORS_PATH 지정 시 Notion 조회를 호출하지 않는다
        from unittest.mock import patch as _p
        from dart_risk_mcp.core import known_actors as ka
        self._write({"version": 1, "actors": {"X": [{"source": "s", "evidence": "e"}]}})
        with _p("dart_risk_mcp.core.known_actors.requests.post") as post:
            data = ka.load_known_actors()
        post.assert_not_called()
        self.assertIn("X", data["actors"])

    def _notion_page(self, name, source="자동 발굴", status="auto_matched", rcept=""):
        props = {
            "인물명": {"title": [{"plain_text": name}]},
            "source": {"rich_text": [{"plain_text": source}]},
            "status": {"select": {"name": status}},
            "evidence": {"rich_text": [{"plain_text": "e"}]},
            "url": {"url": "https://dart.fss.or.kr"},
            "date": {"rich_text": [{"plain_text": "2026-07"}]},
            "tags": {"multi_select": [{"name": "자동 발굴"}]},
            "rcept_no": {"rich_text": [{"plain_text": rcept}] if rcept else []},
        }
        return {"properties": props}

    def test_notion_fetch_when_env_set(self):
        # env 설정 + Notion 성공 → 파싱된 레지스트리 반환 + 캐시 저장
        import os
        import tempfile
        from unittest.mock import patch as _p, MagicMock
        from pathlib import Path
        from dart_risk_mcp.core import known_actors as ka
        self._env.stop()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cache = Path(tmp) / "notion.json"
                resp = MagicMock()
                resp.status_code = 200
                resp.json.return_value = {
                    "results": [self._notion_page("LIU HUAN", rcept="R1"),
                                self._notion_page("LIU HUAN", rcept="R2"),
                                self._notion_page("신승수", source="DART 임원현황",
                                                  status="verified")],
                    "has_more": False,
                }
                with _p("dart_risk_mcp.core.known_actors._CACHE_FILE", cache), \
                     _p("dart_risk_mcp.core.known_actors.requests.post",
                        return_value=resp) as post, \
                     _p.dict("os.environ", {"NOTION_TOKEN": "t",
                                            "DB_KNOWN_ACTORS": "db"}):
                    os.environ.pop("DART_KNOWN_ACTORS_PATH", None)
                    data = ka.load_known_actors()
                post.assert_called_once()
                self.assertEqual(len(data["actors"]["LIU HUAN"]), 2)
                self.assertEqual(data["actors"]["LIU HUAN"][0]["rcept_no"], "R1")
                self.assertEqual(data["actors"]["신승수"][0]["status"], "verified")
                self.assertTrue(cache.exists())
        finally:
            self._env.start()

    def test_notion_failure_falls_back_to_bundled(self):
        # Notion 실패 → 동봉 데이터 fallback (예외 없음)
        import os
        import tempfile
        from unittest.mock import patch as _p
        from pathlib import Path
        from dart_risk_mcp.core import known_actors as ka
        self._env.stop()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cache = Path(tmp) / "notion.json"
                with _p("dart_risk_mcp.core.known_actors._CACHE_FILE", cache), \
                     _p("dart_risk_mcp.core.known_actors.requests.post",
                        side_effect=Exception("net")), \
                     _p.dict("os.environ", {"NOTION_TOKEN": "t",
                                            "DB_KNOWN_ACTORS": "db"}):
                    os.environ.pop("DART_KNOWN_ACTORS_PATH", None)
                    data = ka.load_known_actors()
                self.assertIsInstance(data.get("actors"), dict)
        finally:
            self._env.start()

    def test_no_notion_env_uses_bundled_without_network(self):
        # opt-in — env 미설정 시 네트워크 시도 없이 동봉 데이터 사용
        import os
        from unittest.mock import patch as _p
        from dart_risk_mcp.core import known_actors as ka
        self._env.stop()
        try:
            with _p("dart_risk_mcp.core.known_actors.requests.post") as post:
                for k in ("NOTION_TOKEN", "DB_KNOWN_ACTORS", "DART_KNOWN_ACTORS_PATH"):
                    os.environ.pop(k, None)
                data = ka.load_known_actors()
            post.assert_not_called()
            self.assertIsInstance(data.get("actors"), dict)
        finally:
            self._env.start()

    def test_add_registry_record_skips_without_env(self):
        import os
        from unittest.mock import patch as _p
        from dart_risk_mcp.core.known_actors import add_registry_record
        with _p("dart_risk_mcp.core.known_actors.requests.post") as post:
            for k in ("NOTION_TOKEN", "DB_KNOWN_ACTORS"):
                os.environ.pop(k, None)
            ok = add_registry_record("홍길동", {"source": "자동 발굴", "evidence": "e"})
        self.assertFalse(ok)
        post.assert_not_called()

    def test_add_registry_record_writes_with_env(self):
        from unittest.mock import patch as _p, MagicMock
        from dart_risk_mcp.core.known_actors import add_registry_record
        resp = MagicMock()
        resp.status_code = 200
        with _p("dart_risk_mcp.core.known_actors.requests.post",
                return_value=resp) as post:
            ok = add_registry_record(
                "홍길동",
                {"source": "자동 발굴", "status": "auto_matched", "evidence": "e",
                 "url": "https://dart.fss.or.kr", "date": "2026-07",
                 "tags": ["자동 발굴"], "rcept_no": "R1"},
                token="t", db_id="db")
        self.assertTrue(ok)
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["parent"]["database_id"], "db")
        self.assertEqual(
            payload["properties"]["인물명"]["title"][0]["text"]["content"], "홍길동")
        self.assertEqual(
            payload["properties"]["rcept_no"]["rich_text"][0]["text"]["content"], "R1")

    def test_add_registry_record_tags_companies(self):
        from unittest.mock import patch as _p, MagicMock
        from dart_risk_mcp.core.known_actors import add_registry_record
        resp = MagicMock()
        resp.status_code = 200
        with _p("dart_risk_mcp.core.known_actors.requests.post",
                return_value=resp) as post:
            ok = add_registry_record(
                "홍길동",
                {"source": "자동 발굴", "evidence": "e",
                 "companies": ["A전자", "B바이오"]},
                token="t", db_id="db")
        self.assertTrue(ok)
        payload = post.call_args.kwargs["json"]
        names = {o["name"] for o in payload["properties"]["관련기업"]["multi_select"]}
        self.assertEqual(names, {"A전자", "B바이오"})

    def test_add_registry_record_omits_company_prop_when_empty(self):
        from unittest.mock import patch as _p, MagicMock
        from dart_risk_mcp.core.known_actors import add_registry_record
        resp = MagicMock()
        resp.status_code = 200
        with _p("dart_risk_mcp.core.known_actors.requests.post",
                return_value=resp) as post:
            add_registry_record("홍길동", {"source": "s", "evidence": "e"},
                                token="t", db_id="db")
        payload = post.call_args.kwargs["json"]
        self.assertNotIn("관련기업", payload["properties"])

    def test_page_to_record_roundtrips_companies(self):
        from dart_risk_mcp.core.known_actors import _page_to_record
        page = {"properties": {
            "인물명": {"title": [{"plain_text": "홍길동"}]},
            "source": {"rich_text": [{"plain_text": "s"}]},
            "status": {"select": {"name": "auto_matched"}},
            "evidence": {"rich_text": [{"plain_text": "e"}]},
            "url": {"url": ""},
            "date": {"rich_text": []},
            "tags": {"multi_select": []},
            "관련기업": {"multi_select": [{"name": "A전자"}, {"name": "B바이오"}]},
        }}
        name, rec = _page_to_record(page)
        self.assertEqual(name, "홍길동")
        self.assertEqual(set(rec["companies"]), {"A전자", "B바이오"})

    def test_ensure_registry_schema_skips_without_env(self):
        import os
        from unittest.mock import patch as _p
        from dart_risk_mcp.core.known_actors import ensure_registry_schema
        with _p("dart_risk_mcp.core.known_actors.requests.patch") as patch_call:
            for k in ("NOTION_TOKEN", "DB_KNOWN_ACTORS"):
                os.environ.pop(k, None)
            ok = ensure_registry_schema()
        self.assertFalse(ok)
        patch_call.assert_not_called()

    def test_ensure_registry_schema_adds_only_missing(self):
        # 관련기업은 이미 존재 → PATCH 페이로드에서 제외 (재PATCH가 값을 지우는 사고 방지)
        from unittest.mock import patch as _p, MagicMock
        from dart_risk_mcp.core.known_actors import ensure_registry_schema
        get_resp = MagicMock(); get_resp.status_code = 200
        get_resp.json.return_value = {"properties": {"인물명": {}, "관련기업": {}}}
        patch_resp = MagicMock(); patch_resp.status_code = 200
        with _p("dart_risk_mcp.core.known_actors.requests.get",
                return_value=get_resp), \
             _p("dart_risk_mcp.core.known_actors.requests.patch",
                return_value=patch_resp) as patch_call:
            ok = ensure_registry_schema(token="t", db_id="db")
        self.assertTrue(ok)
        payload = patch_call.call_args.kwargs["json"]
        self.assertNotIn("관련기업", payload["properties"])  # 기존 속성 재PATCH 금지
        self.assertIn("구분", payload["properties"])

    def test_ensure_registry_schema_noop_when_all_exist(self):
        from unittest.mock import patch as _p, MagicMock
        from dart_risk_mcp.core.known_actors import ensure_registry_schema
        get_resp = MagicMock(); get_resp.status_code = 200
        get_resp.json.return_value = {"properties": {"관련기업": {}, "구분": {}}}
        with _p("dart_risk_mcp.core.known_actors.requests.get",
                return_value=get_resp), \
             _p("dart_risk_mcp.core.known_actors.requests.patch") as patch_call:
            ok = ensure_registry_schema(token="t", db_id="db")
        self.assertTrue(ok)
        patch_call.assert_not_called()

    def test_classify_actor_tiers(self):
        from dart_risk_mcp.core.known_actors import classify_actor
        # 개인
        self.assertEqual(classify_actor("홍길동"), "person")
        self.assertEqual(classify_actor("DING SHAO BIN"), "person")
        # 조합·사모 비히클 (최고 관심 — 기관 패턴보다 우선)
        self.assertEqual(classify_actor("아레스1호투자조합"), "fund")
        self.assertEqual(classify_actor("르퓨쳐 코스닥벤처 일반사모투자신탁"), "fund")
        # 일반·외국 법인
        self.assertEqual(classify_actor("(주)스마트에쿼티파트너스"), "corp")
        self.assertEqual(classify_actor("베이스100"), "corp")
        self.assertEqual(classify_actor("ZHUOHUA INVESTMENT HOLDINGS PTE. LTD"), "corp")
        # 제도권 기관 (수집 제외)
        self.assertEqual(classify_actor("한국투자증권"), "institution")
        self.assertEqual(classify_actor("한국산업은행(첨단전략산업기금의 관리,운용기관)"),
                         "institution")
        self.assertEqual(classify_actor("미래에셋자산운용"), "institution")
        self.assertEqual(classify_actor("Citibank, N.A."), "institution")
        # 노이즈
        self.assertEqual(classify_actor(""), "noise")

    def test_classify_actor_rejects_extraction_fragments(self):
        from dart_risk_mcp.core.known_actors import classify_actor
        # 원문 파싱 조각 → noise
        self.assertEqual(classify_actor("으로서 결성 및"), "noise")
        self.assertEqual(classify_actor("등의 다른회사 등기임원"), "noise")
        self.assertEqual(classify_actor("및 공동"), "noise")
        self.assertEqual(classify_actor("에 해당하는"), "noise")
        self.assertEqual(classify_actor("으로 있는 사모투자합자회사"), "noise")
        # 실명은 보존 — 끝글자가 조사와 같아도 단일 토큰이면 통과
        self.assertEqual(classify_actor("여경은"), "person")
        self.assertEqual(classify_actor("이정은"), "person")
        self.assertEqual(classify_actor("홍길동"), "person")
        # 정상 다토큰 조합/외국인명 보존
        self.assertEqual(classify_actor("SUN YANE"), "person")
        self.assertEqual(classify_actor("교보 KDBC 머니볼 신기술사업투자조합"), "fund")

    def test_classify_actor_rejects_table_artifacts(self):
        from dart_risk_mcp.core.known_actors import classify_actor
        # 인수자 명단 표의 헤더·합계행 등이 이름으로 잘못 추출된 경우 → noise
        for junk in ("합계", "합 계", "소계", "총계", "계", "기타", "합",
                     "성명", "주주명", "구분", "비고", "순번", "번호",
                     "으로", "으로서", "및", "등", "등의"):
            self.assertEqual(classify_actor(junk), "noise", junk)
        # 공백·대소문자 변형도 동일 차단
        self.assertEqual(classify_actor(" 합  계 "), "noise")
        # 실명과 겹칠 수 있는 값은 노이즈로 넣지 않음 — '이상'(李箱)은 실명 보존
        self.assertEqual(classify_actor("이상"), "person")
        # 실명·법인명은 보존 (표 헤더 목록과 정확히 일치하지 않음)
        self.assertEqual(classify_actor("김기타"), "person")   # '기타'로 끝나도 실명
        self.assertEqual(classify_actor("등지"), "person")
        self.assertEqual(classify_actor("홍길동"), "person")

    def test_classify_actor_strips_role_qualifier(self):
        from dart_risk_mcp.core.known_actors import classify_actor
        # 증권사 기저 + 역할 괄호 → institution (수집 제외). 가공 예시.
        self.assertEqual(
            classify_actor("가나증권 주식회사 (밸류 전문투자형 사모투자신탁의 신탁업자 지위에서)"),
            "institution")
        # 금융투자사 기저 → institution (신한금융투자류)
        self.assertEqual(
            classify_actor("가나금융투자 주식회사 (본건 펀드7의 신탁업자 지위에서)"),
            "institution")
        # 선행 괄호 형태도 동일 기저 → institution
        self.assertEqual(
            classify_actor("(본건 펀드3의 신탁업자 지위에서) 가나금융투자 주식회사"),
            "institution")
        # 금융투자 단독 (접사 없이도) institution
        self.assertEqual(classify_actor("가나금융투자"), "institution")
        # 법인 기저 + 역할 괄호 → corp (추적 유지)
        self.assertEqual(
            classify_actor("(주)스마트에쿼티파트너스 (본건 펀드의 업무집행 지위에서)"),
            "corp")

    def test_classify_actor_excludes_miraeasset_daewoo(self):
        from dart_risk_mcp.core.known_actors import classify_actor
        # 미래에셋대우: 사명에 '증권/금융투자'가 없어 이전엔 corp로 오분류되던
        # 지배적 오탐 허브. 리터럴로 institution 처리(수집 제외).
        self.assertEqual(classify_actor("미래에셋대우 주식회사"), "institution")
        # HTML 엔티티 붙어도 정제 후 동일 판정
        self.assertEqual(classify_actor("미래에셋대우 주식회사&CR;"), "institution")
        self.assertEqual(classify_actor("&CR;미래에셋대우 주식회사"), "institution")
        # 관측된 오기 '미래애셋대우'도 제외
        self.assertEqual(classify_actor("미래애셋대우"), "institution")
        # ⚠ NEGATIVE: 'bare 대우'를 넣지 않으므로 아래는 기관으로 오제외되지 않는다
        self.assertNotEqual(classify_actor("대우건설"), "institution")
        self.assertNotEqual(classify_actor("(주)대우건설"), "institution")
        self.assertEqual(classify_actor("(주)대우건설"), "corp")
        self.assertNotEqual(classify_actor("대우조선해양"), "institution")
        # 가공 인물 '박대우'는 인물로 보존
        self.assertEqual(classify_actor("박대우"), "person")

    def test_sector_of_securities_and_banks(self):
        from dart_risk_mcp.core.known_actors import sector_of
        # 증권·금융투자·미래에셋대우(오기 포함) → "증권" (수집 제외 대상)
        self.assertEqual(sector_of("가나증권"), "증권")
        self.assertEqual(sector_of("가나투자증권 주식회사"), "증권")
        self.assertEqual(sector_of("가나금융투자"), "증권")
        self.assertEqual(sector_of("미래에셋대우 주식회사"), "증권")
        self.assertEqual(sector_of("미래애셋대우"), "증권")
        # 역할 괄호가 붙어도 기저 실체로 판정
        self.assertEqual(
            sector_of("가나증권 주식회사 (본건 펀드의 신탁업자 지위에서)"), "증권")
        # 은행 → "은행" (수집 제외 대상)
        self.assertEqual(sector_of("가나은행"), "은행")
        self.assertEqual(sector_of("한국산업은행(첨단전략산업기금의 관리,운용기관)"), "은행")

    def test_sector_of_other_institutions(self):
        from dart_risk_mcp.core.known_actors import sector_of
        # 증권·은행이 아닌 제도권 기관 → "기타기관"
        self.assertEqual(sector_of("가나자산운용"), "기타기관")
        self.assertEqual(sector_of("가나생명보험"), "기타기관")
        self.assertEqual(sector_of("가나캐피탈"), "기타기관")
        self.assertEqual(sector_of("교직원공제회"), "기타기관")

    def test_sector_of_advisory_pe_vc(self):
        from dart_risk_mcp.core.known_actors import sector_of
        # 현재 corp로 분류되는 자문·PE·VC 성 법인 → "기타기관"
        self.assertEqual(sector_of("가나투자자문"), "기타기관")
        self.assertEqual(sector_of("(주)스마트에쿼티파트너스"), "기타기관")
        self.assertEqual(sector_of("가나인베스트먼트"), "기타기관")

    def test_sector_of_normal_actors_none(self):
        from dart_risk_mcp.core.known_actors import sector_of
        # 개인·조합·일반법인은 섹터 없음(None) — 항상 표시 대상
        self.assertIsNone(sector_of("홍길동"))
        self.assertIsNone(sector_of("아레스1호투자조합"))
        self.assertIsNone(sector_of("베이스100"))
        self.assertIsNone(sector_of("(주)대우건설"))
        self.assertIsNone(sector_of(""))

    def test_should_store_keeps_trackables_and_other_institutions(self):
        from dart_risk_mcp.core.known_actors import should_store
        # 개인·조합·일반법인 저장
        self.assertTrue(should_store("홍길동"))
        self.assertTrue(should_store("아레스1호투자조합"))
        self.assertTrue(should_store("(주)대우건설"))
        # 증권·은행 제외한 제도권 기관(자산운용 등)은 저장
        self.assertTrue(should_store("가나자산운용"))
        self.assertTrue(should_store("가나생명보험"))
        # 자문·PE·VC(corp)도 저장
        self.assertTrue(should_store("(주)스마트에쿼티파트너스"))

    def test_should_store_drops_securities_banks_and_noise(self):
        from dart_risk_mcp.core.known_actors import should_store
        # 증권·은행은 저장 안 함
        self.assertFalse(should_store("가나증권"))
        self.assertFalse(should_store("가나금융투자"))
        self.assertFalse(should_store("미래에셋대우 주식회사"))
        self.assertFalse(should_store("가나은행"))
        # 노이즈(표 헤더·빈값)도 저장 안 함
        self.assertFalse(should_store("합계"))
        self.assertFalse(should_store(""))

    def test_canonical_name_maps_aliases(self):
        from dart_risk_mcp.core.known_actors import canonical_name, normalize_name
        # 가공의 예시 — 실제 별칭 매핑은 비공개 sightings 저장소에만 둔다
        aliases = {normalize_name("김철수"): normalize_name("KIM CHULSOO"),
                   normalize_name("철수"): normalize_name("KIM CHULSOO")}
        # 별칭 → 정본
        self.assertEqual(canonical_name("김철수", aliases), normalize_name("KIM CHULSOO"))
        self.assertEqual(canonical_name(" 철수 ", aliases), normalize_name("KIM CHULSOO"))
        # 정본 자신은 그대로
        self.assertEqual(canonical_name("KIM CHULSOO", aliases), normalize_name("KIM CHULSOO"))
        # 별칭에 없는 이름은 정규화만
        self.assertEqual(canonical_name("홍길동", aliases), "홍길동")
        # aliases 없으면 normalize_name과 동일
        self.assertEqual(canonical_name("Liu  Huan"), "LIU HUAN")
        self.assertEqual(canonical_name("Liu  Huan", None), "LIU HUAN")

    def test_disclosure_url(self):
        from dart_risk_mcp.core.known_actors import disclosure_url
        self.assertEqual(disclosure_url("20260421000499"),
                         "https://dart.fss.or.kr/dsaf001/main.do?rcpNo=20260421000499")
        self.assertEqual(disclosure_url(""), "")

    def test_evidence_rich_text_hyperlinks_companies(self):
        from dart_risk_mcp.core.known_actors import _evidence_rich_text
        text = "문제 회사 2곳 인수자 반복 등장: 에이디테크놀로지·태웅로직스"
        urls = {"에이디테크놀로지": "https://x/1", "태웅로직스": "https://x/2"}
        rich = _evidence_rich_text(text, urls)
        # 회사명 span만 link, 나머지는 평문
        linked = {s["text"]["content"]: s["text"].get("link", {}).get("url")
                  for s in rich if s["text"].get("link")}
        self.assertEqual(linked, {"에이디테크놀로지": "https://x/1", "태웅로직스": "https://x/2"})
        self.assertEqual("".join(s["text"]["content"] for s in rich), text)

    def test_evidence_rich_text_plain_when_no_links(self):
        from dart_risk_mcp.core.known_actors import _evidence_rich_text
        rich = _evidence_rich_text("그냥 평문", None)
        self.assertEqual(rich, [{"type": "text", "text": {"content": "그냥 평문"}}])

    def test_add_registry_record_hyperlinks_evidence(self):
        from unittest.mock import patch as _p, MagicMock
        from dart_risk_mcp.core.known_actors import add_registry_record
        resp = MagicMock(); resp.status_code = 200
        with _p("dart_risk_mcp.core.known_actors.requests.post",
                return_value=resp) as post:
            add_registry_record("김조합",
                {"source": "자동 발굴", "evidence": "문제 회사 2곳 인수자 반복 등장: A·B",
                 "company_links": {"A": "https://x/1", "B": "https://x/2"}},
                token="t", db_id="db")
        rich = post.call_args.kwargs["json"]["properties"]["evidence"]["rich_text"]
        linked = {s["text"]["content"] for s in rich if s["text"].get("link")}
        self.assertEqual(linked, {"A", "B"})

    def test_add_registry_record_writes_kind(self):
        from unittest.mock import patch as _p, MagicMock
        from dart_risk_mcp.core.known_actors import add_registry_record
        resp = MagicMock()
        resp.status_code = 200
        with _p("dart_risk_mcp.core.known_actors.requests.post",
                return_value=resp) as post:
            add_registry_record("아레스1호투자조합",
                                {"source": "자동 발굴", "evidence": "e", "kind": "조합"},
                                token="t", db_id="db")
        payload = post.call_args.kwargs["json"]
        self.assertEqual(payload["properties"]["구분"]["select"]["name"], "조합")

    # ── 2026-07-29 사고 대응: 재시도 + 진단 로그 ──────────────────────
    # 4/5건 성공(=레이트리밋 패턴)이 "자격증명 확인 필요"로 오진단됐다.
    # add_registry_record는 상태코드·오류를 삼키고 True/False만 반환했고
    # 429 재시도도 없었다. 아래는 그 결함을 재현하는 실패 테스트다.

    def test_notion_credentials_configured_reflects_env(self):
        import os
        from unittest.mock import patch as _p
        from dart_risk_mcp.core.known_actors import notion_credentials_configured
        with _p.dict(os.environ, {"NOTION_TOKEN": "t", "DB_KNOWN_ACTORS": "db"}):
            self.assertTrue(notion_credentials_configured())
        with _p.dict(os.environ, {}, clear=False):
            for k in ("NOTION_TOKEN", "DB_KNOWN_ACTORS"):
                os.environ.pop(k, None)
            self.assertFalse(notion_credentials_configured())

    def test_add_registry_record_retries_on_429_then_succeeds(self):
        """레이트리밋(429) 1회 후 200이면 재시도로 성공해야 한다 — 이게
        오늘 사고(4/5건 성공)의 실제 원인일 가능성이 높다."""
        from unittest.mock import patch as _p, MagicMock
        from dart_risk_mcp.core import known_actors as ka
        resp429 = MagicMock(status_code=429, headers={})
        resp200 = MagicMock(status_code=200, headers={})
        with _p("dart_risk_mcp.core.known_actors.requests.post",
                side_effect=[resp429, resp200]) as post, \
                _p.object(ka.time, "sleep") as sleep:
            ok = ka.add_registry_record(
                "홍길동", {"source": "s", "evidence": "e"}, token="t", db_id="db")
        self.assertTrue(ok)
        self.assertEqual(post.call_count, 2)
        sleep.assert_called()  # 백오프 없이 즉시 재시도하면 안 됨

    def test_add_registry_record_honors_retry_after_header(self):
        """Notion이 Retry-After를 주면 그 값을 대기 시간으로 써야 한다
        (DART용 dart_client._retry는 이 헤더를 보지 않으므로 별도 구현 필요)."""
        from unittest.mock import patch as _p, MagicMock
        from dart_risk_mcp.core import known_actors as ka
        resp429 = MagicMock(status_code=429, headers={"Retry-After": "1.5"})
        resp200 = MagicMock(status_code=200, headers={})
        with _p("dart_risk_mcp.core.known_actors.requests.post",
                side_effect=[resp429, resp200]), \
                _p.object(ka.time, "sleep") as sleep:
            ok = ka.add_registry_record(
                "홍길동", {"source": "s", "evidence": "e"}, token="t", db_id="db")
        self.assertTrue(ok)
        sleep.assert_called_once_with(1.5)

    def test_add_registry_record_exhausts_retries_returns_false_and_logs_diagnosis(self):
        """재시도를 모두 소진해도 예외를 전파하지 않고 False를 반환하되,
        상태코드와 Notion 오류 메시지를 로그로 남겨야 한다(사고 당시엔
        아무 근거도 안 남아 원인을 알 수 없었다)."""
        from unittest.mock import patch as _p, MagicMock
        from dart_risk_mcp.core import known_actors as ka
        resp = MagicMock(status_code=429, headers={})
        resp.json.return_value = {"code": "rate_limited", "message": "너무 빠릅니다"}
        with _p("dart_risk_mcp.core.known_actors.requests.post",
                return_value=resp) as post, \
                _p.object(ka.time, "sleep"), \
                self.assertLogs("dart_risk_mcp.core.known_actors", level="WARNING") as logs:
            ok = ka.add_registry_record(
                "홍길동", {"source": "s", "evidence": "e"}, token="t", db_id="db")
        self.assertFalse(ok)
        self.assertEqual(post.call_count, 3)  # 최대 3회, dart_client._retry와 동일 정책
        joined = "\n".join(logs.output)
        self.assertIn("429", joined)
        self.assertIn("rate_limited", joined)

    def test_add_registry_record_network_exception_exhausted_returns_false(self):
        """네트워크 예외가 재시도를 모두 소진해도 호출측에 전파되면 안 된다
        (레지스트리 코드는 예외를 삼킨다는 저장소 원칙)."""
        from unittest.mock import patch as _p
        import requests as _requests
        from dart_risk_mcp.core import known_actors as ka
        with _p("dart_risk_mcp.core.known_actors.requests.post",
                side_effect=_requests.exceptions.ConnectionError("boom")) as post, \
                _p.object(ka.time, "sleep"):
            ok = ka.add_registry_record(
                "홍길동", {"source": "s", "evidence": "e"}, token="t", db_id="db")
        self.assertFalse(ok)
        self.assertEqual(post.call_count, 3)

    def test_add_registry_record_error_log_omits_notion_message_entirely(self):
        """Notion 오류 message는 검증 실패 시 문제가 된 값을 인용하는 사례가
        있다. 이 레포는 public이고 Actions 로그도 public이며 레지스트리는
        실명 데이터이므로 **자유 텍스트를 통째로 남기지 않는다.**

        길이 제한으로는 부족하다 — 이름이 메시지 앞부분에 오면 잘라도 남는다.
        조치는 code(고정 enum)만으로 정해지므로 그것만 남긴다."""
        from unittest.mock import patch as _p, MagicMock
        from dart_risk_mcp.core import known_actors as ka
        leaked_name = "홍길동"
        leaked_company = "주식회사에코"
        message = f"body.properties.관련기업 should be defined, got {leaked_name}/{leaked_company}"
        resp = MagicMock(status_code=400, headers={})
        resp.json.return_value = {"code": "validation_error", "message": message}
        with _p("dart_risk_mcp.core.known_actors.requests.post",
                return_value=resp), \
                self.assertLogs("dart_risk_mcp.core.known_actors", level="WARNING") as logs:
            ok = ka.add_registry_record(
                leaked_name, {"source": "s", "evidence": "e",
                              "companies": [leaked_company]},
                token="t", db_id="db")
        self.assertFalse(ok)
        joined = "\n".join(logs.output)
        # 조치에 필요한 것은 남는다
        self.assertIn("400", joined)
        self.assertIn("validation_error", joined)
        # 실명·회사명은 어디에도 남지 않는다 — 메시지 앞부분이어도 마찬가지
        self.assertNotIn(leaked_name, joined)
        self.assertNotIn(leaked_company, joined)
        self.assertNotIn("should be defined", joined)

    def test_add_registry_record_other_exception_returns_false_without_raising(self):
        """레코드 형태가 예상과 달라 내부에서 예외가 나도(예: build_change_summary
        가 아니라 props 조립 단계) 호출측에는 전파되지 않고 False만 온다."""
        from dart_risk_mcp.core.known_actors import add_registry_record
        # companies가 문자열 슬라이스 불가능한 값이면 내부 처리에서 예외가 남
        ok = add_registry_record(
            "홍길동", {"source": "s", "evidence": "e", "companies": [123, 456]},
            token="t", db_id="db")
        self.assertFalse(ok)

    def test_lookup_merges_records_across_html_entity_duplicate_keys(self):
        # 실측 사고 재현: 파싱 오류로 같은 실체가 '삼성전자 주식회사'와
        # '삼성전자 &CR;주식회사' 두 키로 저장됨. normalize_name은 이미 두 키를
        # 같은 값으로 접지만(고치지 않는다), lookup_actor는 정확 키 일치에서
        # 즉시 반환해 다른 키의 기록을 놓쳤다. 두 표기 어느 쪽으로 조회해도
        # 합산 3건이 나와야 한다.
        from dart_risk_mcp.core.known_actors import lookup_actor
        self._write({"version": 1, "actors": {
            "삼성전자 주식회사": [
                {"source": "CB 인수", "evidence": "e1", "rcept_no": "R1"},
            ],
            "삼성전자 &CR;주식회사": [
                {"source": "CB 인수", "evidence": "e2", "rcept_no": "R2"},
                {"source": "CB 인수", "evidence": "e3", "rcept_no": "R3"},
            ],
        }})
        recs_plain = lookup_actor("삼성전자 주식회사")
        recs_entity = lookup_actor("삼성전자 &CR;주식회사")
        self.assertEqual(len(recs_plain), 3)
        self.assertEqual(len(recs_entity), 3)
        self.assertEqual({r["rcept_no"] for r in recs_plain}, {"R1", "R2", "R3"})
        self.assertEqual({r["rcept_no"] for r in recs_entity}, {"R1", "R2", "R3"})

    def test_lookup_dedupes_identical_records_across_keys(self):
        # 같은 키가 정확 일치·정규화 일치 양쪽에 걸리므로 그대로 합치면
        # 기록이 겹친다 — 필드 전체가 같은 기록은 한 번만 반환한다.
        from dart_risk_mcp.core.known_actors import lookup_actor
        rec = {"source": "CB 인수", "evidence": "동일 근거", "rcept_no": "R1"}
        self._write({"version": 1, "actors": {
            "케이파트너스 주식회사": [dict(rec)],
            "케이파트너스&CR;주식회사": [dict(rec)],
        }})
        recs = lookup_actor("케이파트너스 주식회사")
        self.assertEqual(len(recs), 1)

    def test_lookup_keeps_records_with_same_evidence_but_different_rcept(self):
        # 근거 텍스트가 같아도 접수번호가 다르면 서로 다른 공시(별개 근거)이므로
        # 중복으로 접지 않는다 — 판정 기준은 필드 전체 일치.
        from dart_risk_mcp.core.known_actors import lookup_actor
        self._write({"version": 1, "actors": {
            "삼성전자 주식회사": [
                {"source": "CB 인수", "evidence": "같은 문구", "rcept_no": "R1"},
            ],
            "삼성전자 &CR;주식회사": [
                {"source": "CB 인수", "evidence": "같은 문구", "rcept_no": "R2"},
            ],
        }})
        recs = lookup_actor("삼성전자 주식회사")
        self.assertEqual(len(recs), 2)
        self.assertEqual({r["rcept_no"] for r in recs}, {"R1", "R2"})

    def test_lookup_deterministic_order_across_calls(self):
        from dart_risk_mcp.core.known_actors import lookup_actor
        self._write({"version": 1, "actors": {
            "삼성전자 주식회사": [
                {"source": "A", "evidence": "e1", "rcept_no": "R1"}],
            "삼성전자 &CR;주식회사": [
                {"source": "B", "evidence": "e2", "rcept_no": "R2"},
                {"source": "C", "evidence": "e3", "rcept_no": "R3"},
            ],
        }})
        first = lookup_actor("삼성전자 주식회사")
        second = lookup_actor("삼성전자 주식회사")
        self.assertEqual(first, second)

    def test_lookup_does_not_merge_distinct_normalized_entities(self):
        # 정규화해도 다른 실체인 두 인물은 합쳐지지 않는다.
        from dart_risk_mcp.core.known_actors import lookup_actor
        self._write({"version": 1, "actors": {
            "홍길동": [{"source": "A", "evidence": "e1"}],
            "김철수": [{"source": "B", "evidence": "e2"}],
        }})
        recs = lookup_actor("홍길동")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["source"], "A")

    def test_lookup_by_company_unaffected_by_entity_duplicate_keys(self):
        # lookup_actors_by_company는 이미 전 키를 순회하므로 이 결함이 없다
        # — 같은 실체가 두 키에 나뉘어도 각 키의 태깅된 회사 기록을 정상 반환.
        from dart_risk_mcp.core.known_actors import lookup_actors_by_company
        self._write({"version": 1, "actors": {
            "삼성전자 주식회사": [
                {"source": "A", "evidence": "e1", "companies": ["A전자"]}],
            "삼성전자 &CR;주식회사": [
                {"source": "B", "evidence": "e2", "companies": ["A전자"]}],
        }})
        hits = lookup_actors_by_company("A전자")
        self.assertEqual(len(hits), 2)
        self.assertEqual([n for n, _ in hits],
                         sorted(["삼성전자 주식회사", "삼성전자 &CR;주식회사"]))

    def test_lookup_by_company_matches(self):
        from dart_risk_mcp.core.known_actors import lookup_actors_by_company
        self._write({"version": 1, "actors": {
            "신승수": [
                {"source": "DART 임원현황", "evidence": "CG인바이츠 등기임원",
                 "date": "2024", "status": "verified",
                 "companies": ["CG인바이츠", "이엠앤아이"]},
                {"source": "CB 인수", "evidence": "티쓰리 CB",
                 "date": "2023", "status": "verified", "companies": ["티쓰리"]},
            ],
            "이호영": [
                {"source": "DART 임원현황", "evidence": "이엠앤아이 등기임원",
                 "date": "2024", "status": "auto_matched",
                 "companies": ["이엠앤아이"]},
            ],
        }})
        hits = lookup_actors_by_company("이엠앤아이")
        # 인물명 오름차순, 해당 회사가 태깅된 기록만
        self.assertEqual([(n, r["source"]) for n, r in hits],
                         [("신승수", "DART 임원현황"), ("이호영", "DART 임원현황")])

    def test_lookup_by_company_normalized_match(self):
        from dart_risk_mcp.core.known_actors import lookup_actors_by_company
        self._write({"version": 1, "actors": {
            "LIU HUAN": [{"source": "자동 발굴", "evidence": "e",
                          "companies": ["ABC Holdings"]}],
        }})
        self.assertEqual(len(lookup_actors_by_company("abc  holdings")), 1)

    def test_lookup_by_company_no_match_or_blank(self):
        from dart_risk_mcp.core.known_actors import lookup_actors_by_company
        self._write({"version": 1, "actors": {
            "신승수": [{"source": "X", "evidence": "y", "companies": ["티쓰리"]}],
            "구기록": [{"source": "X", "evidence": "y"}],  # companies 필드 없는 구 기록
        }})
        self.assertEqual(lookup_actors_by_company("없는회사"), [])
        self.assertEqual(lookup_actors_by_company(""), [])
        self.assertEqual(lookup_actors_by_company("   "), [])

    def test_lookup_by_company_empty_registry(self):
        from dart_risk_mcp.core.known_actors import lookup_actors_by_company
        self._write({"version": 1, "actors": {}})
        self.assertEqual(lookup_actors_by_company("티쓰리"), [])

    # ── SE-5b Task 2: 읽기 단계 기관 필터 ────────────────────────────
    # 실측(2026-07-29)에서 should_store가 거부하는 12명이 전부 auto_matched뿐인
    # 채로 레지스트리 상위를 독점했다. 읽기 경로(load_known_actors)에서
    # should_store를 적용해 그 노이즈를 걷어낸다. 사람이 넣은 기록
    # (verified/maintainer_seed)은 어떤 경우에도 남긴다.

    _NH_INSTITUTION = (
        "엔에이치투자증권 주식회사 "
        "(밸류시스템 코스닥벤처FAST 전문투자형 사모투자신탁의 신탁업자 지위에서)"
    )

    def test_load_filters_institution_with_only_auto_matched(self):
        # 브리프 시나리오 1: 기관 + auto_matched만 → 제외된다
        from dart_risk_mcp.core.known_actors import load_known_actors
        self._write({"version": 1, "actors": {
            self._NH_INSTITUTION: [
                {"source": "자동 발굴", "evidence": "e", "status": "auto_matched"}],
        }})
        data = load_known_actors()
        self.assertNotIn(self._NH_INSTITUTION, data["actors"])

    def test_load_keeps_non_institution_auto_matched(self):
        # 브리프 시나리오 2: 기관이 아닌 실체 + auto_matched → 남는다
        from dart_risk_mcp.core.known_actors import load_known_actors
        self._write({"version": 1, "actors": {
            "시너지파트너스 주식회사": [
                {"source": "자동 발굴", "evidence": "e", "status": "auto_matched"}],
        }})
        data = load_known_actors()
        self.assertIn("시너지파트너스 주식회사", data["actors"])

    def test_load_keeps_institution_with_maintainer_seed(self):
        # 브리프 시나리오 3: 같은 기관명 + maintainer_seed → 남는다(사람이 넣었다)
        from dart_risk_mcp.core.known_actors import load_known_actors
        self._write({"version": 1, "actors": {
            self._NH_INSTITUTION: [
                {"source": "제작자 등록", "evidence": "e", "status": "maintainer_seed"}],
        }})
        data = load_known_actors()
        self.assertIn(self._NH_INSTITUTION, data["actors"])

    def test_load_filters_institution_with_blank_status(self):
        # 브리프 시나리오 4: 같은 기관명 + status: "" → 제외된다
        # (빈 값은 화이트리스트 밖 → 기계 등재로 강등, 옛 SE _actor_status와
        # 동일 원칙. status: "auto_matched"와 정확히 같아야만 통과하는 판정이면
        # 빈 문자열이 "사람이 넣은 것"으로 잘못 분류돼 살아남는다.)
        from dart_risk_mcp.core.known_actors import load_known_actors
        self._write({"version": 1, "actors": {
            self._NH_INSTITUTION: [
                {"source": "자동 발굴", "evidence": "e", "status": ""}],
        }})
        data = load_known_actors()
        self.assertNotIn(self._NH_INSTITUTION, data["actors"])

    def test_load_keeps_institution_with_any_verified_record(self):
        # 브리프 시나리오 5: 기록 2건 중 하나가 verified면 → 남는다
        from dart_risk_mcp.core.known_actors import load_known_actors
        self._write({"version": 1, "actors": {
            self._NH_INSTITUTION: [
                {"source": "자동 발굴", "evidence": "e1", "status": "auto_matched"},
                {"source": "확인", "evidence": "e2", "status": "verified"},
            ],
        }})
        data = load_known_actors()
        self.assertIn(self._NH_INSTITUTION, data["actors"])
        # 필터는 인물 단위 — 살아남은 인물의 기록 자체는 지우지 않는다
        self.assertEqual(len(data["actors"][self._NH_INSTITUTION]), 2)

    def test_lookup_actor_excludes_filtered_institution(self):
        # 브리프 시나리오 6: lookup_actor(기관명) → []
        from dart_risk_mcp.core.known_actors import lookup_actor
        self._write({"version": 1, "actors": {
            self._NH_INSTITUTION: [
                {"source": "자동 발굴", "evidence": "e", "status": "auto_matched"}],
        }})
        self.assertEqual(lookup_actor(self._NH_INSTITUTION), [])

    def test_lookup_by_company_excludes_filtered_institution(self):
        # 브리프 시나리오 7: lookup_actors_by_company 결과에도 그 인물이 없다
        from dart_risk_mcp.core.known_actors import lookup_actors_by_company
        self._write({"version": 1, "actors": {
            self._NH_INSTITUTION: [
                {"source": "자동 발굴", "evidence": "e", "status": "auto_matched",
                 "companies": ["아무회사"]}],
        }})
        hits = lookup_actors_by_company("아무회사")
        self.assertEqual([n for n, _ in hits], [])

    # ── SE-5b Part A: 폴딩 티어까지 병합 ────────────────────────────
    # 실측(2026-07-29): '(주)베이트리'(1건·회사7개)와 '주식회사 베이트리'
    # (2건·회사6개)는 normalize_name은 다르지만(법인 접사 정규화는
    # normalize_name이 아니라 fold_name의 몫) fold_variants 교집합은 같다
    # ({'베이트리'}). 그런데 lookup_actor는 정규화(normalize) 티어에서
    # 매칭이 있으면 즉시 반환해 폴딩 티어로 내려가지 않아, 조회 표기에 따라
    # 답이 갈렸다(Task 1이 없앤 것과 같은 결함이 한 티어 아래서 재발). 폴딩
    # 티어는 이미 "매칭 없을 때 답을 내는" 최종 권한을 가지므로, 답할 권한이
    # 있다면 병합할 권한도 있다고 본다 — 그래서 fold_keys를 조건부 폴백이
    # 아니라 항상 계산해 정규화 결과와 합집합으로 반환한다.
    #
    # 과잉 병합 경계: fold_name은 법인 접사·공백·구두점 제거 + 라틴 음차뿐
    # 이라 "완전한 문자열"이 일치해야 교집합이 생긴다 — 접사를 떼도 나머지
    # 글자가 다른 서로 다른 실체는 교집합이 생기지 않는다
    # (test_lookup_fold_tier_does_not_merge_similar_but_distinct_entities로
    # 고정).
    _BAETRI_CO = "(주)베이트리"
    _BAETRI_JUSIK = "주식회사 베이트리"

    def test_lookup_fold_tier_merges_corp_suffix_variant_keys(self):
        from dart_risk_mcp.core.known_actors import (
            lookup_actor, normalize_name, fold_variants)
        self._write({"version": 1, "actors": {
            self._BAETRI_CO: [
                {"source": "CB 인수", "evidence": "e1", "rcept_no": "R1",
                 "companies": ["가", "나", "다", "라", "마", "바", "사"]},
            ],
            self._BAETRI_JUSIK: [
                {"source": "CB 인수", "evidence": "e2", "rcept_no": "R2",
                 "companies": ["가", "나", "다"]},
                {"source": "CB 인수", "evidence": "e3", "rcept_no": "R3",
                 "companies": ["라", "마", "바"]},
            ],
        }})
        # 전제 확인: 실측대로 normalize_name은 다르고 fold_variants는 겹친다
        self.assertNotEqual(normalize_name(self._BAETRI_CO),
                             normalize_name(self._BAETRI_JUSIK))
        self.assertTrue(
            set(fold_variants(normalize_name(self._BAETRI_CO)))
            & set(fold_variants(normalize_name(self._BAETRI_JUSIK))))

        for query in (self._BAETRI_CO, self._BAETRI_JUSIK):
            recs = lookup_actor(query)
            self.assertEqual(len(recs), 3, f"query={query!r}")
            companies = {c for r in recs for c in r.get("companies", [])}
            self.assertEqual(companies, {"가", "나", "다", "라", "마", "바", "사"})

    def test_lookup_fold_tier_merge_dedupes_and_is_deterministic(self):
        from dart_risk_mcp.core.known_actors import lookup_actor
        rec = {"source": "CB 인수", "evidence": "동일 근거", "rcept_no": "R1"}
        self._write({"version": 1, "actors": {
            self._BAETRI_CO: [dict(rec)],
            self._BAETRI_JUSIK: [
                dict(rec),  # 다른 키에 완전히 동일한 레코드 — 1회만 반환돼야 함
                {"source": "CB 인수", "evidence": "e2", "rcept_no": "R2"},
            ],
        }})
        first = lookup_actor(self._BAETRI_CO)
        second = lookup_actor(self._BAETRI_JUSIK)
        self.assertEqual(len(first), 2)  # 중복 1건 dedup + 별개 R2
        self.assertEqual(first, second)  # 어느 표기로 조회해도 동일 + 결정적

    def test_lookup_fold_tier_does_not_merge_similar_but_distinct_entities(self):
        # 과잉 병합 경계: 접사를 떼도 나머지 글자가 다르면 fold도 갈린다 —
        # '베이트리'와 '베이트리무역'은 같은 실체가 아니므로 합쳐지면 안 된다.
        from dart_risk_mcp.core.known_actors import lookup_actor
        self._write({"version": 1, "actors": {
            "(주)베이트리": [{"source": "A", "evidence": "e1"}],
            "주식회사 베이트리무역": [{"source": "B", "evidence": "e2"}],
        }})
        recs = lookup_actor("(주)베이트리")
        self.assertEqual(len(recs), 1)
        self.assertEqual(recs[0]["source"], "A")

    def test_load_filter_does_not_over_delete(self):
        # 브리프 시나리오 8: 필터 적용 후에도 나머지 인물 수가 그대로다
        # (과잉 삭제 방어) — 기관 1명만 제외되고 개인·조합·법인 3명은 그대로.
        from dart_risk_mcp.core.known_actors import load_known_actors
        self._write({"version": 1, "actors": {
            self._NH_INSTITUTION: [
                {"source": "자동 발굴", "evidence": "e", "status": "auto_matched"}],
            "홍길동": [{"source": "s", "evidence": "e", "status": "auto_matched"}],
            "아레스1호투자조합": [{"source": "s", "evidence": "e", "status": "auto_matched"}],
            "(주)베이트리": [{"source": "s", "evidence": "e", "status": "auto_matched"}],
        }})
        data = load_known_actors()
        self.assertEqual(
            set(data["actors"].keys()),
            {"홍길동", "아레스1호투자조합", "(주)베이트리"})
        self.assertEqual(len(data["actors"]), 3)

    # ── 최종 리뷰 Finding 1: actor_status 화이트리스트 판정 통합 ──────────
    # 두 군데(known_actors._filter_institutions,
    # server.py 인라인 3곳)에 흩어져 있던 status 판정을 이 함수 하나로
    # 합쳤다. 빈 문자열·None·미지 값이 전부 "auto_matched"로 강등되는지를
    # 이 함수 자체에서 고정한다 — 라우팅 지점 각각의 렌더 테스트는
    # test_lookup_known_actor.py·test_registry_company_section.py·
    # test_find_actor_overlap.py에 있다.

    def test_actor_status_blank_string_is_auto_matched(self):
        from dart_risk_mcp.core.known_actors import actor_status
        self.assertEqual(actor_status({"status": ""}), "auto_matched")

    def test_actor_status_missing_key_is_auto_matched(self):
        from dart_risk_mcp.core.known_actors import actor_status
        self.assertEqual(actor_status({}), "auto_matched")

    def test_actor_status_none_is_auto_matched(self):
        from dart_risk_mcp.core.known_actors import actor_status
        self.assertEqual(actor_status({"status": None}), "auto_matched")

    def test_actor_status_unknown_string_is_auto_matched(self):
        from dart_risk_mcp.core.known_actors import actor_status
        self.assertEqual(actor_status({"status": "오타"}), "auto_matched")

    def test_actor_status_non_string_is_auto_matched(self):
        # 리스트/딕셔너리 같은 해시 불가 타입이 와도 죽지 않고 강등한다.
        from dart_risk_mcp.core.known_actors import actor_status
        self.assertEqual(actor_status({"status": ["auto_matched"]}), "auto_matched")

    def test_actor_status_valid_values_pass_through(self):
        from dart_risk_mcp.core.known_actors import actor_status
        for v in ("verified", "maintainer_seed", "auto_matched"):
            self.assertEqual(actor_status({"status": v}), v)

    # ── 최종 리뷰 Finding 4: 손글씨 레지스트리의 malformed 기록 값이
    # TypeError로 죽지 않는다 ────────────────────────────────────────────
    # {"actors": {"이름": null}}처럼 기록 목록 자리에 리스트가 아닌 값이
    # 오면 `for r in recs`(recs=None)가 'NoneType' object is not iterable로
    # 죽었다. 파일이 없거나 형태가 다를 때(_valid 검사 실패)는 이미 조용히
    # 빈 레지스트리로 저하하는데, "최상위는 맞는데 개별 항목만 이상한" 경우는
    # 그 가드를 통과해 죽었다 — 이 저장소 원칙(로딩은 예외를 전파하지 않는다)
    # 에 어긋난다.

    def test_load_does_not_crash_on_null_record_list(self):
        from dart_risk_mcp.core.known_actors import load_known_actors
        self._write({"version": 1, "actors": {"이상한기록": None}})
        data = load_known_actors()  # TypeError를 던지면 안 된다
        self.assertEqual(data["actors"].get("이상한기록"), [])

    def test_lookup_actor_does_not_crash_on_null_record_list(self):
        from dart_risk_mcp.core.known_actors import lookup_actor
        self._write({"version": 1, "actors": {"이상한기록": None}})
        self.assertEqual(lookup_actor("이상한기록"), [])

    def test_lookup_by_company_does_not_crash_on_null_record_list(self):
        from dart_risk_mcp.core.known_actors import lookup_actors_by_company
        self._write({"version": 1, "actors": {"이상한기록": None}})
        self.assertEqual(lookup_actors_by_company("아무회사"), [])

    def test_load_does_not_crash_on_null_record_list_for_institution(self):
        # 기관명 + malformed 값 조합 — should_store가 거부하는 경로도 동시에
        # 통과해야 한다(레코드가 없으니 verified/maintainer_seed 예외도 없어
        # 보수적으로 제외되는 것이 맞는 동작).
        from dart_risk_mcp.core.known_actors import load_known_actors
        self._write({"version": 1, "actors": {self._NH_INSTITUTION: None}})
        data = load_known_actors()
        self.assertNotIn(self._NH_INSTITUTION, data["actors"])

    # ── SE-5c Task 1: 주입 레지스트리 캐시 시임 ─────────────────────────
    # dart_client.py의 _http_cache/set_http_cache/get_http_cache를 그대로
    # 본뜬 패턴. 외부 소비자가 Notion 직전에 캐시를 주입할 수 있다.
    #
    # 저장 시점 결정 — **필터(_filter_institutions/should_store) 적용 전**
    # 데이터를 캐시한다. 이유:
    #   1) 기존 파일 캐시(_CACHE_FILE)가 이미 필터 전(raw) 데이터를 저장하고
    #      있다 — 주입 캐시가 필터 후를 저장하면 두 캐시의 저장 정책이
    #      갈라져 "같은 자리에서 캐시 하나 더"라는 설계 취지가 깨진다.
    #   2) load_known_actors()는 호출마다 _filter_institutions를 다시
    #      적용하는 구조다. 그 비용은 최대 1,270개 dict 항목을 순회하는
    #      순수 in-memory 연산이라 Notion 15회 왕복(15초)에 비해 무시할
    #      수 있다.
    #   3) 반대로 필터 후를 캐시하면 should_store 규칙이 바뀌어도 캐시가
    #      최대 24시간(_CACHE_TTL) 동안 옛 규칙의 결과를 그대로 물고 있게
    #      된다 — 필터 규칙 변경은 배포 즉시 반영돼야 한다.

    class _FakeRegistryCache:
        """get_json/put_json 두 메서드만 요구하는 최소 캐시 더블."""

        def __init__(self, preload=None, get_exc=None, put_exc=None):
            self.preload = preload
            self.get_exc = get_exc
            self.put_exc = put_exc
            self.gets = []
            self.puts = []

        def get_json(self, key):
            self.gets.append(key)
            if self.get_exc:
                raise self.get_exc
            return self.preload

        def put_json(self, key, value, ttl_seconds):
            self.puts.append((key, value, ttl_seconds))
            if self.put_exc:
                raise self.put_exc

    def _notion_success_resp(self, name, status="verified"):
        from unittest.mock import MagicMock
        resp = MagicMock()
        resp.status_code = 200
        resp.json.return_value = {
            "results": [self._notion_page(name, status=status)],
            "has_more": False,
        }
        return resp

    def test_registry_cache_default_is_none(self):
        from dart_risk_mcp.core.known_actors import get_registry_cache
        self.assertIsNone(get_registry_cache())

    def test_no_cache_injected_behaves_like_before(self):
        # 검증 1: 캐시 미주입 시 지금과 동일 — Notion을 정상 호출한다
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch as _p
        from dart_risk_mcp.core import known_actors as ka
        self._env.stop()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cache_file = Path(tmp) / "notion.json"
                resp = self._notion_success_resp("홍길동")
                with _p("dart_risk_mcp.core.known_actors._CACHE_FILE", cache_file), \
                     _p("dart_risk_mcp.core.known_actors.requests.post",
                        return_value=resp) as post, \
                     _p.dict("os.environ", {"NOTION_TOKEN": "t", "DB_KNOWN_ACTORS": "db"}):
                    os.environ.pop("DART_KNOWN_ACTORS_PATH", None)
                    self.assertIsNone(ka.get_registry_cache())
                    data = ka.load_known_actors()
                post.assert_called_once()
                self.assertIn("홍길동", data["actors"])
        finally:
            self._env.start()

    def test_cache_hit_skips_notion(self):
        # 검증 2: 캐시에 유효한 레지스트리가 있으면 Notion을 한 번도 부르지 않는다
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch as _p
        from dart_risk_mcp.core import known_actors as ka
        preload = {"version": 1, "actors": {
            "홍길동": [{"source": "s", "evidence": "e", "status": "verified"}]}}
        cache = self._FakeRegistryCache(preload=preload)
        self._env.stop()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cache_file = Path(tmp) / "notion.json"  # 미존재 → 신선 파일캐시 없음
                with _p("dart_risk_mcp.core.known_actors._CACHE_FILE", cache_file), \
                     _p("dart_risk_mcp.core.known_actors.requests.post") as post, \
                     _p.dict("os.environ", {"NOTION_TOKEN": "t", "DB_KNOWN_ACTORS": "db"}):
                    os.environ.pop("DART_KNOWN_ACTORS_PATH", None)
                    ka.set_registry_cache(cache)
                    try:
                        data = ka.load_known_actors()
                    finally:
                        ka.set_registry_cache(None)
                post.assert_not_called()
                self.assertIn("홍길동", data["actors"])
        finally:
            self._env.start()

    def test_cache_miss_calls_notion_and_stores_pre_filter_data(self):
        # 검증 3: 캐시가 비어 있으면 Notion을 부르고, 그 결과를 캐시에 쓴다
        # (필터 적용 전 원본을 쓴다 — 위 저장 시점 결정 참고)
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch as _p
        from dart_risk_mcp.core import known_actors as ka
        cache = self._FakeRegistryCache(preload=None)
        resp = self._notion_success_resp("홍길동")
        self._env.stop()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cache_file = Path(tmp) / "notion.json"
                with _p("dart_risk_mcp.core.known_actors._CACHE_FILE", cache_file), \
                     _p("dart_risk_mcp.core.known_actors.requests.post",
                        return_value=resp) as post, \
                     _p.dict("os.environ", {"NOTION_TOKEN": "t", "DB_KNOWN_ACTORS": "db"}):
                    os.environ.pop("DART_KNOWN_ACTORS_PATH", None)
                    ka.set_registry_cache(cache)
                    try:
                        data = ka.load_known_actors()
                    finally:
                        ka.set_registry_cache(None)
                post.assert_called_once()
                self.assertEqual(len(cache.puts), 1)
                key, value, ttl = cache.puts[0]
                self.assertEqual(ttl, ka._CACHE_TTL)
                self.assertIn("홍길동", value["actors"])
                self.assertIn("홍길동", data["actors"])
        finally:
            self._env.start()

    def test_cache_broken_shape_falls_back_to_notion(self):
        # 검증 4: 캐시가 깨진 형태를 돌려주면 무시하고 Notion으로 간다
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch as _p
        from dart_risk_mcp.core import known_actors as ka
        cache = self._FakeRegistryCache(preload={"actors": "문자열"})
        resp = self._notion_success_resp("홍길동")
        self._env.stop()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cache_file = Path(tmp) / "notion.json"
                with _p("dart_risk_mcp.core.known_actors._CACHE_FILE", cache_file), \
                     _p("dart_risk_mcp.core.known_actors.requests.post",
                        return_value=resp) as post, \
                     _p.dict("os.environ", {"NOTION_TOKEN": "t", "DB_KNOWN_ACTORS": "db"}):
                    os.environ.pop("DART_KNOWN_ACTORS_PATH", None)
                    ka.set_registry_cache(cache)
                    try:
                        data = ka.load_known_actors()
                    finally:
                        ka.set_registry_cache(None)
                post.assert_called_once()
                self.assertIn("홍길동", data["actors"])
        finally:
            self._env.start()

    def test_cache_get_exception_falls_back_to_notion(self):
        # 검증 5: get_json이 예외를 던져도 예외가 밖으로 안 나가고 Notion으로 폴백
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch as _p
        from dart_risk_mcp.core import known_actors as ka
        cache = self._FakeRegistryCache(get_exc=RuntimeError("cache down"))
        resp = self._notion_success_resp("홍길동")
        self._env.stop()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cache_file = Path(tmp) / "notion.json"
                with _p("dart_risk_mcp.core.known_actors._CACHE_FILE", cache_file), \
                     _p("dart_risk_mcp.core.known_actors.requests.post",
                        return_value=resp) as post, \
                     _p.dict("os.environ", {"NOTION_TOKEN": "t", "DB_KNOWN_ACTORS": "db"}):
                    os.environ.pop("DART_KNOWN_ACTORS_PATH", None)
                    ka.set_registry_cache(cache)
                    try:
                        data = ka.load_known_actors()
                    finally:
                        ka.set_registry_cache(None)
                post.assert_called_once()
                self.assertIn("홍길동", data["actors"])
        finally:
            self._env.start()

    def test_cache_put_exception_load_still_succeeds(self):
        # 검증 6: put_json이 예외를 던져도 로드는 성공한다
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch as _p
        from dart_risk_mcp.core import known_actors as ka
        cache = self._FakeRegistryCache(preload=None, put_exc=RuntimeError("cache down"))
        resp = self._notion_success_resp("홍길동")
        self._env.stop()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cache_file = Path(tmp) / "notion.json"
                with _p("dart_risk_mcp.core.known_actors._CACHE_FILE", cache_file), \
                     _p("dart_risk_mcp.core.known_actors.requests.post",
                        return_value=resp), \
                     _p.dict("os.environ", {"NOTION_TOKEN": "t", "DB_KNOWN_ACTORS": "db"}):
                    os.environ.pop("DART_KNOWN_ACTORS_PATH", None)
                    ka.set_registry_cache(cache)
                    try:
                        data = ka.load_known_actors()  # 예외가 밖으로 나가면 안 된다
                    finally:
                        ka.set_registry_cache(None)
                self.assertIn("홍길동", data["actors"])
        finally:
            self._env.start()

    def test_override_path_skips_injected_cache(self):
        # 검증 7: DART_KNOWN_ACTORS_PATH가 설정돼 있으면 캐시를 보지도 않는다
        from dart_risk_mcp.core import known_actors as ka
        self._write({"version": 1, "actors": {"X": [{"source": "s", "evidence": "e"}]}})
        cache = self._FakeRegistryCache(preload={"version": 1, "actors": {}})
        ka.set_registry_cache(cache)
        try:
            data = ka.load_known_actors()
        finally:
            ka.set_registry_cache(None)
        self.assertEqual(cache.gets, [])
        self.assertEqual(cache.puts, [])
        self.assertIn("X", data["actors"])

    def test_override_missing_file_does_not_fall_through_to_cache(self):
        """검증 7-b: 오버라이드 파일이 **없어도** 캐시로 흘러내리지 않는다.

        SE-5c 최종 리뷰 Finding 4 — 위 test_override_path_skips_injected_cache는
        오버라이드 파일이 존재하는 행복 경로만 고정한다. 파일이 없을 때
        `return`을 지우고 아래 캐시 경로로 흘려보내는 변형이 전체 스위트를
        통과해 버렸다. 오버라이드는 "이 JSON만 본다"는 명시적 선언이므로,
        비어 있는 결과가 나오더라도 다른 출처의 데이터가 섞이면 안 된다.
        """
        import os
        from pathlib import Path
        from dart_risk_mcp.core import known_actors as ka
        missing = Path(self._tmp.name) / "does-not-exist.json"
        self.assertFalse(missing.exists())
        os.environ["DART_KNOWN_ACTORS_PATH"] = str(missing)
        cache = self._FakeRegistryCache(preload={
            "version": 1, "actors": {"캐시인물": [{"source": "s", "evidence": "e"}]}})
        ka.set_registry_cache(cache)
        try:
            data, source = ka.load_known_actors_with_source()
        finally:
            ka.set_registry_cache(None)
        self.assertEqual(cache.gets, [])
        self.assertEqual(data, {"version": 1, "actors": {}})
        self.assertEqual(source, "override")

    def test_override_malformed_file_does_not_fall_through_to_cache(self):
        """검증 7-c: 오버라이드 JSON이 깨져 있어도 캐시로 흘러내리지 않는다."""
        from pathlib import Path
        from dart_risk_mcp.core import known_actors as ka
        Path(self._path).write_text("{ not json ", encoding="utf-8")
        cache = self._FakeRegistryCache(preload={
            "version": 1, "actors": {"캐시인물": [{"source": "s", "evidence": "e"}]}})
        ka.set_registry_cache(cache)
        try:
            data, source = ka.load_known_actors_with_source()
        finally:
            ka.set_registry_cache(None)
        self.assertEqual(cache.gets, [])
        self.assertEqual(data, {"version": 1, "actors": {}})
        self.assertEqual(source, "override")

    def test_fresh_file_cache_wins_over_injected_cache(self):
        """검증 9: 신선한 파일 캐시가 있으면 주입 캐시를 **읽지도 않는다**.

        SE-5c 최종 리뷰 Finding 4 — 모듈 문서가 선언한 우선순위(파일 캐시 >
        주입 캐시)를 고정하는 테스트가 하나도 없었다. 두 블록의 순서를
        맞바꾸는 변형이 전체 스위트를 통과했다. 로컬 파일 읽기가 네트워크
        왕복보다 싸므로 이 순서는 의도된 것이다.
        """
        import json as _json
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch as _p
        from dart_risk_mcp.core import known_actors as ka
        file_data = {"version": 1, "actors": {
            "파일인물": [{"source": "s", "evidence": "e", "status": "verified"}]}}
        cache = self._FakeRegistryCache(preload={"version": 1, "actors": {
            "캐시인물": [{"source": "s", "evidence": "e", "status": "verified"}]}})
        self._env.stop()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cache_file = Path(tmp) / "notion.json"
                cache_file.write_text(_json.dumps(file_data, ensure_ascii=False),
                                      encoding="utf-8")  # 방금 썼으니 신선하다
                with _p("dart_risk_mcp.core.known_actors._CACHE_FILE", cache_file), \
                     _p("dart_risk_mcp.core.known_actors.requests.post") as post, \
                     _p.dict("os.environ", {"NOTION_TOKEN": "t", "DB_KNOWN_ACTORS": "db"}):
                    os.environ.pop("DART_KNOWN_ACTORS_PATH", None)
                    ka.set_registry_cache(cache)
                    try:
                        data, source = ka.load_known_actors_with_source()
                    finally:
                        ka.set_registry_cache(None)
                post.assert_not_called()
                self.assertEqual(cache.gets, [], "파일 캐시가 있으면 주입 캐시를 읽지 않는다")
                self.assertIn("파일인물", data["actors"])
                self.assertNotIn("캐시인물", data["actors"])
                self.assertEqual(source, "file")
        finally:
            self._env.start()

    def test_load_source_labels_each_path(self):
        """검증 10: 출처 라벨이 경로별로 정확하다(SE-5c 최종 리뷰 Finding 1b).

        SE 핸들러가 "opt-in인데 인물 0명"이라는 **추론** 대신 이 라벨을
        보고 실패를 판정한다 — 진짜로 비어 있는 레지스트리(부트스트랩)와
        조회 실패를 구분하는 유일한 근거다.
        """
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch as _p
        from dart_risk_mcp.core import known_actors as ka
        opt_in = {"NOTION_TOKEN": "t", "DB_KNOWN_ACTORS": "db"}
        self._env.stop()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                # 하위 케이스마다 별도 파일 경로를 쓴다 — Notion 성공 경로가
                # 파일 캐시를 채우므로 같은 경로를 재사용하면 다음 케이스가
                # 그 파일을 맞아 "file"이 나온다.
                def cache_file_for(n):
                    return Path(tmp) / f"notion{n}.json"  # 미존재 → 파일 캐시 없음

                # (1) 주입 캐시 적중 → "cache"
                cache_file = cache_file_for(1)
                cache = self._FakeRegistryCache(preload={"version": 1, "actors": {}})
                with _p("dart_risk_mcp.core.known_actors._CACHE_FILE", cache_file), \
                     _p.dict("os.environ", opt_in):
                    os.environ.pop("DART_KNOWN_ACTORS_PATH", None)
                    ka.set_registry_cache(cache)
                    try:
                        self.assertEqual(ka.load_known_actors_with_source()[1], "cache")
                    finally:
                        ka.set_registry_cache(None)

                # (2) Notion 조회 성공(인물 0명이어도) → "notion", bundled 아님
                cache_file = cache_file_for(2)
                empty_resp = self._notion_success_resp("홍길동")
                empty_resp.json.return_value = {"results": [], "has_more": False}
                with _p("dart_risk_mcp.core.known_actors._CACHE_FILE", cache_file), \
                     _p("dart_risk_mcp.core.known_actors.requests.post",
                        return_value=empty_resp), \
                     _p.dict("os.environ", opt_in):
                    os.environ.pop("DART_KNOWN_ACTORS_PATH", None)
                    data, source = ka.load_known_actors_with_source()
                self.assertEqual(source, "notion")
                self.assertEqual(data["actors"], {})

                # (3) Notion 실패 → "bundled" (opt-in인데 bundled = 조회 실패)
                cache_file = cache_file_for(3)
                fail_resp = self._notion_success_resp("홍길동")
                fail_resp.status_code = 500
                with _p("dart_risk_mcp.core.known_actors._CACHE_FILE", cache_file), \
                     _p("dart_risk_mcp.core.known_actors.requests.post",
                        return_value=fail_resp), \
                     _p.dict("os.environ", opt_in):
                    os.environ.pop("DART_KNOWN_ACTORS_PATH", None)
                    self.assertEqual(ka.load_known_actors_with_source()[1], "bundled")

                # (4) opt-in 미설정 → "bundled" (정상 상태)
                cache_file = cache_file_for(4)
                with _p("dart_risk_mcp.core.known_actors._CACHE_FILE", cache_file), \
                     _p.dict("os.environ", {}, clear=True):
                    self.assertEqual(ka.load_known_actors_with_source()[1], "bundled")
        finally:
            self._env.start()

    def test_registry_cache_key_has_no_credentials(self):
        # 검증 8: 캐시 키에 NOTION_TOKEN 값이 들어가지 않는다 (고정 문자열 키)
        import os
        import tempfile
        from pathlib import Path
        from unittest.mock import patch as _p
        from dart_risk_mcp.core import known_actors as ka
        cache = self._FakeRegistryCache(preload=None)
        resp = self._notion_success_resp("홍길동")
        secret_token = "secret-notion-token-xyz"
        self._env.stop()
        try:
            with tempfile.TemporaryDirectory() as tmp:
                cache_file = Path(tmp) / "notion.json"
                with _p("dart_risk_mcp.core.known_actors._CACHE_FILE", cache_file), \
                     _p("dart_risk_mcp.core.known_actors.requests.post",
                        return_value=resp), \
                     _p.dict("os.environ", {"NOTION_TOKEN": secret_token,
                                            "DB_KNOWN_ACTORS": "db"}):
                    os.environ.pop("DART_KNOWN_ACTORS_PATH", None)
                    ka.set_registry_cache(cache)
                    try:
                        ka.load_known_actors()
                    finally:
                        ka.set_registry_cache(None)
                seen_keys = cache.gets + [p[0] for p in cache.puts]
                self.assertTrue(seen_keys)
                for key in seen_keys:
                    self.assertNotIn(secret_token, str(key))
        finally:
            self._env.start()


if __name__ == "__main__":
    unittest.main()
