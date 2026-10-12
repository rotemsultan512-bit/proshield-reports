import os
import secrets
from datetime import timedelta

basedir = os.path.abspath(os.path.dirname(__file__))


def _is_render() -> bool:
    """Detect running on Render.com.

    Render typically sets env vars like RENDER=true / RENDER_SERVICE_ID.
    """
    return os.environ.get('RENDER', '').lower() == 'true' or bool(os.environ.get('RENDER_SERVICE_ID'))


IS_PRODUCTION = _is_render() or os.environ.get('PROSHIELD_ENV') == 'production'


class Config:
    SECRET_KEY = os.environ.get('SECRET_KEY')
    if IS_PRODUCTION and not SECRET_KEY:
        raise RuntimeError('SECRET_KEY is required in production')
    if not SECRET_KEY:
        SECRET_KEY = secrets.token_hex(32)

    # Database
    _db_url = os.environ.get('DATABASE_URL')
    if _db_url:
        SQLALCHEMY_DATABASE_URI = _db_url
    elif IS_PRODUCTION:
        raise RuntimeError('DATABASE_URL is required in production')
    else:
        # Local/dev: keep DB inside the project under ./instance (create folder if missing)
        os.makedirs(os.path.join(basedir, 'instance'), exist_ok=True)
        SQLALCHEMY_DATABASE_URI = 'sqlite:///' + os.path.join(basedir, 'instance', 'proshield.db')

    SQLALCHEMY_TRACK_MODIFICATIONS = False

    # Upload settings
    # Prefer an explicit env var (useful for Render persistent disk mount)
    _upload_override = os.environ.get('UPLOAD_FOLDER')
    if _upload_override:
        UPLOAD_FOLDER = _upload_override
    elif IS_PRODUCTION:
        # Render: point to persistent disk mount (configure in dashboard)
        UPLOAD_FOLDER = os.path.join('/var/data', 'proshield_uploads', 'reports')
    else:
        UPLOAD_FOLDER = os.path.join(basedir, 'uploads', 'reports')
    MAX_IMAGE_SIZE = 5 * 1024 * 1024  # 5MB
    MAX_DOCUMENT_SIZE = 10 * 1024 * 1024  # 10MB
    ALLOWED_IMAGE_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
    ALLOWED_DOCUMENT_EXTENSIONS = {'pdf', 'png', 'jpg', 'jpeg'}

    # Session settings
    PERMANENT_SESSION_LIFETIME = timedelta(days=7)
    SESSION_COOKIE_SECURE = IS_PRODUCTION
    REMEMBER_COOKIE_SECURE = IS_PRODUCTION
    SESSION_COOKIE_HTTPONLY = True
    REMEMBER_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_SAMESITE = 'Lax'
    REMEMBER_COOKIE_DURATION = timedelta(days=7)
    WTF_CSRF_TIME_LIMIT = 7 * 24 * 60 * 60

    # Ten images and one document, including multipart overhead.
    MAX_CONTENT_LENGTH = 70 * 1024 * 1024

    # Image compression
    MAX_IMAGE_DIMENSION = 1920  # Max width/height after compression
    JPEG_QUALITY = 85
