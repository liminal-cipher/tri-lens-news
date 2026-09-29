"""Content preservation and escaping checks for the shared mail renderer."""

import html
from html.parser import HTMLParser
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import email_templates as templates
import email_assets
import evaluate
import preview_email


class Document(HTMLParser):
    def __init__(self, markup):
        super().__init__()
        self.text = []
        self.links = []
        self.tags = []
        self.feed(markup)

    def handle_starttag(self, tag, attrs):
        self.tags.append(tag)
        if tag == "a":
            self.links.append(dict(attrs).get("href"))

    def handle_data(self, data):
        self.text.append(data)


class EmailTemplatesTest(unittest.TestCase):
    def test_every_daily_archive_keeps_lens_content_and_links(self):
        for path in sorted((ROOT / "archive").glob("*.md")):
            with self.subTest(archive=path.name):
                date, sections, models = preview_email.load_daily(path)
                doc = Document(templates.render_daily(date, sections, models))
                text = " ".join(" ".join(doc.text).split())
                self.assertEqual(doc.tags.count("h2"), len(sections))
                self.assertIn(date, text)
                for article, analysis in sections:
                    self.assertIn(article["title"], text)
                    self.assertEqual(doc.links.count(article["url"]), 2)
                    bodies, _ = evaluate.split_lenses(analysis)
                    for body in bodies.values():
                        self.assertIn(" ".join(body.split()), text)

    def test_radar_preserves_all_fields_and_evidence(self):
        for path in sorted((ROOT / "concepts").glob("*.md")):
            data = preview_email.load_radar(path)
            doc = Document(templates.render_radar(*data))
            text = " ".join(doc.text)
            self.assertEqual(doc.tags.count("h2"), len(data[1]))
            for concept in data[1]:
                for key in ("term", "definition", "why_now", "practical_relevance"):
                    self.assertIn(concept[key], text)
                for idx in concept["evidence_indices"]:
                    item = data[2][idx]
                    self.assertIn(item["title"], text)
                    self.assertIn(item["url"], doc.links)

    def test_untrusted_copy_is_text_in_both_editions(self):
        payload = '<script>alert("x")</script> & "quoted"'
        analysis = "\n".join(f"{m} {name}\n{payload}" for m, name in evaluate.LENS_NAMES.items())
        item = {"title": payload, "source": payload, "url": 'https://example.com/?x="&y=1'}
        concept = {key: payload for key in ("term", "definition", "why_now", "practical_relevance")}
        concept["evidence_indices"] = [1]
        for markup in (
            templates.render_daily(payload, [(item, analysis)], [f"provider:{payload}"]),
            templates.render_radar(payload, [concept], {1: item}, [f"provider:{payload}"]),
        ):
            self.assertNotIn("script", Document(markup).tags)
            self.assertIn(html.escape(payload), markup)
            self.assertIn(item["url"], Document(markup).links)

    def test_malformed_lenses_fall_back_without_losing_text(self):
        for text in (
            "plain <text>\nsecond line",
            "🌐 Everyone\nFirst.\n🌐 Everyone\nDuplicate.",
            "🔬 Researchers\nLast first.\n🌐 Everyone\nFirst last.",
        ):
            markup = templates.render_lenses(text)
            self.assertIn(html.escape(text).replace("\n", "<br>"), markup)

    def test_non_web_links_are_not_active(self):
        for url in ("javascript:alert(1)", "data:text/html,test", "file:///tmp/test", "https://[invalid"):
            self.assertEqual(templates.link_url(url), "#")

    def test_model_attribution_uses_supplied_models_once(self):
        self.assertEqual(templates.model_names(["gemini:model-a", "gemini:model-a", "groq:model-b"]), "model-a, model-b")
        self.assertEqual(templates.model_names([]), "언어 모델")

    def test_offline_preview_renders_without_opening_sockets(self):
        with patch("socket.socket", side_effect=AssertionError("Network access during preview")):
            daily = preview_email.load_daily(preview_email.latest_archive(ROOT / "archive"))
            radar = preview_email.load_radar(preview_email.latest_archive(ROOT / "concepts"))
            self.assertIn("Daily Brief", email_assets.preview_html(templates.render_daily(*daily)))
            self.assertIn("Concept Radar", templates.render_radar(*radar))


if __name__ == "__main__":
    unittest.main()
