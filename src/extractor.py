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

try:
    from scrapling import Adaptor
    HAS_SCRAPLING = True
except ImportError:
    HAS_SCRAPLING = False


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
    screenshot_paths: List[str] = Field(default_factory=list)


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

                // Expand max-height constraints on job description containers
                document.querySelectorAll('.jobs-description, .jobs-description__content, .jobs-box__html-content, [class*="description"]').forEach(el => {
                    el.style.maxHeight = 'none';
                    el.style.overflow = 'visible';
                });

                // Scroll to top
                window.scrollTo(0, 0);
            }""")
            time.sleep(0.4)
        except Exception:
            pass

    def capture_screenshots(self, name_prefix: str = "screen", max_slices: int = 8) -> List[str]:
        """
        Captures sequential viewport screenshots down the page so the entire page context
        and all job descriptions/requirements are thoroughly captured without missing information.
        """
        self.clean_page_for_capture()
        captured_paths: List[str] = []
        timestamp = int(time.time())

        try:
            # Check page height and viewport height
            dimensions = self.page.evaluate("""() => {
                const body = document.body;
                const html = document.documentElement;
                const totalHeight = Math.max(
                    body ? body.scrollHeight : 0,
                    body ? body.offsetHeight : 0,
                    html ? html.clientHeight : 0,
                    html ? html.scrollHeight : 0,
                    html ? html.offsetHeight : 0
                );
                return {
                    totalHeight: totalHeight,
                    viewportHeight: window.innerHeight || 800
                };
            }""")
            
            total_height = dimensions.get("totalHeight", 1000)
            viewport_height = dimensions.get("viewportHeight", 800)
            # Use an overlap of ~120px so sentences aren't split across cuts
            step = max(300, viewport_height - 120)
            
            current_y = 0
            slice_idx = 1

            while current_y < total_height and slice_idx <= max_slices:
                self.page.evaluate(f"window.scrollTo(0, {current_y});")
                time.sleep(0.35)  # allow dynamic content and lazy images to settle

                filepath = SCREENSHOTS_DIR / f"{name_prefix}_{timestamp}_part{slice_idx}.png"
                try:
                    self.page.screenshot(path=str(filepath), full_page=False)
                    captured_paths.append(str(filepath.resolve()))
                except Exception:
                    pass

                # If current viewport already covers the bottom, break
                if current_y + viewport_height >= total_height:
                    break

                current_y += step
                slice_idx += 1

                # Re-check total height dynamically in case lazy loading expanded the page
                try:
                    new_total_height = self.page.evaluate("() => Math.max(document.body ? document.body.scrollHeight : 0, document.documentElement ? document.documentElement.scrollHeight : 0)")
                    if new_total_height > total_height:
                        total_height = min(new_total_height, 15000)  # safety cap
                except Exception:
                    pass

            # Restore scroll position to top
            self.page.evaluate("window.scrollTo(0, 0);")
            time.sleep(0.2)

        except Exception:
            pass

        # Fallback to single shot if multi-slice capture produced no images
        if not captured_paths:
            single_path = SCREENSHOTS_DIR / f"{name_prefix}_{timestamp}.png"
            try:
                self.page.screenshot(path=str(single_path), full_page=True)
            except Exception:
                self.page.screenshot(path=str(single_path), full_page=False)
            captured_paths.append(str(single_path.resolve()))

        return captured_paths

    def capture_screenshot(self, name_prefix: str = "screen") -> str:
        """Captures screenshot(s) and returns primary screenshot path for backward compatibility."""
        paths = self.capture_screenshots(name_prefix=name_prefix)
        return paths[0] if paths else ""

    def extract_job_info(self) -> ExtractedJobInfo:
        """Extracts job title, company, location, criteria, and description text from the page."""
        self.clean_page_for_capture()

        # 1. Capture clean visual screenshots across full page
        screenshot_paths = self.capture_screenshots("job_posting")
        screenshot_path = screenshot_paths[0] if screenshot_paths else None

        # 2. Ultra-Fast In-Memory Extraction via Scrapling Adaptor
        title = "Unknown Position"
        company = "Target Company"
        location = ""
        description = ""
        doc = None

        if HAS_SCRAPLING:
            try:
                doc = Adaptor(self.page.content())
                # Fast Title Extraction
                t_node = doc.css_first(
                    "h1.top-card-layout__title, h1.topcard__title, .job-details-jobs-unified-top-card__job-title, "
                    ".jobs-unified-top-card__job-title, h1.t-24, .jobs-details__main-content h1, h1, [data-qa='job-title'], "
                    ".posting-headline h2, .app-title, [class*='title'] h1, [class*='jobTitle']"
                )
                if t_node and t_node.text and len(t_node.text.strip()) < 140:
                    title = t_node.text.strip()

                # Fast Company Extraction
                comp_node = doc.css_first(
                    "a.topcard__org-name-link, .topcard__flavor--black-link, .job-details-jobs-unified-top-card__company-name a, "
                    ".job-details-jobs-unified-top-card__company-name, .jobs-unified-top-card__company-name, "
                    "a[href*='linkedin.com/company/'], [data-qa='company-name'], .posting-categories .org, .company-name, [class*='company']"
                )
                if comp_node and comp_node.text and len(comp_node.text.strip()) < 80:
                    company = comp_node.text.strip()

                # Fast Location Extraction
                loc_node = doc.css_first(
                    "span.topcard__flavor--bullet, .top-card-layout__first-subline .topcard__flavor:nth-child(2), "
                    ".job-details-jobs-unified-top-card__primary-description-container span, .posting-categories .location, "
                    "[data-qa='job-location'], [class*='location']"
                )
                if loc_node and loc_node.text and len(loc_node.text.strip()) < 100:
                    location = loc_node.text.strip()

                # Fast Description Extraction
                desc_node = doc.css_first(
                    ".show-more-less-html__markup, .description__text, .decorated-job-posting__details, "
                    "#job-details, .jobs-description__content, .jobs-box__html-content, .jobs-description, "
                    "article.jobs-description__container, #content, .posting-description, .job-description, [data-qa='job-description'], article, main"
                )
                if desc_node and desc_node.text and len(desc_node.text.strip()) > 100:
                    description = desc_node.text.strip()

            except Exception:
                pass

        # Fallback to Playwright Locators if any field was not resolved
        if title == "Unknown Position":
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

            if title == "Unknown Position":
                doc_title = self.page.title()
                if " - " in doc_title:
                    title = doc_title.split(" - ")[0].strip()
                elif " | " in doc_title:
                    title = doc_title.split(" | ")[0].strip()
                elif doc_title:
                    title = doc_title.strip()

        if company == "Target Company":
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

        if not location:
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

        # Fallback for description if not found via Scrapling
        if not description or len(description) < 100:
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
            screenshot_paths=screenshot_paths,
        )

    def ensure_application_form_open(self) -> bool:
        """Detects if form is visible, or clicks 'Apply' / 'Easy Apply' and follows redirects/new tabs."""
        try:
            self.page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        time.sleep(1)

        # 1. Check if form already exists and has input elements
        if self._is_form_visible():
            return True

        # Listen for any new tab/window opened by clicking Apply
        context = self.page.context
        initial_pages = list(context.pages)
        new_pages = []

        def on_page_opened(p):
            new_pages.append(p)

        try:
            context.on("page", on_page_opened)
        except Exception:
            pass

        try:
            # 2. Search for and click Apply buttons on the current page
            clicked = self._click_apply_button()
            if not clicked:
                return self._is_form_visible()

            # 3. Handle intermediate redirect modal or confirmation popup (e.g. LinkedIn "Continue to apply")
            for _ in range(6):
                time.sleep(0.5)
                redirect_btn = self.page.locator(
                    "div[role='dialog'] button:has-text('Continue'), "
                    "div[role='dialog'] a:has-text('Continue'), "
                    "div[role='dialog'] button:has-text('Apply'), "
                    "div[role='dialog'] a:has-text('Apply on company website'), "
                    ".artdeco-modal button:has-text('Continue'), "
                    "button[aria-label*='Continue to apply'], "
                    "a[aria-label*='Continue to apply']"
                ).first
                if redirect_btn.count() > 0 and redirect_btn.is_visible():
                    try:
                        redirect_btn.click()
                        time.sleep(1.5)
                        break
                    except Exception:
                        pass

            # 4. Check if a new tab was opened
            target_page = None
            if new_pages:
                target_page = new_pages[0]
            elif len(context.pages) > len(initial_pages):
                for p in context.pages:
                    if p not in initial_pages:
                        target_page = p
                        break

            if target_page and target_page != self.page:
                try:
                    target_page.wait_for_load_state("domcontentloaded", timeout=15000)
                except Exception:
                    pass
                time.sleep(2)
                target_page.bring_to_front()
                self.page = target_page

            # 5. Wait for tracking redirects (e.g. linkedin.com/jobs/view/externalApply/...)
            start_redir = time.time()
            while time.time() - start_redir < 10:
                if "externalapply" not in self.page.url.lower():
                    break
                time.sleep(0.5)

            try:
                self.page.wait_for_load_state("domcontentloaded", timeout=10000)
            except Exception:
                pass
            time.sleep(1.5)

            # 6. If we landed on external company site (e.g. Amazon, Workday, Greenhouse),
            # check if the application form is visible. If not, click the external site's "Apply Now" button!
            if not self._is_form_visible():
                self._click_external_site_apply()

            return self._is_form_visible()
        finally:
            try:
                context.remove_listener("page", on_page_opened)
            except Exception:
                pass

    def _click_apply_button(self) -> bool:
        """Finds and clicks the primary Apply or Easy Apply button on the job page."""
        apply_selectors = [
            # LinkedIn Easy Apply button
            ".job-details-jobs-unified-top-card button:has-text('Easy Apply')",
            ".jobs-unified-top-card button:has-text('Easy Apply')",
            ".jobs-details__main-content button:has-text('Easy Apply')",
            "button.jobs-apply-button:has-text('Easy Apply')",
            "button[aria-label*='Easy Apply']",
            ".jobs-s-apply button:has-text('Easy Apply')",
            "button:has-text('Easy Apply')",

            # LinkedIn External Apply button (in job card/details pane)
            ".job-details-jobs-unified-top-card button.jobs-apply-button",
            ".jobs-unified-top-card button.jobs-apply-button",
            ".jobs-details__main-content button.jobs-apply-button",
            ".jobs-apply-button--top-card button",
            ".jobs-apply-button--top-card a",
            ".jobs-s-apply button",
            ".jobs-s-apply a",
            "button.jobs-apply-button",
            "a.jobs-apply-button",
            "button[aria-label*='Apply to']",
            "button[aria-label*='Apply on company website']",
            "a[aria-label*='Apply on company website']",
            "a:has-text('Apply on company website')",

            # Indeed Apply
            "button#indeedApplyButton",
            "div#indeedApplyButton",
            "span:has-text('Apply now')",

            # Generic ATS Apply buttons
            "a:has-text('Apply for this job')",
            "button:has-text('Apply for this job')",
            "a:has-text('Apply Now')",
            "button:has-text('Apply Now')",
            "[data-qa='btn-apply']",
            ".postings-btn",
            "button:has-text('Apply')",
            "a:has-text('Apply')",
        ]

        for sel in apply_selectors:
            try:
                btn = self.page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    btn_text = (btn.inner_text() or "").strip().lower()
                    if "filter" in btn_text or "save" in btn_text or "alert" in btn_text:
                        continue
                    btn.scroll_into_view_if_needed()
                    time.sleep(0.3)
                    btn.click()
                    return True
            except Exception:
                continue
        return False

    def _click_external_site_apply(self) -> bool:
        """On external career sites, clicks 'Apply' or 'Apply Now' if form is not yet visible."""
        external_selectors = [
            "a:has-text('Apply now')",
            "button:has-text('Apply now')",
            "a:has-text('Apply for this job')",
            "button:has-text('Apply for this job')",
            "a:has-text('Apply online')",
            "button:has-text('Apply online')",
            "a:has-text('Start application')",
            "button:has-text('Start application')",
            "[data-automation-id*='apply']",
            "[data-qa='btn-apply']",
            "#apply_button",
            "a[href*='#apply']",
            "button:has-text('Apply')",
            "a:has-text('Apply')",
        ]

        context = self.page.context
        for sel in external_selectors:
            try:
                btn = self.page.locator(sel).first
                if btn.count() > 0 and btn.is_visible():
                    btn_text = (btn.inner_text() or "").strip().lower()
                    if "filter" in btn_text or "search" in btn_text or "save" in btn_text:
                        continue
                    btn.scroll_into_view_if_needed()
                    time.sleep(0.3)
                    btn.click()
                    try:
                        self.page.wait_for_load_state("domcontentloaded", timeout=10000)
                    except Exception:
                        pass
                    time.sleep(2)
                    if len(context.pages) > 1 and context.pages[-1] != self.page:
                        self.page = context.pages[-1]
                        try:
                            self.page.wait_for_load_state("domcontentloaded", timeout=10000)
                        except Exception:
                            pass
                        time.sleep(1)
                    if self._is_form_visible():
                        return True
            except Exception:
                continue
        return False

    def _is_form_visible(self) -> bool:
        """Checks if genuine application input elements or modal dialogs are present on screen."""
        curr_url = self.page.url.lower()

        # 1. On LinkedIn: ONLY Easy Apply modal or dedicated application dialog counts
        if "linkedin.com" in curr_url:
            modal = self.page.locator(".jobs-easy-apply-modal, .jobs-easy-apply-content").first
            if modal.count() > 0 and modal.is_visible():
                return True
            dlg = self.page.locator("div[role='dialog']").first
            if dlg.count() > 0 and dlg.is_visible():
                if dlg.locator(".jobs-easy-apply-form-section__grouping, input[type='file'], textarea, input[type='tel']").count() > 0:
                    return True
            return False

        # 2. On Indeed: ONLY Indeed Apply container or dialog counts
        if "indeed.com" in curr_url:
            ia_cont = self.page.locator("#ia-container, .ia-BasePage").first
            if ia_cont.count() > 0 and ia_cont.is_visible():
                return True
            dlg = self.page.locator("div[role='dialog']").first
            if dlg.count() > 0 and dlg.is_visible():
                if dlg.locator("input[type='file'], textarea, input[type='tel']").count() > 0:
                    return True
            return False

        # 3. External ATS or company career site:
        form_cont = self.page.locator(
            "form#application_form, form#application-form, form[action*='apply'], "
            "[data-qa='application-form'], [data-automation-id*='form'], #apply-form, .application-form"
        ).first
        if form_cont.count() > 0 and form_cont.is_visible():
            return True

        if self.page.locator("input[type='file']:visible").count() > 0:
            return True

        candidate_inputs = self.page.locator(
            "input:not([type='hidden']):not([type='file']):not([type='submit']):not([type='button']):not([type='search']):not([type='checkbox']):not([type='radio']), textarea, select"
        )
        valid_count = 0
        total_to_check = min(candidate_inputs.count(), 12)
        for i in range(total_to_check):
            inp = candidate_inputs.nth(i)
            if not inp.is_visible():
                continue
            name = (inp.get_attribute("name") or "").lower()
            placeholder = (inp.get_attribute("placeholder") or "").lower()
            aria_label = (inp.get_attribute("aria-label") or "").lower()
            inp_id = (inp.get_attribute("id") or "").lower()

            if any(term in name or term in placeholder or term in aria_label or term in inp_id for term in ("search", "keyword", "query", "job-search", "typeahead", "nav")):
                continue
            valid_count += 1
            if valid_count >= 2:
                return True

        return False

    def scan_form_fields(self) -> List[ExtractedField]:
        """Scans the active DOM and accessibility tree for all interactable form fields."""
        fields: List[ExtractedField] = []
        seen_identifiers = set()
        curr_url = self.page.url.lower()

        # If on LinkedIn and no Easy Apply modal is present, do NOT scan the LinkedIn page!
        if "linkedin.com" in curr_url:
            modal = self.page.locator(".jobs-easy-apply-modal, .jobs-easy-apply-content, div[role='dialog']").first
            if modal.count() == 0 or not modal.is_visible():
                return []
            root = modal
        elif "indeed.com" in curr_url:
            modal = self.page.locator("#ia-container, .ia-BasePage, div[role='dialog']").first
            if modal.count() == 0 or not modal.is_visible():
                return []
            root = modal
        else:
            # External career portal / ATS
            modal_container = self.page.locator("div[role='dialog']").first
            if modal_container.count() > 0 and modal_container.is_visible() and modal_container.locator("input, select, textarea, button[aria-haspopup='listbox']").count() > 0:
                root = modal_container
            else:
                root = self.page

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
            "input:not([type='hidden']):not([type='file']):not([type='submit']):not([type='button']):not([type='radio']):not([type='checkbox']):not([type='search'])"
        )
        for i in range(input_locators.count()):
            loc = input_locators.nth(i)
            if not loc.is_visible():
                continue
            name_raw = loc.get_attribute("name") or ""
            placeholder_raw = loc.get_attribute("placeholder") or ""
            name = name_raw.lower()
            placeholder = placeholder_raw.lower()
            aria_label = (loc.get_attribute("aria-label") or "").lower()
            inp_id = (loc.get_attribute("id") or "").lower()

            # Ignore any search boxes, query inputs, or navigation inputs
            if any(term in name or term in placeholder or term in aria_label or term in inp_id for term in ("search", "keyword", "query", "job-search", "typeahead", "nav")):
                continue

            label = self._resolve_label(loc, placeholder_raw or name_raw)
            label_lower = label.lower()
            if any(term in label_lower for term in ("describe the job you want", "search jobs", "search by title")):
                continue

            input_type = loc.get_attribute("type") or "text"
            field_id = f"input_{loc.get_attribute('id') or name_raw or i}"

            if field_id not in seen_identifiers:
                seen_identifiers.add(field_id)
                fields.append(
                    ExtractedField(
                        id=field_id,
                        label=label,
                        field_type=input_type if input_type in ("email", "tel") else "text",
                        name=name_raw,
                        placeholder=placeholder_raw,
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

        # 4. Process Select Dropdowns (Native <select> and Custom ARIA Comboboxes / Triggers)
        # 4A. Native <select> elements (both visible and styled/hidden by custom UI wrappers)
        select_locators = root.locator("select")
        for i in range(select_locators.count()):
            loc = select_locators.nth(i)
            if not loc.is_visible():
                # If select itself is styled/hidden, only process if parent or wrapper is visible
                try:
                    if not loc.locator("xpath=..").is_visible():
                        continue
                except Exception:
                    continue

            name = loc.get_attribute("name") or ""
            label = self._resolve_label(loc, name)
            field_id = f"select_{loc.get_attribute('id') or name or i}"

            # Extract options
            options = []
            opt_locs = loc.locator("option")
            for j in range(opt_locs.count()):
                text = opt_locs.nth(j).inner_text().strip()
                if text and text.lower() not in ("select...", "choose...", "-- select --", "select an option", ""):
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

        # 4B. Custom ARIA Dropdowns / Comboboxes (Cloudscape, React Select, Material UI, AWS UI)
        custom_triggers = root.locator(
            "button[aria-haspopup='listbox'], "
            "div[role='combobox'], "
            "button[role='combobox'], "
            "[data-qa*='select-trigger'], "
            "[data-automation-id*='select'], "
            "button[class*='select-trigger'], "
            "div[class*='awsui-select'] button, "
            "button:has-text('Select an option'), "
            "button:has-text('Choose an option'), "
            "button:has-text('Select one')"
        )
        for i in range(custom_triggers.count()):
            loc = custom_triggers.nth(i)
            if not loc.is_visible():
                continue

            # Skip if adjacent or ancestor already has a native select we extracted
            try:
                if loc.locator("xpath=ancestor::div[1]//select").count() > 0:
                    continue
            except Exception:
                pass

            el_id = loc.get_attribute("id") or ""
            name = loc.get_attribute("name") or ""
            aria_label = loc.get_attribute("aria-label") or ""
            placeholder = loc.inner_text().strip() if loc.inner_text() else ""

            label = self._resolve_label(loc, aria_label or name or "")
            if not label or label.lower() in ("select an option", "choose an option", "select one", "untitled field"):
                try:
                    wrapper = loc.locator("xpath=ancestor::div[contains(@class, 'form-field') or contains(@class, 'awsui-form-field') or contains(@class, 'field') or contains(@class, 'question')][1]").first
                    if wrapper.count() > 0:
                        lbl_el = wrapper.locator("label, [class*='label'], [class*='header'], h3, h4, p").first
                        if lbl_el.count() > 0:
                            label = re.sub(r"[\s*]+$", "", lbl_el.inner_text().strip()).strip()
                except Exception:
                    pass

            field_id = f"custom_select_{el_id or loc.get_attribute('aria-labelledby') or i}"

            # Check if listbox options are already available in DOM via aria-controls
            options = []
            listbox_id = loc.get_attribute("aria-controls")
            if listbox_id:
                try:
                    opt_elements = self.page.locator(f"#{listbox_id} [role='option'], #{listbox_id} li")
                    for j in range(opt_elements.count()):
                        opt_text = opt_elements.nth(j).inner_text().strip()
                        if opt_text and opt_text.lower() not in ("select an option", "select...", "choose...", ""):
                            options.append(opt_text)
                except Exception:
                    pass

            # Build robust selector
            if el_id:
                selector = f"#{el_id}"
            elif loc.get_attribute("aria-labelledby"):
                selector = f"[aria-labelledby='{loc.get_attribute('aria-labelledby')}']"
            else:
                selector = (
                    "button[aria-haspopup='listbox'], div[role='combobox'], button[role='combobox'], "
                    "[data-qa*='select-trigger'], button[class*='select-trigger'], div[class*='awsui-select'] button, "
                    "button:has-text('Select an option'), button:has-text('Choose an option'), button:has-text('Select one')"
                    f" >> nth={i}"
                )

            if field_id not in seen_identifiers:
                seen_identifiers.add(field_id)
                fields.append(
                    ExtractedField(
                        id=field_id,
                        label=label or "Job-specific Question",
                        field_type="select",
                        name=name,
                        placeholder=placeholder,
                        options=options,
                        required=self._is_field_required(loc, label),
                        selector=selector,
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
            # Check referenced labels via aria-labelledby
            aria_labelledby = locator.get_attribute("aria-labelledby")
            if aria_labelledby:
                for ref_id in aria_labelledby.split():
                    ref_id = ref_id.strip()
                    if not ref_id:
                        continue
                    try:
                        lbl_el = self.page.locator(f"#{ref_id}").first
                        if lbl_el.count() > 0 and "*" in lbl_el.inner_text():
                            return True
                    except Exception:
                        pass
            # Check outermost question container wrapper for asterisk
            wrapper = locator.locator(
                "xpath=ancestor::div["
                "contains(@class, 'awsui-form-field') or "
                "contains(@class, 'form-field') or "
                "contains(@class, 'field') or "
                "contains(@class, 'question')"
                "][last()]"
            ).first
            if wrapper.count() > 0:
                if wrapper.locator("[aria-required='true'], [class*='required']").count() > 0 or "*" in wrapper.inner_text():
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
            clean_aria = re.sub(r"[\s*]+$", "", aria_label.strip()).strip()
            if clean_aria and clean_aria.lower() not in ("select an option", "choose an option", "select one", "select...", "-- select --", ""):
                return clean_aria

        # 2. Check aria-labelledby (handles space-separated list of IDs like in Cloudscape/ARIA)
        aria_labelledby = locator.get_attribute("aria-labelledby")
        if aria_labelledby:
            for id_part in aria_labelledby.split():
                id_part = id_part.strip()
                if not id_part:
                    continue
                try:
                    lbl_el = self.page.locator(f"#{id_part}").first
                    if lbl_el.count() > 0:
                        text = lbl_el.inner_text().strip()
                        clean_text = re.sub(r"[\s*]+$", "", text).strip()
                        if clean_text and clean_text.lower() not in ("select an option", "choose an option", "select one", "select...", "-- select --", ""):
                            return clean_text
                except Exception:
                    pass

        # 3. Check element id linked with label for="id"
        el_id = locator.get_attribute("id")
        if el_id:
            lbl = self.page.locator(f"label[for='{el_id}']").first
            if lbl.count() > 0:
                text = lbl.inner_text().strip()
                clean_text = re.sub(r"[\s*]+$", "", text).strip()
                if clean_text:
                    return clean_text

        # 4. Check parent label container
        try:
            parent_label = locator.locator("xpath=ancestor::label").first
            if parent_label.count() > 0:
                text = parent_label.inner_text().strip()
                clean_text = re.sub(r"[\s*]+$", "", text).strip()
                if clean_text:
                    return clean_text
        except Exception:
            pass

        # 5. Check ancestor form-field / question wrapper
        try:
            wrapper = locator.locator(
                "xpath=ancestor::div["
                "contains(@class, 'awsui-form-field') or "
                "contains(@class, 'form-field') or "
                "contains(@class, 'form-group') or "
                "contains(@class, 'field') or "
                "contains(@class, 'question') or "
                "contains(@class, 'formField') or "
                "contains(@data-qa, 'question') or "
                "contains(@data-automation-id, 'formField') or "
                "contains(@role, 'group')"
                "][1]"
            ).first
            if wrapper.count() > 0:
                lbl = wrapper.locator("label, legend, [class*='label'], [class*='header'], [class*='title'], h2, h3, h4, h5, p").first
                if lbl.count() > 0:
                    text = lbl.inner_text().strip()
                    clean_text = re.sub(r"[\s*]+$", "", text).strip()
                    if clean_text and clean_text.lower() not in ("select an option", "choose an option", "select one", "select...", "-- select --", ""):
                        return clean_text
        except Exception:
            pass

        # 6. Check preceding label or text in DOM
        try:
            prev = locator.locator("xpath=preceding::label[1] | xpath=../preceding-sibling::*[1]//label | xpath=../../preceding-sibling::*[1]").first
            if prev.count() > 0:
                text = prev.inner_text().strip()
                clean_text = re.sub(r"[\s*]+$", "", text).strip()
                if clean_text and len(clean_text) > 3 and clean_text.lower() not in ("select an option", "choose an option", "select one", "select...", "-- select --", ""):
                    return clean_text
        except Exception:
            pass

        clean_fallback = re.sub(r"[\s*]+$", "", fallback.strip()).strip()
        return clean_fallback or "Untitled Field"

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
