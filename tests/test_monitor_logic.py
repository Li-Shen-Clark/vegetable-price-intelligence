from __future__ import annotations

import unittest
from pathlib import Path

from src.monitor.build_p1_stories import compute_stories, load_flat_yaml, render_markdown


ROOT = Path(__file__).resolve().parents[1]


class MonitorLogicTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        config = load_flat_yaml(ROOT / "config/p1_stories.yaml")
        cls.stories = compute_stories(ROOT, config)
        cls.markdown = render_markdown(cls.stories)
        cls.page_source = (ROOT / "web/app/page.tsx").read_text(encoding="utf-8")

    def test_01_seasonality_story_recomputes(self) -> None:
        story = self.stories["seasonality"]
        self.assertEqual(story["vegetable_name"], "大白菜")
        self.assertEqual(story["city_name"], "西安市")
        self.assertEqual(story["high_month"], 4)
        self.assertAlmostEqual(story["high_price"], 2.0, 3)
        self.assertEqual(story["low_month"], 12)
        self.assertAlmostEqual(story["low_price"], 1.35, 3)
        self.assertAlmostEqual(story["high_vs_low_pct"], 48.1, 1)

    def test_02_cross_city_story_recomputes(self) -> None:
        story = self.stories["cross_city"]
        self.assertEqual(story["vegetable_name"], "土豆")
        self.assertEqual(story["month"], "2022-05")
        self.assertEqual(story["comparable_city_count"], 66)
        self.assertEqual(story["highest_city"], "衢州市")
        self.assertAlmostEqual(story["highest_price"], 6.2, 3)
        self.assertEqual(story["lowest_city"], "潍坊市")
        self.assertAlmostEqual(story["lowest_price"], 1.8, 3)
        self.assertAlmostEqual(story["city_price_p25"], 2.4, 3)
        self.assertAlmostEqual(story["city_price_median"], 2.6, 3)
        self.assertAlmostEqual(story["city_price_p75"], 3.2, 3)

    def test_03_quality_story_recomputes(self) -> None:
        story = self.stories["quality_risk"]
        self.assertEqual(story["vegetable_name"], "韭菜")
        self.assertEqual(story["city_name"], "宁波市")
        self.assertEqual(story["tier"], "B")
        self.assertEqual(story["valid_days"], 19)
        self.assertEqual(story["poor_days"], 19)
        self.assertEqual(story["good_days"], 0)
        self.assertAlmostEqual(story["reliability"], 0.5763, 4)
        self.assertAlmostEqual(story["poor_day_share_pct"], 100.0, 1)

    def test_04_story_document_has_boundaries_and_sources(self) -> None:
        self.assertEqual(self.markdown.count("## 故事"), 3)
        self.assertIn("不代表当前报价", self.markdown)
        self.assertIn("不能推出", self.markdown)
        self.assertIn(self.stories["city_gold_sha256"], self.markdown)
        self.assertEqual(
            (ROOT / "docs/p1_data_stories.md").read_text(encoding="utf-8"),
            self.markdown,
        )

    def test_05_page_state_responsive_and_accessibility_contract(self) -> None:
        self.assertGreaterEqual(self.page_source.count("<Select"), 12)
        self.assertIn("<LoadingSurface />", self.page_source)
        self.assertIn("<Empty", self.page_source)
        self.assertIn("数据暂时不可用", self.page_source)
        self.assertIn("sm:grid-cols-2", self.page_source)
        self.assertIn("xl:grid-cols", self.page_source)
        self.assertIn("max-h-[420px] overflow-y-auto", self.page_source)
        self.assertIn("aria-label={`切换到", self.page_source)
        self.assertIn("Historical only", self.page_source)
        self.assertIn("数据截至", self.page_source)


if __name__ == "__main__":
    unittest.main()
