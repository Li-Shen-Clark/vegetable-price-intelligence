from __future__ import annotations

import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PricingNarrativeTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.home = (ROOT / "web/app/page.tsx").read_text(encoding="utf-8")
        cls.procurement = (ROOT / "web/app/procurement/page.tsx").read_text(encoding="utf-8")
        cls.layout = (ROOT / "web/app/layout.tsx").read_text(encoding="utf-8")

    def test_01_home_first_viewport_explains_market_to_pricing_chain(self) -> None:
        for phrase in (
            "从城市价格差异到 Pricing 决策输入",
            "01 · 市场基准",
            "02 · 价格预期",
            "03 · 风险信号",
            "04 · 采购情景",
            "05 · 冲击暴露",
            "06 · Pricing Engine",
            "成本基准与毛利复核输入",
        ):
            self.assertIn(phrase, self.home)

    def test_02_home_preserves_complementary_pricing_engine_boundary(self) -> None:
        self.assertIn("本项目提供市场、风险与成本情报", self.home)
        self.assertIn("库存、客户、利润和审批规则", self.home)

    def test_03_procurement_first_viewport_has_pricing_decision_bridge(self) -> None:
        for phrase in (
            "Pricing Decision Bridge",
            "成本与毛利复核输入",
            "毛利与报价复核",
            "供应替代询价",
            "不生成零售价",
        ):
            self.assertIn(phrase, self.procurement)

    def test_04_procurement_translates_controls_into_economics(self) -> None:
        for phrase in ("空间摩擦", "Cost-to-serve", "风险厌恶", "比较静态"):
            self.assertIn(phrase, self.procurement)

    def test_05_pages_do_not_claim_execution_or_optimal_retail_price(self) -> None:
        combined = self.home + self.procurement
        self.assertNotIn("最优供应商", combined)
        self.assertNotIn("最优零售价", combined)
        self.assertNotIn("自动下单", combined)
        self.assertIn("不执行采购", self.procurement)

    def test_06_metadata_positions_economics_informed_pricing_intelligence(self) -> None:
        self.assertIn("economics-informed pricing intelligence", self.layout)
        self.assertIn("From Market Signals to Pricing Decisions", self.layout)


if __name__ == "__main__":
    unittest.main()
