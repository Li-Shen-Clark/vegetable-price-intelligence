import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class P6CareerMaterialsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.career = (ROOT / "docs/p6_career_pack.md").read_text(encoding="utf-8")
        cls.demo = (ROOT / "docs/p6_demo_script.md").read_text(encoding="utf-8")

    def test_01_three_target_roles_are_supported(self):
        for role in [
            "Pricing Analyst",
            "Pricing Data Scientist",
            "Economics / Data Scientist",
        ]:
            self.assertIn(role, self.career)

    def test_02_resume_metrics_match_frozen_results(self):
        for metric in [
            "8.68M",
            "117 cities",
            "6.30%",
            "37.69% recall",
            "9.99% false-positive rate",
            "4/15 frozen edges",
            "177 automated",
        ]:
            self.assertIn(metric, self.career)

    def test_03_demo_covers_success_partial_release_and_no_go(self):
        for phrase in [
            "partial release",
            "baseline fallback",
            "Final recall",
            "36 组敏感性",
            "网络不发布",
            "共同冲击和城市暴露",
        ]:
            self.assertIn(phrase, self.demo)

    def test_04_materials_keep_nonproduction_boundary(self):
        combined = self.career + self.demo
        for phrase in [
            "不执行采购",
            "不能自动调价",
            "不称为实时系统",
            "不称为因果传播",
        ]:
            self.assertIn(phrase, combined)
        self.assertNotIn("/Volumes/", combined)


if __name__ == "__main__":
    unittest.main()
