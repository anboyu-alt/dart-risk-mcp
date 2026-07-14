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


if __name__ == "__main__":
    unittest.main()
