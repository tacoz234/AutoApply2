"""Unit tests for dropdown handling: native selects, custom ARIA comboboxes, and intelligent option matching."""

import unittest
from pathlib import Path
from playwright.sync_api import sync_playwright
from src.extractor import FormExtractor, ExtractedField
from src.filler import FormFiller, FillSummary
from src.scorer import JobScorer
from src.storage import StorageManager, UserProfile


class TestDropdownHandling(unittest.TestCase):
    def setUp(self):
        self.profile_path = Path("data/user_profile.json")
        self.orig_profile_data = self.profile_path.read_text(encoding="utf-8") if self.profile_path.exists() else None
        self.qa_path = Path("data/qa_bank.json")
        self.orig_qa_data = self.qa_path.read_text(encoding="utf-8") if self.qa_path.exists() else None

    def tearDown(self):
        if self.orig_profile_data is not None and self.profile_path.exists():
            self.profile_path.write_text(self.orig_profile_data, encoding="utf-8")
        if self.orig_qa_data is not None and self.qa_path.exists():
            self.qa_path.write_text(self.orig_qa_data, encoding="utf-8")

    def test_find_best_option_match(self):
        """Verifies intelligent option matching across exact, boolean, numeric range, and substring."""
        # Exact match
        self.assertEqual(
            FormFiller._find_best_option_match("Male", ["Female", "Male", "Decline to state"]),
            "Male"
        )

        # Boolean match
        self.assertEqual(
            FormFiller._find_best_option_match("Yes", ["No", "Yes", "Not sure"]),
            "Yes"
        )
        self.assertEqual(
            FormFiller._find_best_option_match("1", ["No", "Yes"]),
            "Yes"
        )
        self.assertEqual(
            FormFiller._find_best_option_match("No", ["Yes", "No"]),
            "No"
        )

        # Numeric range match: candidate has 3 years of experience
        options = ["No experience", "Less than 1 year", "1 - 3 years", "3 - 5 years", "5+ years"]
        # For 3 years, "3 - 5 years" is preferred over "1 - 3 years" (or matches range)
        matched = FormFiller._find_best_option_match("3", options)
        self.assertIn(matched, ["3 - 5 years", "1 - 3 years"])

        # For 0 years (matches "No experience" or "Less than 1 year")
        self.assertIn(
            FormFiller._find_best_option_match("0", options),
            ["No experience", "Less than 1 year"]
        )

        # For 6 years
        self.assertEqual(
            FormFiller._find_best_option_match("6", options),
            "5+ years"
        )

        # Substring / partial match
        veteran_options = ["I am a protected veteran", "I am not a protected veteran", "Decline to self-identify"]
        self.assertEqual(
            FormFiller._find_best_option_match("not a protected veteran", veteran_options),
            "I am not a protected veteran"
        )

    def test_extract_and_fill_custom_aria_dropdown(self):
        """Simulates Amazon Jobs / Cloudscape custom ARIA select dropdown component."""
        amazon_jobs_html = """<!DOCTYPE html>
        <html>
        <head><title>Amazon Jobs Application</title></head>
        <body>
          <main>
            <h1>Job-specific questions</h1>

            <!-- Question 1: Custom Cloudscape Select with aria-labelledby -->
            <div class="awsui-form-field">
              <div class="awsui-form-field-label">
                <label id="q1-label">Which option best describes your total Linux systems administration or devops/software development experience? <span>*</span></label>
              </div>
              <div class="awsui-form-field-control">
                <div class="awsui-select">
                  <button type="button" id="q1-trigger" class="awsui-select-trigger" aria-haspopup="listbox" aria-expanded="false" aria-labelledby="q1-label q1-trigger">
                    <span>Select an option</span>
                  </button>
                </div>
              </div>
            </div>

            <!-- Question 2: Bachelor's degree question -->
            <div class="awsui-form-field">
              <div class="awsui-form-field-label">
                <label id="q2-label">Do you have a Bachelor's degree in Computer Science or other technical field, or 2+ years of related experience? <span>*</span></label>
              </div>
              <div class="awsui-form-field-control">
                <div class="awsui-select">
                  <button type="button" id="q2-trigger" class="awsui-select-trigger" aria-haspopup="listbox" aria-expanded="false" aria-labelledby="q2-label q2-trigger">
                    <span>Select an option</span>
                  </button>
                </div>
              </div>
            </div>

            <!-- Global listbox container that opens on click -->
            <div id="dropdown-portal" style="display:none;">
              <ul role="listbox" id="listbox-options">
                <li role="option">No experience</li>
                <li role="option">Less than 1 year</li>
                <li role="option">1 - 3 years</li>
                <li role="option">3 - 5 years</li>
                <li role="option">5+ years</li>
              </ul>
            </div>
          </main>

          <script>
            // Mock click behavior: opening listbox and selecting
            document.getElementById('q1-trigger').addEventListener('click', function() {
              const portal = document.getElementById('dropdown-portal');
              portal.style.display = 'block';
              document.getElementById('listbox-options').innerHTML = `
                <li role="option">No experience</li>
                <li role="option">Less than 1 year</li>
                <li role="option">1 - 3 years</li>
                <li role="option">3 - 5 years</li>
                <li role="option">5+ years</li>
              `;
              setupOptionClicks(this);
            });

            document.getElementById('q2-trigger').addEventListener('click', function() {
              const portal = document.getElementById('dropdown-portal');
              portal.style.display = 'block';
              document.getElementById('listbox-options').innerHTML = `
                <li role="option">Yes</li>
                <li role="option">No</li>
              `;
              setupOptionClicks(this);
            });

            function setupOptionClicks(triggerBtn) {
              document.querySelectorAll('#listbox-options li').forEach(opt => {
                opt.addEventListener('click', function() {
                  triggerBtn.querySelector('span').innerText = this.innerText;
                  triggerBtn.setAttribute('data-selected-value', this.innerText);
                  document.getElementById('dropdown-portal').style.display = 'none';
                });
              });
            }
          </script>
        </body>
        </html>
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            page.route("https://account.amazon.jobs/apply", lambda route: route.fulfill(
                status=200, content_type="text/html", body=amazon_jobs_html
            ))
            page.goto("https://account.amazon.jobs/apply")

            extractor = FormExtractor(page)
            fields = extractor.scan_form_fields()

            # 1. Verify custom dropdowns were successfully detected
            self.assertEqual(len(fields), 2, "Should extract both custom dropdowns")
            self.assertEqual(fields[0].field_type, "select")
            self.assertEqual(fields[1].field_type, "select")
            self.assertTrue(fields[0].required)
            self.assertTrue(fields[1].required)

            # 2. Verify label resolution cleaned asterisks
            self.assertIn("Linux systems administration", fields[0].label)
            self.assertFalse(fields[0].label.endswith("*"))
            self.assertIn("Bachelor's degree", fields[1].label)

            # 3. Verify FormFiller fills the custom dropdowns
            storage = StorageManager()
            scorer = JobScorer()
            profile = storage.load_profile()

            filler = FormFiller(
                page=page,
                storage=storage,
                scorer=scorer,
                user_profile=profile,
            )

            summary = filler.fill_all_fields(fields)
            self.assertEqual(summary.fields_filled, 2)
            self.assertEqual(summary.fields_skipped, 0)

            # Check that DOM values were updated
            q1_val = page.locator("#q1-trigger span").inner_text()
            q2_val = page.locator("#q2-trigger span").inner_text()
            self.assertIn(q1_val, ["3 - 5 years", "1 - 3 years"])
            self.assertEqual(q2_val, "Yes")

            browser.close()

    def test_native_select_hidden_by_wrapper(self):
        """Verifies native <select> elements hidden by custom wrappers are still extracted and filled."""
        select2_html = """<!DOCTYPE html>
        <html>
        <body>
          <div class="form-group">
            <label for="work_auth">Are you legally authorized to work in the United States?</label>
            <!-- Visually hidden native select -->
            <select id="work_auth" name="work_auth" style="display:none;">
              <option value="">Select an option</option>
              <option value="Yes">Yes</option>
              <option value="No">No</option>
            </select>
            <!-- Custom UI wrapper -->
            <div class="custom-select2-container">
              <span>Select an option</span>
            </div>
          </div>
        </body>
        </html>
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            page.route("https://example.com/apply", lambda route: route.fulfill(
                status=200, content_type="text/html", body=select2_html
            ))
            page.goto("https://example.com/apply")

            extractor = FormExtractor(page)
            fields = extractor.scan_form_fields()

            self.assertEqual(len(fields), 1)
            self.assertEqual(fields[0].field_type, "select")
            self.assertEqual(fields[0].options, ["Yes", "No"])

            storage = StorageManager()
            scorer = JobScorer()
            profile = storage.load_profile()

            filler = FormFiller(
                page=page,
                storage=storage,
                scorer=scorer,
                user_profile=profile,
                prompt_callback=lambda f: "Yes",
            )

            summary = filler.fill_all_fields(fields)
            self.assertEqual(summary.fields_filled, 1)

            selected_val = page.locator("#work_auth").evaluate("el => el.value")
            self.assertEqual(selected_val, "Yes")

            browser.close()

    def test_amazon_jobs_select2_combobox_structure(self):
        """Verifies Amazon Jobs / Select2 comboboxes with GUID IDs and dummy dropDownValues wrapper labels."""
        amazon_select2_html = """<!DOCTYPE html>
        <html>
        <head><title>Amazon Jobs</title></head>
        <body>
          <div class="question-label required">
            <span class="question-prefix d-none" aria-hidden="true">Q. </span>
            <label id="1c0346ab-4506-4de8-332c-48f814ab85cc-AQ-label" class="text-tooltip-label d-inline mb-0" aria-hidden="true">
              Which option best describes your total Linux systems administration and/or development experience?
            </label>
            <span class="sr-only"> required </span>
          </div>
          <div class="drop-down-menu mt-1">
            <div class="drop-down-menu-select">
              <label for="dropDownValues" style="width: 100%;">
                <select tabindex="-1" class="select2-hidden-accessible" aria-hidden="true">
                  <option value=""></option>
                  <option value="1">less than 1 year</option>
                  <option value="2">1 year to less than 2 years</option>
                  <option value="3">2 years to less than 3 years</option>
                  <option value="4">3 years to less than 4 years</option>
                  <option value="5">more than 4 years</option>
                </select>
                <span class="select2 select2-container select2-container--bootstrap" dir="ltr" style="width: 100%;">
                  <span class="selection">
                    <span class="select2-selection select2-selection--single" aria-haspopup="true" aria-expanded="false" tabindex="0" aria-labelledby="1c0346ab-4506-4de8-332c-48f814ab85cc-AQ-label" role="combobox" aria-invalid="false" aria-required="true">
                      <span class="select2-selection__rendered" id="select2-0f3w-container" role="textbox" aria-readonly="true">
                        <span class="select2-selection__placeholder">Select an option</span>
                      </span>
                      <span class="select2-selection__arrow" role="presentation"><b role="presentation"></b></span>
                    </span>
                  </span>
                </span>
              </label>
            </div>
          </div>
        </body>
        </html>
        """
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            context = browser.new_context()
            page = context.new_page()

            page.route("https://example.com/amazon-apply", lambda route: route.fulfill(
                status=200, content_type="text/html", body=amazon_select2_html
            ))
            page.goto("https://example.com/amazon-apply")

            extractor = FormExtractor(page)
            fields = extractor.scan_form_fields()

            self.assertEqual(len(fields), 1)
            f = fields[0]
            self.assertEqual(f.field_type, "select")
            self.assertEqual(
                f.label,
                "Which option best describes your total Linux systems administration and/or development experience?"
            )
            self.assertTrue(f.required)
            self.assertIn("3 years to less than 4 years", f.options)

            storage = StorageManager()
            scorer = JobScorer()
            profile = storage.load_profile()

            filler = FormFiller(
                page=page,
                storage=storage,
                scorer=scorer,
                user_profile=profile,
            )

            summary = filler.fill_all_fields(fields)
            self.assertEqual(summary.fields_filled, 1)
            self.assertEqual(summary.fields_skipped, 0)

            # Underlying select value should be '4' (3 years to less than 4 years)
            select_val = page.locator("select").evaluate("el => el.value")
            self.assertEqual(select_val, "4")

            # Visible Select2 UI text should be updated
            ui_text = page.locator(".select2-selection__rendered").inner_text()
            self.assertEqual(ui_text, "3 years to less than 4 years")

            browser.close()


if __name__ == "__main__":
    unittest.main()
