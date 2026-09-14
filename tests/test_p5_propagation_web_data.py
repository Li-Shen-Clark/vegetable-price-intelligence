from __future__ import annotations

import json
import unittest
from pathlib import Path

from src.procurement.common import sha256
from src.propagation.build_propagation_web_data import EXPOSURE_FIELDS, TIMELINE_FIELDS


ROOT = Path(__file__).resolve().parents[1]
WEB = ROOT / "web/public/data/propagation"


class P5PropagationWebDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.metadata = json.loads((WEB / "metadata.json").read_text(encoding="utf-8"))
        cls.manifest = json.loads((WEB / "manifest.json").read_text(encoding="utf-8"))

    def test_01_metadata_matches_frozen_fallback(self):
        self.assertEqual(self.metadata["release_status"], "common_shock_only")
        self.assertFalse(self.metadata["directional_network_released"])
        self.assertEqual(len(self.metadata["products"]), 10)
        self.assertEqual(self.metadata["data_as_of"], "2022-06-22")
        self.assertEqual(self.metadata["release_metrics"]["final_confirmed_edges"], 4)

    def test_02_product_payloads_have_no_directional_edges(self):
        for product in self.metadata["products"]:
            payload = json.loads(
                (ROOT / "web/public" / product["data_file"]).read_text(
                    encoding="utf-8"
                )
            )
            self.assertFalse(payload["directional_edges_included"])
            self.assertEqual(payload["timeline_fields"], TIMELINE_FIELDS)
            self.assertEqual(payload["exposure_fields"], EXPOSURE_FIELDS)
            serialized = json.dumps(payload, ensure_ascii=False)
            self.assertNotIn("source_city_id", serialized)
            self.assertNotIn("target_city_id", serialized)

    def test_03_all_windows_have_ranked_city_exposure(self):
        expected_windows = {item["id"] for item in self.metadata["windows"]}
        for product in self.metadata["products"]:
            payload = json.loads(
                (ROOT / "web/public" / product["data_file"]).read_text(
                    encoding="utf-8"
                )
            )
            rows = [dict(zip(EXPOSURE_FIELDS, row)) for row in payload["city_exposures"]]
            self.assertEqual({row["window_id"] for row in rows}, expected_windows)
            for window in expected_windows:
                subset = [row for row in rows if row["window_id"] == window]
                ranks = sorted(row["exposure_rank"] for row in subset)
                self.assertEqual(ranks, list(range(1, len(subset) + 1)))
                self.assertTrue(all(0 < row["exposure_score"] <= 100 for row in subset))

    def test_04_evidence_funnel_ends_at_zero_published_edges(self):
        funnel = self.metadata["evidence_funnel"]
        self.assertEqual(funnel[-1]["count"], 0)
        self.assertEqual(funnel[-1]["label"], "产品发布方向边")
        self.assertGreater(funnel[0]["count"], funnel[-1]["count"])

    def test_05_manifest_hashes_match_local_files(self):
        self.assertFalse(self.manifest["directional_edges_included"])
        self.assertEqual(
            self.manifest["metadata"]["sha256"], sha256(WEB / "metadata.json")
        )
        for item in self.manifest["products"]:
            self.assertEqual(item["sha256"], sha256(ROOT / "web/public" / item["path"]))


if __name__ == "__main__":
    unittest.main()
