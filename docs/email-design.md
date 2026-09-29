# Email Design

The three lenses use original line icons: a blue globe, teal code brackets, and an amber flask. The SVG files in `assets/email-icons/` are editable sources; their `stroke` colours also set the HTML labels. The three body paragraphs share the same left edge.

Mail uses 64px transparent PNG exports displayed at 16px. They are packaged once per message as inline MIME images with unique Content-IDs, following the [Python email example](https://docs.python.org/3/library/email.examples.html). The offline preview embeds the same PNG bytes as data URLs. Neither path depends on a remote image host. Text labels remain visible when a client hides images.

After changing an SVG, regenerate and commit the PNG with it. Exporting requires Node 22+ and an installed Chromium browser; these are build tools only, not email pipeline dependencies. For example, on Windows:

```powershell
node scripts/export_email_icons.mjs 'C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe'
python scripts/preview_email.py
```

Open `preview/index.html` to inspect both editions and screen widths. MIME assembly and browser rendering are checked locally; Gmail/Outlook inbox rendering and dark-mode transformations still require a received-message check.
