"""Focused regression checks for account setup, CSRF, and attachment access."""

import atexit
from io import BytesIO
import json
import os
import re
import sys
import tempfile
import unittest
from pathlib import Path


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
from models import db, InventoryItem, InventoryTransaction, Report, ReportImage, User  # noqa: E402


class SecurityTests(unittest.TestCase):
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
        with client.session_transaction() as session:
            session['_user_id'] = str(user_id)
            session['_fresh'] = True
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

    def test_login_requires_csrf_token(self):
        client = app.test_client()
        payload = {'username': 'owner', 'password': 'owner-password'}
        self.assertEqual(client.post('/login', json=payload).status_code, 400)
        page = client.get('/login').get_data(as_text=True)
        token = re.search(r'name="csrf-token" content="([^"]+)"', page).group(1)
        response = client.post('/login', json=payload, headers={'X-CSRFToken': token})
        self.assertEqual(response.status_code, 200)
        self.assertTrue(response.json['success'])

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
