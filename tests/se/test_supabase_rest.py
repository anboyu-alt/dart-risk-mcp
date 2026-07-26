"""Supabase REST 인증 헤더 — legacy JWT와 신형 secret 키를 모두 지원한다."""
import unittest

from se_server.supabase_rest import auth_headers, looks_like_jwt

# legacy service_role 키 형태 (base64url 3파트). 실제 값이 아니다.
LEGACY = "eyJhbGciOiJIUzI1NiJ9.eyJyb2xlIjoic2VydmljZV9yb2xlIn0.c2lnbmF0dXJl"
# 신형 secret 키 형태. 실제 값이 아니다.
NEW = "sb_secret_EXAMPLE-NOT-REAL"


class TestLooksLikeJwt(unittest.TestCase):
    def test_legacy_service_role_is_jwt(self):
        self.assertTrue(looks_like_jwt(LEGACY))

    def test_new_secret_key_is_not_jwt(self):
        self.assertFalse(looks_like_jwt(NEW))

    def test_new_publishable_key_is_not_jwt(self):
        self.assertFalse(looks_like_jwt("sb_publishable_EXAMPLE-NOT-REAL"))

    def test_empty_is_not_jwt(self):
        self.assertFalse(looks_like_jwt(""))

    def test_two_parts_is_not_jwt(self):
        self.assertFalse(looks_like_jwt("header.payload"))

    def test_four_parts_is_not_jwt(self):
        self.assertFalse(looks_like_jwt("a.b.c.d"))

    def test_empty_segment_is_not_jwt(self):
        """빈 조각이 있으면 JWT가 아니다 — "..".split(".")는 3파트지만 전부 빈 값이다."""
        self.assertFalse(looks_like_jwt(".."))
        self.assertFalse(looks_like_jwt("a..c"))

    def test_non_string_is_not_jwt(self):
        for bad in (None, 123, b"a.b.c", []):
            with self.subTest(value=bad):
                self.assertFalse(looks_like_jwt(bad))


class TestAuthHeaders(unittest.TestCase):
    def test_apikey_is_always_sent(self):
        for key in (LEGACY, NEW):
            with self.subTest(key=key[:12]):
                self.assertEqual(auth_headers(key)["apikey"], key)

    def test_legacy_gets_authorization(self):
        """legacy 키는 JWT라 Authorization도 필요하다 — Storage 등이 이를 본다."""
        self.assertEqual(auth_headers(LEGACY)["Authorization"], f"Bearer {LEGACY}")

    def test_new_key_omits_authorization(self):
        """신형 secret 키는 JWT가 아니라 Authorization 헤더에서 거부된다."""
        self.assertNotIn("Authorization", auth_headers(NEW))

    def test_returns_new_dict_each_call(self):
        """호출자가 헤더를 수정해도 다음 호출에 영향이 없어야 한다."""
        a = auth_headers(NEW)
        a["Content-Type"] = "application/json"
        self.assertNotIn("Content-Type", auth_headers(NEW))

    def test_empty_key_still_returns_apikey(self):
        """키가 비어 있어도 형태는 유지한다 — 실패는 서버가 판정한다."""
        self.assertEqual(auth_headers("")["apikey"], "")
        self.assertNotIn("Authorization", auth_headers(""))


if __name__ == "__main__":
    unittest.main()
