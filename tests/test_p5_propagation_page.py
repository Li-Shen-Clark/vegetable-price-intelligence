import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PAGE = ROOT / "web/app/propagation/page.tsx"


class P5PropagationPageTests(unittest.TestCase):
    def test_01_route_has_frozen_release_state_and_disclosures(self):
        text = PAGE.read_text(encoding="utf-8")
        for phrase in [
            "发布状态：共同冲击与城市暴露",
            "方向网络未发布",
            "不代表某个城市导致其他城市涨价",
            "不是价格建议或自动调价触发器",
            "历史研究",
        ]:
            self.assertIn(phrase, text)

    def test_02_route_exposes_pricing_and_economics_logic(self):
        text = PAGE.read_text(encoding="utf-8")
        for phrase in [
            "经济学机制",
            "空间套利",
            "leave-one-out 共同因子",
            "Pricing 接口",
            "成本与报价复核",
            "识别边界",
        ]:
            self.assertIn(phrase, text)

    def test_03_route_has_loading_empty_and_error_states(self):
        text = PAGE.read_text(encoding="utf-8")
        self.assertIn("LoadingSurface", text)
        self.assertIn("当前筛选没有历史证据", text)
        self.assertIn("数据暂时不可用", text)

    def test_04_route_does_not_render_directional_network(self):
        text = PAGE.read_text(encoding="utf-8")
        self.assertNotIn("source_city_id", text)
        self.assertNotIn("target_city_id", text)
        self.assertNotIn("Sankey", text)


if __name__ == "__main__":
    unittest.main()
