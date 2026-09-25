"""Unit tests for ResumeParser and First-Time Setup lifecycle."""

from pathlib import Path
import unittest
from src.resume_parser import ResumeParser
from src.storage import StorageManager, UserProfile


class TestResumeParser(unittest.TestCase):
    def setUp(self):
        self.parser = ResumeParser()
        self.sample_pdf = Path("data/sample_resume.pdf")

    def test_extract_text_from_pdf(self):
        """Verifies text extraction from sample resume PDF."""
        self.assertTrue(self.sample_pdf.exists(), "data/sample_resume.pdf must exist")
        text = self.parser.extract_text_from_file(self.sample_pdf)
        self.assertIn("ALEX CHEN", text.upper())
        self.assertIn("alex.chen.dev@example.com", text)

    def test_parse_heuristics(self):
        """Verifies deterministic regex parsing for essential candidate fields."""
        sample_text = """
        SARAH J. CONNOR - Principal Infrastructure Architect
        Email: sarah.connor@cyberdyne.io | Phone: (415) 555-8920
        Location: Austin, TX 78701
        LinkedIn: linkedin.com/in/sarah-connor-infra | GitHub: github.com/sconnor
        Portfolio: https://sarahconnor.tech

        SKILLS:
        Python, Kubernetes, Docker, Go, AWS, Terraform, PostgreSQL, Redis, CI/CD, Microservices
        """
        parsed = self.parser.parse_heuristics(sample_text)
        self.assertEqual(parsed["full_name"], "SARAH J. CONNOR")
        self.assertEqual(parsed["email"], "sarah.connor@cyberdyne.io")
        self.assertEqual(parsed["phone"], "(415) 555-8920")
        self.assertEqual(parsed["city"], "Austin")
        self.assertEqual(parsed["state"], "TX")
        self.assertEqual(parsed["postal_code"], "78701")
        self.assertIn("sarah-connor-infra", parsed["linkedin"])
        self.assertIn("sconnor", parsed["github"])
        self.assertIn("sarahconnor.tech", parsed["portfolio"])
        self.assertIn("Python", parsed["skills"])
        self.assertIn("Kubernetes", parsed["skills"])
        self.assertIn("Docker", parsed["skills"])

    def test_setup_completion_lifecycle(self):
        """Verifies setup completion persistence and toggle."""
        storage = StorageManager()
        # Test toggle
        storage.set_setup_completed(False)
        profile = storage.load_profile()
        self.assertFalse(profile.is_setup_completed)

        storage.set_setup_completed(True)
        profile = storage.load_profile()
        self.assertTrue(profile.is_setup_completed)

        # Reset back to False for clean onboarding experience
        storage.set_setup_completed(False)
        self.assertFalse(storage.load_profile().is_setup_completed)

    def test_save_uploaded_resume(self):
        """Verifies that an uploaded resume binary is written to data/ and linked to profile."""
        storage = StorageManager()
        orig_resume = storage.load_profile().resume_file
        dummy_content = b"%PDF-1.4 dummy test resume content"
        filename = storage.save_uploaded_resume(dummy_content, "candidate_resume_test.pdf")

        self.assertEqual(filename, "candidate_resume_test.pdf")
        saved_path = storage.profile_path.parent / filename
        self.assertTrue(saved_path.exists())

        profile = storage.load_profile()
        self.assertEqual(profile.resume_file, "candidate_resume_test.pdf")

        # Clean up test file and restore profile
        if saved_path.exists():
            saved_path.unlink()
        profile.resume_file = orig_resume
        storage.save_profile(profile)

    def test_gui_endpoints(self):
        """Verifies GUI API endpoints for resume upload and setup status."""
        from fastapi.testclient import TestClient
        from src.gui_server import app

        client = TestClient(app)

        # 1. GET /api/setup/status
        resp = client.get("/api/setup/status")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("is_setup_completed", resp.json())

        # 2. POST /api/resume/upload
        with open("data/sample_resume.pdf", "rb") as f:
            up_resp = client.post("/api/resume/upload", files={"file": ("upload_test_resume.pdf", f, "application/pdf")})
        self.assertEqual(up_resp.status_code, 200)
        up_data = up_resp.json()
        self.assertEqual(up_data["status"], "success")
        self.assertIn("profile", up_data)
        self.assertEqual(up_data["profile"]["personal"]["full_name"], "Alex Chen")

        # 3. POST /api/setup/complete with QA answers
        setup_payload = {
            "profile": up_data["profile"],
            "qa_answers": {
                "work_authorization_us": "Yes",
                "notice_period": "3 weeks",
            },
            "custom_qa": [
                {"question": "Are you 21 or older?", "answer": "Yes", "category": "legal"}
            ]
        }
        comp_resp = client.post("/api/setup/complete", json=setup_payload)
        self.assertEqual(comp_resp.status_code, 200)
        self.assertIn("qa_bank", comp_resp.json())

        # Verify QA entry updated
        qa_entries = {e["id"]: e["answer"] for e in comp_resp.json()["qa_bank"]}
        self.assertEqual(qa_entries.get("notice_period"), "3 weeks")

        # 4. Verify status is now True
        stat_resp = client.get("/api/setup/status")
        self.assertTrue(stat_resp.json()["is_setup_completed"])

        # 5. Reset back to False
        reset_resp = client.post("/api/setup/reset")
        self.assertEqual(reset_resp.status_code, 200)
        self.assertFalse(reset_resp.json()["is_setup_completed"])

        # Clean up uploaded test file and reset profile
        test_file = Path("data/upload_test_resume.pdf")
        if test_file.exists():
            test_file.unlink()
        sm = StorageManager()
        p = sm.load_profile()
        p.resume_file = "sample_resume.pdf"
        sm.save_profile(p)


if __name__ == "__main__":
    unittest.main()
