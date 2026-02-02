#!/usr/bin/env python3
"""
Proshield Reports - Setup Script
Initializes the application, creates icons, and prepares for first run
"""

import os
import sys
import subprocess

def check_python_version():
    """Check if Python version is compatible"""
    if sys.version_info < (3, 9):
        print("Error: Python 3.9 or higher is required")
        sys.exit(1)
    print(f"[OK] Python {sys.version_info.major}.{sys.version_info.minor}")

def create_virtual_env():
    """Create virtual environment if it doesn't exist"""
    if not os.path.exists('venv'):
        print("[*] Creating virtual environment...")
        subprocess.run([sys.executable, '-m', 'venv', 'venv'], check=True)
        print("[OK] Virtual environment created")
    else:
        print("[OK] Virtual environment exists")

def install_dependencies():
    """Install required packages"""
    print("[*] Installing dependencies...")

    # Determine pip path
    if os.name == 'nt':  # Windows
        pip_path = os.path.join('venv', 'Scripts', 'pip.exe')
    else:  # Linux/Mac
        pip_path = os.path.join('venv', 'bin', 'pip')

    subprocess.run([pip_path, 'install', '-r', 'requirements.txt'], check=True)
    print("[OK] Dependencies installed")

def create_directories():
    """Create required directories"""
    directories = [
        'uploads/reports',
        'instance',
        'static/images'
    ]

    for dir_path in directories:
        os.makedirs(dir_path, exist_ok=True)
        print(f"[OK] Directory: {dir_path}")

def generate_icons():
    """Generate PWA icons using PIL"""
    try:
        from PIL import Image, ImageDraw

        sizes = [72, 96, 128, 144, 152, 192, 384, 512]
        output_dir = 'static/images'

        for size in sizes:
            # Create image with blue background
            img = Image.new('RGB', (size, size), '#2563eb')
            draw = ImageDraw.Draw(img)

            # Draw shield shape
            margin = size // 8
            center_x = size // 2
            points = [
                (margin, margin),
                (size - margin, margin),
                (size - margin, int(size * 0.6)),
                (center_x, size - margin),
                (margin, int(size * 0.6)),
            ]
            draw.polygon(points, fill='white')

            # Draw "P" in center (simple approach without custom font)
            font_size = size // 3
            text_x = center_x - font_size // 4
            text_y = size // 3
            draw.text((text_x, text_y), 'P', fill='#2563eb')

            output_path = os.path.join(output_dir, f'icon-{size}.png')
            img.save(output_path, 'PNG')
            print(f"[OK] Created icon-{size}.png")

    except ImportError:
        print("[!] PIL not available, skipping icon generation")
        print("[!] Open create_icons.html in a browser to generate icons manually")

def initialize_database():
    """Initialize the database and create default admin"""
    print("[*] Initializing database...")

    # Import and initialize
    from app import app, init_db
    init_db()
    print("[OK] Database initialized")
    print("[OK] Default admin: rotem / proshield2025")

def main():
    print("=" * 50)
    print("  Proshield Reports - Setup")
    print("=" * 50)
    print()

    os.chdir(os.path.dirname(os.path.abspath(__file__)))

    check_python_version()
    create_directories()
    create_virtual_env()
    install_dependencies()

    # Add venv to path for imports
    if os.name == 'nt':
        site_packages = os.path.join('venv', 'Lib', 'site-packages')
    else:
        site_packages = os.path.join('venv', 'lib', f'python{sys.version_info.major}.{sys.version_info.minor}', 'site-packages')

    sys.path.insert(0, site_packages)

    generate_icons()
    initialize_database()

    print()
    print("=" * 50)
    print("  Setup Complete!")
    print("=" * 50)
    print()
    print("To run the application:")
    print("  Windows: run.bat")
    print("  Linux/Mac: python run.py")
    print()
    print("Default login: rotem / proshield2025")

if __name__ == '__main__':
    main()
