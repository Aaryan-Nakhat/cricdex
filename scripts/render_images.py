"""Render the README's designed images: every docs/media/src/img-*.html -> docs/media/<name>.png.

    uv run python scripts/media_data.py                                      # the numbers -> data.js
    uv run --with playwright python scripts/render_images.py                 # all of them
    uv run --with playwright python scripts/render_images.py auction ngi     # just these
    uv run --with playwright python scripts/render_images.py og              # the link preview card

The link preview (Open Graph / Twitter card) is docs/media/src/og.html -> site/public/og.png, exactly
1200 x 630 (the size the social sites crop to); site/index.html points its og:image at it.

Each page is 1600 px wide; the image is the #stage element at its natural height. The sources share theme.css
(the same look as the hero video: hero.html -> scripts/render_video.py). Playwright is not a project dependency
(hence ``--with playwright``); the browser is the installed Microsoft Edge (``channel="msedge"``), so no
``playwright install`` download is needed. Set CRICDEX_BROWSER_CHANNEL=chromium to use Playwright's own build.
Run from the repo root.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

SRC = Path("docs/media/src")
OUT = Path("docs/media")
# the link-preview card: source, output and its fixed size
OG_SRC, OG_OUT, OG_SIZE = SRC / "og.html", Path("site/public/og.png"), (1200, 630)
CHANNEL = os.environ.get("CRICDEX_BROWSER_CHANNEL", "msedge")
FONTS_READY = """Promise.all([
  document.fonts.load('500 16px Inter'), document.fonts.load('800 16px Inter'),
  document.fonts.load('700 16px "JetBrains Mono"'),
]).then(() => document.fonts.ready).then(() => true)"""


def main(names: list[str]) -> None:
    from playwright.sync_api import sync_playwright

    pages = sorted(SRC.glob("img-*.html"))
    want_og = not names or "og" in names
    if names:
        pages = [p for p in pages if p.stem.removeprefix("img-") in names]
    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True, channel=None if CHANNEL == "chromium" else CHANNEL
        )
        page = browser.new_page(viewport={"width": 1600, "height": 900}, device_scale_factor=1)
        # a page that fails to fill from data.js would render half empty: stop instead
        errors: list[str] = []
        page.on("pageerror", lambda e: errors.append(str(e)))
        for src in pages:
            errors.clear()
            page.goto(src.resolve().as_uri())
            page.wait_for_function(FONTS_READY)
            page.wait_for_timeout(250)
            if errors:
                sys.exit(f"{src}: {errors[0]}")
            out = OUT / f"{src.stem.removeprefix('img-')}.png"
            page.locator("#stage").screenshot(path=str(out))
            print(f"wrote {out} ({out.stat().st_size / 1e3:.0f} KB)")
        if want_og:
            w, h = OG_SIZE
            og = browser.new_page(viewport={"width": w, "height": h}, device_scale_factor=1)
            og.goto(OG_SRC.resolve().as_uri())
            og.wait_for_function(FONTS_READY)
            og.wait_for_timeout(250)
            og.screenshot(path=str(OG_OUT), clip={"x": 0, "y": 0, "width": w, "height": h})
            print(f"wrote {OG_OUT} ({OG_OUT.stat().st_size / 1e3:.0f} KB)")
        browser.close()


if __name__ == "__main__":
    main(sys.argv[1:])
