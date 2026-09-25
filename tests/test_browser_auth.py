"""Unit tests for persistent browser session and authwall detection."""

import unittest
from unittest.mock import MagicMock
from src.browser import detect_authwall_or_login, InteractiveBrowserSession
from fastapi.testclient import TestClient
from src.gui_server import app


class TestBrowserAuth(unittest.TestCase):
    def test_detect_linkedin_authwall_url(self):
        page_mock = MagicMock()
        page_mock.url = "https://www.linkedin.com/authwall?trk=rip&original_referer="
        page_mock.title.return_value = "LinkedIn Login, Sign in | LinkedIn"
        page_mock.locator.return_value.count.return_value = 0

        res = detect_authwall_or_login(page_mock)
        self.assertTrue(res["auth_required"])
        self.assertEqual(res["platform"], "LinkedIn")

    def test_detect_linkedin_login_page(self):
        page_mock = MagicMock()
        page_mock.url = "https://www.linkedin.com/login?fromSignIn=true"
        page_mock.title.return_value = "Sign In | LinkedIn"
        page_mock.locator.return_value.count.return_value = 0

        res = detect_authwall_or_login(page_mock)
        self.assertTrue(res["auth_required"])
        self.assertEqual(res["platform"], "LinkedIn")

    def test_detect_indeed_login_page(self):
        page_mock = MagicMock()
        page_mock.url = "https://secure.indeed.com/account/login"
        page_mock.title.return_value = "Sign in | Indeed"
        page_mock.locator.return_value.count.return_value = 0

        res = detect_authwall_or_login(page_mock)
        self.assertTrue(res["auth_required"])
        self.assertEqual(res["platform"], "Indeed")

    def test_normal_job_page_no_authwall(self):
        page_mock = MagicMock()
        page_mock.url = "https://boards.greenhouse.io/cloudscale/jobs/12345"
        page_mock.title.return_value = "Senior Distributed Systems Engineer - CloudScale"
        page_mock.locator.return_value.count.return_value = 0

        res = detect_authwall_or_login(page_mock)
        self.assertFalse(res["auth_required"])

    def test_browser_api_endpoints(self):
        client = TestClient(app)
        status_resp = client.get("/api/browser/status")
        self.assertEqual(status_resp.status_code, 200)
        data = status_resp.json()
        self.assertIn("is_active", data)
        self.assertIn("profile_dir", data)

    def test_credentials_api_save_and_status(self):
        client = TestClient(app)
        save_resp = client.post("/api/credentials/save", json={
            "linkedin_email": "candidate@example.com",
            "linkedin_password": "supersecretpassword123",
        })
        self.assertEqual(save_resp.status_code, 200)
        save_data = save_resp.json()
        self.assertEqual(save_data["status"], "saved")
        self.assertIn("LINKEDIN_EMAIL", save_data["updated"])

        status_resp = client.get("/api/credentials/status")
        self.assertEqual(status_resp.status_code, 200)
        status_data = status_resp.json()
        self.assertTrue(status_data["has_linkedin"])
        self.assertEqual(status_data["linkedin_email"], "candidate@example.com")

    def test_perform_automated_login_unsupported_platform(self):
        from src.browser import perform_automated_login
        page_mock = MagicMock()
        success, msg = perform_automated_login(page_mock, "unknown_platform", "test@test.com", "pass")
        self.assertFalse(success)
        self.assertIn("not currently implemented", msg)


if __name__ == "__main__":
    unittest.main()

