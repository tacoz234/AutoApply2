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
        if screenshot_path and Path(screenshot_path).exists():
            try:
                with open(screenshot_path, "rb") as img_file:
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
        """Reliable heuristic fallback ensuring pipeline never crashes."""
        jd_lower = job_description.lower()
        skills = [s.lower() for s in user_profile.skills]
        matched_skills = [s for s in skills if s in jd_lower]
        missing_skills = [
            kw for kw in ["kubernetes", "c++", "rust", "go", "graphql", "terraform"]
            if kw in jd_lower and kw not in skills
        ]

        dealbreakers = []
        if "clearance" in jd_lower and "secret" in jd_lower:
            user_clearance = user_profile.authorization.get("security_clearance", "None")
            if user_clearance == "None":
                dealbreakers.append("Requires active Security Clearance; profile indicates None.")

        if "sponsorship" in jd_lower and ("not provide" in jd_lower or "no sponsorship" in jd_lower):
            if user_profile.authorization.get("requires_sponsorship") == "Yes":
                dealbreakers.append("Job does not sponsor visas; candidate requires sponsorship.")

        chance = 65
        if dealbreakers:
            chance = 15
        elif missing_skills:
            chance = max(25, 65 - (len(missing_skills) * 15))

        brutal_reality = []
        if dealbreakers:
            brutal_reality.extend(dealbreakers)
        if missing_skills:
            brutal_reality.append(
                f"Job specifically calls for {', '.join(missing_skills[:3]).title()}; candidate profile shows zero verified production track record."
            )
        if not brutal_reality:
            brutal_reality.append(
                "High applicant volume role: without a strong internal referral, this application faces a 70%+ chance of ATS queue stagnation."
            )

        strengths = [
            f"Demonstrated background in {s.title()}" for s in matched_skills[:4]
        ] or ["Core software engineering fundamentals."]

        rec = "PASS" if chance < 30 else ("BORDERLINE" if chance < 60 else "PROCEED")

        return MatchScoreResult(
            job_title=job_title or "Software Engineer",
            company=company or "Target Company",
            estimated_callback_chance=chance,
            brutal_reality=brutal_reality[:3],
            strengths=strengths[:3],
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
