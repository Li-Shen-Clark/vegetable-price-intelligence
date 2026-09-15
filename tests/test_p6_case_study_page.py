import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "web/app/case-study/page.tsx"
LAYOUT = ROOT / "web/app/layout.tsx"


class P6CaseStudyPageTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.page = PAGE.read_text(encoding="utf-8")
        cls.layout = LAYOUT.read_text(encoding="utf-8")

    def test_01_case_study_is_data_free(self):
        self.assertNotIn("fetch(", self.page)
        self.assertNotIn("/data/", self.page)
        self.assertNotIn(".json", self.page)
        self.assertNotIn(".csv", self.page)
        self.assertNotIn(".parquet", self.page)

    def test_02_first_viewport_has_positioning_metrics_and_boundary(self):
        for phrase in [
            "从市场信号到可治理的 Pricing 决策",
            "Pricing Intelligence layer",
            "8.68M",
            "117",
            "178",
            "它不是实时 Pricing Engine",
            "数据截至 2022-06-22",
        ]:
            self.assertIn(phrase, self.page)

    def test_03_all_stage_outcomes_and_pricing_interface_are_visible(self):
        for phrase in [
            "partial release",
            "alert release",
            "scenario release",
            "network no-go",
            "1,481 → 776",
            "2,736 → 51 → 15 → 4",
            "拒绝伪网络就是方法论结果",
            "Pricing engine 再结合库存、客户、合同、margin floor 与审批规则",
        ]:
            self.assertIn(phrase, self.page)

    def test_04_social_preview_is_wired_without_real_data(self):
        self.assertTrue((ROOT / "web/public/og.png").is_file())
        self.assertIn("/og.png", self.layout)
        self.assertIn("summary_large_image", self.layout)
        self.assertIn("http://localhost:3000", self.layout)

    def test_05_all_workspaces_link_back_to_case_study(self):
        for route in ["page.tsx", "forecast/page.tsx", "alerts/page.tsx", "procurement/page.tsx", "propagation/page.tsx"]:
            text = (ROOT / "web/app" / route).read_text(encoding="utf-8")
            self.assertIn('href="/case-study"', text)


if __name__ == "__main__":
    unittest.main()
