"""Local lens artwork, browser previews and MIME inline-image packaging."""

import base64
from email.mime.image import MIMEImage
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import make_msgid
from functools import lru_cache
from pathlib import Path
import xml.etree.ElementTree as ET


ICON_DIR = Path(__file__).resolve().parent.parent / "assets" / "email-icons"
ICON_NAMES = ("everyone", "developers", "researchers")


def icon_cid(name):
    return f"cid:tri-lens-{name}"


@lru_cache(maxsize=3)
def icon_colour(name):
    """Use the editable SVG stroke as the label colour, too."""
    return ET.parse(ICON_DIR / f"{name}.svg").getroot().attrib["stroke"]


def referenced_icons(html_body):
    for name in ICON_NAMES:
        if f'src="{icon_cid(name)}"' in html_body:
            yield name, (ICON_DIR / f"{name}.png").read_bytes()


def preview_html(html_body):
    """Resolve mail CIDs to the same PNG bytes for an offline browser preview."""
    for name, data in referenced_icons(html_body):
        encoded = base64.b64encode(data).decode("ascii")
        html_body = html_body.replace(
            f'src="{icon_cid(name)}"', f'src="data:image/png;base64,{encoded}"'
        )
    return html_body


def build_message(subject, html_body, sender, recipients):
    """Assemble only; SMTP and credentials remain the sender's responsibility."""
    images = []
    for name, data in referenced_icons(html_body):
        # Unique per message, so clients cannot reuse stale art from another issue.
        cid = make_msgid(domain="tri-lens-news.local")
        html_body = html_body.replace(f'src="{icon_cid(name)}"', f'src="cid:{cid[1:-1]}"')
        image = MIMEImage(data, _subtype="png")
        image.add_header("Content-ID", cid)
        image.add_header("Content-Disposition", "inline", filename=f"{name}.png")
        images.append(image)

    msg = MIMEMultipart("related", type="text/html") if images else MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = sender
    msg["To"] = ", ".join(recipients)
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    for image in images:
        msg.attach(image)
    return msg
