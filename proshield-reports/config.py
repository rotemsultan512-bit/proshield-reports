import os
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))


def _is_render() -> bool:
    """Detect running on Render.com.

    Render typically sets env vars like RENDER=true / RENDER_SERVICE_ID.
    """
    return os.environ.get('RENDER', '').lower() == 'true' or bool(os.environ.get('RENDER_SERVICE_ID'))


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY') or 'proshield-secret-key-2025-change-in-production'

    # Database
    _db_url = os.environ.get('DATABASE_URL')
    if _db_url:
        SQLALCHEMY_DATABASE_URI = _db_url
    elif _is_render():
        # Render runtime filesystem is ephemeral; /tmp is safe for SQLite.
        SQLALCHEMY_DATABASE_URI = 'sqlite:////tmp/proshield.db'
    else:
        # Local/dev: keep DB inside the project under ./instance (create folder if missing)
        os.makedirs(os.path.join(basedir, 'instance'), exist_ok=True)
        SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'instance', 'proshield.db')

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Upload settings
    if _is_render():
        UPLOAD_FOLDER = os.path.join('/tmp', 'proshield_uploads', 'reports')
    else:
        UPLOAD_FOLDER = os.path.join(basedir, 'uploads', 'reports')
    MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB
    MAX_DOCUMENT_SIZE = 10 * 1024 * 1024  # 10MB
    ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    ALLOWED_DOCUMENT_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}

    # Session settings
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)

    # Image compression
    MAX_IMAGE_DIMENSION = 1920  # Max width/height after compression
    JPEG_QUALITY = 85
