#!/usr/bin/env python3
"""
Generate PWA icons for Proshield Reports
Run this script to create all required icon sizes
"""

from PIL import Image, ImageDraw, ImageFont
import os

def create_icon(size, output_path):
    """Create a simple icon with a shield shape"""
    # Create image with blue background
    img = Image.new('RGB', (size, size), '#2563eb')
    draw = ImageDraw.Draw(img)

    # Draw a simple shield shape
    margin = size // 8
    center_x = size // 2
    bottom_y = size - margin

    # Shield points
    points = [
        (margin, margin),  # Top left
        (size - margin, margin),  # Top right
        (size - margin, size * 0.6),  # Right side
        (center_x, bottom_y),  # Bottom point
        (margin, size * 0.6),  # Left side
    ]

    # Draw white shield
    draw.polygon(points, fill='white')

    # Draw "P" in the center
    try:
        # Try to use a system font
        font_size = size // 3
        try:
            font = ImageFont.truetype("arial.ttf", font_size)
        except:
            try:
                font = ImageFont.truetype("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf", font_size)
            except:
                font = ImageFont.load_default()
    except:
        font = ImageFont.load_default()

    # Draw "P" letter
    text = "P"
    bbox = draw.textbbox((0, 0), text, font=font)
    text_width = bbox[2] - bbox[0]
    text_height = bbox[3] - bbox[1]
    text_x = (size - text_width) // 2
    text_y = (size - text_height) // 2 - margin // 2
    draw.text((text_x, text_y), text, fill='#2563eb', font=font)

    # Save
    img.save(output_path, 'PNG')
    print(f"Created: {output_path}")

def main():
    # Icon sizes needed for PWA
    sizes = [72, 96, 128, 144, 152, 192, 384, 512]

    # Output directory
    output_dir = os.path.join(os.path.dirname(__file__), 'static', 'images')
    os.makedirs(output_dir, exist_ok=True)

    # Generate icons
    for size in sizes:
        output_path = os.path.join(output_dir, f'icon-{size}.png')
        create_icon(size, output_path)

    print(f"\nAll icons generated in: {output_dir}")

if __name__ == '__main__':
    main()
