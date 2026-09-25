"""Unit tests for storage operations, QA pattern matching, and SQLite persistence."""

import unittest
from pathlib import Path
import tempfile
import os

from src.storage import StorageManager, UserProfile, QABankEntry


class TestStorage(unittest.TestCase):
    def setUp(self):
        self.temp_dir = tempfile.TemporaryDirectory()
        self.storage = StorageManager()
        self.storage.profile_path = Path(self.temp_dir.name) / "test_profile.json"
        self.storage.qa_path = Path(self.temp_dir.name) / "test_qa.json"
        self.storage.db_path = Path(self.temp_dir.name) / "test_apps.sqlite"
        self.storage._init_sqlite_db()

    def tearDown(self):
        self.temp_dir.cleanup()

    def test_profile_direct_lookup(self):
        profile = UserProfile()
        profile.personal.first_name = "Jane"
        profile.personal.last_name = "Doe"
        profile.personal.email = "jane@example.com"
        profile.personal.phone = "555-999-1234"
        profile.links["linkedin"] = "https://linkedin.com/in/janedoe"
        self.storage.save_profile(profile)

        self.assertEqual(self.storage.find_direct_profile_field("First Name *"), "Jane")
        self.assertEqual(self.storage.find_direct_profile_field("Last Name"), "Doe")
        self.assertEqual(self.storage.find_direct_profile_field("Email Address"), "jane@example.com")
        self.assertEqual(self.storage.find_direct_profile_field("LinkedIn Profile URL"), "https://linkedin.com/in/janedoe")

    def test_qa_bank_matching_and_persist(self):
        # Initial QA bank entry
        self.storage.add_to_qa_bank(
            question="Do you hold an active US security clearance?",
            answer="Secret",
            field_type="select",
        )

        # Match exact and fuzzy
        ans1 = self.storage.find_in_qa_bank("Do you hold an active US security clearance?")
        self.assertEqual(ans1, "Secret")

        ans2 = self.storage.find_in_qa_bank("security clearance level")
        self.assertEqual(ans2, "Secret")

    def test_application_sqlite_logging(self):
        log = self.storage.log_application(
            app_id="test_001",
            job_title="Software Architect",
            company="Tech Corp",
            url="http://example.com/job/1",
            match_score=85.0,
            brutal_critique="Solid fit; slight lack of Go experience.",
            status="READY_FOR_SUBMIT",
        )
        self.assertEqual(log.id, "test_001")

        history = self.storage.get_history(limit=5)
        self.assertEqual(len(history), 1)
        self.assertEqual(history[0].job_title, "Software Architect")
        self.assertEqual(history[0].match_score, 85.0)


if __name__ == "__main__":
    unittest.main()
