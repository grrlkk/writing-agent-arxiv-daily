"""Offline regressions for year coverage, topic filtering, and generated pages."""
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import yaml

import daily_arxiv as daily


TOPIC = "Multilingual & Cross-Lingual Agents"


def paper(arxiv_id, published, title="Multilingual agents", summary=""):
    return {
        "id": arxiv_id,
        "title": title,
        "summary": summary,
        "published": published,
        "abs_url": f"https://arxiv.org/abs/{arxiv_id}",
    }


def feed(entries):
    root = ET.Element(f"{daily.ATOM}feed")
    for entry in entries:
        node = ET.SubElement(root, f"{daily.ATOM}entry")
        for key in ("id", "title", "summary", "published"):
            value = entry[key]
            if key == "id":
                value = f"https://arxiv.org/abs/{value}v1"
            ET.SubElement(node, f"{daily.ATOM}{key}").text = value
    return ET.tostring(root, encoding="unicode")


class CollectionTests(unittest.TestCase):
    def test_default_years_include_2024_through_current_year(self):
        cfg = daily.load_config(daily.ROOT / "config.yaml")
        self.assertEqual(daily.search_years(cfg), list(range(datetime.now(timezone.utc).year, 2023, -1)))

    def test_explicit_years_are_deduplicated(self):
        self.assertEqual(daily.search_years({"years": [2024, 2025, 2024]}), [2025, 2024])

    def test_query_combines_year_category_and_required_agent_terms(self):
        query = daily.build_query(
            ["multilingual", "korean"],
            {"required_terms": ["agent", "tool use"]},
            {"categories": ["cs.CL"]},
            year=2024,
        )
        self.assertIn('(ti:"multilingual" OR abs:"multilingual" OR ti:"korean" OR abs:"korean")', query)
        self.assertIn(' AND (cat:cs.CL)', query)
        self.assertIn(' AND (ti:"agent" OR abs:"agent" OR ti:"tool use" OR abs:"tool use")', query)
        self.assertTrue(query.endswith(" AND submittedDate:[202401010000 TO 202412312359]"))

    @patch.object(daily.time, "sleep")
    def test_each_year_and_tier_gets_its_own_paginated_budget(self, sleep):
        calls = []

        def request(query, start, size, retries, interval):
            year = next(y for y in (2026, 2025, 2024) if f"[{y}01010000" in query)
            tier = "weak" if 'ti:"weak"' in query else "strong"
            calls.append((year, tier, start, size))
            # Same papers in both tiers must merge without consuming another year's budget.
            return feed([paper(f"{year}-{i}", f"{year}-12-31") for i in range(start, start + size)])

        with patch.object(daily, "request_feed", side_effect=request):
            entries = daily.fetch_topic(
                "Example", {"filters": ["strong"], "weak_filters": ["weak"], "max_results": 99},
                {"years": [2024, 2025, 2026], "max_results": 3, "_force_max_results": True,
                 "page_size": 2, "request_interval": 0},
            )
        self.assertEqual(len(entries), 9)
        self.assertEqual(calls, [
            (year, tier, start, size)
            for year in (2026, 2025, 2024)
            for tier in ("strong", "weak")
            for start, size in ((0, 2), (2, 1))
        ])

    @patch.object(daily.time, "sleep")
    def test_short_page_does_not_stop_other_years_and_wrong_year_is_rejected(self, sleep):
        with patch.object(daily, "request_feed", side_effect=[
            feed([paper("unexpected", "2026-01-01")]),
            feed([paper("last-day", "2024-12-31"), paper("first-day", "2024-01-01")]),
        ]) as request:
            entries = daily.fetch_topic("Example", {"filters": ["agent"]}, {
                "years": [2025, 2024], "max_results": 3, "page_size": 3, "request_interval": 0,
            })
        self.assertEqual(request.call_count, 2)
        self.assertEqual({e["id"] for e in entries}, {"last-day", "first-day"})


class TopicTests(unittest.TestCase):
    def test_multilingual_topic_requires_both_language_and_agent_evidence(self):
        cfg = daily.load_config(daily.ROOT / "config.yaml")
        cases = [
            ("Cross-lingual planning for LLM agents", True),
            ("Arabic tool use benchmark", True),
            ("Japanese writing assistants", True),
            ("Culturally adaptive multi-agent collaboration", True),
            ("Low-resource language transfer for agentic systems", True),
            ("Multilingual text classification", False),
            ("Korean language model pretraining", False),
            ("Planning for LLM agents", False),
            ("Multilingual agents for molecular discovery", False),
        ]
        for title, expected in cases:
            with self.subTest(title=title):
                accepted, _ = daily.keep_entry(paper("example", "2024-01-01", title), cfg["keywords"][TOPIC], cfg, set())
                self.assertEqual(accepted, expected)
        entry = paper("blocked", "2025-01-01", "Korean tool calling")
        self.assertFalse(daily.keep_entry(entry, cfg["keywords"][TOPIC], cfg, {"blocked"})[0])

    def test_required_terms_apply_to_weak_matches_too(self):
        cfg = {"weak_filters": ["multilingual"], "weak_anchors": ["writing"], "required_terms": ["agent"]}
        self.assertFalse(daily.keep_entry(paper("x", "2025-01-01", "Multilingual writing"), cfg, {}, set())[0])
        self.assertTrue(daily.keep_entry(paper("x", "2025-01-01", "Multilingual writing agents"), cfg, {}, set())[0])


class RenderingTests(unittest.TestCase):
    def test_older_years_remain_accessible_below_latest_preview(self):
        entries = [paper("new", "2026-01-01"), paper("middle", "2025-12-31"), paper("old", "2024-01-01")]
        cfg = {"keywords": {TOPIC: {}}, "show_abstract": False}
        store = {"topics": {TOPIC: {e["id"]: e for e in entries}}}
        preview = daily.render_page(store, cfg, "2026-09-22", limit=1, header="Example", new_today=None)
        self.assertIn("[2024 (1)](docs/topics/multilingual-cross-lingual-agents.md#2024)", preview)
        self.assertNotIn("|**2024-01-01**|", preview)
        archive = daily.render_topic_page(TOPIC, entries, cfg, "2026-09-22")
        self.assertIn("[2024 (1)](#2024)", archive)
        self.assertLess(archive.index("## 2026"), archive.index("## 2025"))
        self.assertLess(archive.index("## 2025"), archive.index("## 2024"))
        self.assertIn("|**2024-01-01**|", archive)

    def test_offline_run_renders_new_topic_without_network_or_losing_history(self):
        with tempfile.TemporaryDirectory() as temp:
            base = Path(temp)
            old = paper("old", "2023-01-01", "A stored writing paper")
            old["s2"] = {"venue": "", "checked": "2026-01-01"}
            store = {"topics": {"Writing Agent": {"old": old}}}
            store_path = base / "papers.json"
            store_path.write_text(json.dumps(store), encoding="utf-8")
            cfg = {
                "keywords": {"Writing Agent": {}, TOPIC: {}},
                "store_path": str(store_path), "readme_path": str(base / "README.md"),
                "archive_dir": str(base / "topics"), "archive_path": str(base / "archive.md"),
                "venue_page_path": str(base / "venues.md"),
            }
            config_path = base / "config.yaml"
            config_path.write_text(yaml.safe_dump(cfg), encoding="utf-8")
            with patch.object(daily.requests, "get", side_effect=AssertionError("network forbidden")), \
                 patch.object(daily.s2_enrich, "enrich_store", side_effect=AssertionError("enrichment forbidden")):
                self.assertEqual(daily.main(["--config", str(config_path), "--offline", "--no-enrich"]), 0)
            saved = daily.load_store(store_path)
            self.assertEqual(saved["topics"]["Writing Agent"]["old"]["published"], "2023-01-01")
            self.assertEqual(saved["topics"]["Writing Agent"]["old"]["s2"], old["s2"])
            self.assertIn(f"## {TOPIC}", (base / "README.md").read_text(encoding="utf-8"))
            self.assertIn("2 topics", (base / "archive.md").read_text(encoding="utf-8"))
            self.assertIn("No matching papers collected yet", (base / "topics" / "multilingual-cross-lingual-agents.md").read_text(encoding="utf-8"))


if __name__ == "__main__":
    unittest.main()
