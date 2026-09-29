"""Inline image packaging must survive MIME serialisation and match preview art."""

import base64
from email import message_from_string, policy
from pathlib import Path
import re
import struct
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

import email_assets
import email_templates
import evaluate


class EmailAssetsTest(unittest.TestCase):
    def setUp(self):
        self.body_text = "일상에서 달라지는 점입니다. 구현과 연구의 관점을 함께 읽습니다."
        analysis = "\n".join(
            f"{marker} {label}\n{self.body_text}"
            for marker, label in evaluate.LENS_NAMES.items()
        )
        sections = [
            ({"title": f"Test article {index}", "url": f"https://example.test/{index}", "source": source}, analysis)
            for index, source in enumerate(("Hacker News", "GeekNews", "Hugging Face Papers"))
        ]
        self.html = email_templates.render_daily("2026년 09월 29일", sections, ["test:model"])

    def message(self, html_body):
        message = email_assets.build_message(
            "오늘의 뉴스", html_body, "sender@example.test", ["reader@example.test"]
        )
        return message_from_string(message.as_string(), policy=policy.default)

    def test_inline_images_resolve_all_references_without_duplicate_attachments(self):
        message = self.message(self.html)
        self.assertEqual(message["Subject"], "오늘의 뉴스")
        self.assertEqual(message["To"], "reader@example.test")
        self.assertEqual(message.get_content_type(), "multipart/related")
        self.assertEqual(message.get_param("type"), "text/html")
        body = message.get_body(preferencelist=("html",)).get_content()
        references = re.findall(r'src="cid:([^\"]+)"', body)
        images = [part for part in message.walk() if part.get_content_type() == "image/png"]
        self.assertEqual(len(references), 9)
        self.assertEqual(len(images), 3)
        self.assertEqual(set(references), {part["Content-ID"][1:-1] for part in images})
        for part in images:
            self.assertEqual(part.get_content_disposition(), "inline")
            self.assertEqual(part.get_payload(decode=True), (email_assets.ICON_DIR / part.get_filename()).read_bytes())
        self.assertIn(self.body_text, body)

    def test_content_ids_are_unique_between_messages(self):
        ids = lambda msg: {part["Content-ID"] for part in msg.walk() if part["Content-ID"]}
        self.assertFalse(ids(self.message(self.html)) & ids(self.message(self.html)))

    def test_preview_embeds_exact_exported_pngs(self):
        preview = email_assets.preview_html(self.html)
        sources = re.findall(r'<img src="data:image/png;base64,([^\"]+)"', preview)
        self.assertEqual(len(sources), 9)
        for index, source in enumerate(sources):
            name = email_assets.ICON_NAMES[index % 3]
            data = base64.b64decode(source)
            self.assertEqual(data, (email_assets.ICON_DIR / f"{name}.png").read_bytes())
            self.assertEqual(data[:8], b"\x89PNG\r\n\x1a\n")
            self.assertEqual(struct.unpack(">II", data[16:24]), (64, 64))
        self.assertNotIn('src="cid:', preview)

    def test_radar_does_not_attach_unused_icons(self):
        concept = {
            "term": "Test concept", "definition": "개념 정의입니다.",
            "why_now": "주목하는 이유입니다.", "practical_relevance": "실무 적용 맥락입니다.",
            "evidence_indices": [1],
        }
        evidence = {1: {"title": "Test evidence", "url": "https://example.test/evidence", "source": "Hacker News"}}
        markup = email_templates.render_radar(
            "2026년 09월 29일", [concept], evidence, ["test:model"]
        )
        message = self.message(markup)
        self.assertEqual(message.get_content_type(), "multipart/alternative")
        self.assertFalse(any(p.get_content_maintype() == "image" for p in message.walk()))
        self.assertEqual(email_assets.preview_html(markup), markup)


if __name__ == "__main__":
    unittest.main()
