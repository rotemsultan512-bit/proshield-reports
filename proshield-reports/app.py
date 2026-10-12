from flask import Flask, render_template, request, jsonify, redirect, url_for, flash, send_from_directory, send_file
from flask_login import LoginManager, login_user, logout_user, login_required, current_user
from flask_wtf.csrf import CSRFProtect
from werkzeug.utils import secure_filename
from PIL import Image
from datetime import datetime, timedelta
from io import BytesIO
import hashlib
import ipaddress
import tempfile
import zipfile
from sqlalchemy import or_, text
import os
import uuid
import json
import math

from config import Config
from models import db, User, LoginAttempt, Report, ReportProduct, ReportImage, ReportDocument, CompanyProject, InventoryItem, InventoryTransaction, PRODUCTS

app = Flask(__name__)
app.config.from_object(Config)
csrf = CSRFProtect(app)

# Initialize extensions
db.init_app(app)
login_manager = LoginManager()
login_manager.init_app(app)
login_manager.login_view = 'login'
login_manager.login_message = 'יש להתחבר כדי לגשת לעמוד זה'


@app.after_request
def prevent_private_response_caching(response):
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    response.headers['Referrer-Policy'] = 'same-origin'
    if not request.path.startswith('/static/') and request.path not in ('/manifest.json', '/sw.js', '/healthz'):
        response.headers['Cache-Control'] = 'private, no-store'
    return response


def _is_production_runtime() -> bool:
    """Detect production runtime (Render or any environment with DATABASE_URL).

    We use this to auto-initialize the DB on startup so the first login doesn't
    crash with missing tables.
    """
    return (
        os.environ.get('RENDER', '').lower() == 'true'
        or bool(os.environ.get('RENDER_SERVICE_ID'))
        or bool(os.environ.get('DATABASE_URL'))
    )


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

def init_db():
    """Initialize the schema and inventory catalog.

    In production (Render), the SQLite DB may be created in /tmp and start empty.
    Without this, the first login attempt can crash because tables don't exist.
    """
    with app.app_context():
        db.create_all()

        # Lightweight schema migrations (SQLite only)
        # NOTE: db.create_all() does not add new columns to existing tables.
        from sqlalchemy import text
        try:
            if db.engine.dialect.name == 'sqlite':
                report_columns = [
                    row[1] for row in db.session.execute(text('PRAGMA table_info(reports)')).fetchall()
                ]

                if 'customer_name' not in report_columns:
                    db.session.execute(text('ALTER TABLE reports ADD COLUMN customer_name VARCHAR(200)'))

                if 'company_project' not in report_columns:
                    db.session.execute(text('ALTER TABLE reports ADD COLUMN company_project VARCHAR(200)'))

                if 'recipient_name' not in report_columns:
                    db.session.execute(text('ALTER TABLE reports ADD COLUMN recipient_name VARCHAR(200)'))

                if 'installation_team' not in report_columns:
                    db.session.execute(text('ALTER TABLE reports ADD COLUMN installation_team VARCHAR(20)'))

                if 'additional_worker_name' not in report_columns:
                    db.session.execute(text('ALTER TABLE reports ADD COLUMN additional_worker_name VARCHAR(200)'))

                if 'installation_type' not in report_columns:
                    db.session.execute(text('ALTER TABLE reports ADD COLUMN installation_type VARCHAR(500)'))

                if 'installation_types' not in report_columns:
                    db.session.execute(text('ALTER TABLE reports ADD COLUMN installation_types TEXT'))

                if 'protections_count' not in report_columns:
                    db.session.execute(text('ALTER TABLE reports ADD COLUMN protections_count INTEGER'))

                if 'client_id' not in report_columns:
                    db.session.execute(text('ALTER TABLE reports ADD COLUMN client_id VARCHAR(64)'))
                if 'is_archived' not in report_columns:
                    db.session.execute(text('ALTER TABLE reports ADD COLUMN is_archived INTEGER NOT NULL DEFAULT 0'))
                if 'archived_at' not in report_columns:
                    db.session.execute(text('ALTER TABLE reports ADD COLUMN archived_at DATETIME'))
                if 'archived_by_user_id' not in report_columns:
                    db.session.execute(text('ALTER TABLE reports ADD COLUMN archived_by_user_id INTEGER'))
                db.session.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ix_reports_client_id ON reports (client_id)'))

                # Company/Project list table
                db.session.execute(text('''
                    CREATE TABLE IF NOT EXISTS company_projects (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        name VARCHAR(200) UNIQUE NOT NULL,
                        is_active BOOLEAN DEFAULT 1,
                        created_at DATETIME
                    )
                '''))

                # Inventory tables
                db.session.execute(text('''
                    CREATE TABLE IF NOT EXISTS inventory_items (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        product_name VARCHAR(200) UNIQUE NOT NULL,
                        quantity_unit FLOAT DEFAULT 0,
                        quantity_meter FLOAT DEFAULT 0,
                        updated_at DATETIME
                    )
                '''))
                db.session.execute(text('''
                    CREATE TABLE IF NOT EXISTS inventory_transactions (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        product_name VARCHAR(200) NOT NULL,
                        change_type VARCHAR(50) NOT NULL,
                        quantity FLOAT NOT NULL,
                        unit VARCHAR(20) NOT NULL,
                        report_id INTEGER,
                        user_id INTEGER,
                        notes VARCHAR(500),
                        created_at DATETIME,
                        FOREIGN KEY(report_id) REFERENCES reports(id),
                        FOREIGN KEY(user_id) REFERENCES users(id)
                    )
                '''))

                # Report products: quantity unit
                product_columns = [
                    row[1] for row in db.session.execute(text('PRAGMA table_info(report_products)')).fetchall()
                ]
                if 'quantity_unit' not in product_columns:
                    db.session.execute(text('ALTER TABLE report_products ADD COLUMN quantity_unit VARCHAR(20)'))

                # Rename PP Tape -> לוח PP מ"מ 4 (existing data)
                db.session.execute(text("UPDATE inventory_items SET product_name = 'לוח PP מ\"מ 4' WHERE product_name = 'PP Tape'"))
                db.session.execute(text("UPDATE report_products SET product_name = 'לוח PP מ\"מ 4' WHERE product_name = 'PP Tape'"))
                db.session.execute(text("UPDATE inventory_transactions SET product_name = 'לוח PP מ\"מ 4' WHERE product_name = 'PP Tape'"))

                db.session.commit()

            elif db.engine.dialect.name == 'postgresql':
                # Postgres supports IF NOT EXISTS
                db.session.execute(text('ALTER TABLE reports ADD COLUMN IF NOT EXISTS customer_name VARCHAR(200)'))
                db.session.execute(text('ALTER TABLE reports ADD COLUMN IF NOT EXISTS company_project VARCHAR(200)'))
                db.session.execute(text('ALTER TABLE reports ADD COLUMN IF NOT EXISTS recipient_name VARCHAR(200)'))
                db.session.execute(text('ALTER TABLE reports ADD COLUMN IF NOT EXISTS installation_team VARCHAR(20)'))
                db.session.execute(text('ALTER TABLE reports ADD COLUMN IF NOT EXISTS additional_worker_name VARCHAR(200)'))
                db.session.execute(text('ALTER TABLE reports ADD COLUMN IF NOT EXISTS installation_type VARCHAR(500)'))
                db.session.execute(text('ALTER TABLE reports ADD COLUMN IF NOT EXISTS installation_types TEXT'))
                db.session.execute(text('ALTER TABLE reports ADD COLUMN IF NOT EXISTS protections_count INTEGER'))
                db.session.execute(text('ALTER TABLE reports ADD COLUMN IF NOT EXISTS client_id VARCHAR(64)'))
                db.session.execute(text('ALTER TABLE reports ADD COLUMN IF NOT EXISTS is_archived BOOLEAN NOT NULL DEFAULT FALSE'))
                db.session.execute(text('ALTER TABLE reports ADD COLUMN IF NOT EXISTS archived_at TIMESTAMP'))
                db.session.execute(text('ALTER TABLE reports ADD COLUMN IF NOT EXISTS archived_by_user_id INTEGER'))
                db.session.execute(text('CREATE UNIQUE INDEX IF NOT EXISTS ix_reports_client_id ON reports (client_id)'))
                db.session.execute(text('ALTER TABLE report_products ADD COLUMN IF NOT EXISTS quantity_unit VARCHAR(20)'))

                db.session.execute(text('''
                    CREATE TABLE IF NOT EXISTS company_projects (
                        id SERIAL PRIMARY KEY,
                        name VARCHAR(200) UNIQUE NOT NULL,
                        is_active BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMP
                    )
                '''))

                db.session.execute(text('''
                    CREATE TABLE IF NOT EXISTS inventory_items (
                        id SERIAL PRIMARY KEY,
                        product_name VARCHAR(200) UNIQUE NOT NULL,
                        quantity_unit DOUBLE PRECISION DEFAULT 0,
                        quantity_meter DOUBLE PRECISION DEFAULT 0,
                        updated_at TIMESTAMP
                    )
                '''))
                db.session.execute(text('''
                    CREATE TABLE IF NOT EXISTS inventory_transactions (
                        id SERIAL PRIMARY KEY,
                        product_name VARCHAR(200) NOT NULL,
                        change_type VARCHAR(50) NOT NULL,
                        quantity DOUBLE PRECISION NOT NULL,
                        unit VARCHAR(20) NOT NULL,
                        report_id INTEGER,
                        user_id INTEGER,
                        notes VARCHAR(500),
                        created_at TIMESTAMP
                    )
                '''))

                db.session.execute(text("UPDATE inventory_items SET product_name = 'לוח PP מ\"מ 4' WHERE product_name = 'PP Tape'"))
                db.session.execute(text("UPDATE report_products SET product_name = 'לוח PP מ\"מ 4' WHERE product_name = 'PP Tape'"))
                db.session.execute(text("UPDATE inventory_transactions SET product_name = 'לוח PP מ\"מ 4' WHERE product_name = 'PP Tape'"))

                db.session.commit()
        except Exception as e:
            db.session.rollback()
            raise RuntimeError(f"Schema migration failed: {e}") from e

        # Ensure inventory items exist for all products
        existing_items = {i.product_name for i in InventoryItem.query.all()}
        for product in PRODUCTS:
            if product not in existing_items:
                db.session.add(InventoryItem(product_name=product, quantity_unit=0, quantity_meter=0))
        db.session.commit()

        # Accounts must be created explicitly; never install a known password.


# Auto-init DB on production startup (Gunicorn imports app.py but does not run __main__).
# Safe to call multiple times because create_all() is idempotent.
if _is_production_runtime():
    init_db()

def allowed_file(filename, file_type='image'):
    if file_type == 'image':
        allowed = Config.ALLOWED_IMAGE_EXTENSIONS
    else:
        allowed = Config.ALLOWED_DOCUMENT_EXTENSIONS
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in allowed


def validate_upload(file, file_type, max_size):
    if not allowed_file(file.filename, file_type):
        raise ValueError('סוג קובץ לא חוקי')
    file.seek(0, 2)
    size = file.tell()
    file.seek(0)
    if size <= 0 or size > max_size:
        raise ValueError('גודל קובץ לא תקין')
    if file.filename.lower().endswith('.pdf'):
        if file.read(5) != b'%PDF-':
            raise ValueError('קובץ PDF לא תקין')
    else:
        try:
            with Image.open(file.stream) as image:
                image.verify()
        except Exception as exc:
            raise ValueError('קובץ תמונה לא תקין') from exc
    file.seek(0)


def parse_products(raw):
    try:
        products = json.loads(raw)
    except (TypeError, json.JSONDecodeError) as exc:
        raise ValueError('רשימת מוצרים לא תקינה') from exc
    if not isinstance(products, list) or not products:
        raise ValueError('יש לבחור לפחות מוצר אחד')
    normalized = []
    for product in products:
        if not isinstance(product, dict):
            raise ValueError('מוצר לא תקין')
        name = str(product.get('name') or '').strip()
        try:
            quantity = float(product.get('quantity'))
        except (TypeError, ValueError) as exc:
            raise ValueError('כמות מוצר לא תקינה') from exc
        unit = product.get('unit') or 'unit'
        if not name or not math.isfinite(quantity) or quantity <= 0 or unit not in ('unit', 'meter'):
            raise ValueError('פרטי מוצר לא תקינים')
        normalized.append({'name': name, 'quantity': quantity, 'unit': unit})
    return normalized

def compress_image(image_data, max_size=Config.MAX_IMAGE_DIMENSION, quality=Config.JPEG_QUALITY):
    """Compress and resize image"""
    img = Image.open(BytesIO(image_data))

    # Convert to RGB if necessary
    if img.mode in ('RGBA', 'P'):
        img = img.convert('RGB')

    # Resize if too large
    if img.width > max_size or img.height > max_size:
        img.thumbnail((max_size, max_size), Image.Resampling.LANCZOS)

    # Save to bytes
    output = BytesIO()
    img.save(output, format='JPEG', quality=quality, optimize=True)
    output.seek(0)
    return output

def save_file(file, report_id, file_type='image'):
    """Save uploaded file with compression for images"""
    if not file:
        return None

    # Create directory structure
    report_dir = os.path.join(Config.UPLOAD_FOLDER, str(report_id))
    if file_type == 'image':
        save_dir = os.path.join(report_dir, 'images')
    elif file_type == 'delivery_note':
        save_dir = os.path.join(report_dir, 'delivery_note')
    else:
        save_dir = os.path.join(report_dir, 'documents')

    os.makedirs(save_dir, exist_ok=True)

    # Generate unique filename
    ext = file.filename.rsplit('.', 1)[1].lower() if '.' in file.filename else 'jpg'
    if file_type == 'image':
        ext = 'jpg'  # Always save images as JPEG after compression
    filename = f"{uuid.uuid4().hex}.{ext}"
    filepath = os.path.join(save_dir, filename)

    try:
        if file_type == 'image':
            compressed = compress_image(file.read())
            with open(filepath, 'wb') as f:
                f.write(compressed.read())
        else:
            file.save(filepath)
    except Exception:
        if os.path.exists(filepath):
            os.remove(filepath)
        raise

    # Return relative path for storage
    if file_type == 'image':
        subdir = 'images'
    elif file_type == 'delivery_note':
        subdir = 'delivery_note'
    else:
        subdir = 'documents'
    return os.path.join(str(report_id), subdir, filename)


def apply_inventory_change(product_name, quantity, unit, change_type, report_id=None, user_id=None, notes=None):
    """Apply inventory change and record transaction. Allows negative stock."""
    if unit not in ['unit', 'meter']:
        unit = 'unit'

    item = InventoryItem.query.filter_by(product_name=product_name).first()
    if not item:
        item = InventoryItem(product_name=product_name, quantity_unit=0, quantity_meter=0)
        db.session.add(item)
        db.session.flush()

    if unit == 'meter':
        item.quantity_meter = (item.quantity_meter or 0) + float(quantity)
    else:
        item.quantity_unit = (item.quantity_unit or 0) + float(quantity)

    tx = InventoryTransaction(
        product_name=product_name,
        change_type=change_type,
        quantity=float(quantity),
        unit=unit,
        report_id=report_id,
        user_id=user_id,
        notes=notes
    )
    db.session.add(tx)

# ============ ROUTES ============

@app.route('/healthz')
def healthz():
    """Health check used by the hosting service; no user data is exposed."""
    try:
        db.session.execute(text('SELECT 1'))
        return jsonify({'status': 'ok'})
    except Exception:
        db.session.rollback()
        return jsonify({'status': 'unavailable'}), 503


@app.route('/')
def index():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))
    return redirect(url_for('login'))

@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('dashboard'))

    if request.method == 'POST':
        data = request.get_json(silent=True) if request.is_json else request.form
        if request.is_json and not isinstance(data, dict):
            return jsonify({'success': False, 'error': 'פרטי ההתחברות אינם תקינים'}), 400
        username = data.get('username', '')
        password = data.get('password', '')
        if (not isinstance(username, str) or not isinstance(password, str)
                or len(username) > 80 or len(password.encode('utf-8')) > 72):
            error_msg = 'פרטי ההתחברות אינם תקינים'
            if request.is_json:
                return jsonify({'success': False, 'error': error_msg}), 400
            flash(error_msg, 'error')
            return render_template('login.html'), 400
        username = username.strip()

        # Keep failures in the database so the limit applies across web workers and restarts.
        # Use the final proxy hop, not a caller-controlled prefix in X-Forwarded-For.
        client_ip = request.remote_addr or 'unknown'
        if os.environ.get('RENDER', '').lower() == 'true':
            forwarded = request.headers.get('X-Forwarded-For', '').split(',')[-1].strip()
            try:
                client_ip = str(ipaddress.ip_address(forwarded))
            except ValueError:
                pass
        client_key = hashlib.sha256(f'{client_ip}:{username.casefold()}'.encode('utf-8')).hexdigest()
        now = datetime.utcnow()
        cutoff = now - timedelta(minutes=15)
        recent_attempts = (LoginAttempt.query
                           .filter(LoginAttempt.client_key == client_key,
                                   LoginAttempt.created_at >= cutoff)
                           .order_by(LoginAttempt.created_at.asc())
                           .all())
        if len(recent_attempts) >= 12:
            retry_after = max(1, int((recent_attempts[0].created_at + timedelta(minutes=15) - now).total_seconds()) + 1)
            error_msg = f'יותר מדי ניסיונות התחברות. נסה שוב בעוד {math.ceil(retry_after / 60)} דקות.'
            if request.is_json:
                response = jsonify({'success': False, 'error': error_msg})
            else:
                flash(error_msg, 'error')
                response = app.make_response(render_template('login.html'))
            response.status_code = 429
            response.headers['Retry-After'] = str(retry_after)
            return response

        user = User.query.filter_by(username=username).first()

        if user and user.check_password(password) and user.is_active:
            LoginAttempt.query.filter_by(client_key=client_key).delete()
            db.session.commit()
            login_user(user, remember=True)
            if request.is_json:
                return jsonify({'success': True, 'redirect': url_for('dashboard')})
            return redirect(url_for('dashboard'))

        error_msg = 'שם משתמש או סיסמה שגויים'
        db.session.add(LoginAttempt(client_key=client_key, created_at=now))
        LoginAttempt.query.filter(LoginAttempt.created_at < now - timedelta(days=1)).delete()
        db.session.commit()
        if request.is_json:
            return jsonify({'success': False, 'error': error_msg}), 401
        flash(error_msg, 'error')

    return render_template('login.html')

@app.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('login'))

@app.route('/dashboard')
@login_required
def dashboard():
    return render_template('dashboard.html')

@app.route('/report/new')
@login_required
def new_report():
    return render_template('new_report.html', products=PRODUCTS)

@app.route('/report/<int:report_id>')
@login_required
def view_report(report_id):
    report = Report.query.get_or_404(report_id)

    # Check access permission
    if not current_user.is_admin() and report.user_id != current_user.id:
        flash('אין לך הרשאה לצפות בדוח זה', 'error')
        return redirect(url_for('dashboard'))

    images = list(report.images)
    documents = list(report.documents)
    available_images = [image for image in images if os.path.isfile(os.path.join(Config.UPLOAD_FOLDER, image.image_path))]
    available_documents = [document for document in documents if os.path.isfile(os.path.join(Config.UPLOAD_FOLDER, document.document_path))]
    return render_template(
        'view_report.html',
        report=report,
        available_images=available_images,
        missing_image_count=len(images) - len(available_images),
        available_documents=available_documents,
        missing_document_count=len(documents) - len(available_documents),
    )

@app.route('/report/<int:report_id>/edit')
@login_required
def edit_report(report_id):
    report = Report.query.get_or_404(report_id)

    if not current_user.is_admin() and report.user_id != current_user.id:
        flash('אין לך הרשאה לערוך דוח זה', 'error')
        return redirect(url_for('dashboard'))

    if report.is_archived:
        flash('יש לשחזר את הדוח לפני עריכתו', 'warning')
        return redirect(url_for('view_report', report_id=report_id))

    return render_template('new_report.html', products=PRODUCTS, edit_mode=True, report_id=report.id)

@app.route('/settings')
@login_required
def settings():
    return render_template('settings.html')


@app.route('/api/admin/uploads-backup')
@login_required
def download_uploads_backup():
    """Let managers export the persistent report evidence as a local ZIP."""
    if not current_user.is_admin():
        return jsonify({'success': False, 'error': 'אין הרשאה'}), 403

    archive = tempfile.TemporaryFile()
    file_count = 0
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED, compresslevel=6) as bundle:
        root = Config.UPLOAD_FOLDER
        if os.path.isdir(root):
            for directory, directories, filenames in os.walk(root, followlinks=False):
                directories[:] = [name for name in directories if not os.path.islink(os.path.join(directory, name))]
                for filename in filenames:
                    path = os.path.join(directory, filename)
                    if os.path.islink(path) or not os.path.isfile(path):
                        continue
                    bundle.write(path, arcname=os.path.relpath(path, root).replace(os.sep, '/'))
                    file_count += 1
        bundle.writestr('backup-info.json', json.dumps({
            'created_at_utc': datetime.utcnow().isoformat() + 'Z',
            'file_count': file_count,
            'contents': 'report images and documents; database backup is separate',
        }))
    archive.seek(0)
    response = send_file(
        archive,
        mimetype='application/zip',
        as_attachment=True,
        download_name=f'proshield-uploads-{datetime.utcnow():%Y-%m-%d}.zip',
        conditional=False,
    )
    response.call_on_close(archive.close)
    return response

@app.route('/admin')
@login_required
def admin_dashboard():
    if not current_user.is_admin():
        flash('אין לך הרשאה לגשת לעמוד זה', 'error')
        return redirect(url_for('dashboard'))
    return render_template('admin.html')

@app.route('/inventory')
@login_required
def inventory_page():
    if not current_user.is_admin():
        flash('אין לך הרשאה לגשת לעמוד זה', 'error')
        return redirect(url_for('dashboard'))
    return render_template('inventory.html')

# ============ API ROUTES ============

@app.route('/api/reports', methods=['GET'])
@login_required
def get_reports():
    """Get reports - all for admin, own for regular users"""
    page = request.args.get('page', 1, type=int)
    per_page = request.args.get('per_page', 20, type=int)

    # Filters
    report_type = request.args.get('type')
    status = request.args.get('status')
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    search = request.args.get('search')
    user_search = request.args.get('user_search')
    user_id = request.args.get('user_id', type=int)
    show_archived = request.args.get('archived') == '1'

    # Base query
    if current_user.is_admin():
        query = Report.query
        if user_id:
            query = query.filter(Report.user_id == user_id)
    else:
        query = Report.query.filter_by(user_id=current_user.id)
    query = query.filter(Report.is_archived.is_(show_archived))

    # Apply filters
    if report_type:
        query = query.filter(Report.report_type == report_type)
    if status:
        query = query.filter(Report.status == status)
    if date_from:
        query = query.filter(Report.timestamp >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(Report.timestamp <= datetime.fromisoformat(date_to + 'T23:59:59'))
    if search:
        query = query.filter(or_(
            Report.address.ilike(f'%{search}%'),
            Report.customer_name.ilike(f'%{search}%'),
            Report.company_project.ilike(f'%{search}%')
        ))

    if user_search and current_user.is_admin():
        query = query.join(User).filter(or_(
            User.full_name.ilike(f'%{user_search}%'),
            User.username.ilike(f'%{user_search}%')
        ))

    # Order and paginate
    query = query.order_by(Report.timestamp.desc())
    pagination = query.paginate(page=page, per_page=per_page, error_out=False)

    return jsonify({
        'reports': [r.to_dict() for r in pagination.items],
        'total': pagination.total,
        'pages': pagination.pages,
        'current_page': page
    })

@app.route('/api/reports/stats', methods=['GET'])
@login_required
def get_reports_stats():
    """Get report statistics for dashboard"""
    from sqlalchemy import func, extract

    # Base query based on user role
    if current_user.is_admin():
        base_query = Report.query.filter(Report.is_archived.is_(False))
    else:
        base_query = Report.query.filter_by(user_id=current_user.id, is_archived=False)

    # Total reports
    total = base_query.count()

    # Reports by type
    delivery = base_query.filter(Report.report_type == 'delivery').count()
    installation = base_query.filter(Report.report_type == 'installation').count()

    # Reports this month
    now = datetime.utcnow()
    first_day_of_month = datetime(now.year, now.month, 1)
    this_month = base_query.filter(Report.timestamp >= first_day_of_month).count()

    return jsonify({
        'total': total,
        'delivery': delivery,
        'installation': installation,
        'this_month': this_month
    })

@app.route('/api/reports', methods=['POST'])
@login_required
def create_report():
    """Create a new report"""
    saved_paths = []
    try:
        client_id = (request.form.get('client_id') or '').strip() or None
        if client_id:
            if len(client_id) > 64:
                return jsonify({'success': False, 'error': 'מזהה דוח לא תקין'}), 400
            existing = Report.query.filter_by(client_id=client_id).first()
            if existing:
                if existing.user_id != current_user.id:
                    return jsonify({'success': False, 'error': 'מזהה דוח כבר בשימוש'}), 409
                return jsonify({'success': True, 'report_id': existing.id, 'already_saved': True})

        # Get form data
        report_type = request.form.get('report_type')
        address = request.form.get('address')
        status = request.form.get('status')
        notes = request.form.get('notes', '')
        products_json = request.form.get('products', '[]')

        # Delivery / Installation extra fields
        customer_name = (request.form.get('customer_name') or '').strip()
        company_project = (request.form.get('company_project') or '').strip()
        recipient_name = (request.form.get('recipient_name') or '').strip()
        report_datetime_raw = request.form.get('report_datetime')

        # Installation team fields
        installation_team = (request.form.get('installation_team') or '').strip()
        additional_worker_name = (request.form.get('additional_worker_name') or '').strip()

        # installation_types is expected to be a JSON array string from the client
        installation_types_raw = request.form.get('installation_types')
        # Backward compatibility (if a client still sends a single installation_type)
        installation_type_single = request.form.get('installation_type')

        protections_count_raw = request.form.get('protections_count')

        # Validate required fields
        if not all([report_type, address, status]):
            return jsonify({'success': False, 'error': 'יש למלא את כל השדות הנדרשים'}), 400
        if report_type not in ('delivery', 'installation') or status not in ('completed', 'return_required'):
            return jsonify({'success': False, 'error': 'סוג דוח או סטטוס לא תקינים'}), 400
        if len(address) > 500 or len(customer_name) > 200 or len(company_project) > 200 or len(recipient_name) > 200:
            return jsonify({'success': False, 'error': 'אחד השדות ארוך מדי'}), 400

        if not customer_name:
            return jsonify({'success': False, 'error': 'יש להזין שם לקוח'}), 400

        # Parse report date/time
        report_timestamp = None
        if report_datetime_raw:
            try:
                # Expecting "YYYY-MM-DDTHH:MM" from datetime-local
                report_timestamp = datetime.fromisoformat(report_datetime_raw)
            except ValueError:
                return jsonify({'success': False, 'error': 'תאריך/שעה לא תקין'}), 400
        else:
            return jsonify({'success': False, 'error': 'יש לבחור תאריך ושעה'}), 400

        # Installation extra validation
        protections_count = None
        installation_types_list = []
        installation_type_display = None

        if report_type == 'installation':
            # Parse types
            if installation_types_raw:
                try:
                    installation_types_list = json.loads(installation_types_raw)
                    if not isinstance(installation_types_list, list):
                        installation_types_list = []
                except json.JSONDecodeError:
                    installation_types_list = []

            # Fallback to legacy single field
            if not installation_types_list and installation_type_single:
                installation_types_list = [installation_type_single]

            # Validate
            if not installation_types_list:
                return jsonify({'success': False, 'error': 'יש לבחור לפחות סוג התקנה אחד'}), 400

            installation_type_display = ', '.join([str(x) for x in installation_types_list if x])

            try:
                protections_count = int(protections_count_raw) if protections_count_raw is not None else None
            except (TypeError, ValueError):
                protections_count = None

            # Installation team validation
            if not installation_team:
                return jsonify({'success': False, 'error': 'יש לבחור צוות התקנה'}), 400
            if installation_team not in ('solo', 'with_worker') or len(additional_worker_name) > 200:
                return jsonify({'success': False, 'error': 'פרטי צוות ההתקנה לא תקינים'}), 400

            if installation_team == 'with_worker' and not additional_worker_name:
                return jsonify({'success': False, 'error': 'יש להזין שם עובד נוסף'}), 400

        try:
            products_data = parse_products(products_json)
            delivery_note = request.files.get('delivery_note') if report_type == 'delivery' else None
            if delivery_note and delivery_note.filename:
                validate_upload(delivery_note, 'document', Config.MAX_DOCUMENT_SIZE)
            images = [image for image in request.files.getlist('images') if image and image.filename]
            if len(images) > 10:
                raise ValueError('ניתן לצרף עד 10 תמונות')
            for image in images:
                validate_upload(image, 'image', Config.MAX_IMAGE_SIZE)
        except ValueError as exc:
            return jsonify({'success': False, 'error': str(exc)}), 400

        # Create report
        report = Report(
            user_id=current_user.id,
            client_id=client_id,
            report_type=report_type,
            customer_name=customer_name,
            recipient_name=recipient_name if report_type == 'delivery' else None,
            company_project=company_project or None,
            installation_type=installation_type_display if report_type == 'installation' else None,
            installation_types=(
                json.dumps(installation_types_list, ensure_ascii=False)
                if report_type == 'installation'
                else None
            ),
            protections_count=protections_count if report_type == 'installation' else None,
            installation_team=installation_team if report_type == 'installation' else None,
            additional_worker_name=additional_worker_name if report_type == 'installation' and installation_team == 'with_worker' else None,
            address=address,
            status=status,
            notes=notes,
            timestamp=report_timestamp
        )
        db.session.add(report)
        db.session.flush()  # Get report ID

        # Add products
        for product in products_data:
            if product.get('name') and product.get('quantity'):
                unit = product.get('unit') or 'unit'
                if unit not in ['unit', 'meter']:
                    unit = 'unit'

                report_product = ReportProduct(
                    report_id=report.id,
                    product_name=product['name'],
                    quantity=float(product['quantity']),
                    quantity_unit=unit
                )
                db.session.add(report_product)

                # Inventory: subtract reported quantity
                apply_inventory_change(
                    product_name=product['name'],
                    quantity=-float(product['quantity']),
                    unit=unit,
                    change_type='report',
                    report_id=report.id,
                    user_id=current_user.id,
                    notes=f"Report #{report.id}"
                )

        # Handle delivery note upload (OPTIONAL for delivery reports)
        if report_type == 'delivery':
            if delivery_note and delivery_note.filename:
                doc_path = save_file(delivery_note, report.id, 'delivery_note')
                if doc_path:
                    saved_paths.append(doc_path)
                    report_doc = ReportDocument(
                        report_id=report.id,
                        document_path=doc_path,
                        original_filename=secure_filename(delivery_note.filename)
                    )
                    db.session.add(report_doc)

        # Handle image uploads
        for image in images:
            image_path = save_file(image, report.id, 'image')
            if image_path:
                saved_paths.append(image_path)
                image_type = 'goods' if report_type == 'delivery' else 'project'
                report_image = ReportImage(
                    report_id=report.id,
                    image_path=image_path,
                    image_type=image_type
                )
                db.session.add(report_image)

        db.session.commit()

        return jsonify({
            'success': True,
            'report_id': report.id,
            'message': 'הדוח נשמר בהצלחה'
        })

    except Exception as e:
        db.session.rollback()
        for path in saved_paths:
            full_path = os.path.join(Config.UPLOAD_FOLDER, path)
            if os.path.isfile(full_path):
                os.remove(full_path)
        return jsonify({'success': False, 'error': f'שגיאה בשמירת הדוח: {str(e)}'}), 500


@app.route('/api/reports/<int:report_id>', methods=['GET'])
@login_required
def get_report(report_id):
    """Get single report"""
    report = Report.query.get_or_404(report_id)

    if not current_user.is_admin() and report.user_id != current_user.id:
        return jsonify({'success': False, 'error': 'אין הרשאה'}), 403

    return jsonify(report.to_dict())


@app.route('/api/reports/<int:report_id>', methods=['PUT'])
@login_required
def update_report(report_id):
    """Update a report and sync inventory"""
    report = Report.query.get_or_404(report_id)
    saved_paths = []

    if not current_user.is_admin() and report.user_id != current_user.id:
        return jsonify({'success': False, 'error': 'אין הרשאה'}), 403
    if report.is_archived:
        return jsonify({'success': False, 'error': 'יש לשחזר את הדוח לפני עריכתו'}), 409

    try:
        report_type = request.form.get('report_type')
        address = request.form.get('address')
        status = request.form.get('status')
        notes = request.form.get('notes', '')
        products_json = request.form.get('products', '[]')

        customer_name = (request.form.get('customer_name') or '').strip()
        company_project = (request.form.get('company_project') or '').strip()
        recipient_name = (request.form.get('recipient_name') or '').strip()
        report_datetime_raw = request.form.get('report_datetime')

        installation_team = (request.form.get('installation_team') or '').strip()
        additional_worker_name = (request.form.get('additional_worker_name') or '').strip()

        installation_types_raw = request.form.get('installation_types')
        installation_type_single = request.form.get('installation_type')

        if not all([report_type, address, status]):
            return jsonify({'success': False, 'error': 'יש למלא את כל השדות הנדרשים'}), 400
        if report_type not in ('delivery', 'installation') or status not in ('completed', 'return_required'):
            return jsonify({'success': False, 'error': 'סוג דוח או סטטוס לא תקינים'}), 400
        if len(address) > 500 or len(customer_name) > 200 or len(company_project) > 200 or len(recipient_name) > 200:
            return jsonify({'success': False, 'error': 'אחד השדות ארוך מדי'}), 400

        if not customer_name:
            return jsonify({'success': False, 'error': 'יש להזין שם לקוח'}), 400

        # Parse report date/time
        report_timestamp = None
        if report_datetime_raw:
            try:
                report_timestamp = datetime.fromisoformat(report_datetime_raw)
            except ValueError:
                return jsonify({'success': False, 'error': 'תאריך/שעה לא תקין'}), 400
        else:
            return jsonify({'success': False, 'error': 'יש לבחור תאריך ושעה'}), 400

        # Installation types
        installation_types_list = []
        installation_type_display = None
        if report_type == 'installation':
            if installation_types_raw:
                try:
                    installation_types_list = json.loads(installation_types_raw)
                    if not isinstance(installation_types_list, list):
                        installation_types_list = []
                except json.JSONDecodeError:
                    installation_types_list = []

            if not installation_types_list and installation_type_single:
                installation_types_list = [installation_type_single]

            if not installation_types_list:
                return jsonify({'success': False, 'error': 'יש לבחור לפחות סוג התקנה אחד'}), 400

            installation_type_display = ', '.join([str(x) for x in installation_types_list if x])

            # Installation team validation
            if not installation_team:
                return jsonify({'success': False, 'error': 'יש לבחור צוות התקנה'}), 400
            if installation_team not in ('solo', 'with_worker') or len(additional_worker_name) > 200:
                return jsonify({'success': False, 'error': 'פרטי צוות ההתקנה לא תקינים'}), 400

            if installation_team == 'with_worker' and not additional_worker_name:
                return jsonify({'success': False, 'error': 'יש להזין שם עובד נוסף'}), 400

        try:
            products_data = parse_products(products_json)
            delivery_note = request.files.get('delivery_note') if report_type == 'delivery' else None
            if delivery_note and delivery_note.filename:
                validate_upload(delivery_note, 'document', Config.MAX_DOCUMENT_SIZE)
            images = [image for image in request.files.getlist('images') if image and image.filename]
            if report.images.count() + len(images) > 10:
                raise ValueError('ניתן לצרף עד 10 תמונות בסך הכול')
            for image in images:
                validate_upload(image, 'image', Config.MAX_IMAGE_SIZE)
        except ValueError as exc:
            return jsonify({'success': False, 'error': str(exc)}), 400

        # Revert inventory from old products
        for old_product in report.products:
            apply_inventory_change(
                product_name=old_product.product_name,
                quantity=float(old_product.quantity),
                unit=old_product.quantity_unit or 'unit',
                change_type='report_edit',
                report_id=report.id,
                user_id=current_user.id,
                notes=f"Revert Report #{report.id}"
            )

        # Clear old products
        ReportProduct.query.filter_by(report_id=report.id).delete()

        # Update report fields
        report.report_type = report_type
        report.customer_name = customer_name
        report.recipient_name = recipient_name if report_type == 'delivery' else None
        report.company_project = company_project or None
        report.address = address
        report.status = status
        report.notes = notes
        report.timestamp = report_timestamp
        report.installation_types = (
            json.dumps(installation_types_list, ensure_ascii=False)
            if report_type == 'installation'
            else None
        )
        report.installation_type = installation_type_display if report_type == 'installation' else None
        report.installation_team = installation_team if report_type == 'installation' else None
        report.additional_worker_name = additional_worker_name if report_type == 'installation' and installation_team == 'with_worker' else None

        # Add new products + apply inventory
        for product in products_data:
            if product.get('name') and product.get('quantity'):
                unit = product.get('unit') or 'unit'
                if unit not in ['unit', 'meter']:
                    unit = 'unit'

                report_product = ReportProduct(
                    report_id=report.id,
                    product_name=product['name'],
                    quantity=float(product['quantity']),
                    quantity_unit=unit
                )
                db.session.add(report_product)

                apply_inventory_change(
                    product_name=product['name'],
                    quantity=-float(product['quantity']),
                    unit=unit,
                    change_type='report_edit',
                    report_id=report.id,
                    user_id=current_user.id,
                    notes=f"Update Report #{report.id}"
                )

        if delivery_note and delivery_note.filename:
            doc_path = save_file(delivery_note, report.id, 'delivery_note')
            saved_paths.append(doc_path)
            db.session.add(ReportDocument(
                report_id=report.id,
                document_path=doc_path,
                original_filename=secure_filename(delivery_note.filename)
            ))

        for image in images:
            image_path = save_file(image, report.id, 'image')
            saved_paths.append(image_path)
            db.session.add(ReportImage(
                report_id=report.id,
                image_path=image_path,
                image_type='goods' if report_type == 'delivery' else 'project'
            ))

        db.session.commit()
        return jsonify({'success': True, 'report_id': report.id})

    except Exception as e:
        db.session.rollback()
        for path in saved_paths:
            full_path = os.path.join(Config.UPLOAD_FOLDER, path)
            if os.path.isfile(full_path):
                os.remove(full_path)
        return jsonify({'success': False, 'error': f'שגיאה בעדכון הדוח: {str(e)}'}), 500


@app.route('/api/reports/<int:report_id>', methods=['DELETE'])
@login_required
def delete_report(report_id):
    """Archive a report, preserve its evidence, and reverse its stock movement."""
    report = Report.query.filter_by(id=report_id).with_for_update().first_or_404()

    # Check permission
    if not current_user.is_admin() and report.user_id != current_user.id:
        return jsonify({'success': False, 'error': 'אין לך הרשאה למחוק דוח זה'}), 403
    if report.is_archived:
        return jsonify({'success': True, 'already_archived': True})

    try:
        # Revert inventory changes for this report
        for product in report.products:
            apply_inventory_change(
                product_name=product.product_name,
                quantity=float(product.quantity),
                unit=product.quantity_unit or 'unit',
                change_type='report_archive',
                report_id=report.id,
                user_id=current_user.id,
                notes=f"Archive Report #{report.id}"
            )
        report.is_archived = True
        report.archived_at = datetime.utcnow()
        report.archived_by_user_id = current_user.id
        db.session.commit()

        return jsonify({'success': True, 'message': 'הדוח הועבר לארכיון'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


@app.route('/api/reports/<int:report_id>/restore', methods=['POST'])
@login_required
def restore_report(report_id):
    """Restore an archived report and reapply its stock movement."""
    report = Report.query.filter_by(id=report_id).with_for_update().first_or_404()
    if not current_user.is_admin() and report.user_id != current_user.id:
        return jsonify({'success': False, 'error': 'אין הרשאה לשחזר דוח זה'}), 403
    if not report.is_archived:
        return jsonify({'success': True, 'already_restored': True})

    try:
        for product in report.products:
            apply_inventory_change(
                product_name=product.product_name,
                quantity=-float(product.quantity),
                unit=product.quantity_unit or 'unit',
                change_type='report_restore',
                report_id=report.id,
                user_id=current_user.id,
                notes=f"Restore Report #{report.id}"
            )
        report.is_archived = False
        db.session.commit()
        return jsonify({'success': True, 'message': 'הדוח שוחזר'})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500

@app.route('/api/user/password', methods=['POST'])
@login_required
def change_password():
    """Change user password"""
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'פרטי הבקשה אינם תקינים'}), 400
    current_password = data.get('current_password')
    new_password = data.get('new_password')

    if (not isinstance(current_password, str) or len(current_password.encode('utf-8')) > 72
            or not current_user.check_password(current_password)):
        return jsonify({'success': False, 'error': 'הסיסמה הנוכחית שגויה'}), 400

    if not isinstance(new_password, str) or len(new_password) < 12:
        return jsonify({'success': False, 'error': 'הסיסמה החדשה חייבת להכיל לפחות 12 תווים'}), 400
    if len(new_password.encode('utf-8')) > 72:
        return jsonify({'success': False, 'error': 'הסיסמה החדשה ארוכה מדי'}), 400

    current_user.set_password(new_password)
    db.session.commit()

    return jsonify({'success': True, 'message': 'הסיסמה שונתה בהצלחה'})

@app.route('/api/users', methods=['GET'])
@login_required
def get_users():
    """Get all users (admin only)"""
    if not current_user.is_admin():
        return jsonify({'success': False, 'error': 'אין הרשאה'}), 403

    users = User.query.all()
    return jsonify({
        'users': [{
            'id': u.id,
            'username': u.username,
            'full_name': u.full_name,
            'role': u.role,
            'is_active': u.is_active
        } for u in users]
    })

@app.route('/api/users', methods=['POST'])
@login_required
def create_user():
    """Create new user (admin only)"""
    if not current_user.is_admin():
        return jsonify({'success': False, 'error': 'אין הרשאה'}), 403

    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        return jsonify({'success': False, 'error': 'פרטי הבקשה אינם תקינים'}), 400
    username = data.get('username', '')
    password = data.get('password', '')
    full_name = data.get('full_name', '')
    role = data.get('role', 'user')

    if (not isinstance(username, str) or not isinstance(full_name, str)
            or not isinstance(password, str)):
        return jsonify({'success': False, 'error': 'פרטי המשתמש אינם תקינים'}), 400
    username = username.strip()
    full_name = full_name.strip()

    if not all([username, password, full_name]):
        return jsonify({'success': False, 'error': 'יש למלא את כל השדות'}), 400

    if (len(username) > 80 or len(full_name) > 100 or len(password) < 12
            or len(password.encode('utf-8')) > 72 or role not in ('user', 'admin')):
        return jsonify({'success': False, 'error': 'סיסמה או תפקיד לא תקינים'}), 400

    if User.query.filter_by(username=username).first():
        return jsonify({'success': False, 'error': 'שם משתמש כבר קיים'}), 400

    user = User(username=username, full_name=full_name, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()

    return jsonify({'success': True, 'message': 'המשתמש נוצר בהצלחה'})

@app.route('/api/users/<int:user_id>', methods=['PUT'])
@login_required
def update_user(user_id):
    """Update user details (admin only)"""
    if not current_user.is_admin():
        return jsonify({'success': False, 'error': 'אין הרשאה'}), 403

    data = request.get_json() or {}
    full_name = (data.get('full_name') or '').strip()
    role = (data.get('role') or 'user').strip()
    is_active = data.get('is_active')

    if role not in ['user', 'admin']:
        return jsonify({'success': False, 'error': 'תפקיד לא תקין'}), 400

    user = User.query.get_or_404(user_id)

    if user.id == current_user.id and role != 'admin':
        return jsonify({'success': False, 'error': 'לא ניתן להסיר הרשאת מנהל מעצמך'}), 400

    if full_name:
        user.full_name = full_name
    user.role = role

    if is_active is not None:
        user.is_active = bool(is_active)

    db.session.commit()
    return jsonify({'success': True, 'message': 'המשתמש עודכן בהצלחה'})

@app.route('/api/users/<int:user_id>', methods=['DELETE'])
@login_required
def delete_user(user_id):
    """Delete user (admin only)"""
    if not current_user.is_admin():
        return jsonify({'success': False, 'error': 'אין הרשאה'}), 403

    if user_id == current_user.id:
        return jsonify({'success': False, 'error': 'לא ניתן למחוק את עצמך'}), 400

    user = User.query.get_or_404(user_id)
    db.session.delete(user)
    db.session.commit()

    return jsonify({'success': True, 'message': 'המשתמש נמחק בהצלחה'})


@app.route('/api/company-projects', methods=['GET'])
@login_required
def get_company_projects():
    """Get company/project names"""
    include_inactive = request.args.get('include_inactive') == 'true'

    query = CompanyProject.query
    if not current_user.is_admin() or not include_inactive:
        query = query.filter(CompanyProject.is_active == True)  # noqa: E712

    projects = query.order_by(CompanyProject.name.asc()).all()
    return jsonify({
        'projects': [p.to_dict() for p in projects]
    })


@app.route('/api/company-projects', methods=['POST'])
@login_required
def create_company_project():
    """Create company/project (admin only)"""
    if not current_user.is_admin():
        return jsonify({'success': False, 'error': 'אין הרשאה'}), 403

    data = request.get_json() or {}
    name = (data.get('name') or '').strip()
    if not name:
        return jsonify({'success': False, 'error': 'יש להזין שם'}), 400

    existing = CompanyProject.query.filter_by(name=name).first()
    if existing:
        existing.is_active = True
        db.session.commit()
        return jsonify({'success': True, 'project': existing.to_dict()})

    project = CompanyProject(name=name, is_active=True)
    db.session.add(project)
    db.session.commit()

    return jsonify({'success': True, 'project': project.to_dict()})


@app.route('/api/company-projects/<int:project_id>', methods=['DELETE'])
@login_required
def delete_company_project(project_id):
    """Delete company/project (admin only)"""
    if not current_user.is_admin():
        return jsonify({'success': False, 'error': 'אין הרשאה'}), 403

    project = CompanyProject.query.get_or_404(project_id)
    db.session.delete(project)
    db.session.commit()

    return jsonify({'success': True, 'message': 'הפריט נמחק בהצלחה'})


@app.route('/api/inventory', methods=['GET'])
@login_required
def get_inventory():
    """Get inventory list (admin only)"""
    if not current_user.is_admin():
        return jsonify({'success': False, 'error': 'אין הרשאה'}), 403

    # Ensure inventory items exist for all products
    existing_items = {i.product_name: i for i in InventoryItem.query.all()}
    for product in PRODUCTS:
        if product not in existing_items:
            item = InventoryItem(product_name=product, quantity_unit=0, quantity_meter=0)
            db.session.add(item)
            existing_items[product] = item
    db.session.commit()

    # Reports may create custom products. Keep them visible for reconciliation.
    canonical = [existing_items[p] for p in PRODUCTS if p in existing_items]
    custom = sorted(
        (item for name, item in existing_items.items() if name not in PRODUCTS),
        key=lambda item: item.product_name.casefold()
    )
    items = [item.to_dict() for item in canonical + custom]
    return jsonify({'items': items})


@app.route('/api/inventory/adjust', methods=['POST'])
@login_required
def adjust_inventory():
    """Adjust inventory (admin only). Allows negative stock."""
    if not current_user.is_admin():
        return jsonify({'success': False, 'error': 'אין הרשאה'}), 403

    data = request.get_json() or {}
    items = data.get('items', [])
    if not isinstance(items, list):
        return jsonify({'success': False, 'error': 'נתונים לא תקינים'}), 400

    try:
        for item in items:
            product_name = (item.get('product_name') or '').strip()
            if not product_name:
                continue

            target_unit = float(item.get('quantity_unit') or 0)
            target_meter = float(item.get('quantity_meter') or 0)

            inv = InventoryItem.query.filter_by(product_name=product_name).first()
            if not inv:
                inv = InventoryItem(product_name=product_name, quantity_unit=0, quantity_meter=0)
                db.session.add(inv)
                db.session.flush()

            delta_unit = target_unit - (inv.quantity_unit or 0)
            delta_meter = target_meter - (inv.quantity_meter or 0)

            if delta_unit != 0:
                apply_inventory_change(
                    product_name=product_name,
                    quantity=delta_unit,
                    unit='unit',
                    change_type='adjustment',
                    user_id=current_user.id,
                    notes='Manual adjustment'
                )

            if delta_meter != 0:
                apply_inventory_change(
                    product_name=product_name,
                    quantity=delta_meter,
                    unit='meter',
                    change_type='adjustment',
                    user_id=current_user.id,
                    notes='Manual adjustment'
                )

        db.session.commit()
        return jsonify({'success': True})
    except Exception as e:
        db.session.rollback()
        return jsonify({'success': False, 'error': str(e)}), 500


def _export_inventory_to_excel(items, transactions):
    from openpyxl import Workbook
    from io import BytesIO
    from flask import send_file

    wb = Workbook()
    ws_items = wb.active
    ws_items.title = "מלאי"

    ws_items.append(['מוצר', 'כמות יחידה', 'כמות מטר', 'עודכן לאחרונה'])
    for item in items:
        ws_items.append([
            item.product_name,
            item.quantity_unit or 0,
            item.quantity_meter or 0,
            item.updated_at.strftime('%d/%m/%Y %H:%M') if item.updated_at else ''
        ])

    ws_tx = wb.create_sheet(title="תנועות מלאי")
    ws_tx.append(['מוצר', 'סוג שינוי', 'כמות', 'יחידה', 'דוח', 'משתמש', 'הערה', 'תאריך'])
    for tx in transactions:
        ws_tx.append([
            tx.product_name,
            tx.change_type,
            tx.quantity,
            'יח׳' if tx.unit == 'unit' else 'מ׳',
            tx.report_id or '',
            tx.user_id or '',
            tx.notes or '',
            tx.created_at.strftime('%d/%m/%Y %H:%M') if tx.created_at else ''
        ])

    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'inventory_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )


@app.route('/api/inventory/export')
@login_required
def export_inventory():
    """Export inventory and transactions (admin only)"""
    if not current_user.is_admin():
        return jsonify({'success': False, 'error': 'אין הרשאה'}), 403

    items = InventoryItem.query.order_by(InventoryItem.product_name.asc()).all()
    transactions = InventoryTransaction.query.order_by(InventoryTransaction.created_at.desc()).all()
    return _export_inventory_to_excel(items, transactions)


@app.route('/api/stats')
@login_required
def get_stats():
    """Get statistics (admin only)"""
    if not current_user.is_admin():
        return jsonify({'success': False, 'error': 'אין הרשאה'}), 403

    # Total reports
    active_reports = Report.query.filter(Report.is_archived.is_(False))
    total_reports = active_reports.count()
    completed_reports = active_reports.filter_by(status='completed').count()
    pending_reports = active_reports.filter_by(status='return_required').count()

    # Reports by type
    delivery_reports = active_reports.filter_by(report_type='delivery').count()
    installation_reports = active_reports.filter_by(report_type='installation').count()

    # Reports per user
    users = User.query.all()
    reports_per_user = []
    for user in users:
        count = active_reports.filter_by(user_id=user.id).count()
        reports_per_user.append({
            'user_id': user.id,
            'full_name': user.full_name,
            'count': count
        })

    return jsonify({
        'total_reports': total_reports,
        'completed_reports': completed_reports,
        'pending_reports': pending_reports,
        'delivery_reports': delivery_reports,
        'installation_reports': installation_reports,
        'reports_per_user': reports_per_user
    })

def _export_reports_to_excel(reports, filename_prefix):
    from openpyxl import Workbook
    from openpyxl.styles import Font, Alignment, PatternFill, Border, Side
    from io import BytesIO
    from flask import send_file
    from collections import defaultdict

    wb = Workbook()

    # ---- Sheet 1: Detailed Reports ----
    ws = wb.active
    ws.title = "דוחות מפורטים"
    ws.sheet_view.rightToLeft = True

    # Styles
    header_font = Font(name='Arial', bold=True, size=11, color='FFFFFF')
    header_fill = PatternFill(start_color='2563EB', end_color='2563EB', fill_type='solid')
    header_alignment = Alignment(horizontal='center', vertical='center', wrap_text=True)
    cell_alignment = Alignment(horizontal='right', vertical='center', wrap_text=True)
    number_alignment = Alignment(horizontal='center', vertical='center')
    thin_border = Border(
        left=Side(style='thin'),
        right=Side(style='thin'),
        top=Side(style='thin'),
        bottom=Side(style='thin')
    )
    bold_font = Font(name='Arial', bold=True, size=11)
    title_font = Font(name='Arial', bold=True, size=14)
    subtitle_font = Font(name='Arial', bold=True, size=11, color='555555')

    # Title row
    ws.merge_cells('A1:K1')
    title_cell = ws['A1']
    title_cell.value = 'דוח עבודה מפורט'
    title_cell.font = title_font
    title_cell.alignment = Alignment(horizontal='center', vertical='center')

    # Subtitle with user name and date range
    ws.merge_cells('A2:K2')
    subtitle_cell = ws['A2']
    user_name = reports[0].author.full_name if reports and reports[0].author else ''
    if reports:
        dates = [r.timestamp for r in reports if r.timestamp]
        if dates:
            min_date = min(dates).strftime('%d/%m/%Y')
            max_date = max(dates).strftime('%d/%m/%Y')
            subtitle_cell.value = f'עובד: {user_name} | תקופה: {min_date} - {max_date} | סה"כ דיווחים: {len(reports)}'
        else:
            subtitle_cell.value = f'עובד: {user_name} | סה"כ דיווחים: {len(reports)}'
    subtitle_cell.font = subtitle_font
    subtitle_cell.alignment = Alignment(horizontal='center', vertical='center')

    # Headers (row 4)
    headers = [
        'תאריך',
        'שעה',
        'סוג דוח',
        'שם לקוח',
        'חברת בניה/פרויקט',
        'כתובת',
        'מוצר',
        'כמות',
        'יחידת מידה',
        'סטטוס',
        'הערות'
    ]

    for col_idx, header in enumerate(headers, 1):
        cell = ws.cell(row=4, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border

    # Data rows - one row per product
    row_num = 5
    total_meter = defaultdict(float)
    total_unit = defaultdict(float)

    # Sort reports by date
    sorted_reports = sorted(reports, key=lambda r: r.timestamp or datetime.min)

    for report in sorted_reports:
        products_list = list(report.products)
        if not products_list:
            # Report with no products - still show one row
            for col_idx, val in enumerate([
                report.timestamp.strftime('%d/%m/%Y') if report.timestamp else '',
                report.timestamp.strftime('%H:%M') if report.timestamp else '',
                'אספקה' if report.report_type == 'delivery' else 'התקנה',
                report.customer_name or '',
                report.company_project or '',
                report.address or '',
                '',
                '',
                '',
                'הושלם' if report.status == 'completed' else 'נדרש חזרה',
                report.notes or ''
            ], 1):
                cell = ws.cell(row=row_num, column=col_idx, value=val)
                cell.alignment = cell_alignment if col_idx not in [8] else number_alignment
                cell.border = thin_border
            row_num += 1
        else:
            for p_idx, product in enumerate(products_list):
                unit_label = 'מטר' if product.quantity_unit == 'meter' else 'יחידה'

                # Track totals
                if product.quantity_unit == 'meter':
                    total_meter[product.product_name] += product.quantity
                else:
                    total_unit[product.product_name] += product.quantity

                row_data = [
                    report.timestamp.strftime('%d/%m/%Y') if report.timestamp else '',
                    report.timestamp.strftime('%H:%M') if report.timestamp else '',
                    'אספקה' if report.report_type == 'delivery' else 'התקנה',
                    report.customer_name or '',
                    report.company_project or '',
                    report.address or '',
                    product.product_name,
                    product.quantity,
                    unit_label,
                    'הושלם' if report.status == 'completed' else 'נדרש חזרה',
                    report.notes or '' if p_idx == 0 else ''
                ]

                for col_idx, val in enumerate(row_data, 1):
                    cell = ws.cell(row=row_num, column=col_idx, value=val)
                    cell.alignment = cell_alignment if col_idx not in [8] else number_alignment
                    cell.border = thin_border

                row_num += 1

    # ---- Summary section ----
    row_num += 1
    ws.merge_cells(start_row=row_num, start_column=1, end_row=row_num, end_column=9)
    summary_title = ws.cell(row=row_num, column=1, value='סיכום כמויות')
    summary_title.font = Font(name='Arial', bold=True, size=12)
    summary_title.alignment = Alignment(horizontal='center', vertical='center')
    summary_title.fill = PatternFill(start_color='F59E0B', end_color='F59E0B', fill_type='solid')
    summary_title.font = Font(name='Arial', bold=True, size=12, color='FFFFFF')

    row_num += 1
    # Summary headers
    for col_idx, header in enumerate(['מוצר', 'סה"כ מטר', 'סה"כ יחידות'], 1):
        cell = ws.cell(row=row_num, column=col_idx, value=header)
        cell.font = bold_font
        cell.alignment = header_alignment
        cell.border = thin_border
        cell.fill = PatternFill(start_color='FEF3C7', end_color='FEF3C7', fill_type='solid')

    row_num += 1
    all_products = set(list(total_meter.keys()) + list(total_unit.keys()))
    grand_total_meter = 0
    grand_total_unit = 0

    for product_name in sorted(all_products):
        meters = total_meter.get(product_name, 0)
        units = total_unit.get(product_name, 0)
        grand_total_meter += meters
        grand_total_unit += units

        cell_name = ws.cell(row=row_num, column=1, value=product_name)
        cell_name.alignment = cell_alignment
        cell_name.border = thin_border

        cell_meter = ws.cell(row=row_num, column=2, value=meters if meters else '')
        cell_meter.alignment = number_alignment
        cell_meter.border = thin_border

        cell_units = ws.cell(row=row_num, column=3, value=units if units else '')
        cell_units.alignment = number_alignment
        cell_units.border = thin_border

        row_num += 1

    # Grand total row
    grand_fill = PatternFill(start_color='DBEAFE', end_color='DBEAFE', fill_type='solid')
    cell_total_label = ws.cell(row=row_num, column=1, value='סה"כ כללי')
    cell_total_label.font = bold_font
    cell_total_label.alignment = cell_alignment
    cell_total_label.border = thin_border
    cell_total_label.fill = grand_fill

    cell_total_meter = ws.cell(row=row_num, column=2, value=grand_total_meter if grand_total_meter else '')
    cell_total_meter.font = bold_font
    cell_total_meter.alignment = number_alignment
    cell_total_meter.border = thin_border
    cell_total_meter.fill = grand_fill

    cell_total_unit = ws.cell(row=row_num, column=3, value=grand_total_unit if grand_total_unit else '')
    cell_total_unit.font = bold_font
    cell_total_unit.alignment = number_alignment
    cell_total_unit.border = thin_border
    cell_total_unit.fill = grand_fill

    # Column widths
    col_widths = [14, 8, 10, 18, 22, 28, 28, 10, 12, 12, 20]
    for i, width in enumerate(col_widths, 1):
        ws.column_dimensions[chr(64 + i)].width = width

    # ---- Sheet 2: Daily Summary ----
    ws2 = wb.create_sheet(title="סיכום יומי")
    ws2.sheet_view.rightToLeft = True

    ws2.merge_cells('A1:E1')
    ws2['A1'].value = 'סיכום יומי'
    ws2['A1'].font = title_font
    ws2['A1'].alignment = Alignment(horizontal='center', vertical='center')

    daily_headers = ['תאריך', 'מספר דיווחים', 'אספקה', 'התקנה', 'פירוט']
    for col_idx, header in enumerate(daily_headers, 1):
        cell = ws2.cell(row=3, column=col_idx, value=header)
        cell.font = header_font
        cell.fill = header_fill
        cell.alignment = header_alignment
        cell.border = thin_border

    # Group by date
    daily_data = defaultdict(lambda: {'count': 0, 'delivery': 0, 'installation': 0, 'details': []})
    for report in sorted_reports:
        if report.timestamp:
            date_key = report.timestamp.strftime('%d/%m/%Y')
            daily_data[date_key]['count'] += 1
            if report.report_type == 'delivery':
                daily_data[date_key]['delivery'] += 1
            else:
                daily_data[date_key]['installation'] += 1
            daily_data[date_key]['details'].append(
                f"{report.customer_name or ''} - {report.address or ''}"
            )

    row_num2 = 4
    for date_key in sorted(daily_data.keys(), key=lambda d: datetime.strptime(d, '%d/%m/%Y')):
        data = daily_data[date_key]
        details_str = ' | '.join(data['details'])

        row_data = [date_key, data['count'], data['delivery'], data['installation'], details_str]
        for col_idx, val in enumerate(row_data, 1):
            cell = ws2.cell(row=row_num2, column=col_idx, value=val)
            cell.alignment = cell_alignment if col_idx == 5 else number_alignment
            cell.border = thin_border
        row_num2 += 1

    ws2.column_dimensions['A'].width = 14
    ws2.column_dimensions['B'].width = 14
    ws2.column_dimensions['C'].width = 10
    ws2.column_dimensions['D'].width = 10
    ws2.column_dimensions['E'].width = 50

    # Save to bytes
    output = BytesIO()
    wb.save(output)
    output.seek(0)

    return send_file(
        output,
        mimetype='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
        as_attachment=True,
        download_name=f'{filename_prefix}_{datetime.now().strftime("%Y%m%d_%H%M%S")}.xlsx'
    )


@app.route('/api/export')
@login_required
def export_reports():
    """Export reports to Excel (admin only)"""
    if not current_user.is_admin():
        return jsonify({'success': False, 'error': 'אין הרשאה'}), 403

    # Get filters
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    report_type = request.args.get('type')
    user_id = request.args.get('user_id', type=int)

    query = Report.query.filter(Report.is_archived.is_(False))

    if user_id:
        query = query.filter(Report.user_id == user_id)
    if date_from:
        query = query.filter(Report.timestamp >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(Report.timestamp <= datetime.fromisoformat(date_to + 'T23:59:59'))
    if report_type:
        query = query.filter(Report.report_type == report_type)

    reports = query.order_by(Report.timestamp.desc()).all()

    return _export_reports_to_excel(reports, 'reports')


@app.route('/api/export/mine')
@login_required
def export_my_reports():
    """Export current user's reports (monthly by default)"""
    # Get filters
    date_from = request.args.get('date_from')
    date_to = request.args.get('date_to')
    report_type = request.args.get('type')

    # Default: current month if no dates provided
    if not date_from and not date_to:
        now = datetime.utcnow()
        date_from = f"{now.year}-{now.month:02d}-01"
        date_to = f"{now.year}-{now.month:02d}-{now.day:02d}"

    query = Report.query.filter_by(user_id=current_user.id, is_archived=False)

    if date_from:
        query = query.filter(Report.timestamp >= datetime.fromisoformat(date_from))
    if date_to:
        query = query.filter(Report.timestamp <= datetime.fromisoformat(date_to + 'T23:59:59'))
    if report_type:
        query = query.filter(Report.report_type == report_type)

    reports = query.order_by(Report.timestamp.desc()).all()

    return _export_reports_to_excel(reports, 'my_reports')

@app.route('/api/sync', methods=['POST'])
@login_required
def sync_offline_reports():
    """Import legacy browser drafts one at a time, preserving stock and retry safety."""
    data = request.get_json(silent=True) or {}
    offline_reports = data.get('reports', [])
    if not isinstance(offline_reports, list) or len(offline_reports) > 20:
        return jsonify({'success': False, 'error': 'רשימת דוחות לא תקינה'}), 400

    synced_count = 0
    errors = []

    for report_data in offline_reports:
        try:
            if not isinstance(report_data, dict):
                raise ValueError('דוח לא תקין')
            client_id = str(report_data.get('client_id') or '').strip()
            if not client_id or len(client_id) > 64:
                raise ValueError('מזהה דוח חסר')
            existing = Report.query.filter_by(client_id=client_id).first()
            if existing:
                if existing.user_id != current_user.id:
                    raise ValueError('מזהה דוח כבר בשימוש')
                synced_count += 1
                continue

            offline_type = report_data.get('report_type')
            address = str(report_data.get('address') or '').strip()
            customer_name = str(report_data.get('customer_name') or '').strip()
            status = report_data.get('status')
            if offline_type not in ('delivery', 'installation') or not address or not customer_name or not status:
                raise ValueError('חסרים פרטי דוח נדרשים')

            products = report_data.get('products')
            if not isinstance(products, list) or not products:
                raise ValueError('חסרים מוצרים בדוח')
            validated_products = []
            for product in products:
                if not isinstance(product, dict) or not str(product.get('name') or '').strip():
                    raise ValueError('מוצר לא תקין')
                quantity = float(product.get('quantity') or 0)
                if not math.isfinite(quantity) or quantity <= 0:
                    raise ValueError('כמות מוצר לא תקינה')
                unit = product.get('unit') or 'unit'
                if unit not in ('unit', 'meter'):
                    raise ValueError('יחידת מוצר לא תקינה')
                validated_products.append((str(product['name']).strip(), quantity, unit))

            offline_protections_raw = report_data.get('protections_count')
            try:
                offline_protections_count = int(offline_protections_raw) if offline_protections_raw is not None else None
            except (TypeError, ValueError):
                offline_protections_count = None

            offline_installation_types = report_data.get('installation_types')
            if isinstance(offline_installation_types, str):
                try:
                    offline_installation_types = json.loads(offline_installation_types)
                except json.JSONDecodeError:
                    offline_installation_types = []

            if not isinstance(offline_installation_types, list):
                offline_installation_types = []

            installation_type_display = ', '.join([str(x) for x in offline_installation_types if x])

            report_datetime_raw = report_data.get('report_datetime') or report_data.get('timestamp')
            if not report_datetime_raw:
                raise ValueError('תאריך דוח חסר')
            try:
                report_timestamp = datetime.fromisoformat(report_datetime_raw)
            except (TypeError, ValueError):
                raise ValueError('תאריך דוח לא תקין')

            report = Report(
                user_id=current_user.id,
                client_id=client_id,
                report_type=offline_type,
                customer_name=customer_name,
                company_project=report_data.get('company_project'),
                installation_type=installation_type_display if offline_type == 'installation' else None,
                installation_types=(
                    json.dumps(offline_installation_types, ensure_ascii=False)
                    if offline_type == 'installation'
                    else None
                ),
                protections_count=offline_protections_count if offline_type == 'installation' else None,
                address=address,
                status=status,
                notes=report_data.get('notes', ''),
                timestamp=report_timestamp
            )
            db.session.add(report)
            db.session.flush()

            for name, quantity, unit in validated_products:
                db.session.add(ReportProduct(
                    report_id=report.id,
                    product_name=name,
                    quantity=quantity,
                    quantity_unit=unit
                ))
                apply_inventory_change(name, -quantity, unit, 'report', report.id, current_user.id,
                                       f'Legacy offline report #{report.id}')
            db.session.commit()
            synced_count += 1
        except (TypeError, ValueError) as e:
            db.session.rollback()
            errors.append(str(e))
        except Exception:
            db.session.rollback()
            errors.append('שגיאה בשמירת דוח ישן')

    return jsonify({
        'success': not errors,
        'synced_count': synced_count,
        'errors': errors
    })

@app.route('/uploads/reports/<path:filename>')
@login_required
def uploaded_file(filename):
    """Serve only attachments belonging to a report this user may view."""
    normalized = filename.replace('\\', '/')
    report_id_text = normalized.split('/', 1)[0]
    if not report_id_text.isdecimal():
        return jsonify({'error': 'קובץ לא נמצא'}), 404

    report = Report.query.get_or_404(int(report_id_text))
    if not current_user.is_admin() and report.user_id != current_user.id:
        return jsonify({'error': 'קובץ לא נמצא'}), 404

    attachment_paths = {
        attachment.image_path.replace('\\', '/') for attachment in report.images
    }
    attachment_paths.update(
        attachment.document_path.replace('\\', '/') for attachment in report.documents
    )
    if normalized not in attachment_paths:
        return jsonify({'error': 'קובץ לא נמצא'}), 404

    response = send_from_directory(Config.UPLOAD_FOLDER, normalized)
    response.headers['Cache-Control'] = 'private, no-store'
    return response

# PWA routes
@app.route('/manifest.json')
def manifest():
    return send_from_directory('static', 'manifest.json')

@app.route('/sw.js')
def service_worker():
    response = send_from_directory('static/js', 'sw.js')
    response.headers['Service-Worker-Allowed'] = '/'
    response.headers['Content-Type'] = 'application/javascript'
    return response

# Error handlers
@app.errorhandler(404)
def not_found(e):
    if request.is_json:
        return jsonify({'error': 'לא נמצא'}), 404
    return render_template('404.html'), 404

@app.errorhandler(500)
def server_error(e):
    if request.is_json:
        return jsonify({'error': 'שגיאת שרת'}), 500
    return render_template('500.html'), 500

if __name__ == '__main__':
    init_db()
    app.run(debug=True, host='0.0.0.0', port=5000)
