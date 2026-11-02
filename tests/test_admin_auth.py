"""Security regression tests for server-side administrator authorization."""
import hashlib
import os
import unittest

os.environ.setdefault(
    "DATABASE_URL",
    "sqlite:///file:echo_admin_auth_tests?mode=memory&cache=shared&uri=true",
)
os.environ["ECHO_ADMIN_COOKIE_SECURE"] = "0"  # TestClient uses HTTP; production defaults to Secure.

from fastapi.testclient import TestClient
import main


TEST_USERNAME = "admin-test-user"
TEST_PASSWORD = "test-only-password-with-24-characters"


class AdminAuthTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        salt = b"test-only-salt-0123456789"
        digest = hashlib.pbkdf2_hmac("sha256", TEST_PASSWORD.encode(), salt, 300_000, dklen=32)
        main.ADMIN_USERNAME = TEST_USERNAME
        main.ADMIN_PASSWORD_HASH = f"pbkdf2_sha256$300000${salt.hex()}${digest.hex()}"
        main.ADMIN_COOKIE_SECURE = False
        cls.client = TestClient(main.app)

    def setUp(self):
        self.client.cookies.clear()
        with main._ADMIN_SESSION_LOCK:
            main._ADMIN_SESSIONS.clear()
        with main._ADMIN_LOGIN_LOCK:
            main._ADMIN_LOGIN_ATTEMPTS.clear()

    def login(self, username=TEST_USERNAME, password=TEST_PASSWORD):
        return self.client.post("/api/host/login", json={"username": username, "password": password})

    def test_unauthenticated_admin_data_and_mutations_are_rejected(self):
        requests = [
            ("get", "/api/programs", None),
            ("get", "/api/activities?status=Draft", None),
            ("get", "/api/activities/1?view=host", None),
            ("post", "/api/activities", {"title": "x", "start_time": "2026-01-01", "end_time": "2026-01-02"}),
            ("patch", "/api/activities/1/status", {"status": "Published"}),
            ("patch", "/api/registrations/1/checkin", {"checked_in": True}),
            ("patch", "/api/requirements/1", {"status": "Arranged"}),
        ]
        for method, path, body in requests:
            response = getattr(self.client, method)(path, json=body) if body is not None else getattr(self.client, method)(path)
            with self.subTest(method=method, path=path):
                self.assertEqual(response.status_code, 401)

    def test_student_and_visitor_role_claims_do_not_authorize(self):
        for role in ("STUDENT", "VISITOR", "ADMIN"):
            response = self.client.post(
                "/api/activities",
                headers={"X-Role": role},
                json={"title": "x", "start_time": "2026-01-01", "end_time": "2026-01-02"},
            )
            with self.subTest(role=role):
                self.assertEqual(response.status_code, 401)

    def test_invalid_credentials_use_generic_message(self):
        response = self.login(username="wrong-user", password="wrong-password")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.json().get("detail"), "Invalid username or password")
        self.assertNotIn("test-only", response.text)

    def test_unconfigured_backend_has_no_default_admin_account(self):
        configured_username, configured_hash = main.ADMIN_USERNAME, main.ADMIN_PASSWORD_HASH
        try:
            main.ADMIN_USERNAME = None
            main.ADMIN_PASSWORD_HASH = None
            response = self.login(username="anything", password="anything")
            self.assertEqual(response.status_code, 401)
            self.assertEqual(response.json().get("detail"), "Invalid username or password")
            self.assertNotIn("set-cookie", response.headers)
        finally:
            main.ADMIN_USERNAME, main.ADMIN_PASSWORD_HASH = configured_username, configured_hash

    def test_correct_credentials_issue_http_only_same_site_session_cookie(self):
        response = self.login()
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json()["success"])
        self.assertNotIn("token", response.json())
        self.assertNotIn(TEST_USERNAME, response.text)
        self.assertNotIn(TEST_PASSWORD, response.text)
        cookie = response.headers["set-cookie"].lower()
        self.assertIn("httponly", cookie)
        self.assertIn("samesite=strict", cookie)
        self.assertIn("path=/api", cookie)
        self.assertEqual(self.client.get("/api/host/session").status_code, 200)
        self.assertEqual(self.client.get("/api/programs").status_code, 200)
        self.assertEqual(self.client.get("/api/activities?status=Draft").status_code, 200)
        created = self.client.post("/api/activities", json={
            "title": "Test-only protected activity",
            "start_time": "2026-01-01T10:00:00",
            "end_time": "2026-01-01T11:00:00",
        })
        self.assertEqual(created.status_code, 200)
        activity_id = created.json()["id"]
        self.assertEqual(self.client.get(f"/api/activities/{activity_id}?view=host").status_code, 200)
        visitor = TestClient(main.app)
        self.assertEqual(visitor.get(f"/api/activities/{activity_id}?view=student").status_code, 404)
        self.assertEqual(self.client.patch(
            f"/api/activities/{activity_id}/status", json={"status": "Published"}
        ).status_code, 200)
        self.assertEqual(visitor.get(f"/api/activities/{activity_id}?view=student").status_code, 200)

    def test_secure_cookie_flag_can_be_enabled_for_https_host(self):
        previous = main.ADMIN_COOKIE_SECURE
        try:
            main.ADMIN_COOKIE_SECURE = True
            response = self.login()
            self.assertEqual(response.status_code, 200)
            self.assertIn("secure", response.headers["set-cookie"].lower())
        finally:
            main.ADMIN_COOKIE_SECURE = previous
            self.client.cookies.clear()

    def test_admin_auth_responses_are_not_cached(self):
        response = self.login()
        self.assertEqual(response.headers.get("cache-control"), "no-store")
        self.assertEqual(self.client.get("/api/host/session").headers.get("cache-control"), "no-store")

    def test_logout_revokes_session_and_expired_cookie_cannot_restore_access(self):
        self.assertEqual(self.login().status_code, 200)
        self.assertEqual(self.client.get("/api/host/session").status_code, 200)
        self.assertEqual(self.client.post("/api/host/logout").status_code, 204)
        self.assertEqual(self.client.get("/api/host/session").status_code, 401)
        self.assertEqual(self.client.get("/api/activities?status=Draft").status_code, 401)

    def test_public_event_reads_remain_available(self):
        self.assertEqual(self.client.get("/api/activities").status_code, 200)
        self.assertEqual(self.client.get("/api/activities/999999?view=student").status_code, 404)

    def test_public_login_assets_contain_no_prefilled_admin_credentials(self):
        html = (main.ROOT_DIR / "index.html").read_text(encoding="utf-8")
        js = (main.ROOT_DIR / "script.js").read_text(encoding="utf-8")
        self.assertIn('id="admin-login-error"', html)
        self.assertNotRegex(html, r'id="admin-username"[^>]*\svalue=')
        self.assertNotRegex(html, r'id="admin-password"[^>]*\svalue=')
        backend = main.Path(main.__file__).read_text(encoding="utf-8")
        self.assertNotIn("HOSTS =", backend)
        self.assertNotIn("coach" + "123", js)
        self.assertNotIn("dean" + "123", js)


if __name__ == "__main__":
    unittest.main()
