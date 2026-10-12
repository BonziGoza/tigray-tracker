import unittest

import collect


class PublisherRegistryTests(unittest.TestCase):
    def test_registry_is_loaded_and_has_methodology_profiles(self):
        self.assertGreaterEqual(len(collect.PUBLISHER_REGISTRY), 30)
        self.assertTrue(all(0 <= int(p["publisher_score"]) <= 100 for p in collect.PUBLISHER_REGISTRY))

    def test_major_publishers_match_registry(self):
        for outlet in ("BBC", "CNN", "Reuters", "The Washington Post", "Al Jazeera"):
            with self.subTest(outlet=outlet):
                profile = collect.source_profile({"outlet": outlet, "source_type": "news"})
                self.assertNotEqual(profile["registry_status"], "unassessed")
                self.assertIsNotNone(profile["publisher_score"])

    def test_established_publishers_do_not_fall_below_50_when_evidence_extraction_is_missing(self):
        for outlet in ("BBC", "CNN", "Reuters", "The New York Times", "Al Jazeera"):
            with self.subTest(outlet=outlet):
                source = {
                    "outlet": outlet,
                    "title": "A report about developments in Tigray",
                    "url": "https://news.google.com/rss/articles/example",
                    "source_type": "news",
                }
                self.assertGreaterEqual(collect.article_credibility(source), 50)

    def test_explicitly_weak_or_contested_article_evidence_can_lower_score(self):
        source = {
            "outlet": "BBC",
            "title": "A disputed claim about developments in Tigray",
            "url": "https://www.bbc.com/news/example",
            "source_type": "news",
            "evidence": {
                "named_sources": 0,
                "anonymous_sources": 5,
                "direct_observation": False,
                "official_sources": 0,
                "documentary_evidence": False,
                "visual_evidence": False,
                "attributed_claim": False,
                "source_is_party": True,
                "contested": True,
            },
        }
        self.assertLess(collect.article_credibility(source), 50)

    def test_unassessed_outlet_is_not_treated_as_registry_match(self):
        source = {"outlet": "Unlisted Example Local News", "source_type": "news"}
        profile = collect.source_profile(source)
        self.assertEqual(profile["registry_status"], "unassessed")
        self.assertIsNone(profile["publisher_score"])
        # It should still produce a score/explanation rather than crashing.
        self.assertIsInstance(collect.article_credibility(source), int)
        self.assertIn("unassessed", collect.article_credibility_explanation(source))


if __name__ == "__main__":
    unittest.main()
