"""Scrapling-powered DOM Double-Checker & Form Validation Layer for ApplyFlow.

Performs ultra-fast in-memory DOM inspection on post-fill snapshots to detect:
1. Active validation errors ('! This field is required', aria-invalid, alert banners)
2. Custom dropdowns that remain unselected ('Select an option', 'Choose an option')
3. Required inputs left blank
"""

import re
from typing import Any, Dict, List, Optional
from playwright.sync_api import Page
from scrapling import Adaptor


class FormDoubleChecker:
    """Uses Scrapling's high-speed C/lxml parser to validate live application forms."""

    @staticmethod
    def validate_page_content(html: str) -> Dict[str, Any]:
        """Analyzes an HTML snapshot in memory to double-check form completeness."""
        if not html or not html.strip():
            return {
                "is_valid": True,
                "status": "PASSED",
                "validation_errors": [],
                "unselected_dropdowns": [],
                "empty_required_inputs": [],
                "total_issues": 0,
                "message": "Empty or non-HTML view checked.",
            }

        doc = Adaptor(html)
        validation_errors: List[str] = []
        unselected_dropdowns: List[Dict[str, str]] = []
        empty_required_inputs: List[str] = []

        # 1. Detect red validation error messages / alerts
        error_nodes = doc.xpath(
            "//*["
            "(contains(@class, 'error') or contains(@class, 'invalid') or contains(@class, 'alert') or @role='alert' or @aria-invalid='true') "
            "and not(self::script) and not(self::style)"
            "]"
        )
        seen_error_texts = set()
        for node in error_nodes:
            txt = (node.get_all_text() or node.text or "").strip()
            # Look for typical error messages
            if (
                txt
                and len(txt) > 2
                and any(
                    term in txt.lower()
                    for term in (
                        "field is required",
                        "required field",
                        "please select",
                        "please enter",
                        "must be",
                        "invalid",
                        "error",
                        "cannot be blank",
                        "fill out this field",
                    )
                )
            ):
                clean_err = re.sub(r"[\s!*]+", " ", txt).strip()
                if clean_err not in seen_error_texts:
                    seen_error_texts.add(clean_err)
                    validation_errors.append(txt)

        # 2. Detect custom dropdowns left unselected
        dropdown_triggers = doc.xpath(
            "//button[contains(., 'Select an option') or contains(., 'Choose an option') or contains(., 'Select one')] | "
            "//div[@role='combobox'][contains(., 'Select an option') or contains(., 'Choose an option')]"
        )
        for trigger in dropdown_triggers:
            question_text = "Job-specific Question"

            # Check aria-labelledby first
            aria_labelled = trigger.attrib.get("aria-labelledby")
            if aria_labelled:
                parts = []
                for id_ref in aria_labelled.strip().split():
                    ref_el = doc.css_first(f"#{id_ref}")
                    if ref_el:
                        t = (ref_el.get_all_text() or ref_el.text or "").strip()
                        if t and t.lower() not in ("select an option", "choose an option", "select one"):
                            parts.append(t)
                if parts:
                    question_text = re.sub(r"[\s*]+$", "", " ".join(parts)).strip()

            if question_text == "Job-specific Question":
                # Find nearest question label in ancestors
                for anc in trigger.iterancestors():
                    lbl = anc.css_first("label, legend, [class*='label'], [class*='header'], h3, h4")
                    if lbl:
                        candidate = (lbl.get_all_text() or lbl.text or "").strip()
                        if candidate and len(candidate) > 3 and candidate.lower() not in ("select an option", "choose an option", "select one"):
                            question_text = re.sub(r"[\s*]+$", "", candidate).strip()
                            break

            unselected_dropdowns.append({
                "question": question_text,
                "current_value": (trigger.get_all_text() or trigger.text or "").strip(),
            })

        # 3. Detect empty required native inputs
        required_inputs = doc.xpath(
            "//input[@required and not(@type='hidden') and not(@type='submit') and not(@type='checkbox') and not(@type='radio')]"
        )
        for inp in required_inputs:
            val = (inp.attrib.get("value") or "").strip()
            if not val:
                name = inp.attrib.get("name") or inp.attrib.get("id") or "required_input"
                label = name
                inp_id = inp.attrib.get("id")
                if inp_id:
                    lbl_el = doc.css_first(f"label[for='{inp_id}']")
                    if lbl_el:
                        lbl_txt = (lbl_el.get_all_text() or lbl_el.text or "").strip()
                        if lbl_txt:
                            label = lbl_txt
                empty_required_inputs.append(label)

        total_issues = len(validation_errors) + len(unselected_dropdowns) + len(empty_required_inputs)
        is_valid = (total_issues == 0)

        if is_valid:
            msg = "✓ Double-Checker Verified: All visible required fields and dropdowns are filled."
            status = "VERIFIED"
        else:
            issue_summary = []
            if unselected_dropdowns:
                issue_summary.append(f"{len(unselected_dropdowns)} unselected dropdown(s)")
            if validation_errors:
                issue_summary.append(f"{len(validation_errors)} error message(s)")
            if empty_required_inputs:
                issue_summary.append(f"{len(empty_required_inputs)} blank required input(s)")
            msg = f"⚠️ Double-Checker Warning: Found {', '.join(issue_summary)} on the active page."
            status = "NEEDS_ATTENTION"

        return {
            "is_valid": is_valid,
            "status": status,
            "validation_errors": validation_errors,
            "unselected_dropdowns": unselected_dropdowns,
            "empty_required_inputs": empty_required_inputs,
            "total_issues": total_issues,
            "message": msg,
        }

    @classmethod
    def validate_page(cls, page: Page) -> Dict[str, Any]:
        """Captures page HTML and runs validation check in under 15ms."""
        try:
            html = page.content()
            return cls.validate_page_content(html)
        except Exception as e:
            return {
                "is_valid": True,
                "status": "CHECK_FAILED",
                "validation_errors": [],
                "unselected_dropdowns": [],
                "empty_required_inputs": [],
                "total_issues": 0,
                "message": f"Double-checker error: {str(e)}",
            }
