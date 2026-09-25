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

# Ensure data and screenshot directories exist
DATA_DIR.mkdir(parents=True, exist_ok=True)
SCREENSHOTS_DIR.mkdir(parents=True, exist_ok=True)

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
