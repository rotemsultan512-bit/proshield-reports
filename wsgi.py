"""WSGI entry point for Render / Gunicorn.

This repo keeps the Flask app inside the ./proshield-reports folder.
We add that folder to PYTHONPATH so `from app import app` works.

Render Start Command:
    gunicorn wsgi:app
"""

import os
import sys

PROJECT_DIR = os.path.join(os.path.dirname(__file__), 'proshield-reports')
if PROJECT_DIR not in sys.path:
    sys.path.insert(0, PROJECT_DIR)

from app import app  # noqa: E402,F401
