"""FastAPI GUI Backend Server for ApplyFlow.

Exposes REST and state-polling endpoints to drive ApplyFlow from a modern web dashboard.
"""

from datetime import datetime, timezone
import json
import os
from pathlib import Path
import threading
import time
from typing import Any, Dict, List, Optional
from fastapi import FastAPI, HTTPException, File, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from playwright.sync_api import sync_playwright

from src.browser import (
    create_persistent_context,
    detect_authwall_or_login,
    interactive_browser,
    perform_automated_login,
)
from src.resume_parser import ResumeParser

from src.config import (
    BROWSER_PROFILE_DIR,
    BROWSER_TIMEOUT_MS,
    DATA_DIR,
    HEADLESS,
    ROOT_DIR,
    SCREENSHOTS_DIR,
    SLOW_MO_MS,
    USER_AGENT,
    VIEWPORT,
    get_portal_credentials,
    save_env_credentials,
)
from src.extractor import ExtractedField, FormExtractor
from src.filler import FillSummary, FormFiller
from src.scorer import JobScorer, MatchScoreResult
from src.storage import ApplicationLog, QABankEntry, StorageManager, UserProfile
from src.validator import FormDoubleChecker
from tests.mock_ats_server import MockATSHandler
from http.server import HTTPServer


app = FastAPI(title="ApplyFlow Dashboard API")

# Allow CORS for development convenience
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


class AutofillSession:
    """Manages thread-safe state for an active autofill application run."""

    def __init__(self):
        self.lock = threading.Lock()
        self.status = "idle"  # idle, scanning, scan_complete, filling, waiting_for_input, waiting_for_essay, waiting_for_pin, review_ready, completed, aborted, error
        self.url = ""
        self.job_title = ""
        self.company = ""
        self.location = ""
        self.seniority = ""
        self.employment_type = ""
        self.key_skills: List[str] = []
        self.description = ""
        self.initial_screenshot = ""
        self.initial_screenshots: List[str] = []
        self.post_screenshot = ""
        self.score_result: Optional[Dict[str, Any]] = None
        self.fill_steps: List[Dict[str, Any]] = []
        self.summary: Dict[str, Any] = {"filled": 0, "skipped": 0, "added": 0}
        self.validation_report: Optional[Dict[str, Any]] = None
        self.error_message = ""

        # Thread synchronization events
        self.input_event = threading.Event()
        self.pending_question: Optional[Dict[str, Any]] = None
        self.user_answer: Optional[str] = None

        self.essay_event = threading.Event()
        self.pending_essay: Optional[Dict[str, Any]] = None
        self.essay_decision: Optional[Dict[str, str]] = None

        self.pin_event = threading.Event()
        self.pending_pin: Optional[str] = None
        self.user_pin: Optional[str] = None

        self.submit_event = threading.Event()
        self.submit_decision: Optional[bool] = None

        # Playwright thread handle
        self.thread: Optional[threading.Thread] = None

    def reset(self):
        with self.lock:
            self.status = "idle"
            self.url = ""
            self.job_title = ""
            self.company = ""
            self.location = ""
            self.seniority = ""
            self.employment_type = ""
            self.key_skills = []
            self.description = ""
            self.initial_screenshot = ""
            self.initial_screenshots = []
            self.post_screenshot = ""
            self.score_result = None
            self.fill_steps = []
            self.summary = {"filled": 0, "skipped": 0, "added": 0}
            self.validation_report = None
            self.error_message = ""
            self.pending_question = None
            self.user_answer = None
            self.pending_essay = None
            self.essay_decision = None
            self.pending_pin = None
            self.user_pin = None
            self.submit_decision = None
            self.input_event.clear()
            self.essay_event.clear()
            self.pin_event.clear()
            self.submit_event.clear()


class DevLogger:
    """Thread-safe developer activity logger."""

    def __init__(self, max_entries: int = 1000):
        self.lock = threading.Lock()
        self.entries: List[Dict[str, Any]] = []
        self.max_entries = max_entries

    def log(self, level: str, message: str, details: Optional[Any] = None):
        with self.lock:
            entry = {
                "id": len(self.entries) + 1,
                "timestamp": datetime.now(timezone.utc).strftime("%H:%M:%S.%f")[:-3],
                "level": level.upper(),  # INFO, SUCCESS, WARN, ERROR, DEBUG
                "message": message,
                "details": details,
            }
            self.entries.append(entry)
            if len(self.entries) > self.max_entries:
                self.entries.pop(0)

    def get_logs(self, since_id: int = 0) -> List[Dict[str, Any]]:
        with self.lock:
            if since_id == 0:
                return list(self.entries)
            return [e for e in self.entries if e["id"] > since_id]

    def clear(self):
        with self.lock:
            self.entries.clear()


dev_logger = DevLogger()
dev_logger.log("INFO", "ApplyFlow GUI Backend initialized and ready.")

session = AutofillSession()
storage = StorageManager()
scorer = JobScorer()
resume_parser = ResumeParser()

# Mock ATS server thread
mock_server_instance: Optional[HTTPServer] = None
mock_server_thread: Optional[threading.Thread] = None


class ScanRequest(BaseModel):
    url: str
    force_visible: bool = False


class BrowserLoginRequest(BaseModel):
    url: Optional[str] = "https://www.linkedin.com/login"
    platform: Optional[str] = "LinkedIn"


class AutofillStartRequest(BaseModel):
    url: Optional[str] = None


class AnswerRequest(BaseModel):
    answer: str


class EssayDecisionRequest(BaseModel):
    choice: str  # accept, edit, skip
    text: Optional[str] = None


class FinalSubmitRequest(BaseModel):
    submit: bool


class PinSubmitRequest(BaseModel):
    pin: str


class CredentialsSaveRequest(BaseModel):
    linkedin_email: Optional[str] = None
    linkedin_password: Optional[str] = None
    indeed_email: Optional[str] = None
    indeed_password: Optional[str] = None


# --- API Routes ---

@app.get("/api/status")
def get_status():
    """Returns current active autofill session state."""
    with session.lock:
        return {
            "status": session.status,
            "url": session.url,
            "job_title": session.job_title,
            "company": session.company,
            "location": session.location,
            "seniority": session.seniority,
            "employment_type": session.employment_type,
            "key_skills": session.key_skills,
            "description": session.description,
            "initial_screenshot": session.initial_screenshot,
            "initial_screenshots": session.initial_screenshots,
            "post_screenshot": session.post_screenshot,
            "score_result": session.score_result,
            "fill_steps": session.fill_steps,
            "summary": session.summary,
            "validation_report": session.validation_report,
            "pending_question": session.pending_question,
            "pending_essay": session.pending_essay,
            "pending_pin": session.pending_pin,
            "error_message": session.error_message,
        }


@app.get("/api/credentials/status")
def get_credentials_status():
    """Returns whether job board credentials are configured in .env."""
    li_email, li_pwd = get_portal_credentials("linkedin")
    ind_email, ind_pwd = get_portal_credentials("indeed")
    return {
        "has_linkedin": bool(li_email and li_pwd),
        "linkedin_email": li_email,
        "has_indeed": bool(ind_email and ind_pwd),
        "indeed_email": ind_email,
    }


@app.post("/api/credentials/save")
def save_credentials_route(req: CredentialsSaveRequest):
    """Saves candidate credentials to root .env file for automated AI login."""
    updates = {}
    if req.linkedin_email is not None:
        updates["LINKEDIN_EMAIL"] = req.linkedin_email.strip()
    if req.linkedin_password is not None:
        updates["LINKEDIN_PASSWORD"] = req.linkedin_password.strip()
    if req.indeed_email is not None:
        updates["INDEED_EMAIL"] = req.indeed_email.strip()
    if req.indeed_password is not None:
        updates["INDEED_PASSWORD"] = req.indeed_password.strip()

    if updates:
        save_env_credentials(updates)
        dev_logger.log("SUCCESS", f"Saved portal credentials to .env ({', '.join(updates.keys())}).")
    return {"status": "saved", "updated": list(updates.keys())}


@app.post("/api/browser/submit-pin")
def submit_pin_route(req: PinSubmitRequest):
    """Submits 2FA PIN provided by user from the GUI."""
    if session.status != "waiting_for_pin":
        raise HTTPException(status_code=400, detail="Not currently waiting for PIN.")
    session.user_pin = req.pin
    session.pin_event.set()
    dev_logger.log("INFO", "Received 2FA verification PIN from candidate. Submitting to form...")
    return {"status": "received"}


@app.post("/api/browser/open-login")
def open_browser_login(req: BrowserLoginRequest):
    """Launches an interactive Chromium window with persistent profile for user authentication."""
    try:
        url = req.url or "https://www.linkedin.com/login"
        platform = req.platform or "LinkedIn"
        dev_logger.log("INFO", f"Launching interactive browser for {platform} authentication ({url})...")
        interactive_browser.open_login_window(url=url, platform=platform)
        return {"status": "opened", "url": url, "platform": platform}
    except Exception as e:
        dev_logger.log("ERROR", f"Failed to launch browser login window: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.post("/api/browser/close-login")
def close_browser_login():
    """Closes interactive login window and persists all session cookies."""
    try:
        interactive_browser.close()
        dev_logger.log("SUCCESS", "Interactive login browser closed. Session cookies saved to disk.")
        return {"status": "closed"}
    except Exception as e:
        dev_logger.log("ERROR", f"Failed closing browser: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/browser/status")
def get_browser_status():
    """Returns status of interactive login browser."""
    return interactive_browser.get_status()


@app.post("/api/scan")
def scan_job_url(req: ScanRequest):
    """Navigates to URL, captures screenshot, and generates Brutal Match Score."""
    if interactive_browser.is_active:
        dev_logger.log("INFO", "Closing active login window before initiating scan...")
        interactive_browser.close()
        time.sleep(1)

    session.reset()
    session.url = req.url.strip()
    session.status = "scanning"

    dev_logger.log("INFO", f"Starting job scan for URL: {session.url}")
    profile = storage.load_profile()

    try:
        headless_mode = not req.force_visible
        dev_logger.log("INFO", f"Launching persistent Chromium context ({'headless' if headless_mode else 'visible'})...")
        with sync_playwright() as p:
            context = create_persistent_context(p, headless=headless_mode, slow_mo=0)
            page = context.pages[0] if context.pages else context.new_page()
            page.set_default_timeout(BROWSER_TIMEOUT_MS)
            
            dev_logger.log("INFO", f"Navigating to {session.url}...")
            page.goto(session.url, wait_until="domcontentloaded")
            time.sleep(2.5)

            # Check for authwall / sign-in requirement
            auth_check = detect_authwall_or_login(page)
            if auth_check["auth_required"]:
                platform = auth_check["platform"] or "LinkedIn"
                email, pwd = get_portal_credentials(platform)

                if email and pwd:
                    dev_logger.log("INFO", f"Credentials found in .env for {platform} ({email}). Attempting automated AI login...")

                    def scan_pin_callback(msg: str) -> str:
                        dev_logger.log("WARN", f"2FA PIN requested by {platform}: '{msg}'")
                        with session.lock:
                            session.status = "waiting_for_pin"
                            session.pending_pin = msg
                            session.pin_event.clear()
                        session.pin_event.wait(timeout=120)
                        with session.lock:
                            ans = session.user_pin or ""
                            session.pending_pin = None
                            session.user_pin = None
                            session.status = "scanning"
                        return ans

                    login_success, login_msg = perform_automated_login(
                        page=page,
                        platform=platform,
                        email=email,
                        password=pwd,
                        pin_callback=scan_pin_callback,
                    )

                    if login_success:
                        dev_logger.log("SUCCESS", f"Automated login to {platform} succeeded! Navigating to job posting...")
                        page.goto(session.url, wait_until="domcontentloaded")
                        time.sleep(2.5)
                        re_auth = detect_authwall_or_login(page)
                        if re_auth["auth_required"]:
                            context.close()
                            with session.lock:
                                session.status = "auth_required"
                                session.error_message = f"Still on authwall after login: {re_auth['reason']}"
                            return {
                                "status": "auth_required",
                                "platform": platform,
                                "url": session.url,
                                "reason": re_auth["reason"],
                                "has_credentials": True,
                                "message": f"Login attempted but security checkpoint is active. Please complete challenge in browser.",
                            }
                    else:
                        dev_logger.log("ERROR", f"Automated login to {platform} failed: {login_msg}")
                        context.close()
                        with session.lock:
                            session.status = "auth_required"
                            session.error_message = f"Automated login failed: {login_msg}"
                        return {
                            "status": "auth_required",
                            "platform": platform,
                            "url": session.url,
                            "reason": login_msg,
                            "has_credentials": True,
                            "message": f"Automated login failed: {login_msg}",
                        }
                else:
                    dev_logger.log("WARN", f"Authentication required on {platform}, but no credentials configured in .env.")
                    context.close()
                    with session.lock:
                        session.status = "credentials_required"
                        session.error_message = f"Sign-in required for {platform}. Save your credentials in .env to enable automated AI login."
                    return {
                        "status": "credentials_required",
                        "platform": platform,
                        "url": session.url,
                        "reason": auth_check["reason"],
                        "has_credentials": False,
                        "message": f"{platform} requires authentication. Enter your email & password to enable automated AI login!",
                    }

            dev_logger.log("INFO", "Inspecting page layout and extracting job metadata...")
            extractor = FormExtractor(page)
            job_info = extractor.extract_job_info()

            session.job_title = job_info.title
            session.company = job_info.company
            session.location = job_info.location
            session.seniority = job_info.seniority
            session.employment_type = job_info.employment_type
            session.key_skills = job_info.key_skills
            session.description = job_info.description

            dev_logger.log("SUCCESS", f"Extracted Job: '{job_info.title}' at '{job_info.company}'" + (f" ({job_info.location})" if job_info.location else ""))
            if job_info.key_skills:
                dev_logger.log("INFO", f"Detected Target Tech Stack: {', '.join(job_info.key_skills)}")

            if job_info.screenshot_paths:
                session.initial_screenshots = [f"/screenshots/{Path(p).name}" for p in job_info.screenshot_paths]
                session.initial_screenshot = session.initial_screenshots[0]
                dev_logger.log("INFO", f"Saved {len(job_info.screenshot_paths)} initial visual page screenshots: {[Path(p).name for p in job_info.screenshot_paths]}")
            elif job_info.screenshot_path:
                session.initial_screenshot = f"/screenshots/{Path(job_info.screenshot_path).name}"
                session.initial_screenshots = [session.initial_screenshot]
                dev_logger.log("INFO", f"Saved initial visual screenshot: {Path(job_info.screenshot_path).name}")

            # Calculate Brutally Honest Gap Score
            dev_logger.log("INFO", f"Invoking cynical recruiter gap analysis model ({scorer.model})...")
            score = scorer.score_match(
                job_title=job_info.title,
                company=job_info.company,
                job_description=job_info.description,
                user_profile=profile,
                screenshot_path=job_info.screenshot_path,
                screenshot_paths=job_info.screenshot_paths,
            )

            session.score_result = score.model_dump()
            session.status = "scan_complete"
            dev_logger.log("SUCCESS", f"Match Score Calculated: {score.estimated_callback_chance}% Callback Chance ({score.recommendation})")
            context.close()

        return {
            "status": "scan_complete",
            "job_title": session.job_title,
            "company": session.company,
            "location": session.location,
            "seniority": session.seniority,
            "employment_type": session.employment_type,
            "key_skills": session.key_skills,
            "description": session.description,
            "initial_screenshot": session.initial_screenshot,
            "initial_screenshots": session.initial_screenshots,
            "score": session.score_result,
        }
    except Exception as e:
        session.status = "error"
        session.error_message = str(e)
        dev_logger.log("ERROR", f"Failed during scan: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


def _run_autofill_worker():
    """Background worker executing Playwright in non-headless mode with persistent candidate profile."""
    if interactive_browser.is_active:
        dev_logger.log("INFO", "Closing active login window before initiating autofill...")
        interactive_browser.close()
        time.sleep(1)

    profile = storage.load_profile()
    dev_logger.log("INFO", "Initializing non-headless Chromium window with persistent candidate profile...")

    with sync_playwright() as p:
        context = create_persistent_context(
            p,
            headless=HEADLESS,
            slow_mo=SLOW_MO_MS,
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.set_default_timeout(BROWSER_TIMEOUT_MS)

        try:
            dev_logger.log("INFO", f"Worker navigating to {session.url}...")
            page.goto(session.url, wait_until="domcontentloaded")
            time.sleep(2)

            # Check if redirected to login / authwall
            auth_check = detect_authwall_or_login(page)
            if auth_check["auth_required"]:
                platform = auth_check["platform"] or "LinkedIn"
                email, pwd = get_portal_credentials(platform)

                if email and pwd:
                    dev_logger.log("INFO", f"Credentials found in .env for {platform} ({email}). Executing automated AI login...")
                    def fill_pin_callback(msg: str) -> str:
                        dev_logger.log("WARN", f"2FA PIN requested by {platform}: '{msg}'")
                        with session.lock:
                            session.status = "waiting_for_pin"
                            session.pending_pin = msg
                            session.pin_event.clear()
                        session.pin_event.wait(timeout=120)
                        with session.lock:
                            ans = session.user_pin or ""
                            session.pending_pin = None
                            session.user_pin = None
                            session.status = "filling"
                        return ans

                    login_success, login_msg = perform_automated_login(
                        page=page,
                        platform=platform,
                        email=email,
                        password=pwd,
                        pin_callback=fill_pin_callback,
                    )
                    if login_success:
                        dev_logger.log("SUCCESS", f"Automated login to {platform} succeeded! Reloading target form...")
                        page.goto(session.url, wait_until="domcontentloaded")
                        time.sleep(2.5)
                else:
                    dev_logger.log("WARN", f"Sign-in required on {platform}! Please log in to your account in the open browser window...")
                    for _ in range(60):
                        time.sleep(2)
                        if not detect_authwall_or_login(page)["auth_required"]:
                            dev_logger.log("SUCCESS", f"Successfully authenticated on {platform}! Resuming autofill...")
                            time.sleep(1)
                            break

            extractor = FormExtractor(page)
            dev_logger.log("INFO", "Detecting and opening application form / Easy Apply...")
            form_opened = extractor.ensure_application_form_open()

            # If page changed (e.g. redirected or opened external site in new tab), update page & session.url:
            if extractor.page != page:
                page = extractor.page
                with session.lock:
                    session.url = page.url
                dev_logger.log("SUCCESS", f"Navigated to external application portal: {page.url}")

            fields = extractor.scan_form_fields()
            dev_logger.log("SUCCESS", f"Identified {len(fields)} interactable field(s) on active view.")

            # Define callbacks for GUI synchronization
            def on_field_fill(label: str, status_str: str, val: str):
                with session.lock:
                    session.fill_steps.append({
                        "field": label,
                        "status": status_str,
                        "value": val,
                        "time": datetime.now(timezone.utc).strftime("%H:%M:%S"),
                    })
                lvl = "SUCCESS" if status_str == "FILLED" else ("WARN" if status_str == "SKIPPED" else "ERROR")
                dev_logger.log(lvl, f"Field '{label}' -> [{status_str}] {val[:40] if val else ''}")

            def prompt_callback(field: ExtractedField) -> str:
                dev_logger.log("WARN", f"Unmapped field: '{field.label}'. Requesting user input via modal...")
                with session.lock:
                    session.status = "waiting_for_input"
                    session.pending_question = {
                        "field_id": field.id,
                        "label": field.label,
                        "field_type": field.field_type,
                        "options": field.options,
                    }
                    session.input_event.clear()

                # Wait for user input from GUI (timeout 120s)
                session.input_event.wait(timeout=120)
                with session.lock:
                    ans = session.user_answer or ""
                    session.pending_question = None
                    session.user_answer = None
                    session.status = "filling"
                dev_logger.log("INFO", f"Received user response for '{field.label}': '{ans}'. Auto-persisted to QA bank.")
                return ans

            def essay_callback(question: str, draft: str):
                dev_logger.log("INFO", f"Open-ended essay question found: '{question[:50]}...'. Drafting response with local model...")
                with session.lock:
                    session.status = "waiting_for_essay"
                    session.pending_essay = {
                        "question": question,
                        "draft": draft,
                    }
                    session.essay_event.clear()

                # Wait for essay decision from GUI (timeout 180s)
                session.essay_event.wait(timeout=180)
                with session.lock:
                    decision = session.essay_decision or {"choice": "accept", "text": draft}
                    session.pending_essay = None
                    session.essay_decision = None
                    session.status = "filling"
                dev_logger.log("SUCCESS", f"User selected essay action: '{decision.get('choice')}'")
                return decision.get("choice", "accept"), decision.get("text", draft)

            filler = FormFiller(
                page=page,
                storage=storage,
                scorer=scorer,
                user_profile=profile,
                job_title=session.job_title,
                company=session.company,
                job_description=session.description,
                on_field_fill=on_field_fill,
                prompt_callback=prompt_callback,
                essay_callback=essay_callback,
            )

            with session.lock:
                session.status = "filling"

            summary = filler.fill_multi_step_form(extractor)
            post_screenshot_path = extractor.capture_screenshot("post_fill")

            # Scrapling high-speed DOM double-checker (<15ms)
            validation_report = FormDoubleChecker.validate_page(page)
            if not validation_report.get("is_valid"):
                dev_logger.log("WARN", f"Double-Checker flagged issues: {validation_report.get('message')}")
            else:
                dev_logger.log("SUCCESS", f"Double-Checker passed: {validation_report.get('message')}")

            dev_logger.log("SUCCESS", f"Autofill execution complete. Filled: {summary.fields_filled}, Skipped: {summary.fields_skipped}, Added to QA: {summary.questions_added_to_qa}")

            with session.lock:
                session.post_screenshot = f"/screenshots/{Path(post_screenshot_path).name}"
                session.validation_report = validation_report
                session.summary = {
                    "filled": summary.fields_filled,
                    "skipped": summary.fields_skipped,
                    "added": summary.questions_added_to_qa,
                    "validation": validation_report,
                }
                session.status = "review_ready"
                session.submit_event.clear()

            dev_logger.log("WARN", "Safety Halt Reached! Form completed on screen. Awaiting user review confirmation.")

            # Wait for final submission decision
            session.submit_event.wait(timeout=300)

            final_status = "REVIEWED_NOT_SUBMITTED"
            if session.submit_decision is True:
                dev_logger.log("INFO", "User confirmed submission. Locating submit button...")
                submit_btn = page.locator("button[type='submit'], input[type='submit'], button:has-text('Submit Application'), button:has-text('Submit application')").first
                if submit_btn.count() > 0:
                    submit_btn.click()
                    time.sleep(3)
                    final_status = "SUBMITTED"
                    dev_logger.log("SUCCESS", "Final submit button clicked!")
                else:
                    final_status = "SUBMITTED_MANUALLY"
                    dev_logger.log("WARN", "Submit button not found automatically. User submitted manually.")
            else:
                dev_logger.log("INFO", "User elected not to submit. Form left in current state.")

            # Log to SQLite
            app_id = f"app_{int(time.time())}"
            chance = session.score_result.get("estimated_callback_chance", 50) if session.score_result else 50
            critique = "\n".join(session.score_result.get("brutal_reality", [])) if session.score_result else ""

            storage.log_application(
                app_id=app_id,
                job_title=session.job_title or "Job Application",
                company=session.company or "Company",
                url=session.url,
                match_score=chance,
                brutal_critique=critique,
                status=final_status,
                screenshot_path=post_screenshot_path,
            )
            dev_logger.log("INFO", f"Logged application record '{app_id}' to SQLite database.")

            with session.lock:
                session.status = "completed"

        except Exception as e:
            with session.lock:
                session.status = "error"
                session.error_message = str(e)
            dev_logger.log("ERROR", f"Error in Playwright worker: {str(e)}")
        finally:
            context.close()
            dev_logger.log("INFO", "Playwright persistent browser session closed.")


@app.post("/api/autofill/start")
def start_autofill(req: AutofillStartRequest):
    """Starts the autofill worker in background thread."""
    if session.status in ("filling", "waiting_for_input", "waiting_for_essay"):
        return {"status": session.status, "message": "Autofill already in progress."}

    if req.url:
        session.url = req.url.strip()

    session.thread = threading.Thread(target=_run_autofill_worker, daemon=True)
    session.thread.start()
    return {"status": "started", "url": session.url}


@app.post("/api/autofill/answer")
def answer_pending_question(req: AnswerRequest):
    """Provides user answer to an unmapped form field prompt."""
    if session.status != "waiting_for_input":
        raise HTTPException(status_code=400, detail="Not currently waiting for input.")

    session.user_answer = req.answer
    session.input_event.set()
    return {"status": "received", "answer": req.answer}


@app.post("/api/autofill/essay")
def answer_pending_essay(req: EssayDecisionRequest):
    """Submits decision for an open-ended essay draft."""
    if session.status != "waiting_for_essay":
        raise HTTPException(status_code=400, detail="Not currently waiting for essay decision.")

    session.essay_decision = {"choice": req.choice, "text": req.text or ""}
    session.essay_event.set()
    return {"status": "received", "decision": req.choice}


@app.post("/api/autofill/submit")
def final_submit_decision(req: FinalSubmitRequest):
    """Confirms or skips final submission."""
    if session.status != "review_ready":
        raise HTTPException(status_code=400, detail="Not in review_ready status.")

    session.submit_decision = req.submit
    session.submit_event.set()
    return {"status": "received", "submit": req.submit}


@app.post("/api/autofill/abort")
def abort_autofill():
    """Aborts current session."""
    with session.lock:
        session.status = "aborted"
        session.input_event.set()
        session.essay_event.set()
        session.submit_event.set()
    return {"status": "aborted"}


# --- Profile & QA & History Endpoints ---

@app.get("/api/profile")
def get_profile():
    return storage.load_profile().model_dump()


@app.post("/api/profile")
def update_profile(profile_data: Dict[str, Any]):
    profile = UserProfile(**profile_data)
    profile.is_setup_completed = True
    storage.save_profile(profile)
    dev_logger.log("SUCCESS", f"Candidate profile for '{profile.personal.full_name}' permanently saved to disk.")
    return {"status": "success", "profile": profile.model_dump()}


@app.post("/api/resume/upload")
async def upload_resume(file: UploadFile = File(...)):
    """Uploads resume file, saves to data/, and extracts structured candidate profile."""
    try:
        file_bytes = await file.read()
        if not file_bytes:
            raise HTTPException(status_code=400, detail="Empty file uploaded.")

        saved_filename = storage.save_uploaded_resume(file_bytes, file.filename or "resume.pdf")
        saved_path = storage.profile_path.parent / saved_filename

        dev_logger.log("INFO", f"Uploaded resume '{saved_filename}' ({len(file_bytes)} bytes). Parsing text...")
        parsed_data = resume_parser.parse_resume(saved_path)

        # Auto-persist extracted candidate profile fields so they survive across all sessions
        profile = storage.load_profile()
        profile.resume_file = saved_filename
        profile.is_setup_completed = True

        parsed_pers = parsed_data.get("personal", {})
        if parsed_pers.get("first_name"):
            profile.personal.first_name = parsed_pers["first_name"]
        if parsed_pers.get("last_name"):
            profile.personal.last_name = parsed_pers["last_name"]
        if parsed_pers.get("full_name"):
            profile.personal.full_name = parsed_pers["full_name"]
        elif profile.personal.first_name and profile.personal.last_name:
            profile.personal.full_name = f"{profile.personal.first_name} {profile.personal.last_name}"
        if parsed_pers.get("email"):
            profile.personal.email = parsed_pers["email"]
        if parsed_pers.get("phone"):
            profile.personal.phone = parsed_pers["phone"]
        if parsed_pers.get("city"):
            profile.personal.city = parsed_pers["city"]
        if parsed_pers.get("state"):
            profile.personal.state = parsed_pers["state"]
        if parsed_pers.get("postal_code"):
            profile.personal.postal_code = parsed_pers["postal_code"]

        parsed_links = parsed_data.get("links", {})
        for k, v in parsed_links.items():
            if v:
                profile.links[k] = v

        parsed_skills = parsed_data.get("skills", [])
        if parsed_skills:
            existing_skills = set(profile.skills)
            for s in parsed_skills:
                if s not in existing_skills:
                    profile.skills.append(s)

        storage.save_profile(profile)

        dev_logger.log(
            "SUCCESS",
            f"Resume parsed & profile saved! Candidate '{profile.personal.full_name}' with {len(profile.skills)} skills linked to '{saved_filename}'.",
        )
        return {
            "status": "success",
            "filename": saved_filename,
            "profile": profile.model_dump(),
        }
    except Exception as e:
        dev_logger.log("ERROR", f"Failed to upload or parse resume: {str(e)}")
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/api/setup/status")
def get_setup_status():
    """Returns whether the first-time setup has been completed."""
    profile = storage.load_profile()
    return {
        "is_setup_completed": profile.is_setup_completed,
        "resume_file": profile.resume_file,
        "candidate_name": profile.personal.full_name or "Candidate",
    }


@app.post("/api/setup/complete")
def complete_setup(payload: Dict[str, Any]):
    """Saves candidate profile and QA Knowledge Bank answers, marking setup as completed."""
    try:
        # Support both nested 'profile' and flat profile dict
        profile_dict = payload.get("profile", payload)
        if not isinstance(profile_dict, dict):
            profile_dict = payload
        profile_dict["is_setup_completed"] = True
        profile = UserProfile(**profile_dict)
        storage.save_profile(profile)

        # Update QA Bank answers if supplied
        qa_answers = payload.get("qa_answers", {})
        if qa_answers and isinstance(qa_answers, dict):
            storage.update_qa_answers(qa_answers)
            dev_logger.log(
                "INFO",
                f"Updated {len(qa_answers)} screening answers in QA Knowledge Bank from setup wizard.",
            )

        # Add any custom QA entry if supplied
        custom_qa = payload.get("custom_qa", [])
        if isinstance(custom_qa, list):
            for item in custom_qa:
                if item.get("question") and item.get("answer"):
                    storage.add_to_qa_bank(
                        question=item["question"],
                        answer=item["answer"],
                        field_type=item.get("field_type", "text"),
                        category=item.get("category", "custom"),
                    )

        dev_logger.log(
            "SUCCESS",
            f"First-time setup completed! Candidate: '{profile.personal.full_name}'. QA Knowledge Bank ready.",
        )
        return {
            "status": "success",
            "profile": profile.model_dump(),
            "qa_bank": [e.model_dump() for e in storage.load_qa_bank()],
        }
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid setup data: {str(e)}")


@app.post("/api/setup/reset")
def reset_setup():
    """Resets first-time setup state so the onboarding wizard can be re-run."""
    storage.set_setup_completed(False)
    dev_logger.log("INFO", "First-time setup state reset by user.")
    return {"status": "reset", "is_setup_completed": False}


@app.get("/api/qa")
def get_qa_bank():
    return [e.model_dump() for e in storage.load_qa_bank()]


@app.post("/api/qa")
def add_qa_entry(entry_data: Dict[str, Any]):
    new_entry = storage.add_to_qa_bank(
        question=entry_data.get("question", ""),
        answer=entry_data.get("answer", ""),
        field_type=entry_data.get("field_type", "text"),
        category=entry_data.get("category", "custom"),
    )
    return {"status": "success", "entry": new_entry.model_dump()}


@app.delete("/api/qa/{entry_id}")
def delete_qa_entry(entry_id: str):
    entries = storage.load_qa_bank()
    filtered = [e for e in entries if e.id != entry_id]
    storage.save_qa_bank(filtered)
    return {"status": "deleted", "id": entry_id}


@app.get("/api/history")
def get_history(limit: int = 50):
    return [l.model_dump() for l in storage.get_history(limit=limit)]


# --- Developer Logs Endpoints ---

@app.get("/api/logs")
def get_developer_logs(since_id: int = 0):
    """Returns developer logs, optionally filtered since a specific entry id."""
    logs = dev_logger.get_logs(since_id=since_id)
    return {"logs": logs, "total": len(dev_logger.entries)}


@app.post("/api/logs/clear")
def clear_developer_logs():
    """Clears in-memory developer activity log buffer."""
    dev_logger.clear()
    dev_logger.log("INFO", "Developer log buffer reset.")
    return {"status": "cleared"}


# --- Mock ATS Server Controller ---

@app.get("/api/mock-server/status")
def mock_server_status():
    global mock_server_instance
    is_running = mock_server_instance is not None
    return {"running": is_running, "url": "http://127.0.0.1:8088/"}


@app.post("/api/mock-server/toggle")
def toggle_mock_server():
    global mock_server_instance, mock_server_thread
    if mock_server_instance is None:
        try:
            mock_server_instance = HTTPServer(("127.0.0.1", 8088), MockATSHandler)
            mock_server_thread = threading.Thread(
                target=mock_server_instance.serve_forever, daemon=True
            )
            mock_server_thread.start()
            return {"running": True, "url": "http://127.0.0.1:8088/"}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed starting mock server: {e}")
    else:
        try:
            mock_server_instance.shutdown()
            mock_server_instance.server_close()
            mock_server_instance = None
            mock_server_thread = None
            return {"running": False, "url": ""}
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"Failed stopping mock server: {e}")


# --- Static Files Mounting ---

# Ensure screenshots dir is mounted
app.mount("/screenshots", StaticFiles(directory=str(SCREENSHOTS_DIR)), name="screenshots")

# Static directory for GUI assets
STATIC_DIR = ROOT_DIR / "src" / "static"
STATIC_DIR.mkdir(parents=True, exist_ok=True)
app.mount("/", StaticFiles(directory=str(STATIC_DIR), html=True), name="static")
