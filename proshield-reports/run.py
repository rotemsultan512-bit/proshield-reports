#!/usr/bin/env python3
"""
Proshield Reports - Run Script
Start the application with proper initialization
"""

import os
import sys

# Add the current directory to the path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, init_db

def main():
    """Main entry point"""
    print("=" * 50)
    print("  Proshield Reports - Field Reporting System")
    print("=" * 50)

    # Initialize database
    print("\n[*] Initializing database...")
    init_db()

    # Generate icons if they don't exist
    icon_path = os.path.join(os.path.dirname(__file__), 'static', 'images', 'icon-192.png')
    if not os.path.exists(icon_path):
        print("[*] Generating PWA icons...")
        try:
            from generate_icons import main as generate_icons
            generate_icons()
        except Exception as e:
            print(f"[!] Warning: Could not generate icons: {e}")
            print("[!] You may need to run: python generate_icons.py")

    # Create upload directories
    upload_dir = os.path.join(os.path.dirname(__file__), 'uploads', 'reports')
    os.makedirs(upload_dir, exist_ok=True)
    print(f"[*] Upload directory: {upload_dir}")

    print("\n[*] Starting server...")
    print("[*] Access the app at: http://localhost:5000")
    print("[*] Default admin login: rotem / proshield2025")
    print("\n[*] Press Ctrl+C to stop the server")
    print("-" * 50)

    # Run the app
    app.run(
        debug=True,
        host='0.0.0.0',
        port=5000,
        threaded=True
    )

if __name__ == '__main__':
    main()
