"""Local Resume Parsing Engine for ApplyFlow.

Extracts text from PDF (via PyMuPDF/fitz), Word (.docx), or plain text,
and synthesizes structured candidate profiles using local Ollama inference
paired with a deterministic regex and heuristic extraction safety net.
"""

from __future__ import annotations

from pathlib import Path
import json
import re
from typing import Any, Dict, List, Optional, Union
import fitz  # PyMuPDF
import requests

from src.config import OLLAMA_BASE_URL, SYNTHESIS_MODEL, VISION_MODEL


COMMON_SKILLS_DICTIONARY = [
    # Languages
    "python", "javascript", "typescript", "go", "golang", "rust", "java", "c++", "c#", "c",
    "ruby", "php", "swift", "kotlin", "scala", "sql", "html", "css", "bash", "shell",
    # Frameworks & Libraries
    "fastapi", "flask", "django", "react", "next.js", "nextjs", "vue", "angular", "node.js",
    "nodejs", "express", "spring", "spring boot", "asp.net", "graphql", "tailwind", "redux",
    # Data & Storage
    "postgresql", "postgres", "mysql", "sqlite", "mongodb", "redis", "elasticsearch",
    "cassandra", "dynamodb", "snowflake", "kafka", "rabbitmq",
    # Cloud & DevOps
    "docker", "kubernetes", "k8s", "aws", "amazon web services", "gcp", "google cloud",
    "azure", "terraform", "ansible", "ci/cd", "github actions", "gitlab ci", "jenkins",
    "prometheus", "grafana", "linux", "nginx",
    # AI & ML
    "machine learning", "deep learning", "nlp", "computer vision", "pytorch", "tensorflow",
    "llm", "rag", "langchain", "ollama", "pandas", "numpy", "scikit-learn",
    # Architecture & Tools
    "microservices", "distributed systems", "rest api", "grpc", "git", "linux", "agile", "scrum"
]


class ResumeParser:
    """Extracts raw text and parses candidate fields into structured profile schema."""

    def __init__(self, ollama_url: str = OLLAMA_BASE_URL):
        self.ollama_url = ollama_url.rstrip("/")

    def extract_text_from_file(self, file_path: str | Path) -> str:
        """Extracts plain text from PDF, DOCX, or TXT file."""
        path = Path(file_path)
        if not path.exists():
            raise FileNotFoundError(f"Resume file not found at: {path}")

        suffix = path.suffix.lower()
        if suffix == ".pdf":
            return self._extract_text_from_pdf(path)
        elif suffix in (".docx", ".doc"):
            return self._extract_text_from_docx(path)
        else:
            return path.read_text(encoding="utf-8", errors="ignore")

    def _extract_text_from_pdf(self, path: Path) -> str:
        """Extracts text from PDF using PyMuPDF (fitz)."""
        text_parts = []
        with fitz.open(str(path)) as doc:
            for page in doc:
                text_parts.append(page.get_text())
        return "\n".join(text_parts).strip()

    def _extract_text_from_docx(self, path: Path) -> str:
        """Extracts text from DOCX using python-docx."""
        try:
            import docx
            doc = docx.Document(str(path))
            return "\n".join([p.text for p in doc.paragraphs if p.text.strip()]).strip()
        except Exception:
            # Fallback to binary/string search if docx parsing fails
            return path.read_text(encoding="utf-8", errors="ignore")

    def parse_heuristics(self, text: str) -> Dict[str, Any]:
        """Deterministic regex and keyword parsing for essential profile fields."""
        res: Dict[str, Any] = {
            "first_name": "",
            "last_name": "",
            "full_name": "",
            "email": "",
            "phone": "",
            "city": "",
            "state": "",
            "postal_code": "",
            "country": "United States",
            "linkedin": "",
            "github": "",
            "portfolio": "",
            "skills": [],
            "desired_salary": "",
            "notice_period": "2 weeks",
        }

        # 1. Email extraction
        email_match = re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", text)
        if email_match:
            res["email"] = email_match.group(0).strip()

        # 2. Phone extraction (handles (123) 456-7890, 123-456-7890, 123.456.7890)
        phone_match = re.search(r"(?:\+?1[-.\s]?)?\(?[0-9]{3}\)?[-.\s]?[0-9]{3}[-.\s]?[0-9]{4}", text)
        if phone_match:
            res["phone"] = phone_match.group(0).strip()

        # 3. LinkedIn link
        linkedin_match = re.search(r"(?:https?:\/\/)?(?:www\.)?linkedin\.com\/in\/([a-zA-Z0-9_-]+)", text, re.IGNORECASE)
        if linkedin_match:
            slug = linkedin_match.group(1)
            res["linkedin"] = f"https://linkedin.com/in/{slug}"

        # 4. GitHub link
        github_match = re.search(r"(?:https?:\/\/)?(?:www\.)?github\.com\/([a-zA-Z0-9_-]+)", text, re.IGNORECASE)
        if github_match:
            user = github_match.group(1)
            if user.lower() not in ("about", "features", "pricing"):
                res["github"] = f"https://github.com/user" if user == "user" else f"https://github.com/{user}"

        # 5. Portfolio / website link
        pref_match = re.search(r"(?:portfolio|website|site):\s*(https?:\/\/[^\s]+|[a-zA-Z0-9_-]+\.[a-zA-Z]{2,})", text, re.IGNORECASE)
        if pref_match:
            p_url = pref_match.group(1).strip()
            if not p_url.startswith("http"):
                p_url = f"https://{p_url}"
            res["portfolio"] = p_url
        else:
            portfolio_match = re.search(r"(?<!@)\b(?:https?:\/\/)?(?:www\.)?([a-zA-Z0-9_-]+\.(?:dev|me|io|tech))(?:\/)?\b", text, re.IGNORECASE)
            if portfolio_match:
                found_url = portfolio_match.group(0).strip()
                if "linkedin" not in found_url and "github" not in found_url:
                    if not found_url.startswith("http"):
                        found_url = f"https://{found_url}"
                    res["portfolio"] = found_url

        # 6. Name extraction from top lines
        lines = [line.strip() for line in text.splitlines() if line.strip()]
        for line in lines[:5]:
            if "@" in line or "http" in line or "resume" in line.lower() or "curriculum" in line.lower():
                continue
            clean_name = re.sub(r"\s*[-–|].*$", "", line).strip()
            tokens = clean_name.split()
            if 2 <= len(tokens) <= 4 and all(t.replace(".", "").isalpha() for t in tokens):
                res["full_name"] = clean_name
                res["first_name"] = tokens[0]
                res["last_name"] = tokens[-1]
                break

        # 7. City, State, Postal extraction heuristic
        loc_match = re.search(r"\b([A-Z][a-zA-Z\s]+),\s*([A-Z]{2})\b(?:\s+(\d{5}))?", text)
        if loc_match:
            res["city"] = loc_match.group(1).strip()
            res["state"] = loc_match.group(2).strip()
            if loc_match.group(3):
                res["postal_code"] = loc_match.group(3).strip()

        # 8. Skills extraction against dictionary
        lower_text = " " + text.lower() + " "
        found_skills = []
        for skill in COMMON_SKILLS_DICTIONARY:
            pattern = r"(?<!\w)" + re.escape(skill) + r"(?!\w)"
            if re.search(pattern, lower_text):
                # Format nicely
                found_skills.append(skill.title() if len(skill) > 3 and skill not in ("ci/cd", "k8s") else skill.upper() if len(skill) <= 3 else skill)

        # Standardize skill capitalizations
        canonical_map = {
            "python": "Python", "javascript": "JavaScript", "typescript": "TypeScript",
            "fastapi": "FastAPI", "react": "React", "docker": "Docker", "kubernetes": "Kubernetes",
            "k8s": "Kubernetes", "aws": "AWS", "gcp": "GCP", "sql": "SQL", "postgresql": "PostgreSQL",
            "postgres": "PostgreSQL", "redis": "Redis", "mongodb": "MongoDB", "node.js": "Node.js",
            "nodejs": "Node.js", "ci/cd": "CI/CD", "linux": "Linux", "git": "Git", "graphql": "GraphQL"
        }
        cleaned_skills = []
        for s in found_skills:
            val = canonical_map.get(s.lower(), s.title())
            if val not in cleaned_skills:
                cleaned_skills.append(val)
        res["skills"] = cleaned_skills[:15]

        return res

    def parse_with_llm(self, text: str) -> Optional[Dict[str, Any]]:
        """Uses local Ollama structured inference to extract comprehensive profile."""
        prompt = f"""You are a professional technical resume parser. Analyze this resume text and extract candidate details.

RESUME TEXT:
{text[:4500]}

Return ONLY valid JSON matching this schema:
{{
  "first_name": "string",
  "last_name": "string",
  "full_name": "string",
  "email": "string",
  "phone": "string",
  "city": "string",
  "state": "string",
  "postal_code": "string",
  "linkedin": "string",
  "github": "string",
  "portfolio": "string",
  "skills": ["string"],
  "desired_salary": "string",
  "notice_period": "string",
  "work_experience": [
    {{
      "title": "string",
      "company": "string",
      "location": "string",
      "start_date": "string",
      "end_date": "string",
      "description": "string"
    }}
  ],
  "education": [
    {{
      "degree": "string",
      "field_of_study": "string",
      "school": "string",
      "graduation_year": "string"
    }}
  ]
}}
"""
        models_to_try = [SYNTHESIS_MODEL, VISION_MODEL, "llama3.2-vision:latest", "llama3.1:8b", "qwen2.5:7b"]
        for model in models_to_try:
            try:
                resp = requests.post(
                    f"{self.ollama_url}/api/generate",
                    json={
                        "model": model,
                        "prompt": prompt,
                        "format": "json",
                        "stream": False,
                        "options": {"temperature": 0.1},
                    },
                    timeout=18,
                )
                if resp.status_code == 200:
                    data = resp.json().get("response", "{}")
                    parsed = json.loads(data)
                    if isinstance(parsed, dict) and (parsed.get("full_name") or parsed.get("email") or parsed.get("skills")):
                        return parsed
            except Exception:
                continue

        return None

    def parse_resume(self, file_path: str | Path) -> Dict[str, Any]:
        """High-level entry point: extracts text and combines LLM extraction with deterministic heuristics."""
        raw_text = self.extract_text_from_file(file_path)
        heuristic_data = self.parse_heuristics(raw_text)

        # Attempt LLM extraction
        llm_data = self.parse_with_llm(raw_text)

        # Merge results, preferring LLM when available, falling back to heuristics
        merged: Dict[str, Any] = {
            "personal": {
                "first_name": (llm_data.get("first_name") if llm_data else "") or heuristic_data["first_name"],
                "last_name": (llm_data.get("last_name") if llm_data else "") or heuristic_data["last_name"],
                "full_name": (llm_data.get("full_name") if llm_data else "") or heuristic_data["full_name"],
                "email": (llm_data.get("email") if llm_data else "") or heuristic_data["email"],
                "phone": (llm_data.get("phone") if llm_data else "") or heuristic_data["phone"],
                "address": (llm_data.get("address") if llm_data else "") or "",
                "city": (llm_data.get("city") if llm_data else "") or heuristic_data["city"],
                "state": (llm_data.get("state") if llm_data else "") or heuristic_data["state"],
                "postal_code": (llm_data.get("postal_code") if llm_data else "") or heuristic_data["postal_code"],
                "country": "United States",
            },
            "links": {
                "linkedin": (llm_data.get("linkedin") if llm_data else "") or heuristic_data["linkedin"],
                "github": (llm_data.get("github") if llm_data else "") or heuristic_data["github"],
                "portfolio": (llm_data.get("portfolio") if llm_data else "") or heuristic_data["portfolio"],
            },
            "skills": list(set((llm_data.get("skills") if llm_data and llm_data.get("skills") else []) + heuristic_data["skills"])),
            "preferences": {
                "desired_salary": (llm_data.get("desired_salary") if llm_data else "") or heuristic_data["desired_salary"] or "150,000",
                "notice_period": (llm_data.get("notice_period") if llm_data else "") or heuristic_data["notice_period"] or "2 weeks",
            },
            "authorization": {
                "us_work_authorized": "Yes",
                "requires_sponsorship": "No",
                "security_clearance": "None",
            },
            "work_experience": (llm_data.get("work_experience") if llm_data else []) or [],
            "education": (llm_data.get("education") if llm_data else []) or [],
            "resume_file": Path(file_path).name,
            "raw_text_snippet": raw_text[:500],
        }

        # If full_name is populated but first/last are missing
        if merged["personal"]["full_name"] and not merged["personal"]["first_name"]:
            parts = merged["personal"]["full_name"].split()
            if len(parts) >= 2:
                merged["personal"]["first_name"] = parts[0]
                merged["personal"]["last_name"] = parts[-1]

        return merged
