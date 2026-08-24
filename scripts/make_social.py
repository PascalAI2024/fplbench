"""Screenshot the generated public board into docs/img/social.png.

Usage:
  python scripts/make_social.py

Needs Playwright Chromium. Run ``scripts/build_board.py`` first, then crop the
responsive public ``#board`` at the canonical 1280 px preview width.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_HTML = ROOT / "outputs" / "board" / "index.html"
DEFAULT_OUT = ROOT / "docs" / "img" / "social.png"


def screenshot_board(html: Path, out: Path) -> Path:
    from playwright.sync_api import sync_playwright

    if not html.is_file():
        raise SystemExit(f"generated board not found: {html}")

    out.parent.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as p:
        browser = p.chromium.launch()
        page = browser.new_page(
            viewport={"width": 1280, "height": 800},
            device_scale_factor=1,
        )
        page.goto(html.resolve().as_uri(), wait_until="load")
        page.wait_for_selector("#board")
        page.wait_for_selector("#chips .chip")
        page.locator("#board").screenshot(path=str(out), type="png")
        browser.close()
    return out


def main(argv: list[str] | None = None) -> None:
    p = argparse.ArgumentParser(description="Screenshot #board → docs/img/social.png")
    p.add_argument("--html", type=Path, default=DEFAULT_HTML, help="pitch HTML")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help="PNG output")
    args = p.parse_args(argv)
    out = screenshot_board(args.html, args.out)
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
