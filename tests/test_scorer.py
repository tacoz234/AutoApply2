"""Unit tests for MatchScorer schema and heuristic fallback."""

import unittest
from src.scorer import JobScorer, MatchScoreResult
from src.storage import UserProfile


class TestScorer(unittest.TestCase):
    def setUp(self):
        self.scorer = JobScorer()
        self.profile = UserProfile()
        self.profile.skills = ["Python", "FastAPI", "Docker", "PostgreSQL"]
        self.profile.authorization = {
            "us_work_authorized": "Yes",
            "requires_sponsorship": "No",
            "security_clearance": "None",
        }

    def test_heuristic_scoring_with_dealbreaker(self):
        # Clearance required but user has None
        job_desc = "Role requires Active Secret Clearance. You must have TS/SCI or Secret clearance."
        result = self.scorer._heuristic_fallback_score(
            job_title="Defense Software Engineer",
            company="AeroTech",
            job_description=job_desc,
            user_profile=self.profile,
        )

        self.assertIsInstance(result, MatchScoreResult)
        self.assertLessEqual(result.estimated_callback_chance, 25)
        self.assertGreater(len(result.dealbreakers), 0)
        self.assertEqual(result.recommendation, "PASS")

    def test_heuristic_scoring_solid_fit(self):
        job_desc = "Looking for a Python backend engineer with FastAPI and Docker experience."
        result = self.scorer._heuristic_fallback_score(
            job_title="Backend Engineer",
            company="Startup Labs",
            job_description=job_desc,
            user_profile=self.profile,
        )

        self.assertIsInstance(result, MatchScoreResult)
        self.assertGreaterEqual(result.estimated_callback_chance, 50)
        self.assertIn("Python", "".join(result.strengths))


if __name__ == "__main__":
    unittest.main()
