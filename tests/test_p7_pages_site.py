import unittest
from pathlib import Path

from scripts.verify_pages_bundle import verify


ROOT = Path(__file__).resolve().parents[1]
SITE = ROOT / "portfolio-site"
INDEX = SITE / "index.html"
WORKFLOW = ROOT / ".github/workflows/pages.yml"


class P7PagesSiteTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.index = INDEX.read_text(encoding="utf-8")
        cls.workflow = WORKFLOW.read_text(encoding="utf-8")

    def test_01_recruiter_first_view_has_role_scale_and_decision(self):
        for phrase in [
            "From wholesale market signals to governed pricing decisions.",
            "End-to-end owner",
            "8.68M",
            "117",
            "30",
            "47.6%</strong><span>apparent relationships removed",
            "Built by",
            "Li Shen",
            "Applied Economist · Pricing &amp; Decision Science",
        ]:
            self.assertIn(phrase, self.index)
        self.assertIn('<meta name="author" content="Li Shen"', self.index)
        self.assertIn('href="#evidence">See the evidence gates', self.index)

    def test_02_formal_product_states_and_failure_remain_visible(self):
        for phrase in [
            "Partial release",
            "Alert release",
            "Scenario release",
            "Network no-go",
            "How controls stopped 99.9% of candidates from becoming claims",
            "1,481",
            "776",
            "174",
            "51",
            "26.7%</strong> positive vs <b>70%</b> gate",
            "−1.39%</strong> median RMSE uplift vs <b>+1%</b> gate",
            "0</b><span>directional edges released",
            "without common-shock control and product-level multiple-testing discipline",
            "common_shock_only",
            "Forecast release by horizon",
            "Alert stability: validation → final",
            "42.15 → 37.69%",
            "21.28 → 22.04%",
            "2,736",
            "No row-level price data",
            "178 tests",
        ]:
            self.assertIn(phrase, self.index)
        self.assertNotIn("Propagation evidence funnel", self.index)

    def test_03_economics_and_pricing_engine_boundary_are_explicit(self):
        for phrase in [
            "Price dispersion &amp; measurement",
            "Expectations &amp; uncertainty",
            "Transaction costs &amp; risk",
            "Common shocks &amp; identification",
            "Complementary to a Pricing Engine—not a competing engine.",
            "Then—and only then—produce an executable price.",
        ]:
            self.assertIn(phrase, self.index)

    def test_04_historical_and_nonproduction_limits_are_explicit(self):
        for phrase in [
            "Historical cutoff: 2022-06-22",
            "No automated pricing",
            "Not supported",
            "Demand elasticity or willingness to pay",
            "Causal price propagation",
        ]:
            self.assertIn(phrase, self.index)

    def test_05_metadata_uses_the_final_github_pages_origin(self):
        origin = "https://li-shen-clark.github.io/vegetable-price-intelligence/"
        self.assertIn(f'<link rel="canonical" href="{origin}"', self.index)
        self.assertIn(f'<meta property="og:url" content="{origin}"', self.index)
        self.assertIn(f'{origin}og.png', self.index)
        self.assertNotIn("localhost", self.index)

    def test_06_public_page_has_no_data_or_active_runtime(self):
        for phrase in ["<script", "fetch(", "<form", ".csv", ".parquet", ".json", "/data/"]:
            self.assertNotIn(phrase, self.index)

    def test_07_pages_workflow_has_minimum_permissions_and_exact_payload(self):
        for phrase in [
            "contents: read",
            "pages: write",
            "id-token: write",
            "actions/configure-pages@v5",
            "actions/upload-pages-artifact@v4",
            "actions/deploy-pages@v4",
            "path: portfolio-site",
            "python3 scripts/verify_pages_bundle.py",
        ]:
            self.assertIn(phrase, self.workflow)
        for phrase in ["secrets.", "web/public/data", "artifacts/", ".csv", ".parquet"]:
            self.assertNotIn(phrase, self.workflow)

    def test_08_pages_bundle_verifier_passes(self):
        result = verify()
        self.assertEqual(result["status"], "pass")
        self.assertEqual(result["files"], 6)


if __name__ == "__main__":
    unittest.main()
