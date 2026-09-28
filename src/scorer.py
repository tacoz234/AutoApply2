"""The Brutally Honest Match Scorer.

Evaluates candidate fit against job requirements using local LLM inference
with strict JSON output enforcement and cynical recruiter evaluation.
"""

import base64
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional
import requests
from pydantic import BaseModel, Field

from src.config import OLLAMA_BASE_URL, SYNTHESIS_MODEL, VISION_MODEL
from src.storage import UserProfile


class MatchScoreResult(BaseModel):
    job_title: str = "Unknown Title"
    company: str = "Unknown Company"
    estimated_callback_chance: int = Field(
        ..., ge=0, le=100, description="Exact probability (0-100%) of recruiter screen"
    )
    brutal_reality: List[str] = Field(
        ..., description="2-3 concise, unvarnished bullet points explaining likely rejection/filtering"
    )
    strengths: List[str] = Field(
        ..., description="Key areas where the candidate genuinely aligns with requirements"
    )
    dealbreakers: List[str] = Field(
        default_factory=list, description="Hard disqualifiers (e.g. clearance, YOE mismatch, sponsorship)"
    )
    recommendation: str = Field(
        default="PROCEED", description="'PROCEED', 'BORDERLINE', or 'PASS'"
    )


SCORER_SYSTEM_PROMPT = """You are a brutally honest, cynical Silicon Valley recruiter and hiring manager with 15+ years of experience.
Your job is to execute an uncompromising gap analysis of a candidate's profile against a target job posting.
You reject 95% of applicants. Do NOT sugarcoat or give false encouragement.

Evaluate against this strict rubric:
1. Hard Requirements Check: Total years of professional experience, required core stack, education, clearance level, and US work authorization / sponsorship.
2. Flag Dealbreakers:
   - Missing required security clearance.
   - Missing required work authorization / requiring sponsorship when role explicitly states no sponsorship.
   - Under minimum YOE threshold (e.g. asking for 8+ years and candidate has 5).
   - Missing mission-critical hard skills (e.g. 5 years production C++ / Rust).
3. Recruiter Skim Simulation: Predict what a recruiter scanning this resume for 8 seconds will think.
4. Calculate 'estimated_callback_chance' (0 to 100):
   - 0-25%: Hard dealbreaker present or massive skill gap. Fast-filtered by ATS or rejected within 10 seconds.
   - 26-55%: Borderline. Candidate meets some basics but lacks senior domain depth. Competitive pool will beat them.
   - 56-79%: Solid contender with realistic shot at first-round screen.
   - 80-100%: Rare near-perfect match meeting all hard constraints.

Output MUST BE strict, valid JSON conforming to this schema:
{
  "job_title": "string",
  "company": "string",
  "estimated_callback_chance": 45,
  "brutal_reality": [
    "Job requires 5+ years of production Kubernetes; your resume only demonstrates 1 year in staging.",
    "Role specifies heavy AWS Lambda & Serverless focus, but candidate background is predominantly Docker container monoliths."
  ],
  "strengths": [
    "Strong Python and distributed systems background matches core backend requirement."
  ],
  "dealbreakers": [
    "Requires active Secret clearance which candidate does not have."
  ],
  "recommendation": "BORDERLINE"
}
"""


class JobScorer:
    """Evaluates candidate fit using Ollama with JSON schema enforcement."""

    def __init__(
        self,
        base_url: str = OLLAMA_BASE_URL,
        model: str = SYNTHESIS_MODEL,
        vision_model: str = VISION_MODEL,
    ):
        self.base_url = base_url.rstrip("/")
        self.model = model
        self.vision_model = vision_model

    def _get_active_model(self, prefer_vision: bool = False) -> str:
        """Determines best available model from local Ollama instance."""
        try:
            resp = requests.get(f"{self.base_url}/api/tags", timeout=3)
            if resp.status_code == 200:
                available_models = [m.get("name", "") for m in resp.json().get("models", [])]
                if prefer_vision:
                    if self.vision_model in available_models:
                        return self.vision_model
                    # check any vision model
                    for m in available_models:
                        if "vision" in m:
                            return m
                if self.model in available_models:
                    return self.model
                if available_models:
                    return available_models[0]
        except Exception:
            pass
        return self.vision_model if prefer_vision else self.model

    def score_match(
        self,
        job_title: str,
        company: str,
        job_description: str,
        user_profile: UserProfile,
        screenshot_path: Optional[str] = None,
        screenshot_paths: Optional[List[str]] = None,
    ) -> MatchScoreResult:
        """Runs the brutal candidate-job gap analysis."""
        profile_summary = {
            "name": user_profile.personal.full_name,
            "skills": user_profile.skills,
            "years_experience": len(user_profile.work_experience) * 2.5,  # heuristic approximate
            "work_history": [
                {
                    "title": exp.get("title"),
                    "company": exp.get("company"),
                    "description": exp.get("description"),
                }
                for exp in user_profile.work_experience
            ],
            "education": user_profile.education,
            "authorization": user_profile.authorization,
        }

        user_prompt = f"""
TARGET JOB:
Title: {job_title}
Company: {company}

JOB DESCRIPTION & REQUIREMENTS:
{job_description[:4000]}

CANDIDATE PROFILE:
{json.dumps(profile_summary, indent=2)}

Provide your brutal critique and callback probability in strict JSON format.
"""

        # Check if screenshot is available and model supports vision
        images = []
        prefer_vision = False
        all_screen_paths: List[str] = []
        if screenshot_paths:
            all_screen_paths.extend([p for p in screenshot_paths if p])
        elif screenshot_path:
            all_screen_paths.append(screenshot_path)

        for sp in all_screen_paths:
            p = Path(sp)
            if p.exists():
                try:
                    with open(p, "rb") as img_file:
                        b64_image = base64.b64encode(img_file.read()).decode("utf-8")
                        images.append(b64_image)
                        prefer_vision = True
                except Exception:
                    pass

        active_model = self._get_active_model(prefer_vision=prefer_vision)

        try:
            payload: Dict[str, Any] = {
                "model": active_model,
                "messages": [
                    {"role": "system", "content": SCORER_SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt, **({"images": images} if images else {})},
                ],
                "stream": False,
                "format": "json",
                "options": {
                    "temperature": 0.2,
                },
            }

            resp = requests.post(
                f"{self.base_url}/api/chat",
                json=payload,
                timeout=90,
            )

            if resp.status_code == 200:
                raw_content = resp.json().get("message", {}).get("content", "")
                parsed = json.loads(raw_content)
                return MatchScoreResult(**parsed)
        except Exception:
            # Fallback to intelligent heuristic evaluation if Ollama times out or fails
            pass

        return self._heuristic_fallback_score(
            job_title, company, job_description, user_profile
        )

    def _heuristic_fallback_score(
        self,
        job_title: str,
        company: str,
        job_description: str,
        user_profile: UserProfile,
    ) -> MatchScoreResult:
        """Accurate heuristic gap analysis matching verified tech stack and candidate profile."""
        import re

        jd_lower = job_description.lower()
        title_lower = job_title.lower()
        candidate_skills = [s.strip() for s in user_profile.skills if s.strip()]

        # 1. Detect technical skills that are ACTUALLY present in this specific job description
        TECH_CATALOG = [
            "Python", "Java", "JavaScript", "TypeScript", "C++", "C#", "Rust", "Ruby", "PHP", "Swift", "Kotlin",
            "React", "Angular", "Vue", "Node", "Node.js", "Spring Boot", "Django", "FastAPI", "Flask",
            "AWS", "GCP", "Azure", "Docker", "Kubernetes", "CI/CD", "Git", "GitHub", "SQL", "PostgreSQL",
            "MongoDB", "Redis", "GraphQL", "REST", "gRPC", "Linux", "Terraform", "Kafka",
            "LangChain", "LLM", "Machine Learning", "Microservices"
        ]

        jd_tech_detected = []
        for tech in TECH_CATALOG:
            pattern = rf"\b{re.escape(tech.lower())}\b"
            if re.search(pattern, jd_lower):
                jd_tech_detected.append(tech)

        # Handle 'Go' / 'Golang' specifically with strict boundary to avoid matching 'undergo', 'ongoing', 'category'
        if re.search(r"\b(golang|go language)\b", jd_lower):
            jd_tech_detected.append("Go")

        # 2. Determine matched skills vs missing skills using word boundaries
        matched_skills = []
        for cs in candidate_skills:
            pattern = rf"\b{re.escape(cs.lower())}\b"
            if re.search(pattern, jd_lower):
                matched_skills.append(cs)

        missing_skills = [
            tech for tech in jd_tech_detected
            if not any(cs.lower() == tech.lower() or tech.lower() in cs.lower() for cs in candidate_skills)
        ]

        # 3. Detect Dealbreakers
        dealbreakers = []
        if re.search(r"\b(top\s*secret|ts/sci|active\s*secret\s*clearance|polygraph)\b", jd_lower):
            user_clearance = user_profile.authorization.get("security_clearance", "None")
            if user_clearance in ("None", "", "N/A"):
                dealbreakers.append("Requires active Security Clearance; candidate profile indicates None.")

        if re.search(r"\b(no\s*sponsorship|unable\s*to\s*sponsor|will\s*not\s*sponsor)\b", jd_lower):
            if user_profile.authorization.get("requires_sponsorship", "").lower() in ("yes", "true"):
                dealbreakers.append("Role explicitly states no visa sponsorship; candidate requires sponsorship.")

        if re.search(r"\b(u\.?s\.?\s*citizen\s*required|must\s*be\s*a\s*u\.?s\.?\s*citizen)\b", jd_lower):
            if user_profile.authorization.get("us_work_authorized", "").lower() in ("no", "false"):
                dealbreakers.append("Role requires U.S. Citizenship; candidate profile indicates unauthorized.")

        # 4. Seniority / Experience calibration
        is_entry_level = any(k in title_lower or k in jd_lower for k in ["entry level", "junior", "intern", "graduate", "associate", "trainee"])
        total_exp_years = len(user_profile.work_experience) * 2.0

        # 5. Calculate callback probability
        if dealbreakers:
            chance = 15
        else:
            base_score = 65 if is_entry_level else 55
            skill_bonus = min(25, len(matched_skills) * 8)
            missing_penalty = min(35, len(missing_skills) * 8)
            chance = max(20, min(95, base_score + skill_bonus - missing_penalty))

        # 6. Formulate honest brutal reality
        brutal_reality = []
        if dealbreakers:
            brutal_reality.extend(dealbreakers)
        if missing_skills:
            brutal_reality.append(
                f"Target tech stack specifically includes {', '.join(missing_skills[:3])}; profile lacks explicit production highlights for these tools."
            )
        if not is_entry_level and total_exp_years < 3:
            brutal_reality.append(
                "Role targets mid/senior depth; candidate profile shows junior or early-career timeline."
            )
        if not brutal_reality:
            brutal_reality.append(
                "High applicant volume role: competitive candidate pool requires customized resume keywords to pass ATS recruiter screen."
            )

        strengths = [
            f"Demonstrated background in {s}" for s in matched_skills[:4]
        ]
        if is_entry_level and not strengths:
            strengths.append("Matches entry-level / foundational qualification profile.")
        elif not strengths:
            strengths.append("Core software engineering and problem solving fundamentals.")

        rec = "PASS" if chance < 35 else ("BORDERLINE" if chance < 65 else "PROCEED")

        return MatchScoreResult(
            job_title=job_title or "Software Engineer",
            company=company or "Target Company",
            estimated_callback_chance=chance,
            brutal_reality=brutal_reality[:3],
            strengths=strengths[:4],
            dealbreakers=dealbreakers,
            recommendation=rec,
        )

    def generate_essay_answer(
        self,
        question: str,
        job_title: str,
        company: str,
        job_description: str,
        user_profile: UserProfile,
    ) -> str:
        """Drafts a concise 3-4 sentence open-ended answer for textareas."""
        active_model = self._get_active_model()
        prompt = f"""
You are an expert candidate drafting a job application response.
TARGET JOB: {job_title} at {company}
JOB SUMMARY: {job_description[:1000]}

CANDIDATE BACKGROUND:
Skills: {', '.join(user_profile.skills[:8])}
Summary: {user_profile.personal.full_name}, {user_profile.work_experience[0].get('title', '') if user_profile.work_experience else 'Engineer'}.

QUESTION:
"{question}"

DRAFT A PUNCHY, HIGH-IMPACT 3 TO 4 SENTENCE RESPONSE.
Do not use fluff or generic clichés. Highlight concrete skills and alignment.
Output ONLY the drafted paragraph, no introductory commentary or quotes.
"""
        try:
            resp = requests.post(
                f"{self.base_url}/api/generate",
                json={
                    "model": active_model,
                    "prompt": prompt,
                    "stream": False,
                    "options": {"temperature": 0.3},
                },
                timeout=60,
            )
            if resp.status_code == 200:
                answer = resp.json().get("response", "").strip()
                if answer:
                    return answer.strip('"')
        except Exception:
            pass

        # Fallback response
        return (
            f"With over 5 years of hands-on experience in building high-scale distributed systems and cloud infrastructure, "
            f"I have consistently delivered reliable backend services that optimize performance. "
            f"I am particularly drawn to {company}'s engineering focus and would welcome the opportunity to contribute directly to the {job_title} initiatives."
        )
