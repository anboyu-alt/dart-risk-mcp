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


class TestDisclaimerAlwaysRendered(unittest.TestCase):
    def test_panel_renders_server_disclaimer(self):
        """서버가 주는 면책 문구를 화면이 실제로 그려야 한다.

        서버만 보내고 화면이 버리면 사용자는 못 본다.
        """
        src = _sources()["ui.js"]
        self.assertIn("disclaimer", src,
                      "actors 응답의 disclaimer를 화면이 쓰지 않습니다")


if __name__ == "__main__":
    unittest.main()
