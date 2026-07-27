"""SE 페이지 정적 검사.

이 페이지는 실명과 공시 원문을 그대로 표시하고, 사용자의 DART 키를
보관한다. 브라우저에서만 돌아가므로 파이썬 테스트로는 동작을 볼 수 없다 —
대신 **소스를 정적으로 검사**해 되돌아오면 안 되는 것들을 막는다.

`tests/se/test_vercel_bundle.py`와 같은 계열이다: 로컬에서는 아무 문제가
없어 보이지만 배포하면 깨지거나 새는 부류를 소스 대조로 잡는다.
"""
import pathlib
import re
import unittest

_ROOT = pathlib.Path(__file__).resolve().parent.parent.parent
_SE = _ROOT / "docs" / "tool" / "se"


def _sources() -> dict[str, str]:
    """검사 대상은 **브라우저가 실행하는 파일**뿐이다.

    `*.*`로 훑으면 Task 5의 README.md까지 걸려서, 안내 문서가 설명을 위해
    쓴 단어 때문에 테스트가 깨진다. 검사의 목적은 실행되는 코드를 막는
    것이지 문서를 검열하는 것이 아니다.
    """
    out = {}
    for pattern in ("*.html", "*.js"):
        for f in _SE.glob(pattern):
            out[f.name] = f.read_text(encoding="utf-8")
    return out


def _extract_function_body(src: str, name: str) -> str:
    """함수 선언(`function name(...) { ... }`, `async` 접두 포함)의 본문을
    중괄호 균형을 직접 세어 추출한다. 정규식만으로는 중첩된 `{}`를 정확히
    구분할 수 없어서다. 반환값은 여는/닫는 중괄호를 포함한다.
    """
    m = re.search(r"(?:async\s+)?function\s+" + re.escape(name) + r"\s*\([^)]*\)\s*{", src)
    if not m:
        raise AssertionError(f"함수 {name}을 찾지 못했습니다")
    start = m.end() - 1  # 여는 '{' 위치
    depth = 0
    for i in range(start, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[start:i + 1]
    raise AssertionError(f"함수 {name}의 닫는 중괄호를 찾지 못했습니다")


def _extract_braced_block(src: str, open_idx: int) -> str:
    """`open_idx`가 가리키는 여는 `{`부터 중괄호 균형이 맞는 지점까지
    추출한다(`_extract_function_body`와 같은 방식 — 중첩된 `{}`가 있어
    정규식만으로는 블록 경계를 정확히 못 잡는다). 반환값은 여는/닫는
    중괄호를 포함한다.
    """
    if src[open_idx] != "{":
        raise AssertionError(f"{open_idx} 위치가 '{{'가 아닙니다")
    depth = 0
    for i in range(open_idx, len(src)):
        if src[i] == "{":
            depth += 1
        elif src[i] == "}":
            depth -= 1
            if depth == 0:
                return src[open_idx:i + 1]
    raise AssertionError("닫는 중괄호를 찾지 못했습니다")


def _strip_js_comments(src: str) -> str:
    """`//`·`/* */` 주석을 지운다.

    이 저장소의 실제 소스에는 문자열 리터럴 안에 `//`가 등장하지 않으므로
    (URL은 전부 `+` 연결로 조립돼 있다 — `gotrue()` 참고) 이 단순한 정규식
    제거로 충분하다. "정의만 있고 호출은 없다"를 검사할 때 설명 주석 속에
    적힌 함수 이름("openActorPanel과 같은 이유" 같은 문구)이 실제 호출부로
    잘못 잡히는 것을 막기 위해 쓴다.
    """
    src = re.sub(r"/\*.*?\*/", "", src, flags=re.S)
    src = re.sub(r"//[^\n]*", "", src)
    return src


def _has_real_call_site(src: str, func_name: str) -> bool:
    """func_name의 함수 **선언**을 제외하고, 주석을 지운 소스에 실제 호출
    (`func_name(`)이 하나라도 남아 있는지 확인한다.

    단순 등장 횟수(`len(re.findall(...))>=2`)는 주석 한 줄에 함수 이름이
    한 번 더 언급되기만 해도 "호출부가 있다"고 착각한다 — 실제로 저장소에서
    한 번 발생한 사고다. 선언을 도려낸 뒤 나머지에서 호출 패턴을 찾는
    쪽이, 카운트만 세는 것보다 무엇을 "호출부"로 인정하는지 명확하다.
    """
    without_comments = _strip_js_comments(src)
    decl_pattern = re.compile(
        r"(?:async\s+)?function\s+" + re.escape(func_name) + r"\s*\([^)]*\)\s*\{"
    )
    without_decl = decl_pattern.sub("", without_comments, count=1)
    return re.search(re.escape(func_name) + r"\s*\(", without_decl) is not None


def _is_safe_html_literal(expr: str) -> bool:
    """HTML 싱크에 들어가는 값이 순수 문자열 리터럴인지 판정한다.

    변수·연결(+)·템플릿 치환(`${...}`)이 섞이면 안전하지 않다고 본다 —
    공시 원문·인물명 같은 사용자/외부 데이터가 그런 경로로 섞여 들어오면
    그 문자열 하나로 스크립트가 실행된다.
    """
    expr = expr.strip()
    if expr.endswith(";"):
        expr = expr[:-1].strip()
    if re.fullmatch(r'"([^"\\]|\\.)*"', expr):
        return True
    if re.fullmatch(r"'([^'\\]|\\.)*'", expr):
        return True
    if re.fullmatch(r"`([^`\\$]|\\.|\$(?!\{))*`", expr):
        return True
    return False


class TestPageExists(unittest.TestCase):
    """파일이 없으면 아래 정적 검사들이 전부 공허하게 통과한다.

    이 브랜치 계열에서 반복해서 나온 결함이 정확히 그 부류다 — 검사 대상에
    도달하지 못한 채 초록으로 보이는 것.
    """

    def test_expected_files_are_present(self):
        for name in ("index.html", "app.js", "ui.js"):
            self.assertTrue((_SE / name).exists(), f"{name}이 없습니다")


class TestNoExternalDependencies(unittest.TestCase):
    """빌드 스텝도 CDN도 없다 — 기존 공개 뷰어와 같은 방식이다."""

    def test_no_external_script_or_style(self):
        offenders = []
        for name, src in _sources().items():
            for m in re.finditer(r'<(?:script|link)[^>]*\b(?:src|href)="([^"]+)"', src):
                url = m.group(1)
                if url.startswith(("http://", "https://", "//")):
                    offenders.append(f"{name}: {url}")
        self.assertEqual(offenders, [],
                         "외부 스크립트·스타일을 불러오면 안 됩니다:\n  "
                         + "\n  ".join(offenders))

    def test_no_package_json_introduced(self):
        self.assertFalse((_ROOT / "package.json").exists(),
                         "npm 의존성을 도입하면 안 됩니다")


class TestNoSecretsInPage(unittest.TestCase):
    def test_no_service_key_or_jwt_literal(self):
        """service_role 키·JWT 리터럴이 소스에 박히면 안 된다.

        anon 키조차 하드코딩하지 않는다 — 런타임에 /api/se/config로 받는다.
        """
        for name, src in _sources().items():
            self.assertNotIn("service_role", src, f"{name}에 service_role 언급")
            self.assertNotIn("sb_secret_", src, f"{name}에 secret 키 접두어")
            self.assertNotRegex(src, r"eyJ[A-Za-z0-9_-]{20,}",
                                f"{name}에 JWT 리터럴로 보이는 문자열")

    def test_dart_key_is_sent_as_header_only(self):
        """쿼리스트링으로 보내면 URL 로그·리퍼러에 키가 남는다."""
        src = _sources()["ui.js"]
        self.assertIn("X-DART-Key", src)
        self.assertNotRegex(src, r"[?&](?:dart_key|crtfc_key|key)=",
                            "DART 키를 쿼리스트링에 실으면 안 됩니다")


class TestNoDataIntoInnerHtml(unittest.TestCase):
    """실명과 공시 원문이 그대로 들어오는 페이지다.

    데이터를 innerHTML에 넣으면 공시 원문 한 줄로 스크립트가 실행된다.
    정적 마크업을 넣는 innerHTML은 허용하되(리터럴만), 변수가 섞이면 막는다.

    innerHTML만 막으면 `insertAdjacentHTML`·`outerHTML`·`document.write`로
    똑같은 위험을 우회할 수 있어 네 가지 싱크를 모두 검사한다. 이 검사는
    현재 소스에 넷 다 없어 공허하게 통과하지만(가드레일), 앞으로 데이터가
    이 경로들 중 하나로 섞여 들어오는 것을 막는 회귀 방지 역할을 한다.
    """

    _SINKS = (
        ("innerHTML 대입", re.compile(r"\.innerHTML\s*=\s*(.+)")),
        ("outerHTML 대입", re.compile(r"\.outerHTML\s*=\s*(.+)")),
        ("insertAdjacentHTML 호출",
         re.compile(r"\.insertAdjacentHTML\s*\([^,]+,\s*([^)]+)\)")),
        ("document.write 호출", re.compile(r"document\.write\s*\(([^)]+)\)")),
    )

    def test_no_variable_interpolation_into_html_sinks(self):
        offenders = []
        for name, src in _sources().items():
            if not name.endswith(".js"):
                continue
            for label, pattern in self._SINKS:
                for m in pattern.finditer(src):
                    expr = m.group(1).strip()
                    if not _is_safe_html_literal(expr):
                        offenders.append(f"{name} [{label}]: {expr[:60]}")
        self.assertEqual(offenders, [],
                         "데이터를 HTML 싱크(innerHTML/outerHTML/"
                         "insertAdjacentHTML/document.write)에 넣으면 안 됩니다 — "
                         "textContent를 쓰세요:\n  " + "\n  ".join(offenders))


class TestNoVerdictVocabulary(unittest.TestCase):
    """v0.8.5 원칙 — 점수·등급·판정 어휘를 화면 문구로 쓰지 않는다."""

    _BANNED = ("매우위험", "고위험", "위험도", "위험등급",
               "의심스", "종합점수", "리스크 점수", "등급 부여")

    def test_no_grade_words(self):
        for name, src in _sources().items():
            for word in self._BANNED:
                self.assertNotIn(word, src, f"{name}에 판정 어휘 '{word}'")


class TestLogoutClearsDartKey(unittest.TestCase):
    """계획 인수 기준(`task-5-brief.md`): "로그아웃 후 — DART 키와 세션이
    지워진다". doLogout()이 세션만 지우고 DART 키(localStorage + 입력
    필드)를 남기면, 공용 PC에서 다음 사용자가 앞사람의 DART 키로 조회할
    수 있다.
    """

    def test_logout_clears_session_storage_dart_key_storage_and_input(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "doLogout")
        # 세션 정리는 clearSession()으로 위임해도 된다 — 그 함수 자체가
        # LS_SESSION을 지우는지는 TestTokenRefreshFailureRecovers에서 검증한다.
        session_cleared = "clearSession(" in body or "LS_SESSION" in body
        self.assertTrue(session_cleared, "doLogout이 세션을 지우지 않습니다")
        self.assertRegex(body, r"removeItem\(\s*LS_DART_KEY\s*\)",
                         "doLogout이 저장된 DART 키를 지우지 않습니다")
        # `getElementById("dartkey")`를 변수에 담아 쓰는 스타일과 체이닝하는
        # 스타일을 모두 허용하되, 어느 쪽이든 그 참조의 `.value`가 빈 문자열로
        # 비워지는지까지 확인한다(단순히 dartkey를 "언급"만 하는 걸로는 부족).
        direct = re.search(
            r'getElementById\(\s*["\']dartkey["\']\s*\)[^;\n]*\.value\s*=\s*["\']["\']',
            body,
        )
        via_var = None
        m_var = re.search(
            r'(\w+)\s*=\s*document\.getElementById\(\s*["\']dartkey["\']\s*\)', body
        )
        if m_var:
            via_var = re.search(
                re.escape(m_var.group(1)) + r'\.value\s*=\s*["\']["\']', body
            )
        self.assertTrue(
            direct or via_var,
            "doLogout이 DART 키 입력 필드를 비우지 않습니다 — DOM에 평문으로 남습니다",
        )


class TestTokenRefreshFailureRecovers(unittest.TestCase):
    """토큰 갱신 실패 시 세션을 정리하고 로그인 화면으로 돌아가야 한다.

    안 그러면 폴링 루프가 매번 실패한 채 새로고침 전까지 본문에 멈춰 있고,
    사용자는 로그인 화면으로 돌아갈 방법이 없다.
    """

    def test_token_catches_refresh_failure_and_returns_to_gate(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "token")
        m = re.search(r"catch\s*\([^)]*\)\s*\{(.*)\}\s*$", body, re.S)
        self.assertIsNotNone(m, "token()이 갱신 실패를 catch하지 않습니다")
        catch_body = m.group(1)
        self.assertIn("clearSession(", catch_body,
                      "갱신 실패 시 세션을 정리하지 않습니다")
        self.assertIn("showGate(", catch_body,
                      "갱신 실패 시 로그인 화면으로 돌아가지 않습니다")

    def test_clear_session_nulls_state_and_removes_storage(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "clearSession")
        self.assertRegex(body, r"SESSION\s*=\s*null",
                         "clearSession이 메모리 세션을 지우지 않습니다")
        self.assertRegex(body, r"removeItem\(\s*LS_SESSION\s*\)",
                         "clearSession이 저장된 세션을 지우지 않습니다")


class TestGotrueDistinguishesFailureReasons(unittest.TestCase):
    """세션 만료(refresh_token 실패)를 비밀번호 오류 문구로 안내하면
    사용자가 애먼 비밀번호를 의심하며 헤맨다. 서버 응답 원문을 노출하지
    않는다는 원칙(계정 존재 여부 유출 방지)은 유지한 채 실패 유형만
    구분해야 한다.
    """

    def test_refresh_and_password_failures_get_different_messages(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "gotrue")
        self.assertIn("refresh_token", body,
                      "gotrue가 grant 종류로 분기하지 않습니다")
        messages = re.findall(r'safeError\(\s*"([^"]+)"', body)
        self.assertGreaterEqual(len(messages), 2,
                                "gotrue가 실패 문구를 한 가지로만 씁니다")
        self.assertEqual(len(set(messages)), len(messages),
                         "실패 문구가 중복됩니다 — 로그인 실패와 세션 만료를 "
                         "구분해야 합니다")


class TestLoadConfigValidatesServerSettings(unittest.TestCase):
    """se_server/config.py는 SUPABASE_URL/SUPABASE_ANON_KEY가 없어도
    supabase_anon_key=""로 200을 돌려줄 수 있다. 그대로 두면 gotrue()가
    상대 경로로 요청해 404를 받고, 실제 원인(서버 환경변수 누락)이 아니라
    "로그인 실패"로만 보인다.
    """

    def test_load_config_rejects_empty_server_settings_distinctly(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "loadConfig")
        self.assertIn("supabase_url", body,
                      "loadConfig이 supabase_url을 검증하지 않습니다")
        self.assertIn("supabase_anon_key", body,
                      "loadConfig이 supabase_anon_key를 검증하지 않습니다")
        self.assertIn("throw", body, "loadConfig이 빈 설정에서 실패하지 않습니다")
        self.assertNotIn("이메일과 비밀번호", body,
                         "설정 오류를 로그인 실패 문구로 안내하면 안 됩니다 — "
                         "원인이 다릅니다")


class TestTokenEnsuresConfigLoaded(unittest.TestCase):
    """CONFIG가 null인 채 gotrue()를 부르면 CONFIG.supabase_url에서
    TypeError가 난다. 저장된 세션을 페이지 로드 직후 복원하는 경로에서
    발생할 수 있으므로, token()이 refresh를 시도하기 전에 CONFIG 로드를
    스스로 보장해야 한다.
    """

    def test_token_loads_config_before_calling_refresh(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "token")
        m_load = re.search(r"loadConfig\(", body)
        m_gotrue = re.search(r'gotrue\(\s*["\']refresh_token', body)
        self.assertIsNotNone(m_load, "token()이 CONFIG 로드를 보장하지 않습니다")
        self.assertIsNotNone(m_gotrue, "token()이 refresh_token으로 갱신하지 않습니다")
        self.assertLess(m_load.start(), m_gotrue.start(),
                        "CONFIG 로드 보장이 gotrue() 갱신 호출보다 뒤에 있어 "
                        "여전히 CONFIG가 비어 있을 때 갱신을 시도할 수 있습니다")


class TestLoginDoesNotLeakRawErrors(unittest.TestCase):
    """doLogin()의 catch가 e.message를 그대로 표시하면 네트워크 예외의
    "Failed to fetch" 같은 브라우저 내부 문구가 사용자에게 노출된다.
    """

    def test_do_login_uses_safe_message_wrapper_not_raw_message(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "doLogin")
        self.assertIn("safeMessage(", body,
                      "doLogin이 안전 문구 판별 없이 오류를 표시할 수 있습니다")
        self.assertNotRegex(body, r"\be\.message\b",
                            "doLogin이 e.message를 직접 노출합니다 — 브라우저 "
                            "내부 오류 문구가 샐 수 있습니다")


class TestNoDeadCode(unittest.TestCase):
    """ui.js는 node로 실행되지 않는다(순수하지 않다 — DOM/fetch/localStorage
    를 직접 만진다). module.exports와 소비처 없는 getDartKey()를 남겨두면
    "쓰이는 것처럼 보이지만 아무도 안 쓰는" 코드가 된다.
    """

    def test_ui_js_has_no_module_exports_or_unused_get_dart_key(self):
        src = _sources()["ui.js"]
        self.assertNotIn("module.exports", src,
                         "ui.js는 node 테스트 대상이 아니므로 module.exports가 필요 없습니다")
        self.assertNotRegex(src, r"function\s+getDartKey\s*\(",
                            "getDartKey()는 소비처가 없는 죽은 코드입니다")


class TestAnalyzeIsolatesFetchedStatePerCall(unittest.TestCase):
    """FETCHED가 모듈 전역이면, 같은 페이지에서 analyze()를 두 번째 부를 때
    이전 작업에서 받은 섹션 키가 그대로 남아 nextKeysToFetch가 매번 []를
    돌려준다 — 두 번째 분석은 섹션이 하나도 안 그려진다.

    단순히 소스에 "FETCHED"라는 이름이 없다고 통과시키면 약하다(이름만
    바꾸고 여전히 모듈 최상위에 두는 회귀를 못 잡는다) — analyze() 본문
    안에서 실제로 새 Set을 선언해 쓰는지, 그리고 같은 이름이 모듈
    최상위에도 선언돼 있지 않은지까지 확인한다.
    """

    def test_analyze_declares_and_uses_a_locally_scoped_fetched_set(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "analyze")

        m = re.search(r"(?:let|const)\s+(\w+)\s*=\s*new Set\(\s*\)", body)
        self.assertIsNotNone(
            m,
            "analyze()가 호출마다 새 Set을 선언하지 않습니다 — 이전 작업의 "
            "키가 새 작업으로 새어 들어갈 수 있습니다",
        )
        var_name = m.group(1)

        self.assertRegex(
            body,
            r"nextKeysToFetch\([^,]+,\s*\[\.\.\." + re.escape(var_name) + r"\]\)",
            "analyze()의 루프가 방금 선언한 지역 Set을 쓰지 않습니다",
        )

        # 같은 이름이 모듈 최상위(들여쓰기 없는 줄)에서도 선언돼 있으면,
        # 지역 선언이 있어도 바깥 전역이 여전히 상태를 공유하게 된다.
        self.assertNotRegex(
            src,
            r"(?m)^(?:let|const)\s+" + re.escape(var_name) + r"\b",
            f"{var_name}이 모듈 최상위(전역)에서도 선언돼 있습니다 — "
            "analyze() 호출 간에 상태가 샙니다",
        )


class TestSectionFetchFailureIsNotSilentlyLost(unittest.TestCase):
    """FETCHED.add(key)가 요청 **전**에 일어나면, 실패한 섹션은 재시도되지도
    사용자에게 알려지지도 않고 영원히 사라진다 — 화면은 아무 일 없었던
    것처럼 보인다. "받음" 표시는 성공을 확인한 뒤에만 해야 하고, 실패는
    화면에 보이는 경로로 넘어가야 한다.

    이 검사도 함수 본문을 실제로 파싱해서 확인한다 — "sec.status"라는
    문자열이 소스 어딘가에 있다는 것만으로는 그 검사가 받음-표시보다
    먼저 일어나는지 알 수 없다.
    """

    def _section_loop_body(self, analyze_body: str) -> str:
        loop_m = re.search(
            r"for\s*\(\s*const\s+key\s+of\s+nextKeysToFetch\([^)]*\)\s*\)\s*\{",
            analyze_body,
        )
        self.assertIsNotNone(loop_m, "analyze()에서 섹션 수신 루프를 찾지 못했습니다")
        return _extract_braced_block(analyze_body, loop_m.end() - 1)

    def test_fetched_is_marked_only_after_checking_success(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "analyze")
        loop_body = self._section_loop_body(body)

        if_m = re.search(r"if\s*\(\s*sec\.status\s*===\s*200\s*\)\s*\{", loop_body)
        self.assertIsNotNone(
            if_m, "루프가 섹션 요청의 성공 여부(sec.status)를 확인하지 않습니다"
        )
        if_body = _extract_braced_block(loop_body, if_m.end() - 1)

        self.assertRegex(
            if_body, r"\.add\(\s*key\s*\)",
            "성공했을 때 받은 키를 기록하지 않습니다",
        )

        # 성공 분기 블록(if_body)을 들어내고도 여전히 .add(key)가 남아
        # 있다면, 요청 결과를 확인하기 전(또는 실패 분기)에도 "받음"으로
        # 표시하는 것이다.
        rest = loop_body.replace(if_body, "", 1)
        self.assertNotRegex(
            rest, r"\.add\(\s*key\s*\)",
            "요청 성공 여부를 확인하기 전(또는 실패 시)에도 키를 '받음'으로 "
            "표시합니다 — 실패한 섹션이 재시도되지 않고 영원히 사라집니다",
        )

    def test_failure_is_pushed_to_a_list_that_reaches_render_failures(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "analyze")
        loop_body = self._section_loop_body(body)

        if_m = re.search(r"if\s*\(\s*sec\.status\s*===\s*200\s*\)\s*\{", loop_body)
        self.assertIsNotNone(if_m)
        if_body = _extract_braced_block(loop_body, if_m.end() - 1)

        after_if = loop_body[loop_body.index(if_body) + len(if_body):]
        else_m = re.match(r"\s*else\s*\{", after_if)
        self.assertIsNotNone(
            else_m,
            "요청 실패 시 처리 분기(else)가 없습니다 — 실패가 조용히 "
            "사라집니다",
        )
        else_body = _extract_braced_block(after_if, else_m.end() - 1)

        push_m = re.search(r"(\w+)\.push\(", else_body)
        self.assertIsNotNone(
            push_m, "실패를 어디에도 기록하지 않습니다 — 조용히 사라집니다"
        )
        array_name = push_m.group(1)

        # 그 배열이 renderFailures로 전달돼야 실제로 화면에 보이는 경로를
        # 탄다. 배열에 담기만 하고 아무 데도 넘기지 않으면 여전히 죽은
        # 데이터다. renderFailures(...) 인자에는 `(prog.body.failed || [])`
        # 처럼 중첩 괄호가 섞일 수 있어 `[^)]*`로는 못 잡는다 — 괄호
        # 균형을 실제로 세어 호출 전체를 추출한다.
        call_m = re.search(r"renderFailures\(", body)
        self.assertIsNotNone(
            call_m,
            "실패 목록을 만들기만 하고 renderFailures를 부르지 않습니다 — "
            "여전히 사용자에게 보이지 않습니다",
        )
        depth = 0
        call_end = None
        for i in range(call_m.end() - 1, len(body)):
            if body[i] == "(":
                depth += 1
            elif body[i] == ")":
                depth -= 1
                if depth == 0:
                    call_end = i + 1
                    break
        self.assertIsNotNone(call_end, "renderFailures(...) 호출의 닫는 괄호를 찾지 못했습니다")
        call_expr = body[call_m.start():call_end]
        self.assertIn(
            array_name, call_expr,
            "실패 목록을 만들기만 하고 renderFailures로 넘기지 않습니다 — "
            "여전히 사용자에게 보이지 않습니다",
        )


class TestAnalyzeLoopSurvivesTokenRefreshFailure(unittest.TestCase):
    """루프 안 await token()이 실패하면 analyze()가 reject된다 — 그러면 이
    함수를 부르는 쪽마다 매번 try/catch를 해야 한다. token()이 실패 시
    이미 clearSession()+showGate()로 로그인 화면을 띄우므로, analyze()는
    조용히 루프만 멈추면 된다.
    """

    def test_loop_body_is_wrapped_in_try_catch(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "analyze")
        for_m = re.search(r"for\s*\(\s*;;\s*\)\s*\{", body)
        self.assertIsNotNone(for_m, "analyze()에서 폴링 루프(for (;;))를 찾지 못했습니다")
        for_body = _extract_braced_block(body, for_m.end() - 1)
        # _extract_braced_block은 for(;;)의 여는/닫는 중괄호까지 포함해
        # 돌려주므로 그 바깥 중괄호를 벗겨내고 안쪽 내용만 본다.
        for_inner = for_body[1:-1].strip()
        # for(;;) 본문이 사실상 try { ... } catch (...) { ... } 하나로만
        # 이뤄져 있는지 확인한다 — 그래야 루프 안 어디서 던지든(await
        # token() 포함) analyze() 밖으로 새지 않는다.
        self.assertRegex(
            for_inner,
            r"^try\s*\{",
            "폴링 루프 본문이 try로 시작하지 않습니다 — 루프 안 예외가 "
            "analyze()를 reject시킬 수 있습니다",
        )
        self.assertRegex(
            for_body, r"\}\s*catch\s*\([^)]*\)\s*\{",
            "폴링 루프에 catch가 없습니다",
        )


class TestDisclaimerRenderedWhenPresent(unittest.TestCase):
    """서버가 면책 문구를 주면 화면이 실제로 그려야 한다 — 단, 항상은 아니다.

    이 클래스는 예전엔 "TestDisclaimerAlwaysRendered"였지만, 서버가
    disclaimer를 빠뜨린 예상 밖 응답에서 빈 문단을 만들지 않도록
    `if (body.disclaimer) {...}` 가드가 들어가면서(Minor 수정) 실제 동작은
    "있으면 그린다"이지 "항상 그린다"가 아니게 됐다 — 이름이 구현과
    어긋나 있었다.

    이전 검사(`assertIn("disclaimer", src)`)는 주석 한 줄만 있어도 통과하는
    공허한 검사였다 — openActorPanel 본문을 파싱해 disclaimer 값이 실제로
    textContent에 담기고, 그 요소가 appendChild로 DOM에 붙는지까지 확인한다.
    """

    def test_panel_renders_server_disclaimer_when_present(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "openActorPanel")

        m = re.search(
            r"(\w+)\.textContent\s*=\s*[^;\n]*\.disclaimer\b[^;\n]*;",
            body,
        )
        self.assertIsNotNone(
            m, "disclaimer 값을 textContent로 담는 코드를 찾지 못했습니다"
        )
        var_name = m.group(1)

        self.assertRegex(
            body,
            r"appendChild\(\s*" + re.escape(var_name) + r"\s*\)",
            f"{var_name}를 만들었지만 appendChild로 화면에 붙이지 않습니다 — "
            "면책 문구를 만들기만 하고 화면에 붙이지 않으면 사용자는 못 봅니다",
        )

    def test_disclaimer_block_is_skipped_when_server_omits_it(self):
        """disclaimer가 없는 예상 밖 응답에서 빈 문단만 남기지 않는지
        확인한다 — textContent 대입이 `if (body.disclaimer)` 같은 조건
        안에 있어야 한다(무조건 실행되면 빈 `<p class="note">`가 남는다).
        """
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "openActorPanel")

        m = re.search(
            r"(\w+)\.textContent\s*=\s*[^;\n]*\.disclaimer\b[^;\n]*;",
            body,
        )
        self.assertIsNotNone(m)
        assign_idx = m.start()

        if_m = re.search(r"if\s*\([^)]*\.disclaimer\b[^)]*\)\s*\{", body)
        self.assertIsNotNone(
            if_m,
            "disclaimer 렌더링이 존재 여부를 확인하는 if 없이 무조건 "
            "실행됩니다 — 서버가 disclaimer를 빠뜨리면 빈 문단이 남습니다",
        )
        open_brace_idx = if_m.end() - 1
        guard_block = _extract_braced_block(body, open_brace_idx)
        guard_start = if_m.start()
        guard_end = open_brace_idx + len(guard_block)  # 닫는 '}' 바로 다음 인덱스
        self.assertTrue(
            guard_start <= assign_idx < guard_end,
            "disclaimer textContent 대입이 존재 여부 확인 if 블록 밖에 "
            "있습니다 — 조건 없이 실행되면 빈 문단이 남습니다",
        )


class TestPanelsAreWiredAndReachable(unittest.TestCase):
    """openActorPanel/openDocPanel의 호출부가 실제로 존재하고, 그 호출부가
    걸리는 DOM 엘리먼트가 index.html에도 실재하는지 확인한다.

    리뷰의 핵심 지적: 패널을 만드는 함수 정의는 있었지만 부르는 곳이
    저장소 전체에 0개였다 — 패널에 도달할 방법이 없었다. 이 클래스는 그
    사고가 되풀이되지 않도록 "정의만 있고 호출은 없는" 상태를 기계적으로
    잡는다.
    """

    def test_actor_button_exists_and_opens_the_panel_for_current_company(self):
        html = _sources()["index.html"]
        self.assertIn('id="actor-btn"', html,
                      "행위자 패널을 여는 헤더 버튼이 마크업에 없습니다")

        src = _sources()["ui.js"]
        self.assertRegex(
            src,
            r'getElementById\(\s*["\']actor-btn["\']\s*\)'
            r'[^;]*addEventListener\(\s*["\']click["\']',
            "actor-btn에 클릭 리스너가 연결돼 있지 않습니다",
        )
        # 버튼 핸들러가 실제로 openActorPanel을 부르는지까지 확인한다 —
        # 리스너만 걸려 있고 정작 패널을 안 열면 여전히 도달 불가능하다.
        m = re.search(
            r'getElementById\(\s*["\']actor-btn["\']\s*\)\s*'
            r'\.addEventListener\(\s*["\']click["\']\s*,\s*function[^{]*\{'
            r'([\s\S]*?)\}\s*\)\s*;',
            src,
        )
        self.assertIsNotNone(m, "actor-btn 클릭 핸들러 본문을 찾지 못했습니다")
        self.assertIn("openActorPanel(", m.group(1),
                      "actor-btn 클릭 핸들러가 openActorPanel을 부르지 않습니다")

    def test_open_actor_panel_is_not_dead_code(self):
        """단순 등장 횟수(≥2)는 설명 주석 속 함수 이름 언급까지 "호출부"로
        착각한다(실제로 이 파일의 openDocPanel 옆 주석 "openActorPanel과
        같은 이유"가 그 경우다) — 주석을 지운 뒤 선언을 제외한 자리에
        실제 호출이 있는지 확인한다.
        """
        src = _sources()["ui.js"]
        # 정의 자체가 있는지 먼저 확인한다(없으면 아래 호출부 검사가
        # 공허하게 통과한다).
        _extract_function_body(src, "openActorPanel")
        self.assertTrue(
            _has_real_call_site(src, "openActorPanel"),
            "openActorPanel 정의만 있고 부르는 곳이 없습니다 — "
            "패널에 도달할 방법이 없습니다",
        )

    def test_open_doc_panel_is_wired_from_the_rcept_no_cell(self):
        """공시 원문 패널은 rcept_no 열의 셀에서만 열려야 한다 — 확인되지
        않은 필드(공시 제목 등)로 어느 칸이 클릭 가능한지 추측하지 않는다.
        """
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "tableEl")
        self.assertIn("rcept_no", body,
                      "tableEl이 rcept_no 열을 특정하지 않습니다")
        self.assertIn("openDocPanel(", body,
                      "tableEl이 openDocPanel을 부르지 않습니다 — "
                      "공시 원문 패널에 도달할 방법이 없습니다")

        # 단순 등장 횟수 대신 주석을 지운 뒤 실제 호출부를 확인한다
        # (openActorPanel과 같은 이유 — 위 test_open_actor_panel_is_not_dead_code
        # 참고). 위에서 이미 tableEl 본문 안 호출을 확인했으니 여기선
        # "정의만 있고 어디서도 안 불린다"는 극단적 회귀만 잡으면 된다.
        self.assertTrue(
            _has_real_call_site(src, "openDocPanel"),
            "openDocPanel 정의만 있고 부르는 곳이 없습니다 — "
            "패널에 도달할 방법이 없습니다",
        )

    def test_clickable_doc_cell_reuses_existing_css_class(self):
        """index.html에 이미 정의된 `.doc` 클래스를 재사용해야 한다 —
        새 클래스를 만들면 스타일이 없는 채로 방치되기 쉽다.
        """
        html = _sources()["index.html"]
        self.assertIn(".doc{", html.replace(" ", ""),
                      "index.html에 .doc 클래스 스타일이 없습니다")
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "tableEl")
        self.assertIn('"doc"', body,
                      "클릭 가능한 rcept_no 셀이 .doc 클래스를 쓰지 않습니다")

    def test_panel_has_a_close_button_and_escape_key_support(self):
        html = _sources()["index.html"]
        self.assertIn('id="panel-close"', html,
                      "패널을 닫는 버튼이 마크업에 없습니다")

        src = _sources()["ui.js"]
        self.assertRegex(
            src, r'classList\.remove\(\s*["\']open["\']\s*\)',
            "패널을 닫는 코드(classList.remove(\"open\"))가 없습니다 — "
            "열려도 닫을 방법이 없습니다",
        )
        self.assertRegex(
            src, r'["\']Escape["\']',
            "Esc 키로 패널을 닫는 처리가 없습니다",
        )
        self.assertRegex(
            src,
            r'getElementById\(\s*["\']panel-close["\']\s*\)'
            r'[^;]*addEventListener\(\s*["\']click["\']',
            "panel-close 버튼에 클릭 리스너가 연결돼 있지 않습니다",
        )

    def test_show_gate_closes_the_panel_so_names_do_not_linger_on_the_gate(self):
        """#panel은 #main 밖(형제 노드)이라 showGate()가 #main을 숨겨도
        열려 있던 패널은 그대로 보인다.

        showGate()는 로그아웃(doLogout)뿐 아니라 세션 만료(token() 갱신
        실패, init()의 자동 로그인 실패)에서도 불린다 — 패널을 닫는 처리를
        doLogout() 안에만 두면 로그아웃 경로만 덮이고, 패널이 열린 채로
        세션이 만료되는 경로(예: 폴링 루프 중 갱신 실패)에서는 여전히
        이전 사용자의 실명이 로그인 화면 위에 남는다. 그래서 이 검사는
        doLogout이 아니라 showGate 본문을 직접 본다 — 그래야 두 경로가
        모두 덮이는지 실제로 확인된다.
        """
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "showGate")
        self.assertIn(
            "closePanel(", body,
            "showGate가 열려 있을 수 있는 패널을 닫지 않습니다 — "
            "세션 만료 시에도 이전 사용자의 실명이 화면에 남을 수 있습니다",
        )
        # `getElementById("panel-body")`를 변수에 담아 그 변수의
        # `.textContent`를 비우는 스타일이라, 참조와 대입이 같은 줄에
        # 붙어 있지 않다 — 변수명을 먼저 찾고 그 변수의 대입까지 확인한다.
        m_var = re.search(
            r'(\w+)\s*=\s*document\.getElementById\(\s*["\']panel-body["\']\s*\)', body
        )
        self.assertIsNotNone(
            m_var, "showGate가 panel-body 엘리먼트를 참조하지 않습니다"
        )
        self.assertRegex(
            body,
            re.escape(m_var.group(1)) + r'\.textContent\s*=\s*["\']["\']',
            "showGate가 panel-body 내용을 비우지 않습니다 — 패널을 닫아도 "
            "DOM에 이전 사용자의 실명이 그대로 남아 있을 수 있습니다",
        )

    def test_logout_delegates_panel_cleanup_to_show_gate_without_duplicating_it(self):
        """closePanel()+panel-body 비우기가 showGate() 안으로 옮겨졌으므로,
        doLogout()은 showGate()를 불러 위임하기만 해야 하고 같은 처리를
        중복해서 갖고 있으면 안 된다(두 곳에 같은 로직이 있으면 한쪽만
        고치고 잊어버리는 사고가 되풀이된다).
        """
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "doLogout")
        self.assertIn("showGate(", body,
                      "doLogout이 showGate()를 부르지 않습니다 — 패널 정리가 "
                      "이뤄지지 않습니다")
        self.assertNotIn("closePanel(", body,
                         "doLogout이 closePanel()을 중복 호출합니다 — "
                         "이제 showGate() 안에서 처리되므로 여기선 필요 없습니다")


class TestPanelResponsesAreValidatedDefensively(unittest.TestCase):
    """서버 응답이 예상과 다를 때(본문이 없거나 필드 타입이 다를 때) 예외가
    그대로 전파되면 패널이 열리지도, 안내가 뜨지도 않는다(unhandled
    rejection). 조용히 넘어가지 않고 실패를 화면에 알려야 한다.
    """

    def test_open_actor_panel_guards_against_non_array_actors(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "openActorPanel")
        self.assertRegex(
            body, r"Array\.isArray\(",
            "openActorPanel이 actors가 배열인지 확인하지 않습니다 — "
            "문자열이면 글자 수만큼 빈 카드가 그려질 수 있습니다",
        )

    def test_open_actor_panel_and_open_doc_panel_catch_token_failure(self):
        """analyze()의 루프는 await token() 실패를 catch하는데 이 두
        함수는 무처리라면, 세션이 만료된 상태에서 패널을 열 때 아무 일도
        일어나지 않은 것처럼 보인다(unhandled promise rejection).
        """
        src = _sources()["ui.js"]
        for name in ("openActorPanel", "openDocPanel"):
            body = _extract_function_body(src, name)
            self.assertRegex(
                body, r"await\s+token\(\)",
                f"{name}이 token()을 부르지 않습니다",
            )
            self.assertRegex(
                body, r"try\s*\{[\s\S]*await\s+token\(\)[\s\S]*\}\s*catch\s*\(",
                f"{name}이 await token() 실패를 catch하지 않습니다 — "
                "세션 만료 시 패널을 열면 아무 반응도 없는 것처럼 보입니다",
            )

    def test_open_doc_panel_does_not_render_literal_undefined(self):
        """200인데 text가 없으면(예상 밖 응답) <pre>에 리터럴 "undefined"가
        뜨고, truncated만 참이면 "원문 0자 중 일부입니다"라는 앞뒤 안 맞는
        안내까지 나온다 — 둘 다 typeof 가드로 막아야 한다.
        """
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "openDocPanel")
        self.assertRegex(
            body, r'typeof\s+\w+\.text\s*===\s*["\']string["\']',
            "openDocPanel이 text가 문자열인지 확인하지 않습니다 — "
            "예상 밖 응답에서 리터럴 undefined가 표시될 수 있습니다",
        )


if __name__ == "__main__":
    unittest.main()
