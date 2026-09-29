"""Unit tests for Scrapling FormDoubleChecker validation engine."""

import unittest
from src.validator import FormDoubleChecker


class TestScraplingValidator(unittest.TestCase):
    def test_empty_or_blank_html(self):
        result = FormDoubleChecker.validate_page_content("")
        self.assertTrue(result["is_valid"])
        self.assertEqual(result["total_issues"], 0)

        result_ws = FormDoubleChecker.validate_page_content("   \n\t  ")
        self.assertTrue(result_ws["is_valid"])

    def test_valid_form_passes(self):
        html = """
        <html>
          <body>
            <form>
              <div class="field">
                <label for="name">Full Name</label>
                <input id="name" name="name" required value="Cole Determan" />
              </div>
              <div class="field">
                <label for="email">Email</label>
                <input id="email" name="email" required value="cole@example.com" />
              </div>
              <div class="field">
                <label id="lbl-linux">How many years of Linux experience do you have?*</label>
                <button type="button" aria-haspopup="listbox" aria-labelledby="lbl-linux">
                  3 - 5 years
                </button>
              </div>
            </form>
          </body>
        </html>
        """
        result = FormDoubleChecker.validate_page_content(html)
        self.assertTrue(result["is_valid"])
        self.assertEqual(result["status"], "VERIFIED")
        self.assertEqual(result["total_issues"], 0)
        self.assertEqual(len(result["validation_errors"]), 0)
        self.assertEqual(len(result["unselected_dropdowns"]), 0)
        self.assertEqual(len(result["empty_required_inputs"]), 0)

    def test_unselected_custom_dropdown_flagged(self):
        html = """
        <html>
          <body>
            <div class="awsui-form-field">
              <div class="awsui-form-field-label">
                <label id="q1">How many years of DevOps experience do you have?*</label>
              </div>
              <div class="awsui-form-field-control">
                <button type="button" aria-haspopup="listbox" aria-labelledby="q1" class="awsui-select">
                  <span>Select an option</span>
                </button>
              </div>
            </div>
          </body>
        </html>
        """
        result = FormDoubleChecker.validate_page_content(html)
        self.assertFalse(result["is_valid"])
        self.assertEqual(result["status"], "NEEDS_ATTENTION")
        self.assertEqual(result["total_issues"], 1)
        self.assertEqual(len(result["unselected_dropdowns"]), 1)
        dd = result["unselected_dropdowns"][0]
        self.assertIn("DevOps experience", dd["question"])
        self.assertEqual(dd["current_value"], "Select an option")

    def test_red_validation_error_flagged(self):
        html = """
        <html>
          <body>
            <div class="awsui-form-field">
              <label>Work Authorization*</label>
              <button>Select an option</button>
              <div class="awsui-form-field-error" role="alert">
                ! This field is required
              </div>
            </div>
          </body>
        </html>
        """
        result = FormDoubleChecker.validate_page_content(html)
        self.assertFalse(result["is_valid"])
        self.assertGreaterEqual(result["total_issues"], 1)
        self.assertTrue(any("field is required" in err.lower() for err in result["validation_errors"]))

    def test_empty_required_input_flagged(self):
        html = """
        <html>
          <body>
            <form>
              <div>
                <label for="phone-input">Phone Number</label>
                <input id="phone-input" name="phone" required value="" />
              </div>
            </form>
          </body>
        </html>
        """
        result = FormDoubleChecker.validate_page_content(html)
        self.assertFalse(result["is_valid"])
        self.assertIn("Phone Number", result["empty_required_inputs"])


if __name__ == "__main__":
    unittest.main()
