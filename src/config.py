"""Configuration settings and paths for ApplyFlow."""

from pathlib import Path
import os

# Project root directory
ROOT_DIR = Path(__file__).resolve().parent.parent

# Data paths
DATA_DIR = ROOT_DIR / "data"
SCREENSHOTS_DIR = DATA_DIR / "screenshots"
USER_PROFILE_PATH = DATA_DIR / "user_profile.json"
QA_BANK_PATH = DATA_DIR / "qa_bank.json"
APPLICATIONS_DB_PATH = DATA_DIR / "applications.sqlite"
DEFAULT_RESUME_PATH = DATA_DIR / "sample_resume.pdf"
BROWSER_PROFILE_DIR = DATA_DIR / "browser_profile"

# Ensure data and screenshot directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)
BROWSER_PROFILE_DIR.mkdir(parents=True, exist_ok=True)

# Ollama & LLM configurations
OLLAMA_BASE_URL = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434")

# Model configuration with environment variable overrides
# Preferred vision model for screenshot inspection & reading
VISION_MODEL = os.getenv("OLLAMA_VISION_MODEL", "llama3.2-vision:latest")
# Preferred synthesis / reasoning model for match critique and essay answers
SYNTHESIS_MODEL = os.getenv("OLLAMA_SYNTHESIS_MODEL", "llama3.2-vision:latest")
# Preferred fast model for field extraction / JSON parsing
EXTRACTION_MODEL = os.getenv("OLLAMA_EXTRACTION_MODEL", "llama3.2-vision:latest")

# Playwright Browser configurations
HEADLESS = os.getenv("HEADLESS", "false").lower() in ("true", "1", "yes")
SLOW_MO_MS = int(os.getenv("SLOW_MO_MS", "150"))
VIEWPORT = {"width": 1280, "height": 900}
BROWSER_TIMEOUT_MS = int(os.getenv("BROWSER_TIMEOUT_MS", "30000"))
USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/124.0.0.0 Safari/537.36"
)

# Automated Portal Credentials (from .env)
ENV_FILE_PATH = ROOT_DIR / ".env"
try:
    from dotenv import load_dotenv
    if ENV_FILE_PATH.exists():
        load_dotenv(ENV_FILE_PATH, override=True)
except Exception:
    pass

LINKEDIN_EMAIL = os.getenv("LINKEDIN_EMAIL", "").strip()
LINKEDIN_PASSWORD = os.getenv("LINKEDIN_PASSWORD", "").strip()
INDEED_EMAIL = os.getenv("INDEED_EMAIL", "").strip()
INDEED_PASSWORD = os.getenv("INDEED_PASSWORD", "").strip()


def get_portal_credentials(platform: str = "linkedin") -> tuple[str, str]:
    """Retrieves stored email & password for a job platform."""
    p_lower = platform.lower()
    if "link" in p_lower:
        email = os.getenv("LINKEDIN_EMAIL", "").strip()
        pwd = os.getenv("LINKEDIN_PASSWORD", "").strip()
    elif "indeed" in p_lower:
        email = os.getenv("INDEED_EMAIL", "").strip()
        pwd = os.getenv("INDEED_PASSWORD", "").strip()
    else:
        email = ""
        pwd = ""
    return email, pwd


def save_env_credentials(updates: dict[str, str]) -> None:
    """Updates key-value pairs in the root .env file and updates os.environ in memory."""
    lines = []
    existing_keys = set()
    if ENV_FILE_PATH.exists():
        with open(ENV_FILE_PATH, "r", encoding="utf-8") as f:
            for line in f:
                stripped = line.strip()
                if stripped and not stripped.startswith("#") and "=" in stripped:
                    key = stripped.split("=", 1)[0].strip()
                    if key in updates:
                        lines.append(f"{key}={updates[key]}\n")
                        existing_keys.add(key)
                        continue
                lines.append(line)

    for k, v in updates.items():
        if k not in existing_keys:
            lines.append(f"{k}={v}\n")
        os.environ[k] = v

    with open(ENV_FILE_PATH, "w", encoding="utf-8") as f:
        f.writelines(lines)

