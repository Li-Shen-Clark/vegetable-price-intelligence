import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
WORKFLOW = ROOT / ".github/workflows/portfolio-ci.yml"


class P6CIContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_01_workflow_runs_only_publishable_code_checks(self):
        for phrase in [
            "code-only-contracts",
            "tests.test_portfolio_bundle",
            "tests.test_p6_ci_contract",
            "npm run lint",
            "npm run build",
        ]:
            self.assertIn(phrase, self.workflow)

    def test_02_workflow_has_read_only_repository_permissions(self):
        self.assertIn("permissions:\n  contents: read", self.workflow)
        self.assertNotIn("contents: write", self.workflow)
        self.assertNotIn("pull-requests: write", self.workflow)

    def test_03_workflow_never_moves_project_data_or_artifacts(self):
        forbidden = [
            "upload-artifact",
            "download-artifact",
            "web/public/data",
            "artifacts/",
            ".csv",
            ".parquet",
        ]
        for phrase in forbidden:
            self.assertNotIn(phrase, self.workflow)

    def test_04_workflow_needs_no_secrets_or_external_services(self):
        for phrase in ["secrets.", "curl ", "wget ", "aws ", "gh "]:
            self.assertNotIn(phrase, self.workflow)


if __name__ == "__main__":
    unittest.main()
