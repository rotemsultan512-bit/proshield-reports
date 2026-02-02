"""WSGI entry point for production servers (Render / Gunicorn).

Render Start Command should be: gunicorn wsgi:app
"""

from app import app  # noqa: F401
