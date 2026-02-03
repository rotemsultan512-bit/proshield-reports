#!/usr/bin/env python3
"""Generate PWA icons from the ProShield app icon.

This script reads the source image from:
    static/images/proshield-icon.png
and regenerates icon-*.png in static/images/.

Notes:
- Icons are generated with padding so they work better as "maskable".
- Background is deep blue to match the app palette.
"""

from __future__ import annotations

import os
from PIL import Image


def _load_logo(logo_path: str) -> Image.Image:
    logo = Image.open(logo_path).convert("RGBA")

    # Trim fully-transparent borders (if any)
    bbox = logo.getbbox()
    if bbox:
        logo = logo.crop(bbox)

    return logo


def create_icon(size: int, logo: Image.Image, output_path: str) -> None:
    """Create one square icon with padding and a deep-blue background."""
    bg_color = (11, 18, 32, 255)  # deep blue (#0B1220)
    canvas = Image.new("RGBA", (size, size), bg_color)

    # Keep more padding so the icon doesn't fill the whole square
    margin = int(size * 0.22)
    max_w = size - (2 * margin)
    max_h = size - (2 * margin)

    resized = logo.copy()
    resized.thumbnail((max_w, max_h), Image.Resampling.LANCZOS)

    x = (size - resized.width) // 2
    y = (size - resized.height) // 2
    canvas.alpha_composite(resized, (x, y))

    canvas.save(output_path, "PNG")
    print(f"Created: {output_path}")


def main() -> None:
    sizes = [72, 96, 128, 144, 152, 192, 384, 512]

    base_dir = os.path.dirname(__file__)
    images_dir = os.path.join(base_dir, "static", "images")
    os.makedirs(images_dir, exist_ok=True)

    logo_path = os.path.join(images_dir, "proshield-icon.png")
    if not os.path.exists(logo_path):
        raise FileNotFoundError(f"Icon not found: {logo_path}")

    logo = _load_logo(logo_path)

    for size in sizes:
        output_path = os.path.join(images_dir, f"icon-{size}.png")
        create_icon(size, logo, output_path)

    print(f"\nAll icons generated in: {images_dir}")


if __name__ == "__main__":
    main()
