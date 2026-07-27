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
        """이전 버전은 "supabase_url"·"supabase_anon_key"·"throw"가 함수
        본문 어딘가에 각각 있는지만 따로따로 확인했다 — 서로 무관한 throw
        (예: 응답이 200이 아닐 때의 throw)로도 세 조건이 전부 만족돼 공허하게
        통과했다(뮤테이션으로 확인됨: 검증 if문 자체를 지워도 이 검사는
        여전히 통과했다). supabase_url·supabase_anon_key를 함께 검사하는
        조건문을 실제로 찾아, 그 조건문 **안에서** throw가 일어나는지까지
        확인한다.
        """
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "loadConfig")
        if_m = re.search(
            r"if\s*\([^)]*supabase_url[^)]*supabase_anon_key[^)]*\)\s*\{",
            body,
        )
        self.assertIsNotNone(
            if_m,
            "loadConfig이 supabase_url·supabase_anon_key를 함께 검사하는 "
            "조건문을 갖고 있지 않습니다",
        )
        guard_block = _extract_braced_block(body, if_m.end() - 1)
        self.assertIn("throw", guard_block,
                      "loadConfig이 빈 설정에서 실패하지 않습니다 — 검증 "
                      "조건문 안에 throw가 없습니다")
        self.assertNotIn("이메일과 비밀번호", guard_block,
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
    """FETCHED가 모듈 전역이면, 같은 페이지에서 폴링을 두 번째 돌릴 때
    이전 작업에서 받은 섹션 키가 그대로 남아 nextKeysToFetch가 매번 []를
    돌려준다 — 두 번째 분석은 섹션이 하나도 안 그려진다.

    폴링 루프는 analyze()(새 작업)와 resumeIfAny()(탭을 다시 열어 이어받는
    작업)가 공유하는 pollUntilDone()에 있다(Task 5에서 분리) — 두 곳에
    루프를 따로 두면 한쪽만 고치고 잊어버리는 사고가 되풀이되기 때문이다.
    그래서 이 검사는 이제 pollUntilDone() 본문을 본다.

    단순히 소스에 "FETCHED"라는 이름이 없다고 통과시키면 약하다(이름만
    바꾸고 여전히 모듈 최상위에 두는 회귀를 못 잡는다) — pollUntilDone()
    본문 안에서 실제로 새 Set을 선언해 쓰는지, 그리고 같은 이름이 모듈
    최상위에도 선언돼 있지 않은지까지 확인한다.
    """

    def test_poll_until_done_declares_and_uses_a_locally_scoped_fetched_set(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "pollUntilDone")

        m = re.search(r"(?:let|const)\s+(\w+)\s*=\s*new Set\(\s*\)", body)
        self.assertIsNotNone(
            m,
            "pollUntilDone()이 호출마다 새 Set을 선언하지 않습니다 — 이전 "
            "작업의 키가 새 작업으로 새어 들어갈 수 있습니다",
        )
        var_name = m.group(1)

        self.assertRegex(
            body,
            r"nextKeysToFetch\([^,]+,\s*\[\.\.\." + re.escape(var_name) + r"\]\)",
            "pollUntilDone()의 루프가 방금 선언한 지역 Set을 쓰지 않습니다",
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

    폴링 루프는 Task 5에서 pollUntilDone()으로 분리됐다(analyze()와
    resumeIfAny()가 공유) — 이 검사도 그 본문을 본다.

    이 검사도 함수 본문을 실제로 파싱해서 확인한다 — "sec.status"라는
    문자열이 소스 어딘가에 있다는 것만으로는 그 검사가 받음-표시보다
    먼저 일어나는지 알 수 없다.
    """

    def _section_loop_body(self, poll_body: str) -> str:
        loop_m = re.search(
            r"for\s*\(\s*const\s+key\s+of\s+nextKeysToFetch\([^)]*\)\s*\)\s*\{",
            poll_body,
        )
        self.assertIsNotNone(loop_m, "pollUntilDone()에서 섹션 수신 루프를 찾지 못했습니다")
        return _extract_braced_block(poll_body, loop_m.end() - 1)

    def test_fetched_is_marked_only_after_checking_success(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "pollUntilDone")
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
        body = _extract_function_body(src, "pollUntilDone")
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
    """루프 안 await token()이 실패하면 pollUntilDone()이 reject된다 —
    그러면 이 함수를 부르는 analyze()·resumeIfAny() 양쪽 모두 매번
    try/catch를 해야 한다. token()이 실패 시 이미 clearSession()+
    showGate()로 로그인 화면을 띄우므로, pollUntilDone()은 조용히 루프만
    멈추면 된다(Task 5에서 폴링 루프가 analyze()에서 pollUntilDone()으로
    분리됐다 — analyze()와 resumeIfAny()가 공유하기 위해서다).
    """

    def test_loop_body_is_wrapped_in_try_catch(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "pollUntilDone")
        for_m = re.search(r"for\s*\(\s*;;\s*\)\s*\{", body)
        self.assertIsNotNone(for_m, "pollUntilDone()에서 폴링 루프(for (;;))를 찾지 못했습니다")
        for_body = _extract_braced_block(body, for_m.end() - 1)
        # _extract_braced_block은 for(;;)의 여는/닫는 중괄호까지 포함해
        # 돌려주므로 그 바깥 중괄호를 벗겨내고 안쪽 내용만 본다.
        for_inner = for_body[1:-1].strip()
        # for(;;) 본문이 사실상 try { ... } catch (...) { ... } 하나로만
        # 이뤄져 있는지 확인한다 — 그래야 루프 안 어디서 던지든(await
        # token() 포함) pollUntilDone() 밖으로 새지 않는다.
        self.assertRegex(
            for_inner,
            r"^try\s*\{",
            "폴링 루프 본문이 try로 시작하지 않습니다 — 루프 안 예외가 "
            "pollUntilDone()을 reject시킬 수 있습니다",
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

    # test_open_actor_panel_is_not_dead_code는 삭제했다 — 바로 위
    # test_actor_button_exists_and_opens_the_panel_for_current_company가
    # actor-btn 클릭 핸들러 본문을 파싱해 "openActorPanel(" 호출을 이미
    # 확인한다(주석이 아니라 실제 핸들러 본문에서). 그 핸들러 안의 호출을
    # 지우면 그 테스트가 바로 실패하므로 뮤테이션 kill 커버리지 손실이
    # 없다 — 완전한 중복이었다.

    def test_open_doc_panel_is_wired_from_the_rcept_no_cell(self):
        """공시 원문 패널은 rcept_no 열의 셀에서만 열려야 한다 — 확인되지
        않은 필드(공시 제목 등)로 어느 칸이 클릭 가능한지 추측하지 않는다.

        이 검사는 문자열 존재만 본다 — tableEl 본문에 "rcept_no"·
        "openDocPanel(" 이 있는지만 확인하고 실제로 클릭했을 때 무슨 값이
        전달되는지는 보지 않는다. 그래서 rcept_no가 상수라 캡션으로
        승격되는 경우(affiliates·financials 실측)에 배선이 끊겨도 이
        검사는 계속 초록이었다 — 캡션 블록에도 "rcept_no"·"openDocPanel("
        문자열은 여전히 등장하기 때문이다(문자열 존재 ≠ 그 경로가 실제로
        연결됨). 세 가지 실제 형태(가로 열·세로 행·캡션 승격)를 node vm
        가짜 DOM으로 렌더링해 실제 클릭까지 재현하는 검사는
        tests/se/test_se_app_js.py의 TestDocPanelClickWiring이 맡는다 —
        이 정적 검사는 최소한의 문자열 가드로만 남긴다.
        """
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "tableEl")
        self.assertIn("rcept_no", body,
                      "tableEl이 rcept_no 열을 특정하지 않습니다")
        self.assertIn("openDocPanel(", body,
                      "tableEl이 openDocPanel을 부르지 않습니다 — "
                      "공시 원문 패널에 도달할 방법이 없습니다")
        # 캡션(상수로 승격된 rcept_no) 경로도 openDocPanel을 불러야 한다 —
        # 그러지 않으면 캡션 조립 블록(c.key === "rcept_no")이 있어도
        # 클릭 리스너가 없는 채로 남을 수 있다. 실제 클릭 재현은
        # TestDocPanelClickWiring이 한다 — 여기선 소스에 그 분기 자체가
        # 있는지만 본다.
        self.assertRegex(
            body, r'c\.key\s*===\s*["\']rcept_no["\']',
            "tableEl이 캡션으로 승격된 rcept_no를 따로 처리하지 않습니다 — "
            "affiliates·financials처럼 rcept_no가 상수라 캡션으로 올라가면 "
            "공시 원문 패널에 도달할 방법이 없어집니다",
        )

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


class TestRenderFailuresReplacesNotAccumulates(unittest.TestCase):
    """앞 리뷰가 이 태스크로 넘긴 지적(a): renderFailures는 폴링마다(루프
    한 바퀴마다) 불린다. "누적"이 아니라 "교체"로 그려야 한다 — 안 그러면
    같은 실패가 화면에 계속 쌓인다. renderSection이 sec-<key> 고정 노드를
    재사용하는 방식과 같은 패턴을 검사한다.
    """

    def test_render_failures_reuses_a_fixed_node_instead_of_always_appending(self):
        """이전 버전은 `removeChild(`가 본문에 두 군데(빈 목록일 때의
        `wrap.parentNode.removeChild(wrap)`, 내용을 비우는 `while` 루프) 있어
        후자를 통째로 지워도 여전히 통과했다(공허 통과, 뮤테이션으로 확인됨).
        내용을 비우는 `while (...firstChild) ...removeChild(...)` 루프
        패턴을 직접 찾는다 — 단순 `removeChild(` 등장 여부가 아니라.
        """
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "renderFailures")
        self.assertRegex(
            body, r'getElementById\(',
            "renderFailures가 고정 노드를 재사용하지 않고 매번 새로 붙일 수 있습니다",
        )
        # 내용을 비우는 처리(removeChild 루프)가 있어야 다시 그릴 때 이전
        # 실패 목록 위에 새 목록이 쌓이지 않는다. `wrap.parentNode.removeChild`
        # (빈 목록 분기)와는 다른, 반복해서 자식을 비우는 while 루프여야 한다.
        self.assertRegex(
            body, r"while\s*\(\s*\w+\.firstChild\s*\)\s*\w+\.removeChild\(",
            "renderFailures가 기존 내용을 비우는 while 루프를 갖고 있지 "
            "않습니다 — 폴링마다 실패 목록이 누적될 수 있습니다",
        )

    def test_render_failures_clears_the_node_when_no_failures_remain(self):
        """실패가 없어졌는데(재시도 성공) 이전 실패 노드가 화면에 그대로
        남으면 사용자는 이미 해결된 문제를 계속 보게 된다.

        이전 버전은 if 조건문의 정규식 존재만 확인했다 — 그 분기 **본문**이
        실제로 노드를 지우는지는 보지 않아서, 분기 안을 빈 채로 두거나
        무관한 코드로 바꿔도 통과했다(공허 통과, 뮤테이션으로 확인됨). 분기
        본문을 직접 추출해 `removeChild`로 기존 노드를 실제로 제거하는지까지
        확인한다.
        """
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "renderFailures")
        if_m = re.search(
            r"if\s*\(\s*!failed\s*\|\|\s*failed\.length\s*===\s*0\s*\)\s*\{",
            body,
        )
        self.assertIsNotNone(
            if_m,
            "renderFailures가 빈 실패 목록을 별도로 처리하지 않습니다 — 이전 "
            "실패 노드가 화면에 남을 수 있습니다",
        )
        guard_block = _extract_braced_block(body, if_m.end() - 1)
        self.assertRegex(
            guard_block, r"removeChild\(",
            "빈 실패 목록 분기가 기존 노드를 실제로 지우지 않습니다 — 이전 "
            "실패 노드가 화면에 남을 수 있습니다",
        )


class TestPollLoopSurfacesNonUserSafeErrors(unittest.TestCase):
    """앞 리뷰가 이 태스크로 넘긴 지적(b): 폴링 루프의 `catch (e) { break; }`가
    예외를 무메시지로 삼킨다. token() 실패(e.userSafe)는 이미 showGate로
    처리되지만, fetch 자체가 던지는 네트워크 예외 등은 폴링이 조용히
    멈추고 진행률 바가 멈춘 채 남는다 — 최소한의 안내가 있어야 한다.
    """

    def test_catch_distinguishes_user_safe_errors_and_shows_a_message_otherwise(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "pollUntilDone")
        catch_m = re.search(r"catch\s*\([^)]*\)\s*\{", body)
        self.assertIsNotNone(catch_m, "pollUntilDone()이 루프 예외를 catch하지 않습니다")
        catch_body = _extract_braced_block(body, catch_m.end() - 1)
        self.assertIn(
            "userSafe", catch_body,
            "catch가 token() 실패(e.userSafe, 이미 showGate로 안내됨)와 그 외 "
            "예외를 구분하지 않습니다",
        )
        self.assertIn(
            "showBar(", catch_body,
            "catch가 사용자에게 아무 안내도 남기지 않습니다 — 진행률 바가 "
            "멈춘 채 남고 사용자는 원인을 알 수 없습니다",
        )


class TestSectionTitleUsesKoreanLabel(unittest.TestCase):
    """앞 리뷰가 이 태스크로 넘긴 지적(d): 섹션 h2 제목이 원본 키 그대로였다
    (예: "fund_usage"). label()이 아는 키는 한국어로, 모르는 키는 원본
    그대로(숨기지 않는다) 나와야 한다.
    """

    def test_section_holder_labels_the_h2_title(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "sectionHolder")
        self.assertRegex(
            body, r"h2\.textContent\s*=\s*label\(\s*key\s*\)",
            "sectionHolder가 h2 제목에 label()을 쓰지 않습니다 — 섹션 제목이 "
            "원본 키 그대로 나올 수 있습니다",
        )


class TestAnalyzeAndResumeShareThePollingLoop(unittest.TestCase):
    """analyze()와 resumeIfAny() 둘 다 pollUntilDone()을 불러야 한다 —
    폴링 로직이 두 곳에 따로 있으면 한쪽만 고치고 잊어버리는 사고가
    되풀이된다(브리프: "Task 2의 폴링 루프를 pollUntilDone(jobId)로 떼어내
    analyze()와 resumeIfAny()가 함께 쓴다").
    """

    def test_analyze_remembers_polls_and_forgets_the_job(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "analyze")
        self.assertIn(
            "rememberJob(", body,
            "analyze()가 job_id를 기억하지 않습니다 — 탭을 닫았다 열면 "
            "이어받을 수 없습니다",
        )
        self.assertIn(
            "pollUntilDone(", body,
            "analyze()가 공유 폴링 루프(pollUntilDone)를 부르지 않습니다",
        )
        self.assertIn(
            "forgetJob(", body,
            "analyze()가 완료 후 저장된 job_id를 지우지 않습니다",
        )

    def test_resume_if_any_validates_with_resume_target_and_shares_poll_until_done(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "resumeIfAny")
        self.assertIn(
            "resumeTarget(", body,
            "resumeIfAny()가 resumeTarget()으로 유효성을 판정하지 않습니다 "
            "— 오래된 작업을 무한정 이어받을 수 있습니다",
        )
        self.assertIn(
            "pollUntilDone(", body,
            "resumeIfAny()가 공유 폴링 루프(pollUntilDone)를 부르지 않습니다",
        )

    def test_resume_if_any_is_wired_and_reachable(self):
        """정의만 있고 아무도 안 부르면 탭을 다시 열어도 이어받지 못한다
        (이 파일의 다른 검사들과 같은 원칙 — openActorPanel이 한때 그랬듯,
        정의는 있지만 호출부가 없는 죽은 코드를 잡는다)."""
        src = _sources()["ui.js"]
        _extract_function_body(src, "resumeIfAny")  # 정의 자체가 있는지 먼저 확인
        self.assertTrue(
            _has_real_call_site(src, "resumeIfAny"),
            "resumeIfAny 정의만 있고 부르는 곳이 없습니다 — 탭을 다시 열어도 "
            "이어받을 방법이 없습니다",
        )


class TestAnalyzeFormIsWiredAndReachable(unittest.TestCase):
    """회사를 입력해 analyze()를 시작하는 UI가 실제로 존재하고 도달
    가능한지 검사한다.

    앞서 우측 패널(openActorPanel/openDocPanel)이 정의만 있고 호출부가
    없어 죽은 코드였던 것과 같은 부류의 결함이다 — analyze()와
    resumeIfAny()는 구현돼 있었지만, 회사명을 입력해 analyze()를 부를
    폼·버튼 자체가 화면에 없어 로그인해도 아무 일도 일어나지 않았다.
    이 클래스는 그 배선이 다시 빠지는 것을 기계적으로 잡는다.
    """

    def test_company_input_form_exists_in_markup(self):
        html = _sources()["index.html"]
        self.assertIn('id="company-input"', html,
                      "회사명(또는 종목코드) 입력창이 마크업에 없습니다")
        self.assertIn('id="analyze-btn"', html,
                      "분석 시작 버튼이 마크업에 없습니다")
        self.assertIn('id="lookback-years"', html,
                      "조회 범위(lookback_years) 선택 UI가 마크업에 없습니다")

    def test_lookback_years_select_offers_only_server_contract_range(self):
        """서버 계약(se_server/api/handlers.py `_MIN_YEARS=1`,
        `_MAX_YEARS=5`)을 벗어난 값을 고를 수 있으면 안 된다 — 서버가
        결국 clamp하더라도, 선택지 자체가 계약과 다르면 사용자가 고른
        값과 실제 적용된 값이 달라 혼란을 준다."""
        html = _sources()["index.html"]
        m = re.search(r'<select id="lookback-years">(.*?)</select>', html, re.S)
        self.assertIsNotNone(m, "lookback-years select를 찾지 못했습니다")
        values = sorted(int(v) for v in re.findall(r'<option value="(\d+)"', m.group(1)))
        self.assertEqual(values, [1, 2, 3, 4, 5],
                         "조회 범위 선택지가 서버 계약(1~5년)과 다릅니다")

    def test_analyze_button_is_wired_to_a_handler_that_calls_analyze(self):
        src = _sources()["ui.js"]
        self.assertRegex(
            src,
            r'getElementById\(\s*["\']analyze-btn["\']\s*\)'
            r'[^;]*addEventListener\(\s*["\']click["\']',
            "analyze-btn에 클릭 리스너가 연결돼 있지 않습니다",
        )
        # 리스너만 걸려 있고 정작 analyze()에 도달하지 않으면 여전히
        # 회사를 입력해도 아무 일도 일어나지 않는다 — 핸들러 본문을
        # 파싱해 실제로 analyze()를 부르는지까지 확인한다.
        body = _extract_function_body(src, "doAnalyze")
        self.assertRegex(body, r"\banalyze\s*\(",
                         "doAnalyze가 analyze()를 부르지 않습니다")

    def test_company_input_enter_key_also_reaches_analyze(self):
        src = _sources()["ui.js"]
        self.assertRegex(
            src,
            r'getElementById\(\s*["\']company-input["\']\s*\)'
            r'[^;]*addEventListener\(\s*["\']keydown["\']',
            "company-input에 키 입력 리스너가 연결돼 있지 않습니다 — "
            "입력창 Enter로 분석을 시작할 수 없습니다",
        )

    def test_do_analyze_is_not_dead_code(self):
        """단순 등장 횟수는 설명 주석 속 함수 이름 언급까지 "호출부"로
        착각한다(openActorPanel이 한때 그랬던 사고, 위 클래스들 참고) —
        주석을 지운 뒤 선언을 제외한 자리에 실제 호출이 있는지 확인한다.
        """
        src = _sources()["ui.js"]
        _extract_function_body(src, "doAnalyze")  # 정의 자체가 있는지 먼저 확인
        self.assertTrue(
            _has_real_call_site(src, "doAnalyze"),
            "doAnalyze 정의만 있고 부르는 곳이 없습니다 — 회사 입력 폼에서 "
            "분석을 시작할 방법이 없습니다",
        )

    # test_analyze_itself_is_reachable_not_only_resume_if_any은 삭제했다 —
    # 바로 아래 test_do_analyze_is_not_dead_code(doAnalyze가 실제로 불린다)와
    # 위 test_analyze_button_is_wired_to_a_handler_that_calls_analyze(doAnalyze
    # 본문이 실제로 `analyze(`를 부른다)가 이어지면 analyze()에도 이미 실제
    # 호출부가 있음이 전이적으로 보장된다 — analyze( 호출을 doAnalyze에서
    # 지우면 후자가 바로 실패하므로 뮤테이션 kill 커버리지 손실이 없다.

    def test_do_analyze_rejects_empty_company_without_calling_analyze(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "doAnalyze")
        if_m = re.search(r"if\s*\(\s*!company\s*\)\s*\{", body)
        self.assertIsNotNone(
            if_m, "doAnalyze가 빈 입력을 걸러내지 않습니다 — 빈 회사명이 "
                  "서버로 그대로 나갈 수 있습니다",
        )
        guard_block = _extract_braced_block(body, if_m.end() - 1)
        self.assertNotIn("analyze(", guard_block,
                         "빈 입력 분기 안에서 analyze()를 부르면 안 됩니다")
        self.assertIn("return", guard_block,
                      "빈 입력이면 doAnalyze가 더 진행하지 않고 돌아가야 "
                      "합니다")

    def test_do_analyze_guards_against_double_submission(self):
        """분석은 수 분이 걸린다 — 진행 중 재클릭이 새 작업을 또 만들면
        사용자의 DART 호출 한도를 태운다. doLogin()의 LOGGING_IN 가드와
        같은 부류의 재진입 가드가 있어야 한다."""
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "doAnalyze")
        m = re.search(r"if\s*\(\s*(\w+)\s*\)\s*return\s*;", body)
        self.assertIsNotNone(
            m, "doAnalyze가 연타 방지 가드(진행 중이면 즉시 반환)를 갖고 "
               "있지 않습니다",
        )
        guard_name = m.group(1)
        # 가드 변수를 선언만 하고 실제로 안 쓰면(true/false로 안 바뀌면)
        # 여전히 무력하다 — analyze() 호출 전후로 실제 갱신되는지 확인한다.
        self.assertRegex(
            body, re.escape(guard_name) + r"\s*=\s*true",
            f"{guard_name}을 true로 설정하는 코드가 없습니다 — 가드가 "
            "실제로 걸리지 않습니다",
        )
        self.assertRegex(
            body, re.escape(guard_name) + r"\s*=\s*false",
            f"{guard_name}을 false로 되돌리는 코드가 없습니다 — 한 번 "
            "분석을 시작하면 다시는 못 합니다",
        )

    def test_new_analysis_clears_previous_bodys_sections(self):
        """이전 회사의 섹션이 새 회사 화면에 남아 섞이면 안 된다.
        renderHeadPlaceholder는 analyze()와 resumeIfAny() 양쪽 모두에서
        새 분석/재개 시작 시 불리는 지점이므로, 여기서 #body를 비워야
        두 경로 모두 덮인다(패널을 닫는 처리가 이미 여기 있는 것과 같은
        이유 — 한 곳에서 정리하면 모든 경로가 한 번에 덮인다)."""
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "renderHeadPlaceholder")
        m_var = re.search(
            r'(\w+)\s*=\s*document\.getElementById\(\s*["\']body["\']\s*\)', body
        )
        self.assertIsNotNone(
            m_var, "renderHeadPlaceholder가 #body를 참조하지 않습니다 — "
                   "이전 회사의 섹션이 남을 수 있습니다",
        )
        self.assertRegex(
            body, r"removeChild\(",
            "renderHeadPlaceholder가 #body의 기존 내용을 비우지 않습니다 — "
            "새 회사 분석 시작 시 이전 회사의 섹션이 그대로 남을 수 "
            "있습니다",
        )


class TestShowGateClearsScreenState(unittest.TestCase):
    """리뷰 지적 ①(심각): showGate()는 패널만 정리하고 #body·#head-name·
    #bar는 그대로 남겨, 사용자 A 조회 → 로그아웃 → 사용자 B 로그인 경로에서
    B의 화면 위에 A가 조회한 회사의 실명이 그대로 보였다. showGate()는
    로그아웃뿐 아니라 세션 만료 경로도 공유하므로, 여기 한 곳에서 비워야
    화면을 떠나는 모든 경로가 한 번에 덮인다.

    (①의 실제 재현·수정 확인은 node vm 가짜 DOM으로 별도 검증했다 — 사용자
    A가 조회한 표를 렌더한 뒤 doLogout()을 호출해 #body·#head-name·#bar가
    실제로 비는지까지 실행해서 확인했다. 이 클래스는 그 수정이 되돌아오지
    않도록 잠그는 정적 회귀 테스트다.)
    """

    def test_show_gate_clears_head_name(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "showGate")
        m = re.search(
            r'(\w+)\s*=\s*document\.getElementById\(\s*["\']head-name["\']\s*\)', body
        )
        self.assertIsNotNone(
            m, "showGate가 head-name 엘리먼트를 참조하지 않습니다 — 이전 "
               "사용자의 헤더 문구가 남을 수 있습니다",
        )
        self.assertRegex(
            body, re.escape(m.group(1)) + r'\.textContent\s*=\s*["\']["\']',
            "showGate가 head-name 내용을 비우지 않습니다",
        )

    def test_show_gate_clears_bar(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "showGate")
        m = re.search(
            r'(\w+)\s*=\s*document\.getElementById\(\s*["\']bar["\']\s*\)', body
        )
        self.assertIsNotNone(
            m, "showGate가 bar 엘리먼트를 참조하지 않습니다 — 이전 진행률 "
               "문구가 남을 수 있습니다",
        )
        self.assertRegex(
            body, re.escape(m.group(1)) + r'\.textContent\s*=\s*["\']["\']',
            "showGate가 bar 내용을 비우지 않습니다",
        )

    def test_show_gate_clears_body_section_list(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "showGate")
        m = re.search(
            r'(\w+)\s*=\s*document\.getElementById\(\s*["\']body["\']\s*\)', body
        )
        self.assertIsNotNone(
            m, "showGate가 body 엘리먼트를 참조하지 않습니다 — 이전 회사의 "
               "섹션이 남을 수 있습니다",
        )
        var_name = m.group(1)
        self.assertRegex(
            body,
            r"while\s*\(\s*" + re.escape(var_name) + r"\.firstChild\s*\)\s*"
            + re.escape(var_name) + r"\.removeChild\(",
            "showGate가 body의 기존 섹션을 비우는 while 루프를 갖고 있지 "
            "않습니다 — 이전 사용자가 조회한 회사의 실명 표가 다음 사용자 "
            "화면에 남을 수 있습니다",
        )

    def test_do_logout_no_longer_duplicates_screen_clearing(self):
        """CURRENT_COMPANY·actor-btn 초기화가 showGate()로 옮겨졌으므로
        doLogout()이 다시 갖고 있으면 두 곳에서 같은 처리를 하게 된다 —
        한쪽만 고치고 잊어버리는 사고가 되풀이된다. 설명 주석 속 언급까지
        "중복 코드"로 착각하지 않도록 주석을 지운 뒤 확인한다."""
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "doLogout")
        code_only = _strip_js_comments(body)
        self.assertNotIn("CURRENT_COMPANY", code_only,
                         "doLogout이 CURRENT_COMPANY 정리를 중복으로 갖고 "
                         "있습니다 — showGate()로 옮겼으면 여기 있으면 안 "
                         "됩니다")


class TestPollingGenerationPreventsConcurrentLoops(unittest.TestCase):
    """리뷰 지적 ②(심각): 이어받기 루프(resumeIfAny)가 도는 중 새 분석
    (analyze)이 시작되면, 늦게 도착한 옛 루프의 응답이 새 화면 위에 섞이고
    옛 루프의 forgetJob()이 새 작업의 se_job을 지운다. POLL_GEN 세대
    토큰으로 언제나 최신 루프만 그리고, 자기 작업이 아니면 정리도 하지
    않아야 한다.

    (②의 실제 재현·수정 확인은 node vm 가짜 DOM + 지연 가능한 fetch
    목업으로 별도 검증했다 — 이어받기 루프의 응답을 일부러 붙잡아 둔 채
    새 분석을 시작·완료시키고, 붙잡아 둔 응답을 뒤늦게 흘려보내 화면·
    localStorage가 섞이지 않는지까지 실행해서 확인했다. 이 클래스는 그
    수정이 되돌아오지 않도록 잠그는 정적 회귀 테스트다.)
    """

    def test_poll_until_done_takes_a_generation_token_and_checks_it(self):
        src = _sources()["ui.js"]
        m = re.search(
            r"async\s+function\s+pollUntilDone\s*\(\s*\w+\s*,\s*\w+\s*,\s*(\w+)\s*\)",
            src,
        )
        self.assertIsNotNone(
            m, "pollUntilDone이 세대 토큰(gen) 인자를 받지 않습니다 — 늦게 "
               "도착한 옛 루프의 응답을 걸러낼 방법이 없습니다",
        )
        gen_param = m.group(1)
        body = _extract_function_body(src, "pollUntilDone")
        checks = re.findall(
            r"\b" + re.escape(gen_param) + r"\s*!==\s*POLL_GEN\b", body,
        )
        self.assertGreaterEqual(
            len(checks), 2,
            "pollUntilDone이 루프 도중 여러 지점에서 세대가 여전히 최신인지 "
            "확인하지 않습니다 — 응답을 기다리는 동안 더 새 루프가 시작돼도 "
            "계속 화면을 그릴 수 있습니다",
        )

    def test_analyze_and_resume_if_any_bump_the_generation_before_polling(self):
        src = _sources()["ui.js"]
        for name in ("analyze", "resumeIfAny"):
            body = _extract_function_body(src, name)
            self.assertRegex(
                body, r"\+\+POLL_GEN\b",
                f"{name}이 폴링을 시작하기 전에 세대 토큰(POLL_GEN)을 올리지 "
                "않습니다",
            )
            # pollUntilDone(...) 호출 인자에 중첩 괄호(예:
            # localStorage.getItem(LS_DART_KEY))가 섞일 수 있어 `[^)]*`로는
            # 못 잡는다 — 괄호 균형을 실제로 세어 호출 전체를 추출한다.
            call_m = re.search(r"pollUntilDone\(", body)
            self.assertIsNotNone(
                call_m, f"{name}이 pollUntilDone을 부르지 않습니다",
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
            self.assertIsNotNone(call_end, "pollUntilDone(...) 호출의 닫는 괄호를 찾지 못했습니다")
            call_expr = body[call_m.start():call_end]
            self.assertRegex(
                call_expr, r"\bgen\b",
                f"{name}이 자기가 올린 세대 번호를 pollUntilDone에 넘기지 "
                "않습니다",
            )

    def test_forget_job_is_guarded_by_generation_ownership(self):
        """세대가 이미 지나간 루프가 forgetJob()을 부르면 방금 시작된 새
        작업의 se_job을 지워버릴 수 있다 — gen === POLL_GEN일 때만 정리해야
        한다.
        """
        src = _sources()["ui.js"]
        for name in ("analyze", "resumeIfAny"):
            body = _extract_function_body(src, name)
            m = re.search(r"if\s*\(\s*gen\s*===\s*POLL_GEN\s*\)\s*\{", body)
            self.assertIsNotNone(
                m, f"{name}이 gen === POLL_GEN 확인 없이 뒷정리를 할 수 "
                   "있습니다 — 더 새 작업의 se_job·헤더를 건드릴 수 있습니다",
            )
            guard_block = _extract_braced_block(body, m.end() - 1)
            self.assertIn(
                "forgetJob(", guard_block,
                f"{name}의 forgetJob() 호출이 세대 확인 밖에 있습니다",
            )


class TestResumeMessagePromiseIsKept(unittest.TestCase):
    """리뷰 지적 ③(중간): 네트워크가 끊겨 "새로고침하면 이어받습니다"를
    띄운 직후 forgetJob()을 무조건 부르면 새로고침해도 이어받지 못해
    문구가 거짓말이 된다. pollUntilDone이 그 경로에서 resumable:true를
    돌려주고, 호출부가 그 값을 실제로 확인해 forgetJob()을 건너뛰어야 한다.
    """

    def test_network_disconnect_branch_reports_resumable(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "pollUntilDone")
        m = re.search(r'showBar\(\s*"연결이 끊겨[^"]*"\s*\)\s*;', body)
        self.assertIsNotNone(
            m, "pollUntilDone에 연결 끊김 안내 문구가 없습니다",
        )
        tail = body[m.end():m.end() + 200]
        self.assertRegex(
            tail, r"resumable\s*:\s*true",
            "연결 끊김 안내 직후 resumable:true를 돌려주지 않습니다 — "
            "호출부가 이 값 없이는 새로고침 시 이어받기를 보장할 수 없습니다",
        )

    def test_analyze_and_resume_if_any_skip_forget_job_when_resumable(self):
        src = _sources()["ui.js"]
        for name in ("analyze", "resumeIfAny"):
            body = _extract_function_body(src, name)
            self.assertRegex(
                body, r"!\s*result\.resumable",
                f"{name}이 result.resumable을 확인하지 않고 forgetJob()을 "
                "부를 수 있습니다 — \"새로고침하면 이어받습니다\" 안내가 "
                "거짓말이 됩니다",
            )


class TestHeadNameReflectsCompletion(unittest.TestCase):
    """리뷰 지적 ④(중간): 분석이 끝나도 #head-name이 "N 분석을 시작합니다…"
    에서 그대로다 — 완료 상태가 화면에 드러나지 않는다.
    """

    def test_render_head_done_updates_head_name(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "renderHeadDone")
        self.assertRegex(
            body, r'getElementById\(\s*["\']head-name["\']\s*\)',
            "renderHeadDone이 head-name 엘리먼트를 건드리지 않습니다",
        )
        self.assertIn("textContent", body,
                      "renderHeadDone이 textContent를 갱신하지 않습니다")

    def test_analyze_and_resume_if_any_call_render_head_done_on_success(self):
        src = _sources()["ui.js"]
        for name in ("analyze", "resumeIfAny"):
            body = _extract_function_body(src, name)
            self.assertIn(
                "renderHeadDone(", body,
                f"{name}이 완료 시 renderHeadDone()을 부르지 않습니다 — "
                "분석이 끝나도 헤더가 시작 문구 그대로 남습니다",
            )


class TestAnalyzeFailureClearsPreviousScreen(unittest.TestCase):
    """리뷰 지적 5(낮음): analyze()가 201이 아닐 때 renderHeadPlaceholder를
    안 불러서, 이전 회사 본문 위에 오류만 표시됐다.
    """

    def test_non_201_branch_calls_render_head_placeholder(self):
        src = _sources()["ui.js"]
        body = _extract_function_body(src, "analyze")
        m = re.search(r"if\s*\(\s*created\.status\s*!==\s*201\s*\)\s*\{", body)
        self.assertIsNotNone(m, "analyze가 201이 아닌 응답을 확인하지 않습니다")
        guard_block = _extract_braced_block(body, m.end() - 1)
        self.assertIn(
            "renderHeadPlaceholder(", guard_block,
            "analyze가 실패 시 renderHeadPlaceholder를 부르지 않습니다 — "
            "이전 회사의 본문·헤더가 오류 문구 아래 그대로 남습니다",
        )


class TestLsJobConstantLivesWithOtherStorageKeys(unittest.TestCase):
    """리뷰 지적 6(낮음): LS_JOB 상수만 ui.js에 있어 다른 LS_*
    상수(LS_DART_KEY·LS_SESSION, app.js)와 위치가 어긋났다.
    """

    def test_ls_job_is_declared_in_app_js_not_ui_js(self):
        app_src = _sources()["app.js"]
        ui_src = _sources()["ui.js"]
        self.assertRegex(
            app_src, r'const\s+LS_JOB\s*=\s*"se_job"',
            "LS_JOB이 app.js로 옮겨지지 않았습니다",
        )
        self.assertNotRegex(
            ui_src, r'const\s+LS_JOB\s*=',
            "ui.js가 여전히 자체 LS_JOB을 선언합니다 — 저장소 키가 두 "
            "파일에 흩어져 있습니다",
        )



class TestAssetPathsSurviveTrailingSlashRedirect(unittest.TestCase):
    """페이지가 부르는 스크립트·스타일이 배포 후에도 실제로 로드되는지 본다.

    실제 배포에서 겪은 실패다: `index.html`이 `<script src="app.js">`처럼
    상대경로를 썼는데, `vercel.json`의 `trailingSlash: false`가 `/se/`를
    `/se`로 되돌린다. 슬래시가 없는 `/se`에서 브라우저는 현재 디렉토리를
    루트로 보므로 `app.js`를 `/app.js`로 해석해 **404**를 받는다.

    증상이 고약했다 — 스크립트가 통째로 로드되지 않아 로그인 버튼이 아무
    반응도 하지 않는데, 오류를 띄우는 코드마저 그 스크립트 안에 있어
    화면에는 아무 안내도 뜨지 않는다. 파일 내용만 검사하는 다른 테스트들은
    전부 초록이었다. 파일은 멀쩡했고, 브라우저가 요청하는 **주소**가
    틀렸기 때문이다.

    그래서 이 테스트는 내용이 아니라 **경로 해석**을 검사한다.
    """

    # vercel.json의 outputDirectory. 여기가 배포 루트(/)가 된다.
    _OUTPUT_DIR = _ROOT / "docs" / "tool"

    def _local_refs(self):
        """HTML이 참조하는 로컬 자산 (파일명, 원본 URL) 목록."""
        refs = []
        for name, src in _sources().items():
            if not name.endswith(".html"):
                continue
            for m in re.finditer(
                r'<(?:script|link)[^>]*\b(?:src|href)="([^"]+)"', src
            ):
                url = m.group(1)
                if url.startswith(("http://", "https://", "//", "data:", "#")):
                    continue  # 외부 참조는 다른 테스트가 막는다
                refs.append((name, url))
        return refs

    def test_there_is_at_least_one_local_asset(self):
        """참조가 하나도 없으면 아래 검사들이 공허하게 통과한다."""
        self.assertTrue(self._local_refs(),
                        "검사할 로컬 자산 참조를 찾지 못했습니다")

    def test_local_assets_use_root_absolute_paths(self):
        offenders = [
            f"{name}: {url}" for name, url in self._local_refs()
            if not url.startswith("/")
        ]
        self.assertEqual(
            offenders, [],
            "상대경로로 자산을 부르고 있습니다. trailingSlash:false 때문에 "
            "/se/ 가 /se 로 되돌아가면 상대경로는 루트 기준으로 해석돼 404가 "
            "납니다. `/se/app.js`처럼 루트 기준 절대경로를 쓰세요:\n  "
            + "\n  ".join(offenders),
        )

    def test_referenced_assets_actually_exist_in_the_deployed_tree(self):
        """경로가 절대적이어도 가리키는 파일이 없으면 똑같이 404다."""
        missing = []
        for name, url in self._local_refs():
            target = self._OUTPUT_DIR / url.lstrip("/").split("?")[0]
            if not target.exists():
                missing.append(f"{name}: {url} → {target} 없음")
        self.assertEqual(
            missing, [],
            "참조하는 자산 파일이 배포 트리에 없습니다:\n  " + "\n  ".join(missing),
        )

class TestLayoutAndTheme(unittest.TestCase):
    """Task 5: 2단 레이아웃·좌측 목차·라이트 모드 토글.

    SE-4b에서 "정의만 있고 배선이 없다" 사고가 두 번(우측 패널, 회사 입력
    폼) 났다 — 여기서도 같은 부류의 사고를 막는다. 라이트 모드는 CSS
    변수를 일부만 덮으면 배경만 밝아지고 글자는 다크 모드 색 그대로 남아
    안 보이게 되므로, "일부만 덮음"을 기계적으로 잡는 테스트를 둔다.
    """

    def test_toc_and_two_column_grid_exist(self):
        html = _sources()["index.html"]
        self.assertIn('id="toc"', html)
        self.assertRegex(html, r"grid-template-columns")

    def test_theme_toggle_is_wired_not_dead(self):
        """SE-4b에서 배선 없는 함수가 두 번 나왔다. 같은 일을 막는다."""
        ui = _sources()["ui.js"]
        body = _extract_function_body(ui, "init")
        self.assertIn("theme", body, "init에서 테마 토글을 배선하지 않습니다")

    def test_theme_toggle_button_has_a_real_click_listener(self):
        """위 test_theme_toggle_is_wired_not_dead는 "theme"라는 글자만
        본다 — document.getElementById("theme-toggle")처럼 아무 동작도
        없는 참조 한 줄만 남아도 그 글자가 있어 통과해버린다
        (TestAnalyzeFormIsWiredAndReachable이 analyze-btn에 쓰는 것과
        같은 더 엄격한 검사를 여기도 둔다)."""
        src = _sources()["ui.js"]
        self.assertRegex(
            src,
            r'getElementById\(\s*["\']theme-toggle["\']\s*\)'
            r'[^;]*addEventListener\(\s*["\']click["\']',
            "theme-toggle 버튼에 클릭 리스너가 연결돼 있지 않습니다",
        )

    def test_theme_choice_is_persisted(self):
        self.assertIn("se_theme", _sources()["app.js"] + _sources()["ui.js"])

    def test_light_theme_overrides_every_dark_variable(self):
        """일부 변수만 덮으면 라이트 모드에서 글자가 안 보인다."""
        html = _sources()["index.html"]
        dark = set(re.findall(r"(--[a-z0-9-]+)\s*:", html.split('[data-theme="light"]')[0]))
        light = set(re.findall(r"(--[a-z0-9-]+)\s*:", html.split('[data-theme="light"]')[1]))
        missing = sorted(v for v in dark if v not in light and not v.startswith("--mono"))
        self.assertEqual(missing, [], f"라이트 모드에 없는 변수: {missing}")

    def test_narrow_screen_falls_back_to_one_column(self):
        self.assertRegex(_sources()["index.html"], r"@media[^{]*max-width")


if __name__ == "__main__":
    unittest.main()
