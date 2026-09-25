"""Browser management and persistent session handler for ApplyFlow.

Provides anti-detection Playwright persistent contexts (preserving logins for LinkedIn,
Indeed, Greenhouse, etc.), automated authwall/login detection, and interactive login tools.
"""

from contextlib import contextmanager
import os
from pathlib import Path
import re
import threading
import time
from typing import Any, Dict, Generator, Optional, Tuple
from playwright.sync_api import sync_playwright, BrowserContext, Page, Playwright

from src.config import (
    BROWSER_PROFILE_DIR,
    BROWSER_TIMEOUT_MS,
    HEADLESS,
    SLOW_MO_MS,
    USER_AGENT,
    VIEWPORT,
)

# Standard stealth arguments to bypass automated scraper detection (like LinkedIn authwall)
CHROME_STEALTH_ARGS = [
    "--disable-blink-features=AutomationControlled",
    "--no-sandbox",
    "--disable-dev-shm-usage",
    "--disable-infobars",
    "--disable-features=IsolateOrigins,site-per-process",
    "--window-size=1280,900",
]

STEALTH_EVASION_SCRIPT = """
// Mask webdriver property
Object.defineProperty(navigator, 'webdriver', {
    get: () => undefined
});

// Mock plugins
Object.defineProperty(navigator, 'plugins', {
    get: () => [1, 2, 3, 4, 5]
});

// Mock languages
Object.defineProperty(navigator, 'languages', {
    get: () => ['en-US', 'en']
});

// Mock chrome runtime
window.chrome = window.chrome || {
    runtime: {},
    loadTimes: function() {},
    csi: function() {},
    app: {}
};
"""


def create_persistent_context(
    p: Playwright,
    headless: bool = False,
    user_data_dir: Optional[Path] = None,
    slow_mo: int = SLOW_MO_MS,
) -> BrowserContext:
    """Creates a persistent Chromium browser context storing cookies and session state."""
    profile_dir = user_data_dir or BROWSER_PROFILE_DIR
    profile_dir.mkdir(parents=True, exist_ok=True)

    context = p.chromium.launch_persistent_context(
        user_data_dir=str(profile_dir.resolve()),
        headless=headless,
        slow_mo=slow_mo,
        viewport=VIEWPORT,
        user_agent=USER_AGENT,
        args=CHROME_STEALTH_ARGS,
        ignore_default_args=["--enable-automation"],
        locale="en-US",
        timezone_id="America/New_York",
    )

    # Inject evasions into every page/frame opened in this context
    context.add_init_script(STEALTH_EVASION_SCRIPT)
    context.set_default_timeout(BROWSER_TIMEOUT_MS)
    return context


def detect_authwall_or_login(page: Page) -> Dict[str, Any]:
    """Detects whether current page redirected to an authwall, login wall, or verification challenge."""
    current_url = page.url.lower()

    # 1. URL-based detection
    linkedin_login_urls = [
        "linkedin.com/authwall",
        "linkedin.com/login",
        "linkedin.com/checkpoint",
        "linkedin.com/signup",
        "linkedin.com/uas/login",
    ]
    if any(k in current_url for k in linkedin_login_urls):
        return {
            "auth_required": True,
            "platform": "LinkedIn",
            "url": page.url,
            "reason": "LinkedIn authwall or login redirect detected in URL.",
        }

    if "login.indeed.com" in current_url:
        return {
            "auth_required": True,
            "platform": "Indeed",
            "url": page.url,
            "reason": "Indeed sign-in page detected.",
        }

    # 2. Page Title checks
    try:
        title = page.title().lower()
        if "sign in | linkedin" in title or "linkedin login" in title or "security verification | linkedin" in title:
            return {
                "auth_required": True,
                "platform": "LinkedIn",
                "url": page.url,
                "reason": f"LinkedIn login title: '{page.title()}'",
            }
        if "sign in | indeed" in title:
            return {
                "auth_required": True,
                "platform": "Indeed",
                "url": page.url,
                "reason": f"Indeed login title: '{page.title()}'",
            }
    except Exception:
        pass

    # 3. DOM element checks for sign-in prompts blocking page
    try:
        # LinkedIn authwall modal or join banner
        if page.locator(".authwall-join-form, #login-submit, form[action*='checkpoint']").count() > 0:
            return {
                "auth_required": True,
                "platform": "LinkedIn",
                "url": page.url,
                "reason": "LinkedIn login or checkpoint form element present on page.",
            }

        # Check for generic sign-in walls blocking the body
        if page.locator("input[type='password']").count() > 0 and page.locator("input[type='email'], input[name='session_key'], input#username").count() > 0:
            # Check if main content is hidden or minimal
            body_text = page.locator("body").inner_text().lower()
            if "sign in to view" in body_text or "log in to continue" in body_text or "join linkedin to view" in body_text:
                return {
                    "auth_required": True,
                    "platform": "LinkedIn" if "linkedin" in body_text else "Generic",
                    "url": page.url,
                    "reason": "Login requirement detected in page content.",
                }
    except Exception:
        pass

    return {
        "auth_required": False,
        "platform": "",
        "url": page.url,
        "reason": "",
    }


class InteractiveBrowserSession:
    """Manages an interactive visible browser window for candidate authentication."""

    def __init__(self):
        self.lock = threading.Lock()
        self.playwright: Optional[Playwright] = None
        self.context: Optional[BrowserContext] = None
        self.page: Optional[Page] = None
        self.active_platform: Optional[str] = None
        self.active_url: Optional[str] = None
        self.is_active = False

    def open_login_window(self, url: str = "https://www.linkedin.com/login", platform: str = "LinkedIn") -> bool:
        """Launches a visible Chromium session with persistent profile for interactive login."""
        with self.lock:
            if self.is_active:
                if self.page:
                    try:
                        self.page.goto(url)
                        self.active_url = url
                        self.active_platform = platform
                        return True
                    except Exception:
                        pass
                return True

            try:
                self.playwright = sync_playwright().start()
                self.context = create_persistent_context(
                    self.playwright,
                    headless=False,
                    slow_mo=0,
                )
                self.page = self.context.pages[0] if self.context.pages else self.context.new_page()
                self.page.goto(url)
                self.active_platform = platform
                self.active_url = url
                self.is_active = True
                return True
            except Exception as e:
                self.cleanup()
                raise e

    def close(self):
        """Closes the interactive login window and persists all cookies."""
        with self.lock:
            self.cleanup()

    def cleanup(self):
        try:
            if self.context:
                self.context.close()
        except Exception:
            pass
        try:
            if self.playwright:
                self.playwright.stop()
        except Exception:
            pass
        self.context = None
        self.playwright = None
        self.page = None
        self.is_active = False
        self.active_platform = None
        self.active_url = None

    def get_status(self) -> Dict[str, Any]:
        """Returns the current state of interactive login session."""
        with self.lock:
            return {
                "is_active": self.is_active,
                "platform": self.active_platform,
                "current_url": self.active_url,
                "profile_dir": str(BROWSER_PROFILE_DIR),
            }


# Global interactive login session manager
interactive_browser = InteractiveBrowserSession()
