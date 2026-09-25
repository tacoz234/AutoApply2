"""Screen Reader & Form Extractor for ApplyFlow.

Inspects web pages using Playwright's Accessibility Tree, DOM layout, and screenshots.
Detects job specs, 'Apply' buttons, and maps interactive application fields.
"""

from pathlib import Path
import re
import time
from typing import Any, Dict, List, Optional, Tuple
from playwright.sync_api import Page, Locator
from pydantic import BaseModel, Field

from src.config import SCREENSHOTS_DIR


class ExtractedJobInfo(BaseModel):
    title: str = "Unknown Role"
    company: str = "Unknown Company"
    location: str = ""
    seniority: str = ""
    employment_type: str = ""
    description: str = ""
    requirements_text: str = ""
    key_skills: List[str] = Field(default_factory=list)
    screenshot_path: Optional[str] = None


class ExtractedField(BaseModel):
    id: str
    label: str
    field_type: str  # text, email, tel, file, select, combobox, radio, checkbox, textarea
    name: str = ""
    placeholder: str = ""
    required: bool = False
    options: List[str] = Field(default_factory=list)
    selector: str = ""
    element_handle_id: Optional[str] = None


class FormExtractor:
    """Extracts job posting info and form fields using visual and accessibility inspection."""

    def __init__(self, page: Page):
        self.page = page

    def clean_page_for_capture(self) -> None:
        """Dismisses popups, sign-in banners, cookie prompts, and stabilizes sticky elements."""
        try:
            # 1. Click common dismiss / close buttons on overlays
            dismiss_selectors = [
                "button.modal__dismiss",
                "button[aria-label='Dismiss']",
                "button[data-modal='dismiss']",
                ".contextual-sign-in-modal__modal-dismiss-btn",
                "button.artdeco-modal__dismiss",
                "button:has-text('Dismiss')",
                "button.cookie-policy-banner__dismiss",
            ]
            for sel in dismiss_selectors:
                loc = self.page.locator(sel)
                if loc.count() > 0:
                    try:
                        loc.first.click(timeout=1000)
                    except Exception:
                        pass

            # 2. Expand all description "Show more" toggles
            expand_selectors = [
                "button.show-more-less-html__button--more",
                "button[data-tracking-control-name*='show-more']",
                "button.jobs-description__footer-button",
                "button[aria-label*='Expand description']",
                "button:has-text('Show more')",
            ]
            for sel in expand_selectors:
                loc = self.page.locator(sel)
                if loc.count() > 0 and loc.first.is_visible():
                    try:
                        loc.first.click(timeout=1500)
                    except Exception:
                        pass

            # 3. Clean up obstructive DOM elements and neutralize sticky headers during full page captures
            self.page.evaluate("""() => {
                // Remove floating modals, sign-in banners, backdrops
                const removeSelectors = [
                    '.contextual-sign-in-modal',
                    '[data-tracking-control-name*="contextual-sign-in-modal"]',
                    '.modal__overlay',
                    '.artdeco-modal-overlay',
                    '#artdeco-modal-outlet',
                    '.authwall-join-form',
                    '.cta-modal',
                    '.signin-prompt',
                    '.guest-interstitial',
                    '.toast-container',
                    '#session_key-login',
                    '.flavor-modal'
                ];
                removeSelectors.forEach(sel => {
                    document.querySelectorAll(sel).forEach(el => el.remove());
                });

                // Neutralize fixed & sticky navigation banners during full-page rendering
                document.querySelectorAll('header, nav, .sub-nav-cta, .nav__button-secondary, .top-card-layout__cta-container, [data-view-name*="floating"]').forEach(el => {
                    const style = window.getComputedStyle(el);
                    if (style.position === 'fixed' || style.position === 'sticky') {
                        el.style.position = 'absolute';
                        el.style.top = '0px';
                    }
                });

                // Scroll to top
                window.scrollTo(0, 0);
            }""")
            time.sleep(0.4)
        except Exception:
            pass

    def capture_screenshot(self, name_prefix: str = "screen") -> str:
        """Captures a clean, unobstructed screenshot for visual review and vision LLM analysis."""
        timestamp = int(time.time())
        filename = f"{name_prefix}_{timestamp}.png"
        filepath = SCREENSHOTS_DIR / filename
        
        self.clean_page_for_capture()

        try:
            self.page.screenshot(path=str(filepath), full_page=True)
        except Exception:
            self.page.screenshot(path=str(filepath), full_page=False)
        return str(filepath.resolve())

    def extract_job_info(self) -> ExtractedJobInfo:
        """Extracts job title, company, location, criteria, and description text from the page."""
        self.clean_page_for_capture()

        # 1. Capture clean visual screenshot
        screenshot_path = self.capture_screenshot("job_posting")

        # 2. Extract title using priority heuristics
        title = "Unknown Position"
        title_selectors = [
            "h1.top-card-layout__title",
            "h1.topcard__title",
            ".job-details-jobs-unified-top-card__job-title",
            ".jobs-unified-top-card__job-title",
            "h1.t-24",
            ".jobs-details__main-content h1",
            "h1",
            "[data-qa='job-title']",
            ".posting-headline h2",
            ".app-title",
            "[class*='title'] h1",
            "[class*='jobTitle']",
        ]
        for sel in title_selectors:
            loc = self.page.locator(sel).first
            if loc.count() > 0 and loc.is_visible():
                text = loc.inner_text().strip()
                if text and len(text) < 140:
                    title = text
                    break

        # If still unknown, check document title
        if title == "Unknown Position":
            doc_title = self.page.title()
            if " - " in doc_title:
                title = doc_title.split(" - ")[0].strip()
            elif " | " in doc_title:
                title = doc_title.split(" | ")[0].strip()
            elif doc_title:
                title = doc_title.strip()

        # 3. Extract company name
        company = "Target Company"
        company_selectors = [
            "a.topcard__org-name-link",
            ".topcard__flavor--black-link",
            ".job-details-jobs-unified-top-card__company-name a",
            ".job-details-jobs-unified-top-card__company-name",
            ".jobs-unified-top-card__company-name",
            "a.ember-view[href*='/company/']",
            "a[href*='linkedin.com/company/']",
            "[data-qa='company-name']",
            ".posting-categories .org",
            ".company-name",
            "[class*='company']",
            "meta[property='og:site_name']",
        ]
        for sel in company_selectors:
            loc = self.page.locator(sel).first
            if loc.count() > 0:
                text = loc.get_attribute("content") if "meta" in sel else loc.inner_text().strip()
                if text and len(text) < 80:
                    company = text
                    break

        # 4. Extract Location
        location = ""
        location_selectors = [
            "span.topcard__flavor--bullet",
            ".top-card-layout__first-subline .topcard__flavor:nth-child(2)",
            ".job-details-jobs-unified-top-card__primary-description-container span",
            ".posting-categories .location",
            "[data-qa='job-location']",
            "[class*='location']",
        ]
        for sel in location_selectors:
            loc = self.page.locator(sel).first
            if loc.count() > 0:
                loc_text = loc.inner_text().strip()
                if loc_text and len(loc_text) < 100:
                    location = loc_text
                    break

        # 5. Extract Seniority & Employment Type
        seniority = ""
        employment_type = ""
        try:
            criteria_items = self.page.locator(".description__job-criteria-item, .job-details-jobs-unified-top-card__job-insight, .jobs-unified-top-card__job-insight")
            for i in range(criteria_items.count()):
                item_text = criteria_items.nth(i).inner_text().strip()
                if "Seniority" in item_text:
                    seniority = item_text.replace("Seniority level", "").replace("Seniority", "").strip()
                elif "Employment" in item_text:
                    employment_type = item_text.replace("Employment type", "").replace("Employment", "").strip()
        except Exception:
            pass

        # 6. Extract job description body
        desc_selectors = [
            ".show-more-less-html__markup",
            ".description__text",
            ".decorated-job-posting__details",
            "#job-details",
            ".jobs-description__content",
            ".jobs-box__html-content",
            ".jobs-description",
            "article.jobs-description__container",
            "#content",
            ".posting-description",
            ".job-description",
            "[data-qa='job-description']",
            "article",
            "main",
        ]
        description = ""
        for sel in desc_selectors:
            loc = self.page.locator(sel).first
            if loc.count() > 0:
                description = loc.inner_text().strip()
                if len(description) > 100:
                    break

        if not description or len(description) < 100:
            body_text = self.page.locator("body").inner_text()
            description = body_text[:6000]

        # Clean description artifacts
        description = description.replace("\ufffd", "'")
        for cut in ["Similar Searches", "Similar searches", "People also viewed", "Search more jobs"]:
            if cut in description:
                description = description.split(cut)[0].strip()

        # 7. Extract Key Tech Skills Detected
        KNOWN_TECH = [
            "Python", "Java", "JavaScript", "TypeScript", "C++", "C#", "Go", "Golang", "Rust",
            "React", "Angular", "Vue", "Node", "Node.js", "Spring Boot", "Django", "FastAPI", "Flask",
            "AWS", "GCP", "Azure", "Docker", "Kubernetes", "CI/CD", "Git", "GitHub", "SQL", "PostgreSQL",
            "MongoDB", "Redis", "GraphQL", "REST", "gRPC", "Linux", "Terraform", "Kafka",
            "LangChain", "LLM", "Machine Learning", "Microservices"
        ]
        import re
        key_skills = []
        for tech in KNOWN_TECH:
            pattern = rf"\b{re.escape(tech)}\b"
            if re.search(pattern, description, re.IGNORECASE):
                key_skills.append(tech)

        return ExtractedJobInfo(
            title=title,
            company=company,
            location=location,
            seniority=seniority,
            employment_type=employment_type,
            description=description,
            requirements_text=description,
            key_skills=key_skills,
            screenshot_path=screenshot_path,
        )

    def ensure_application_form_open(self) -> bool:
        """Detects if form is visible, or clicks 'Apply' / 'Apply Now' / 'Easy Apply' if needed."""
        self.page.wait_for_load_state("domcontentloaded")
        time.sleep(1)

        # Check if form already exists and has input elements
        if self._is_form_visible():
            return True

        # Search for Apply buttons/links
        apply_buttons = [
            "button.jobs-apply-button",
            "button:has-text('Easy Apply')",
            "button[aria-label*='Easy Apply']",
            ".jobs-s-apply button",
            "a:has-text('Apply for this job')",
            "a:has-text('Apply Now')",
            "button:has-text('Apply Now')",
            "button:has-text('Apply')",
            "a:has-text('Apply')",
            "[data-qa='btn-apply']",
            ".postings-btn",
        ]

        for sel in apply_buttons:
            btn = self.page.locator(sel).first
            if btn.count() > 0 and btn.is_visible():
                try:
                    btn.click()
                    self.page.wait_for_load_state("domcontentloaded", timeout=5000)
                    time.sleep(1.5)
                    if self._is_form_visible():
                        return True
                except Exception:
                    continue

        return self._is_form_visible()

    def _is_form_visible(self) -> bool:
        """Checks if input elements or modal dialogs are present on screen."""
        if self.page.locator(".jobs-easy-apply-modal, div[role='dialog']").count() > 0:
            return True
        input_count = self.page.locator("input:not([type='hidden']), textarea, select").count()
        return input_count >= 2

    def scan_form_fields(self) -> List[ExtractedField]:
        """Scans the active DOM and accessibility tree for all interactable form fields."""
        fields: List[ExtractedField] = []
        seen_identifiers = set()

        # Priority container: LinkedIn Easy Apply modal / dialog, or standard ATS form
        modal_container = self.page.locator(".jobs-easy-apply-modal, div[role='dialog']").first
        if modal_container.count() > 0 and modal_container.is_visible():
            root = modal_container
        else:
            form_container = self.page.locator("form, #application_form, #application-form, [data-qa='application-form']").first
            root = form_container if form_container.count() > 0 else self.page

        # 1. Process File Inputs (Resume / CV Upload)
        file_locators = root.locator("input[type='file']")
        for i in range(file_locators.count()):
            loc = file_locators.nth(i)
            label = self._resolve_label(loc, "Upload Resume / CV")
            field_id = f"file_{loc.get_attribute('id') or loc.get_attribute('name') or i}"
            if field_id not in seen_identifiers:
                seen_identifiers.add(field_id)
                fields.append(
                    ExtractedField(
                        id=field_id,
                        label=label,
                        field_type="file",
                        name=loc.get_attribute("name") or "",
                        required=self._is_field_required(loc, label) or "resume" in label.lower(),
                        selector=f"input[type='file'] >> nth={i}",
                    )
                )

        # 2. Process Standard Inputs (text, email, tel, etc.)
        input_locators = root.locator(
            "input:not([type='hidden']):not([type='file']):not([type='submit']):not([type='button']):not([type='radio']):not([type='checkbox'])"
        )
        for i in range(input_locators.count()):
            loc = input_locators.nth(i)
            if not loc.is_visible():
                continue
            input_type = loc.get_attribute("type") or "text"
            name = loc.get_attribute("name") or ""
            placeholder = loc.get_attribute("placeholder") or ""
            label = self._resolve_label(loc, placeholder or name)
            field_id = f"input_{loc.get_attribute('id') or name or i}"

            if field_id not in seen_identifiers:
                seen_identifiers.add(field_id)
                fields.append(
                    ExtractedField(
                        id=field_id,
                        label=label,
                        field_type=input_type if input_type in ("email", "tel") else "text",
                        name=name,
                        placeholder=placeholder,
                        required=self._is_field_required(loc, label),
                        selector=f"input:not([type='hidden']):not([type='file']):not([type='submit']):not([type='button']):not([type='radio']):not([type='checkbox']) >> nth={i}",
                    )
                )

        # 3. Process Textarea Elements (Multi-line / Open-ended questions)
        textarea_locators = root.locator("textarea")
        for i in range(textarea_locators.count()):
            loc = textarea_locators.nth(i)
            if not loc.is_visible():
                continue
            name = loc.get_attribute("name") or ""
            placeholder = loc.get_attribute("placeholder") or ""
            label = self._resolve_label(loc, placeholder or name)
            field_id = f"textarea_{loc.get_attribute('id') or name or i}"

            if field_id not in seen_identifiers:
                seen_identifiers.add(field_id)
                fields.append(
                    ExtractedField(
                        id=field_id,
                        label=label,
                        field_type="textarea",
                        name=name,
                        placeholder=placeholder,
                        required=self._is_field_required(loc, label),
                        selector=f"textarea >> nth={i}",
                    )
                )

        # 4. Process Select Dropdowns
        select_locators = root.locator("select")
        for i in range(select_locators.count()):
            loc = select_locators.nth(i)
            if not loc.is_visible():
                continue
            name = loc.get_attribute("name") or ""
            label = self._resolve_label(loc, name)
            field_id = f"select_{loc.get_attribute('id') or name or i}"

            # Extract options
            options = []
            opt_locs = loc.locator("option")
            for j in range(opt_locs.count()):
                text = opt_locs.nth(j).inner_text().strip()
                if text and text.lower() not in ("select...", "choose...", "-- select --", ""):
                    options.append(text)

            if field_id not in seen_identifiers:
                seen_identifiers.add(field_id)
                fields.append(
                    ExtractedField(
                        id=field_id,
                        label=label,
                        field_type="select",
                        name=name,
                        options=options,
                        required=self._is_field_required(loc, label),
                        selector=f"select >> nth={i}",
                    )
                )

        # 5. Process Radio Button Groups
        radio_groups = self._extract_radio_groups(root)
        for group in radio_groups:
            if group.id not in seen_identifiers:
                seen_identifiers.add(group.id)
                fields.append(group)

        # 6. Process Checkboxes
        checkbox_locators = root.locator("input[type='checkbox']")
        for i in range(checkbox_locators.count()):
            loc = checkbox_locators.nth(i)
            if not loc.is_visible():
                continue
            name = loc.get_attribute("name") or ""
            label = self._resolve_label(loc, name or "Agreement")
            field_id = f"check_{loc.get_attribute('id') or name or i}"

            if field_id not in seen_identifiers:
                seen_identifiers.add(field_id)
                fields.append(
                    ExtractedField(
                        id=field_id,
                        label=label,
                        field_type="checkbox",
                        name=name,
                        required=self._is_field_required(loc, label),
                        selector=f"input[type='checkbox'] >> nth={i}",
                    )
                )

        return fields

    def _is_field_required(self, locator: Locator, label: str) -> bool:
        """Determines if input is marked required via HTML attribute, aria, or asterisk."""
        try:
            req = locator.get_attribute("required")
            if req is not None and req.lower() != "false":
                return True
            aria_req = locator.get_attribute("aria-required")
            if aria_req and aria_req.lower() == "true":
                return True
        except Exception:
            pass
        if "*" in label or "(required)" in label.lower():
            return True
        return False

    def _resolve_label(self, locator: Locator, fallback: str = "") -> str:
        """Resolves accessible label text using accessibility, aria, and DOM relationships."""
        # 1. Check aria-label
        aria_label = locator.get_attribute("aria-label")
        if aria_label and aria_label.strip():
            return aria_label.strip()

        # 2. Check aria-labelledby
        aria_labelledby = locator.get_attribute("aria-labelledby")
        if aria_labelledby:
            lbl_el = self.page.locator(f"#{aria_labelledby}").first
            if lbl_el.count() > 0:
                text = lbl_el.inner_text().strip()
                if text:
                    return text

        # 3. Check element id linked with label for="id"
        el_id = locator.get_attribute("id")
        if el_id:
            lbl = self.page.locator(f"label[for='{el_id}']").first
            if lbl.count() > 0:
                text = lbl.inner_text().strip()
                if text:
                    return text

        # 4. Check parent label container
        try:
            parent_label = locator.locator("xpath=ancestor::label").first
            if parent_label.count() > 0:
                text = parent_label.inner_text().strip()
                if text:
                    return text
        except Exception:
            pass

        # 5. Check immediate preceding label or text element in same wrapper
        try:
            wrapper = locator.locator("xpath=ancestor::div[contains(@class, 'field') or contains(@class, 'form-group') or contains(@class, 'application-question')]").first
            if wrapper.count() > 0:
                lbl = wrapper.locator("label, .label, legend, [class*='label']").first
                if lbl.count() > 0:
                    text = lbl.inner_text().strip()
                    if text:
                        return text
        except Exception:
            pass

        return fallback.strip() or "Untitled Field"

    def _extract_radio_groups(self, root: Locator) -> List[ExtractedField]:
        """Groups radio buttons by group name or container."""
        radio_locs = root.locator("input[type='radio']")
        groups: Dict[str, List[Dict[str, Any]]] = {}

        for i in range(radio_locs.count()):
            r = radio_locs.nth(i)
            name = r.get_attribute("name") or f"radio_group_{i}"
            val = r.get_attribute("value") or ""
            lbl_text = self._resolve_label(r, val)

            if name not in groups:
                groups[name] = []
            groups[name].append({"value": val, "label": lbl_text, "index": i})

        extracted = []
        for name, items in groups.items():
            options = [it["label"] or it["value"] for it in items if (it["label"] or it["value"])]
            # Find group label / legend
            group_label = name
            try:
                first_r = root.locator(f"input[type='radio'][name='{name}']").first
                fieldset = first_r.locator("xpath=ancestor::fieldset").first
                if fieldset.count() > 0:
                    legend = fieldset.locator("legend").first
                    if legend.count() > 0:
                        group_label = legend.inner_text().strip()
                else:
                    wrapper = first_r.locator("xpath=ancestor::div[contains(@class, 'field') or contains(@class, 'question')]").first
                    if wrapper.count() > 0:
                        lbl = wrapper.locator("label, .label, [class*='label']").first
                        if lbl.count() > 0:
                            group_label = lbl.inner_text().strip()
            except Exception:
                pass

            extracted.append(
                ExtractedField(
                    id=f"radio_{name}",
                    label=group_label,
                    field_type="radio",
                    name=name,
                    options=options,
                    selector=f"input[type='radio'][name='{name}']",
                )
            )

        return extracted
