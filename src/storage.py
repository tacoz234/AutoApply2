"""Storage and persistence layer for ApplyFlow.

Handles user profile loading, QA bank querying and real-time auto-persistence,
and SQLite application logging.
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import re
import sqlite3
from typing import Any, Dict, List, Optional
from pydantic import BaseModel, Field

from src.config import (
    APPLICATIONS_DB_PATH,
    QA_BANK_PATH,
    USER_PROFILE_PATH,
    DEFAULT_RESUME_PATH,
)


class PersonalInfo(BaseModel):
    first_name: str = ""
    last_name: str = ""
    full_name: str = ""
    email: str = ""
    phone: str = ""
    address: str = ""
    city: str = ""
    state: str = ""
    postal_code: str = ""
    country: str = "United States"


class UserProfile(BaseModel):
    personal: PersonalInfo = Field(default_factory=PersonalInfo)
    links: Dict[str, str] = Field(default_factory=dict)
    preferences: Dict[str, str] = Field(default_factory=dict)
    authorization: Dict[str, str] = Field(default_factory=dict)
    eeoc: Dict[str, str] = Field(default_factory=dict)
    work_experience: List[Dict[str, Any]] = Field(default_factory=list)
    education: List[Dict[str, Any]] = Field(default_factory=list)
    skills: List[str] = Field(default_factory=list)
    certifications: List[str] = Field(default_factory=list)
    resume_file: str = "sample_resume.pdf"
    is_setup_completed: bool = False


class QABankEntry(BaseModel):
    id: str
    category: str = "general"
    question_patterns: List[str] = Field(default_factory=list)
    answer: str
    field_type: str = "text"
    created_at: str = Field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )


class ApplicationLog(BaseModel):
    id: str
    job_title: str
    company: str
    url: str
    match_score: float
    brutal_critique: str
    status: str
    applied_at: str
    screenshot_path: Optional[str] = None


class StorageManager:
    """Manages files and database stores for ApplyFlow."""

    def __init__(self):
        self.profile_path = USER_PROFILE_PATH
        self.qa_path = QA_BANK_PATH
        self.db_path = APPLICATIONS_DB_PATH
        self._init_sqlite_db()

    def _init_sqlite_db(self) -> None:
        """Initializes the applications SQLite table if not present."""
        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                CREATE TABLE IF NOT EXISTS applications (
                    id TEXT PRIMARY KEY,
                    job_title TEXT NOT NULL,
                    company TEXT NOT NULL,
                    url TEXT NOT NULL,
                    match_score REAL,
                    brutal_critique TEXT,
                    status TEXT NOT NULL,
                    applied_at TEXT NOT NULL,
                    screenshot_path TEXT
                )
                """
            )
            conn.commit()
        finally:
            conn.close()

    def load_profile(self) -> UserProfile:
        """Loads canonical user profile from JSON."""
        if not self.profile_path.exists():
            default_profile = UserProfile()
            self.save_profile(default_profile)
            return default_profile
        with open(self.profile_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return UserProfile(**data)

    def save_profile(self, profile: UserProfile) -> None:
        """Saves user profile back to JSON."""
        with open(self.profile_path, "w", encoding="utf-8") as f:
            json.dump(profile.model_dump(), f, indent=2)

    def set_setup_completed(self, status: bool = True) -> None:
        """Sets the first-time setup completion state."""
        profile = self.load_profile()
        profile.is_setup_completed = status
        self.save_profile(profile)

    def save_uploaded_resume(self, file_bytes: bytes, filename: str) -> str:
        """Saves an uploaded resume file into data/ directory and links it to user profile."""
        clean_name = re.sub(r"[^\w\.-]", "_", Path(filename).name)
        if not clean_name:
            clean_name = f"resume_{int(datetime.now().timestamp())}.pdf"
        target_path = self.profile_path.parent / clean_name
        with open(target_path, "wb") as f:
            f.write(file_bytes)

        profile = self.load_profile()
        profile.resume_file = clean_name
        self.save_profile(profile)
        return clean_name

    def get_resume_path(self) -> str:
        """Returns the absolute path to the configured resume PDF."""
        profile = self.load_profile()
        resume_name = profile.resume_file or "sample_resume.pdf"
        target_path = self.profile_path.parent / resume_name
        if target_path.exists():
            return str(target_path.resolve())
        return str(DEFAULT_RESUME_PATH.resolve())

    def load_qa_bank(self) -> List[QABankEntry]:
        """Loads question-and-answer patterns from JSON."""
        if not self.qa_path.exists():
            return []
        with open(self.qa_path, "r", encoding="utf-8") as f:
            data = json.load(f)
            return [QABankEntry(**entry) for entry in data]

    def save_qa_bank(self, entries: List[QABankEntry]) -> None:
        """Saves question-and-answer list to JSON."""
        with open(self.qa_path, "w", encoding="utf-8") as f:
            json.dump([e.model_dump() for e in entries], f, indent=2)

    def update_qa_answers(self, answers_by_id: Dict[str, str]) -> None:
        """Updates answers for existing question IDs in the QA bank."""
        entries = self.load_qa_bank()
        updated_any = False
        for entry in entries:
            if entry.id in answers_by_id and answers_by_id[entry.id] is not None:
                entry.answer = str(answers_by_id[entry.id]).strip()
                updated_any = True
        if updated_any:
            self.save_qa_bank(entries)

    @staticmethod
    def normalize_text(text: str) -> str:
        """Normalizes text for fuzzy pattern matching."""
        text = text.lower()
        text = re.sub(r"[^\w\s]", " ", text)
        return " ".join(text.split())

    def find_direct_profile_field(self, label: str) -> Optional[str]:
        """Stage 1: Direct profile lookup based on canonical labels."""
        norm = self.normalize_text(label)
        profile = self.load_profile()
        p = profile.personal
        links = profile.links

        # First name
        if re.search(r"\bfirst\s*name\b|\bgiven\s*name\b|\bforename\b", norm):
            return p.first_name
        # Last name
        if re.search(r"\blast\s*name\b|\bsurname\b|\bfamily\s*name\b", norm):
            return p.last_name
        # Full name
        if re.search(r"\bfull\s*name\b|\bcandidate\s*name\b|^\s*name\s*$", norm):
            return p.full_name or f"{p.first_name} {p.last_name}".strip()
        # Email
        if re.search(r"\bemail\b|\be-mail\b", norm):
            return p.email
        # Phone
        if re.search(r"\bphone\b|\bmobile\b|\bcell\b|\btelephone\b", norm):
            return p.phone
        # LinkedIn
        if re.search(r"\blinkedin\b", norm):
            return links.get("linkedin", "")
        # GitHub
        if re.search(r"\bgithub\b|\bgit\b", norm):
            return links.get("github", "")
        # Website / Portfolio
        if re.search(r"\bportfolio\b|\bwebsite\b|\bpersonal\s*site\b|\burl\b", norm):
            return links.get("portfolio", "")
        # Address / Location
        if re.search(r"\bstreet\s*address\b|\baddress\b", norm) and not re.search(
            r"\bemail\b", norm
        ):
            return p.address
        if re.search(r"^\s*city\s*$|\bcurrent\s*city\b", norm):
            return p.city
        if re.search(r"^\s*state\s*$|\bprovince\b|\bregion\b", norm):
            return p.state
        if re.search(r"\bzip\b|\bpostal\s*code\b", norm):
            return p.postal_code
        if re.search(r"^\s*country\s*$", norm):
            return p.country

        return None

    def find_in_qa_bank(self, question: str) -> Optional[str]:
        """Stage 2: Semantic and token similarity against QA bank."""
        norm_q = self.normalize_text(question)
        qa_bank = self.load_qa_bank()

        # 1. Exact substring in patterns
        for entry in qa_bank:
            for pattern in entry.question_patterns:
                norm_pat = self.normalize_text(pattern)
                if norm_pat in norm_q or norm_q in norm_pat:
                    return entry.answer

        # 2. Token overlap score with stopword filtering
        STOP_WORDS = {
            "do", "you", "hold", "an", "a", "the", "is", "are", "have", "what",
            "which", "your", "for", "in", "to", "of", "and", "or", "please", "with", "status"
        }
        q_tokens = {w for w in norm_q.split() if w not in STOP_WORDS}
        if not q_tokens:
            q_tokens = set(norm_q.split())

        best_score = 0.0
        best_answer = None

        for entry in qa_bank:
            for pattern in entry.question_patterns:
                pat_tokens = {w for w in self.normalize_text(pattern).split() if w not in STOP_WORDS}
                if not pat_tokens:
                    pat_tokens = set(self.normalize_text(pattern).split())
                if not pat_tokens:
                    continue
                overlap = len(q_tokens.intersection(pat_tokens))
                union = len(q_tokens.union(pat_tokens))
                score = overlap / union if union > 0 else 0.0
                
                # If 2 or more significant keywords match or high overlap score
                if overlap >= 2 or score > best_score:
                    if score > best_score:
                        best_score = score
                        best_answer = entry.answer

        if best_score >= 0.35 or (best_answer is not None and best_score > 0.3):
            return best_answer

        return None

    def add_to_qa_bank(
        self,
        question: str,
        answer: str,
        field_type: str = "text",
        category: str = "custom",
    ) -> QABankEntry:
        """Stage 3: Auto-persist new Q&A pair with normalized tokens so it's never asked again."""
        qa_bank = self.load_qa_bank()
        clean_q = question.strip()
        norm_q = self.normalize_text(clean_q)

        # Generate unique ID from slug
        slug = re.sub(r"\W+", "_", norm_q[:30]).strip("_")
        entry_id = f"{slug}_{int(datetime.now(timezone.utc).timestamp())}"

        # Collect normalized patterns
        patterns = [clean_q.lower(), norm_q]
        # Remove duplicates while preserving order
        unique_patterns = list(dict.fromkeys(patterns))

        new_entry = QABankEntry(
            id=entry_id,
            category=category,
            question_patterns=unique_patterns,
            answer=answer,
            field_type=field_type,
            created_at=datetime.now(timezone.utc).isoformat(),
        )

        qa_bank.append(new_entry)
        self.save_qa_bank(qa_bank)
        return new_entry

    def log_application(
        self,
        app_id: str,
        job_title: str,
        company: str,
        url: str,
        match_score: float,
        brutal_critique: str,
        status: str,
        screenshot_path: Optional[str] = None,
    ) -> ApplicationLog:
        """Logs application run into SQLite database."""
        now_str = datetime.now(timezone.utc).isoformat()
        log = ApplicationLog(
            id=app_id,
            job_title=job_title,
            company=company,
            url=url,
            match_score=match_score,
            brutal_critique=brutal_critique,
            status=status,
            applied_at=now_str,
            screenshot_path=screenshot_path,
        )

        conn = sqlite3.connect(self.db_path)
        try:
            cursor = conn.cursor()
            cursor.execute(
                """
                INSERT OR REPLACE INTO applications 
                (id, job_title, company, url, match_score, brutal_critique, status, applied_at, screenshot_path)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    log.id,
                    log.job_title,
                    log.company,
                    log.url,
                    log.match_score,
                    log.brutal_critique,
                    log.status,
                    log.applied_at,
                    log.screenshot_path,
                ),
            )
            conn.commit()
        finally:
            conn.close()

        return log

    def get_history(self, limit: int = 20) -> List[ApplicationLog]:
        """Retrieves recent applications from SQLite."""
        conn = sqlite3.connect(self.db_path)
        try:
            conn.row_factory = sqlite3.Row
            cursor = conn.cursor()
            cursor.execute(
                """
                SELECT id, job_title, company, url, match_score, brutal_critique, status, applied_at, screenshot_path
                FROM applications
                ORDER BY applied_at DESC
                LIMIT ?
                """,
                (limit,),
            )
            rows = cursor.fetchall()
            return [ApplicationLog(**dict(row)) for row in rows]
        finally:
            conn.close()
