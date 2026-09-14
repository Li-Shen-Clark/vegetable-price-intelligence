import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class P6PortfolioContractTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.case_study = (ROOT / "PORTFOLIO_CASE_STUDY.md").read_text(encoding="utf-8")
        cls.matrix = (ROOT / "docs/p6_evidence_matrix.md").read_text(encoding="utf-8")
        cls.integration = (ROOT / "docs/pricing_integration_contract.md").read_text(
            encoding="utf-8"
        )

    def test_01_case_study_preserves_all_formal_release_states(self):
        for value in [
            "partial_release",
            "alert_release",
            "scenario_release",
            "common_shock_only",
            "Direction network `no-go`",
        ]:
            self.assertIn(value, self.case_study)

    def test_02_evidence_matrix_has_baseline_and_claim_boundary(self):
        for stage in ["P0", "P1", "P2", "P3", "P4", "P5"]:
            self.assertIn(f"| {stage} ", self.matrix)
        for phrase in [
            "Counterfactual / baseline",
            "Not allowed",
            "Historical",
            "Predictive or descriptive, not causal",
            "Decision support, not execution",
        ]:
            self.assertIn(phrase, self.matrix)

    def test_03_pricing_contract_stops_before_execution(self):
        for phrase in [
            "**design contract**, not a live API",
            "review_required",
            "insufficient_evidence",
            "may not set `approved_price`",
            "baseline fallback cannot be renamed",
            "common_shock_only",
        ]:
            self.assertIn(phrase, self.integration)

    def test_04_public_documents_do_not_expose_local_absolute_paths(self):
        combined = self.case_study + self.matrix + self.integration
        self.assertNotIn("/Volumes/", combined)
        self.assertNotIn("/Users/", combined)


if __name__ == "__main__":
    unittest.main()
