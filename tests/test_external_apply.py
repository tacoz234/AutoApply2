"""Unit tests for External Apply flow, search input filtering, and session persistence."""

import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright
from src.extractor import FormExtractor
from src.storage import StorageManager, UserProfile
from fastapi.testclient import TestClient
from src.gui_server import app


class TestExternalApplyAndPersistence(unittest.TestCase):
    def setUp(self):
        self.profile_path = Path("data/user_profile.json")
        self.orig_profile_data = self.profile_path.read_text(encoding="utf-8") if self.profile_path.exists() else None

    def tearDown(self):
        if self.orig_profile_data is not None and self.profile_path.exists():
            self.profile_path.write_text(self.orig_profile_data, encoding="utf-8")

    def test_linkedin_search_inputs_not_mistaken_for_application_form(self):
        """Verifies that LinkedIn header and search bars are never treated as application forms."""
        linkedin_html = """<!DOCTYPE html>
        <html>
        <head><title>Systems Engineer - Amazon | LinkedIn</title></head>
        <body>
          <header class="global-nav">
            <input type="search" class="search-global-typeahead__input" placeholder="Describe the job you want">
            <input type="text" class="jobs-search-box__input" placeholder="City, state, or zip code">
          </header>
          <main>
            <div class="job-details-jobs-unified-top-card">
              <h1 class="job-title">Systems Engineer, Controls Fleet</h1>
              <div class="company-name">Amazon Web Services (AWS)</div>
              <div class="jobs-apply-button--top-card">
                <button class="jobs-apply-button" aria-label="Apply to Systems Engineer">
                  <span>Apply</span>
                </button>
              </div>
            </div>
            <div class="jobs-description">Job description text...</div>
          </main>
        </body>
        </html>
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            # Route a fake linkedin URL to the HTML
            page.route("https://www.linkedin.com/jobs/view/12345", lambda route: route.fulfill(
                status=200, content_type="text/html", body=linkedin_html
            ))
            page.goto("https://www.linkedin.com/jobs/view/12345")

            extractor = FormExtractor(page)

            # 1. _is_form_visible should be False because we are on LinkedIn without an Easy Apply modal
            self.assertFalse(extractor._is_form_visible())

            # 2. scan_form_fields should be empty (NOT extracting "Describe the job you want")
            fields = extractor.scan_form_fields()
            self.assertEqual(len(fields), 0)

            # 3. If LinkedIn Easy Apply modal appears, _is_form_visible becomes True
            page.evaluate("""() => {
              const modal = document.createElement('div');
              modal.className = 'jobs-easy-apply-modal';
              modal.innerHTML = '<input type="text" id="phone" name="phone"><input type="file" id="resume">';
              document.body.appendChild(modal);
            }""")
            self.assertTrue(extractor._is_form_visible())

            # Now fields should only extract the modal inputs, not "Describe the job you want"
            modal_fields = extractor.scan_form_fields()
            labels = [f.label.lower() for f in modal_fields]
            self.assertFalse(any("describe the job you want" in l for l in labels))

            browser.close()

    def test_external_apply_navigation_to_new_site(self):
        """Verifies clicking external Apply transitions to the new page / ATS."""
        linkedin_html = """<!DOCTYPE html>
        <html>
        <head><title>Job on LinkedIn</title></head>
        <body>
          <div class="jobs-apply-button--top-card">
            <button class="jobs-apply-button" onclick="window.open('https://amazon.jobs/apply/123', '_blank')">Apply</button>
          </div>
        </body>
        </html>
        """
        amazon_html = """<!DOCTYPE html>
        <html>
        <head><title>Apply to Amazon</title></head>
        <body>
          <form id="application_form">
            <label for="full_name">Full Name</label>
            <input type="text" id="full_name" name="full_name">
            <label for="email">Email</label>
            <input type="email" id="email" name="email">
            <input type="file" id="resume" name="resume">
          </form>
        </body>
        </html>
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            page.route("https://www.linkedin.com/jobs/view/12345", lambda route: route.fulfill(
                status=200, content_type="text/html", body=linkedin_html
            ))
            context.route("https://amazon.jobs/apply/123", lambda route: route.fulfill(
                status=200, content_type="text/html", body=amazon_html
            ))

            page.goto("https://www.linkedin.com/jobs/view/12345")
            extractor = FormExtractor(page)

            form_ready = extractor.ensure_application_form_open()
            self.assertTrue(form_ready)
            # Extractor should have switched page to amazon.jobs
            self.assertIn("amazon.jobs", extractor.page.url)

            fields = extractor.scan_form_fields()
            self.assertGreaterEqual(len(fields), 2)

            browser.close()

    def test_candidate_profile_persistence(self):
        """Verifies candidate profile and resume file persist across sessions."""
        client = TestClient(app)

        # 1. Upload sample resume
        with open("data/sample_resume.pdf", "rb") as f:
            resp = client.post("/api/resume/upload", files={"file": ("persist_test_resume.pdf", f, "application/pdf")})
        self.assertEqual(resp.status_code, 200)

        # 2. Verify that profile is immediately saved in storage
        sm = StorageManager()
        prof = sm.load_profile()
        self.assertEqual(prof.resume_file, "persist_test_resume.pdf")
        self.assertTrue(prof.is_setup_completed)
        self.assertEqual(prof.personal.full_name.upper(), "ALEX CHEN")

        # 3. Clean up the test file
        test_file = Path("data/persist_test_resume.pdf")
        if test_file.exists():
            test_file.unlink()


if __name__ == "__main__":
    unittest.main()
