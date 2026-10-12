"""Focused regression checks for account setup, CSRF, and attachment access."""

import atexit
import base64
from datetime import datetime, timedelta
from io import BytesIO
import json
import os
import re
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from PIL import Image, ImageDraw
from pypdf import PdfReader, PdfWriter


ROOT = Path(__file__).resolve().parents[1]
APP_DIR = ROOT / 'proshield-reports'
sys.path.insert(0, str(APP_DIR))
TEMP = tempfile.TemporaryDirectory()
atexit.register(TEMP.cleanup)
os.environ['DATABASE_URL'] = 'sqlite:///' + (Path(TEMP.name) / 'test.db').as_posix()
os.environ['UPLOAD_FOLDER'] = str(Path(TEMP.name) / 'uploads')
os.environ['SECRET_KEY'] = 'test-only-secret'
os.environ.pop('RENDER', None)
os.environ.pop('RENDER_SERVICE_ID', None)

from app import app  # noqa: E402
from models import db, DeliveryNote, InventoryItem, InventoryTransaction, PasswordResetToken, Report, ReportDocument, ReportImage, User  # noqa: E402


class SecurityTests(unittest.TestCase):
    @staticmethod
    def image_bytes():
        image = Image.new('RGB', (8, 8), '#d88221')
        buffer = BytesIO()
        image.save(buffer, format='PNG')
        buffer.seek(0)
        return buffer

    @staticmethod
    def signature_data(blank=False):
        image = Image.new('RGBA', (960, 320), (0, 0, 0, 0))
        if not blank:
            ImageDraw.Draw(image).line([(100, 170), (190, 120), (280, 200), (410, 110),
                                        (560, 180), (710, 125)], fill='#183d5c', width=8)
        buffer = BytesIO()
        image.save(buffer, format='PNG')
        return 'data:image/png;base64,' + base64.b64encode(buffer.getvalue()).decode('ascii')

    @classmethod
    def setUpClass(cls):
        with app.app_context():
            cls.owner = User(username='owner', full_name='Owner', role='user')
            cls.owner.set_password('owner-password')
            cls.other = User(username='other', full_name='Other', role='user')
            cls.other.set_password('other-password')
            cls.admin = User(username='admin', full_name='Admin', role='admin')
            cls.admin.set_password('admin-password')
            db.session.add_all([cls.owner, cls.other, cls.admin])
            db.session.flush()
            cls.owner_id, cls.other_id, cls.admin_id = (
                cls.owner.id, cls.other.id, cls.admin.id
            )
            report = Report(
                user_id=cls.owner_id,
                report_type='delivery',
                address='Test address',
                status='completed',
            )
            db.session.add(report)
            db.session.flush()
            cls.report_id = report.id
            relative = f'{report.id}/images/photo.jpg'
            db.session.add(ReportImage(report_id=report.id, image_path=relative))
            db.session.commit()
            file_path = Path(os.environ['UPLOAD_FOLDER']) / relative
            file_path.parent.mkdir(parents=True, exist_ok=True)
            file_path.write_bytes(b'test fixture')
            (file_path.parent / 'unlisted.jpg').write_bytes(b'private fixture')

    def client_as(self, user_id):
        client = app.test_client()
        with app.app_context():
            user = db.session.get(User, user_id)
            auth_version = user.session_version or 0
        with client.session_transaction() as session:
            session['_user_id'] = str(user_id)
            session['_fresh'] = True
            session['auth_version'] = auth_version
        return client

    def csrf_for(self, client):
        page = client.get('/dashboard').get_data(as_text=True)
        return re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)

    @classmethod
    def tearDownClass(cls):
        with app.app_context():
            db.session.remove()
            db.engine.dispose()

    def test_no_known_default_account_created(self):
        with app.app_context():
            self.assertIsNone(User.query.filter_by(username='rotem').first())

    def test_health_check_and_private_cache_header(self):
        self.assertEqual(app.test_client().get('/healthz').json['status'], 'ok')
        response = self.client_as(self.owner_id).get('/dashboard')
        self.assertEqual(response.headers['Cache-Control'], 'private, no-store')

    def test_attachment_requires_report_access_and_database_record(self):
        url = f'/uploads/reports/{self.report_id}/images/photo.jpg'
        with self.client_as(self.owner_id).get(url) as response:
            self.assertEqual(response.status_code, 200)
        with self.client_as(self.admin_id).get(url) as response:
            self.assertEqual(response.status_code, 200)
        self.assertEqual(self.client_as(self.other_id).get(url).status_code, 404)
        unlisted = f'/uploads/reports/{self.report_id}/images/unlisted.jpg'
        self.assertEqual(self.client_as(self.owner_id).get(unlisted).status_code, 404)

    def test_report_names_missing_evidence_without_broken_image(self):
        relative = f'{self.report_id}/images/photo.jpg'
        file_path = Path(os.environ['UPLOAD_FOLDER']) / relative
        original = file_path.read_bytes()
        try:
            file_path.unlink()
            page = self.client_as(self.owner_id).get(f'/report/{self.report_id}').get_data(as_text=True)
            self.assertIn('תמונה מקורית אחת חסרה בשרת', page)
            self.assertNotIn(f'<img src="/uploads/reports/{relative}"', page)
        finally:
            file_path.write_bytes(original)

    def test_only_admin_can_download_complete_upload_backup(self):
        self.assertEqual(self.client_as(self.owner_id).get('/api/admin/uploads-backup').status_code, 403)
        self.assertNotIn('הורד גיבוי קבצים', self.client_as(self.owner_id).get('/settings').get_data(as_text=True))
        self.assertIn('הורד גיבוי קבצים', self.client_as(self.admin_id).get('/settings').get_data(as_text=True))
        with self.client_as(self.admin_id).get('/api/admin/uploads-backup') as response:
            self.assertEqual(response.status_code, 200)
            self.assertIn('attachment', response.headers['Content-Disposition'])
            with zipfile.ZipFile(BytesIO(response.data)) as archive:
                paths = archive.namelist()
                self.assertIn(f'{self.report_id}/images/photo.jpg', paths)
                self.assertIn('backup-info.json', paths)
                self.assertGreaterEqual(json.loads(archive.read('backup-info.json'))['file_count'], 1)

    def test_login_requires_csrf_token(self):
        client = app.test_client()
        payload = {'username': 'owner', 'password': 'owner-password'}
        self.assertEqual(client.post('/login', json=payload).status_code, 400)
        page = client.get('/login').get_data(as_text=True)
        token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
        response = client.post('/login', json=payload, headers={'X-CSRFToken': token})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['success'])

    def test_repeated_bad_passwords_pause_only_that_visitor_and_account(self):
        client = app.test_client()
        page = client.get('/login').get_data(as_text=True)
        token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
        headers = {'X-CSRFToken': token}
        first_ip = {'REMOTE_ADDR': '203.0.113.10'}
        for _ in range(12):
            response = client.post('/login', json={'username': 'owner', 'password': 'wrong'},
                                   headers=headers, environ_overrides=first_ip)
            self.assertEqual(response.status_code, 401)
        blocked = client.post('/login', json={'username': 'owner', 'password': 'owner-password'},
                              headers=headers, environ_overrides=first_ip)
        self.assertEqual(blocked.status_code, 429)
        self.assertIn('Retry-After', blocked.headers)
        allowed = client.post('/login', json={'username': 'owner', 'password': 'owner-password'},
                              headers=headers, environ_overrides={'REMOTE_ADDR': '203.0.113.11'})
        self.assertEqual(allowed.status_code, 200)
        self.assertTrue(allowed.json['success'])

    def test_login_handles_malformed_json_without_server_error(self):
        client = app.test_client()
        page = client.get('/login').get_data(as_text=True)
        token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
        headers = {'X-CSRFToken': token}
        for payload in ([], {'username': ['owner'], 'password': 'bad'},
                        {'username': 'owner', 'password': None}):
            response = client.post('/login', json=payload, headers=headers)
            self.assertEqual(response.status_code, 400)

    def test_employee_recovery_code_is_one_use_and_revokes_old_sessions(self):
        with app.app_context():
            worker = User(username='recovery-worker', full_name='Recovery Worker', role='user')
            worker.set_password('old-pass-8')
            db.session.add(worker)
            db.session.commit()
            worker_id = worker.id

        admin = self.client_as(self.admin_id)
        admin_headers = {'X-CSRFToken': self.csrf_for(admin)}
        worker_client = self.client_as(worker_id)
        worker_headers = {'X-CSRFToken': self.csrf_for(worker_client)}
        issue_url = f'/api/users/{worker_id}/password-reset'
        self.assertEqual(worker_client.post(issue_url, json={'admin_password': 'admin-password'},
                                            headers=worker_headers).status_code, 403)
        self.assertEqual(admin.post(issue_url, json={'admin_password': 'wrong'},
                                    headers=admin_headers).status_code, 403)
        issued = admin.post(issue_url, json={'admin_password': 'admin-password'},
                            headers=admin_headers)
        self.assertEqual(issued.status_code, 200)
        code = issued.json['code']
        with app.app_context():
            token = PasswordResetToken.query.filter_by(user_id=worker_id).one()
            self.assertNotEqual(token.token_hash, code)
            self.assertGreater(token.expires_at, datetime.utcnow())

        anonymous = app.test_client()
        token = re.search(r'name="csrf-token" content="([^"]+)"',
                          anonymous.get('/reset-password').get_data(as_text=True)).group(1)
        headers = {'X-CSRFToken': token}
        payload = {'username': 'recovery-worker', 'code': code, 'new_password': 'new-pass'}
        self.assertEqual(anonymous.post('/api/password-reset', json=payload).status_code, 400)
        self.assertEqual(anonymous.post('/api/password-reset', json={**payload, 'code': 'bad-code'},
                                        headers=headers).status_code, 400)
        self.assertEqual(anonymous.post('/api/password-reset', json={**payload, 'new_password': '1234567'},
                                        headers=headers).status_code, 400)
        self.assertEqual(anonymous.post('/api/password-reset', json=payload, headers=headers).status_code, 200)
        self.assertEqual(anonymous.post('/api/password-reset', json=payload, headers=headers).status_code, 400)
        self.assertEqual(worker_client.get('/settings').status_code, 302)

        new_login = app.test_client()
        login_token = re.search(r'name="csrf-token" content="([^"]+)"',
                                new_login.get('/login').get_data(as_text=True)).group(1)
        new_headers = {'X-CSRFToken': login_token}
        self.assertEqual(new_login.post('/login', json={'username': 'recovery-worker',
                                                       'password': 'old-pass-8'}, headers=new_headers).status_code, 401)
        self.assertEqual(new_login.post('/login', json={'username': 'recovery-worker',
                                                       'password': 'new-pass'}, headers=new_headers).status_code, 200)

    def test_recovery_code_replacement_expiry_and_eight_character_policy(self):
        admin = self.client_as(self.admin_id)
        headers = {'X-CSRFToken': self.csrf_for(admin)}
        too_short = admin.post('/api/users', json={
            'username': 'eight-char-worker', 'full_name': 'Eight Char Worker',
            'password': '1234567', 'role': 'user'
        }, headers=headers)
        self.assertEqual(too_short.status_code, 400)
        created = admin.post('/api/users', json={
            'username': 'eight-char-worker', 'full_name': 'Eight Char Worker',
            'password': '12345678', 'role': 'user'
        }, headers=headers)
        self.assertEqual(created.status_code, 200)
        with app.app_context():
            worker_id = User.query.filter_by(username='eight-char-worker').one().id

        issue_url = f'/api/users/{worker_id}/password-reset'
        first = admin.post(issue_url, json={'admin_password': 'admin-password'}, headers=headers).json['code']
        second = admin.post(issue_url, json={'admin_password': 'admin-password'}, headers=headers).json['code']
        anon = app.test_client()
        token = re.search(r'name="csrf-token" content="([^"]+)"',
                          anon.get('/reset-password').get_data(as_text=True)).group(1)
        reset_headers = {'X-CSRFToken': token}
        self.assertEqual(anon.post('/api/password-reset', json={
            'username': 'eight-char-worker', 'code': first, 'new_password': 'new-pass'
        }, headers=reset_headers).status_code, 400)
        with app.app_context():
            stored = PasswordResetToken.query.filter_by(user_id=worker_id).one()
            stored.expires_at = datetime.utcnow() - timedelta(seconds=1)
            db.session.commit()
        self.assertEqual(anon.post('/api/password-reset', json={
            'username': 'eight-char-worker', 'code': second, 'new_password': 'new-pass'
        }, headers=reset_headers).status_code, 400)

        worker = self.client_as(worker_id)
        change_headers = {'X-CSRFToken': self.csrf_for(worker)}
        changed = worker.post('/api/user/password', json={
            'current_password': '12345678', 'new_password': 'abcdefgh'
        }, headers=change_headers)
        self.assertEqual(changed.status_code, 200)
        self.assertEqual(worker.get('/settings').status_code, 200)

    def test_assigned_delivery_note_signature_and_report_attachment(self):
        admin = self.client_as(self.admin_id)
        admin_headers = {'X-CSRFToken': self.csrf_for(admin)}
        created = admin.post('/delivery-notes', data={
            'employee_id': str(self.owner_id), 'customer_name': 'Delivery Customer',
            'address': 'Delivery Street 5', 'document': (self.image_bytes(), 'note.png'),
        }, headers=admin_headers)
        self.assertEqual(created.status_code, 302)
        with app.app_context():
            note_id = DeliveryNote.query.filter_by(customer_name='Delivery Customer').one().id
        original_url = f'/delivery-notes/{note_id}/file/original'
        signed_url = f'/delivery-notes/{note_id}/file/signed'

        owner = self.client_as(self.owner_id)
        owner_headers = {'X-CSRFToken': self.csrf_for(owner)}
        other = self.client_as(self.other_id)
        self.assertEqual(other.get(f'/delivery-notes/{note_id}').status_code, 404)
        self.assertEqual(other.get(original_url).status_code, 404)
        self.assertEqual(other.post(f'/api/delivery-notes/{note_id}/sign', json={
            'recipient_name': 'Wrong signer', 'signature': self.signature_data(), 'acknowledged': True
        }, headers={'X-CSRFToken': self.csrf_for(other)}).status_code, 403)
        with owner.get(original_url) as original:
            self.assertEqual(original.status_code, 200)
        self.assertEqual(owner.get(signed_url).status_code, 404)
        self.assertEqual(owner.post(f'/api/delivery-notes/{note_id}/sign', json={
            'recipient_name': 'Recipient Name', 'signature': self.signature_data(blank=True), 'acknowledged': True
        }, headers=owner_headers).status_code, 400)

        signed = owner.post(f'/api/delivery-notes/{note_id}/sign', json={
            'recipient_name': 'Recipient Name', 'signature': self.signature_data(), 'acknowledged': True
        }, headers=owner_headers)
        self.assertEqual(signed.status_code, 200, signed.json)
        self.assertEqual(owner.post(f'/api/delivery-notes/{note_id}/sign', json={
            'recipient_name': 'Recipient Name', 'signature': self.signature_data(), 'acknowledged': True
        }, headers=owner_headers).status_code, 409)
        self.assertEqual(admin.delete(f'/api/delivery-notes/{note_id}', headers=admin_headers).status_code, 409)
        with owner.get(signed_url) as pdf:
            self.assertEqual(pdf.status_code, 200)
            self.assertEqual(len(PdfReader(BytesIO(pdf.data)).pages), 2)
        self.assertEqual(other.get(signed_url).status_code, 404)

        report_form = {
            'client_id': 'signed-delivery-test', 'report_type': 'delivery',
            'customer_name': 'Delivery Customer', 'address': 'Delivery Street 5',
            'report_datetime': '2026-10-13T09:00', 'status': 'completed',
            'products': json.dumps([{'name': 'Delivery test product', 'quantity': 2, 'unit': 'unit'}]),
            'delivery_note_id': str(note_id),
        }
        self.assertEqual(owner.post('/api/reports', data={**report_form, 'address': 'Wrong address'},
                                    headers=owner_headers).status_code, 400)
        report = owner.post('/api/reports', data=report_form, headers=owner_headers)
        self.assertEqual(report.status_code, 200, report.json)
        report_id = report.json['report_id']
        data = owner.get(f'/api/reports/{report_id}').json
        self.assertEqual(data['recipient_name'], 'Recipient Name')
        self.assertEqual(len(data['documents']), 1)
        with app.app_context():
            self.assertEqual(db.session.get(DeliveryNote, note_id).report_id, report_id)
        copied_url = '/uploads/reports/' + data['documents'][0]['document_path'].replace('\\', '/')
        with owner.get(copied_url) as copied:
            self.assertEqual(copied.status_code, 200)
        self.assertEqual(other.get(copied_url).status_code, 404)

    def test_delivery_note_library_combines_sources_without_duplicate_and_restricts_classification(self):
        with app.app_context():
            report = Report(user_id=self.owner_id, report_type='delivery', customer_name='Library Contractor',
                            company_project='Library Builder', address='Library Street 4', status='completed')
            db.session.add(report)
            db.session.flush()
            note = DeliveryNote(employee_id=self.owner_id, created_by_id=self.admin_id,
                                customer_name='Library Contractor', company_project='Library Builder',
                                address='Library Street 4', original_filename='library-original.png',
                                original_path='library/original.png', signed_path='library/signed.pdf',
                                signed_at=datetime.utcnow(), report_id=report.id)
            db.session.add(note)
            db.session.flush()
            copied_name = f'delivery-note-{note.id}-signed.pdf'
            db.session.add_all([
                ReportDocument(report_id=report.id, document_path='library/copied.pdf',
                               original_filename=copied_name),
                ReportDocument(report_id=report.id, document_path='library/camera.png',
                               original_filename='camera-scan.png'),
            ])
            db.session.commit()
            note_id, report_id = note.id, report.id
            library_files = Path(os.environ['UPLOAD_FOLDER']) / 'library'
            library_files.mkdir(parents=True, exist_ok=True)
            for name in ('original.png', 'signed.pdf', 'copied.pdf', 'camera.png'):
                (library_files / name).write_bytes(b'fixture')

        admin = self.client_as(self.admin_id)
        page = admin.get('/delivery-notes/library?company=Library+Builder')
        self.assertEqual(page.status_code, 200, page.data[:1000])
        html = page.get_data(as_text=True)
        self.assertIn('library-original.png', html)
        self.assertIn('camera-scan.png', html)
        self.assertNotIn(copied_name, html)
        self.assertIn('Library Contractor', html)
        self.assertIn('חתומה', html)
        self.assertEqual(admin.get('/delivery-notes/library?company=No+Match').status_code, 200)
        self.assertNotIn('library-original.png', admin.get('/delivery-notes/library?company=No+Match').get_data(as_text=True))
        self.assertNotIn('library-original.png', admin.get('/delivery-notes/library?company=__unassigned__').get_data(as_text=True))

        owner = self.client_as(self.owner_id)
        self.assertEqual(owner.get('/delivery-notes/library').status_code, 403)
        self.assertEqual(owner.post('/delivery-notes/library/classify', data={
            'kind': 'assigned', 'record_id': note_id, 'company_project': 'Other Builder'
        }, headers={'X-CSRFToken': self.csrf_for(owner)}).status_code, 403)
        changed = admin.post('/delivery-notes/library/classify', data={
            'kind': 'assigned', 'record_id': note_id, 'company_project': 'Updated Builder'
        }, headers={'X-CSRFToken': self.csrf_for(admin)})
        self.assertEqual(changed.status_code, 302)
        with app.app_context():
            self.assertEqual(db.session.get(DeliveryNote, note_id).company_project, 'Updated Builder')
            self.assertEqual(db.session.get(Report, report_id).company_project, 'Updated Builder')

    def test_delivery_note_assignment_rejects_invalid_file_and_can_cancel_pending(self):
        admin = self.client_as(self.admin_id)
        headers = {'X-CSRFToken': self.csrf_for(admin)}
        self.assertEqual(admin.post('/delivery-notes', data={
            'employee_id': str(self.owner_id), 'customer_name': 'Bad note',
            'address': 'Address', 'document': (BytesIO(b'not-a-pdf'), 'note.pdf')
        }, headers=headers).status_code, 302)
        with app.app_context():
            self.assertIsNone(DeliveryNote.query.filter_by(customer_name='Bad note').first())

        writer = PdfWriter()
        writer.add_blank_page(width=400, height=500)
        document = BytesIO()
        writer.write(document)
        document.seek(0)
        created = admin.post('/delivery-notes', data={
            'employee_id': str(self.owner_id), 'customer_name': 'Pending note',
            'address': 'Address', 'document': (document, 'note.pdf')
        }, headers=headers)
        self.assertEqual(created.status_code, 302)
        with app.app_context():
            note_id = DeliveryNote.query.filter_by(customer_name='Pending note').one().id
        owner = self.client_as(self.owner_id)
        with owner.get(f'/delivery-notes/{note_id}/preview') as preview:
            self.assertEqual(preview.status_code, 200)
            self.assertEqual(preview.mimetype, 'image/png')
        self.assertEqual(self.client_as(self.other_id).get(f'/delivery-notes/{note_id}/preview').status_code, 404)
        self.assertEqual(admin.delete(f'/api/delivery-notes/{note_id}', headers=headers).status_code, 200)
        self.assertEqual(owner.get(f'/delivery-notes/{note_id}').status_code, 404)

    def test_signed_delivery_note_can_be_added_to_an_existing_report_once(self):
        owner = self.client_as(self.owner_id)
        owner_headers = {'X-CSRFToken': self.csrf_for(owner)}
        form = {
            'client_id': 'edit-signed-delivery-test', 'report_type': 'delivery',
            'customer_name': 'Edit Note Customer', 'address': 'Edit Note Address',
            'report_datetime': '2026-10-13T10:00', 'status': 'completed',
            'products': json.dumps([{'name': 'Edit note product', 'quantity': 1, 'unit': 'unit'}]),
        }
        report_id = owner.post('/api/reports', data=form, headers=owner_headers).json['report_id']
        admin = self.client_as(self.admin_id)
        created = admin.post('/delivery-notes', data={
            'employee_id': str(self.owner_id), 'customer_name': 'Edit Note Customer',
            'address': 'Edit Note Address', 'document': (self.image_bytes(), 'edit-note.png'),
        }, headers={'X-CSRFToken': self.csrf_for(admin)})
        self.assertEqual(created.status_code, 302)
        with app.app_context():
            note_id = DeliveryNote.query.filter_by(customer_name='Edit Note Customer').one().id
        signed = owner.post(f'/api/delivery-notes/{note_id}/sign', json={
            'recipient_name': 'Edit Recipient', 'signature': self.signature_data(),
            'acknowledged': True,
        }, headers=owner_headers)
        self.assertEqual(signed.status_code, 200, signed.json)
        for _ in range(2):
            updated = owner.put(f'/api/reports/{report_id}', data={
                **form, 'delivery_note_id': str(note_id)
            }, headers=owner_headers)
            self.assertEqual(updated.status_code, 200, updated.json)
        data = owner.get(f'/api/reports/{report_id}').json
        self.assertEqual(data['recipient_name'], 'Edit Recipient')
        self.assertEqual(len(data['documents']), 1)

    def test_custom_inventory_item_is_visible(self):
        with app.app_context():
            db.session.add(InventoryItem(product_name='Custom field product'))
            db.session.commit()
        response = self.client_as(self.admin_id).get('/api/inventory')
        self.assertEqual(response.status_code, 200)
        names = {item['product_name'] for item in response.json['items']}
        self.assertIn('Custom field product', names)

    def test_offline_retry_creates_one_report_and_one_stock_change(self):
        client = self.client_as(self.owner_id)
        headers = {'X-CSRFToken': self.csrf_for(client)}
        form = {
            'client_id': 'offline-test-001',
            'report_type': 'delivery',
            'customer_name': 'Test Customer',
            'report_datetime': '2026-10-12T12:00',
            'address': 'Test address',
            'status': 'completed',
            'products': json.dumps([{'name': 'Offline test product', 'quantity': 3, 'unit': 'unit'}]),
        }
        first = client.post('/api/reports', data=form, headers=headers)
        second = client.post('/api/reports', data=form, headers=headers)
        self.assertEqual(first.status_code, 200)
        self.assertEqual(second.status_code, 200)
        self.assertEqual(first.json['report_id'], second.json['report_id'])
        self.assertTrue(second.json['already_saved'])
        with app.app_context():
            self.assertEqual(Report.query.filter_by(client_id='offline-test-001').count(), 1)
            item = InventoryItem.query.filter_by(product_name='Offline test product').one()
            self.assertEqual(item.quantity_unit, -3)
            self.assertEqual(InventoryTransaction.query.filter_by(report_id=first.json['report_id']).count(), 1)

    def test_archive_and_restore_keep_report_files_and_stock_history(self):
        client = self.client_as(self.owner_id)
        headers = {'X-CSRFToken': self.csrf_for(client)}
        form = {
            'client_id': 'archive-test-001',
            'report_type': 'delivery',
            'customer_name': 'Archive Customer',
            'report_datetime': '2026-10-12T13:00',
            'address': 'Archive address',
            'status': 'completed',
            'products': json.dumps([{'name': 'Archive test product', 'quantity': 4, 'unit': 'unit'}]),
        }
        created = client.post('/api/reports', data=form, headers=headers)
        self.assertEqual(created.status_code, 200)
        report_id = created.json['report_id']
        with app.app_context():
            report = db.session.get(Report, report_id)
            relative = f'{report_id}/images/retained.jpg'
            db.session.add(ReportImage(report_id=report_id, image_path=relative))
            db.session.commit()
            path = Path(os.environ['UPLOAD_FOLDER']) / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(b'retained file')

        other = self.client_as(self.other_id)
        other_headers = {'X-CSRFToken': self.csrf_for(other)}
        self.assertEqual(other.delete(f'/api/reports/{report_id}', headers=other_headers).status_code, 403)
        archived = client.delete(f'/api/reports/{report_id}', headers=headers)
        self.assertEqual(archived.status_code, 200)
        self.assertTrue(archived.json['success'])
        self.assertEqual(client.delete(f'/api/reports/{report_id}', headers=headers).json['already_archived'], True)
        self.assertEqual(client.get('/api/reports?search=Archive%20address').json['total'], 0)
        self.assertEqual(client.get('/api/reports?archived=1&search=Archive%20address').json['total'], 1)
        with client.get(f'/uploads/reports/{relative}') as file_response:
            self.assertEqual(file_response.status_code, 200)
        with app.app_context():
            self.assertEqual(db.session.get(Report, report_id).is_archived, True)
            self.assertEqual(InventoryItem.query.filter_by(product_name='Archive test product').one().quantity_unit, 0)
            self.assertEqual(InventoryTransaction.query.filter_by(report_id=report_id).count(), 2)

        restored = client.post(f'/api/reports/{report_id}/restore', headers=headers)
        self.assertEqual(restored.status_code, 200)
        self.assertTrue(restored.json['success'])
        self.assertEqual(client.post(f'/api/reports/{report_id}/restore', headers=headers).json['already_restored'], True)
        with app.app_context():
            self.assertEqual(db.session.get(Report, report_id).is_archived, False)
            self.assertEqual(InventoryItem.query.filter_by(product_name='Archive test product').one().quantity_unit, -4)
            self.assertEqual(InventoryTransaction.query.filter_by(report_id=report_id).count(), 3)

    def test_report_edit_adds_valid_evidence_and_updates_stock(self):
        client = self.client_as(self.owner_id)
        headers = {'X-CSRFToken': self.csrf_for(client)}
        form = {
            'client_id': 'edit-evidence-test',
            'report_type': 'delivery',
            'customer_name': 'Evidence Customer',
            'report_datetime': '2026-10-12T14:00',
            'address': 'Evidence address',
            'status': 'completed',
            'products': json.dumps([{'name': 'Evidence test product', 'quantity': 1, 'unit': 'unit'}]),
        }
        created = client.post('/api/reports', data=form, headers=headers)
        self.assertEqual(created.status_code, 200)
        report_id = created.json['report_id']

        edited = client.put(f'/api/reports/{report_id}', data={
            **form,
            'products': json.dumps([{'name': 'Evidence test product', 'quantity': 2, 'unit': 'unit'}]),
            'images': (self.image_bytes(), 'field.png'),
            'delivery_note': (BytesIO(b'%PDF-1.4\n%%EOF\n'), 'signed.pdf'),
        }, headers=headers)
        self.assertEqual(edited.status_code, 200)
        data = client.get(f'/api/reports/{report_id}').json
        self.assertEqual(len(data['images']), 1)
        self.assertEqual(len(data['documents']), 1)
        with app.app_context():
            self.assertEqual(InventoryItem.query.filter_by(product_name='Evidence test product').one().quantity_unit, -2)
        for path in (data['images'][0]['image_path'], data['documents'][0]['document_path']):
            with client.get('/uploads/reports/' + path.replace('\\', '/')) as file_response:
                self.assertEqual(file_response.status_code, 200)

    def test_installation_report_keeps_team_and_restricts_evidence(self):
        owner = self.client_as(self.owner_id)
        headers = {'X-CSRFToken': self.csrf_for(owner)}
        created = owner.post('/api/reports', data={
            'client_id': 'installation-flow-test',
            'report_type': 'installation',
            'customer_name': 'Installation Customer',
            'report_datetime': '2026-10-12T15:00',
            'address': 'Installation address',
            'status': 'return_required',
            'installation_types': json.dumps(['הגנת מדרגות']),
            'installation_team': 'with_worker',
            'additional_worker_name': 'Test colleague',
            'products': json.dumps([{'name': 'Installation test product', 'quantity': 3, 'unit': 'meter'}]),
            'images': (self.image_bytes(), 'worksite.png'),
        }, headers=headers)
        self.assertEqual(created.status_code, 200)
        report_id = created.json['report_id']
        data = owner.get(f'/api/reports/{report_id}').json
        self.assertEqual(data['installation_team'], 'with_worker')
        self.assertEqual(data['additional_worker_name'], 'Test colleague')
        self.assertEqual(json.loads(data['installation_types']), ['הגנת מדרגות'])
        self.assertEqual(len(data['images']), 1)

        other = self.client_as(self.other_id)
        self.assertEqual(other.get(f'/api/reports/{report_id}').status_code, 403)
        image_url = '/uploads/reports/' + data['images'][0]['image_path'].replace('\\', '/')
        self.assertEqual(other.get(image_url).status_code, 404)
        with owner.get(image_url) as image_response:
            self.assertEqual(image_response.status_code, 200)
        with app.app_context():
            self.assertEqual(InventoryItem.query.filter_by(product_name='Installation test product').one().quantity_meter, -3)

    def test_report_rejects_invalid_type_and_status(self):
        client = self.client_as(self.owner_id)
        headers = {'X-CSRFToken': self.csrf_for(client)}
        form = {
            'report_type': 'delivery',
            'customer_name': 'Validation Customer',
            'report_datetime': '2026-10-12T15:00',
            'address': 'Test address',
            'status': 'completed',
            'products': json.dumps([{'name': 'Validation test product', 'quantity': 1, 'unit': 'unit'}]),
        }
        for field, invalid_value in (('report_type', 'unknown'), ('status', 'unknown')):
            invalid_form = dict(form, **{field: invalid_value})
            self.assertEqual(client.post('/api/reports', data=invalid_form, headers=headers).status_code, 400)
        with app.app_context():
            self.assertEqual(Report.query.filter_by(customer_name='Validation Customer').count(), 0)
            self.assertEqual(InventoryItem.query.filter_by(product_name='Validation test product').count(), 0)

    def test_legacy_offline_sync_preserves_stock_and_retry_safety(self):
        client = self.client_as(self.owner_id)
        headers = {'X-CSRFToken': self.csrf_for(client)}
        payload = {'reports': [{
            'client_id': 'legacy-test-001',
            'report_type': 'installation',
            'customer_name': 'Legacy Customer',
            'report_datetime': '2026-10-12T11:00',
            'installation_types': ['window'],
            'address': 'Legacy address',
            'status': 'completed',
            'products': [{'name': 'Legacy test product', 'quantity': 2, 'unit': 'meter'}],
        }]}
        first = client.post('/api/sync', json=payload, headers=headers)
        second = client.post('/api/sync', json=payload, headers=headers)
        self.assertEqual(first.json['synced_count'], 1)
        self.assertEqual(second.json['synced_count'], 1)
        with app.app_context():
            self.assertEqual(Report.query.filter_by(client_id='legacy-test-001').count(), 1)
            item = InventoryItem.query.filter_by(product_name='Legacy test product').one()
            self.assertEqual(item.quantity_meter, -2)

    def test_rejects_invalid_product_and_fake_image_without_creating_report(self):
        client = self.client_as(self.owner_id)
        headers = {'X-CSRFToken': self.csrf_for(client)}
        form = {
            'client_id': 'invalid-upload-test',
            'report_type': 'delivery',
            'customer_name': 'Test Customer',
            'report_datetime': '2026-10-12T12:00',
            'address': 'Test address',
            'status': 'completed',
            'products': json.dumps([{'name': 'Invalid test product', 'quantity': -2, 'unit': 'unit'}]),
        }
        self.assertEqual(client.post('/api/reports', data=form, headers=headers).status_code, 400)
        form['products'] = json.dumps([{'name': 'Invalid test product', 'quantity': 2, 'unit': 'unit'}])
        form['images'] = (BytesIO(b'not an image'), 'fake.jpg')
        self.assertEqual(client.post('/api/reports', data=form, headers=headers).status_code, 400)
        with app.app_context():
            self.assertIsNone(Report.query.filter_by(client_id='invalid-upload-test').first())


if __name__ == '__main__':
    unittest.main()
