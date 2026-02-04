from flask_sqlalchemy import SQLAlchemy
from flask_login import UserMixin
from datetime import datetime
import bcrypt

db = SQLAlchemy()

class User(UserMixin, db.Model):
    __tablename__ = 'users'

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(80), unique=True, nullable=False)
    password_hash = db.Column(db.String(128), nullable=False)
    role = db.Column(db.String(20), nullable=False, default='user')  # 'admin' or 'user'
    full_name = db.Column(db.String(100), nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_active = db.Column(db.Boolean, default=True)

    # Relationship
    reports = db.relationship('Report', backref='author', lazy='dynamic')

    def set_password(self, password):
        self.password_hash = bcrypt.hashpw(password.encode('utf-8'), bcrypt.gensalt()).decode('utf-8')

    def check_password(self, password):
        return bcrypt.checkpw(password.encode('utf-8'), self.password_hash.encode('utf-8'))

    def is_admin(self):
        return self.role == 'admin'

    def __repr__(self):
        return f'<User {self.username}>'


class Report(db.Model):
    __tablename__ = 'reports'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    report_type = db.Column(db.String(20), nullable=False)  # 'delivery' or 'installation'

    # Delivery extra field (relevant when report_type == 'delivery')
    customer_name = db.Column(db.String(200))

    # Optional: Company / Project name
    company_project = db.Column(db.String(200))

    address = db.Column(db.String(500), nullable=False)
    status = db.Column(db.String(20), nullable=False)  # 'completed' or 'return_required'
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    notes = db.Column(db.Text)

    # Installation extra fields (relevant when report_type == 'installation')
    # installation_type is kept for backward compatibility / display
    installation_type = db.Column(db.String(500))
    installation_types = db.Column(db.Text)  # JSON array string
    protections_count = db.Column(db.Integer)

    synced = db.Column(db.Boolean, default=True)  # For offline support

    # Relationships
    products = db.relationship('ReportProduct', backref='report', lazy='dynamic', cascade='all, delete-orphan')
    images = db.relationship('ReportImage', backref='report', lazy='dynamic', cascade='all, delete-orphan')
    documents = db.relationship('ReportDocument', backref='report', lazy='dynamic', cascade='all, delete-orphan')

    def to_dict(self):
        return {
            'id': self.id,
            'user_id': self.user_id,
            'user_name': self.author.full_name if self.author else '',
            'report_type': self.report_type,
            'customer_name': self.customer_name,
            'company_project': self.company_project,
            'installation_type': self.installation_type,
            'installation_types': self.installation_types,
            'protections_count': self.protections_count,
            'address': self.address,
            'status': self.status,
            'timestamp': self.timestamp.isoformat() if self.timestamp else None,
            'notes': self.notes,
            'products': [p.to_dict() for p in self.products],
            'images': [i.to_dict() for i in self.images],
            'documents': [d.to_dict() for d in self.documents]
        }

    def __repr__(self):
        return f'<Report {self.id} - {self.report_type}>'


class ReportProduct(db.Model):
    __tablename__ = 'report_products'

    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('reports.id'), nullable=False)
    product_name = db.Column(db.String(200), nullable=False)
    quantity = db.Column(db.Float, nullable=False)
    quantity_unit = db.Column(db.String(20), default='unit')  # 'unit' or 'meter'

    def to_dict(self):
        return {
            'id': self.id,
            'product_name': self.product_name,
            'quantity': self.quantity,
            'quantity_unit': self.quantity_unit
        }

    def __repr__(self):
        return f'<ReportProduct {self.product_name} x {self.quantity}>'


class ReportImage(db.Model):
    __tablename__ = 'report_images'

    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('reports.id'), nullable=False)
    image_path = db.Column(db.String(500), nullable=False)
    image_type = db.Column(db.String(50))  # 'goods' or 'project'
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'image_path': self.image_path,
            'image_type': self.image_type
        }

    def __repr__(self):
        return f'<ReportImage {self.image_path}>'


class ReportDocument(db.Model):
    __tablename__ = 'report_documents'

    id = db.Column(db.Integer, primary_key=True)
    report_id = db.Column(db.Integer, db.ForeignKey('reports.id'), nullable=False)
    document_path = db.Column(db.String(500), nullable=False)
    original_filename = db.Column(db.String(255))
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'document_path': self.document_path,
            'original_filename': self.original_filename
        }

    def __repr__(self):
        return f'<ReportDocument {self.document_path}>'


class CompanyProject(db.Model):
    __tablename__ = 'company_projects'

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(200), unique=True, nullable=False)
    is_active = db.Column(db.Boolean, default=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'name': self.name,
            'is_active': self.is_active
        }

    def __repr__(self):
        return f'<CompanyProject {self.name}>'


class InventoryItem(db.Model):
    __tablename__ = 'inventory_items'

    id = db.Column(db.Integer, primary_key=True)
    product_name = db.Column(db.String(200), unique=True, nullable=False)
    quantity_unit = db.Column(db.Float, default=0)   # יחידה
    quantity_meter = db.Column(db.Float, default=0)  # מטר
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'product_name': self.product_name,
            'quantity_unit': self.quantity_unit,
            'quantity_meter': self.quantity_meter,
            'updated_at': self.updated_at.isoformat() if self.updated_at else None
        }

    def __repr__(self):
        return f'<InventoryItem {self.product_name}>'


class InventoryTransaction(db.Model):
    __tablename__ = 'inventory_transactions'

    id = db.Column(db.Integer, primary_key=True)
    product_name = db.Column(db.String(200), nullable=False)
    change_type = db.Column(db.String(50), nullable=False)  # 'report' or 'adjustment'
    quantity = db.Column(db.Float, nullable=False)
    unit = db.Column(db.String(20), nullable=False)  # 'unit' or 'meter'
    report_id = db.Column(db.Integer, db.ForeignKey('reports.id'))
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'))
    notes = db.Column(db.String(500))
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    def to_dict(self):
        return {
            'id': self.id,
            'product_name': self.product_name,
            'change_type': self.change_type,
            'quantity': self.quantity,
            'unit': self.unit,
            'report_id': self.report_id,
            'user_id': self.user_id,
            'notes': self.notes,
            'created_at': self.created_at.isoformat() if self.created_at else None
        }

    def __repr__(self):
        return f'<InventoryTransaction {self.product_name} {self.quantity} {self.unit}>'


# Product list constant
PRODUCTS = [
    "Floorliner - Vapor Shield",
    "Floorliner - Original Shield",
    "Allprotect - White Shield",
    "Allprotect - Original",
    "Allprotect - Flex",
    "Allprotect - Original cut to 20cm",
    "Allprotect - Flex cut to 10cm",
    "Allprotect - Flex cut to 15cm",
    "Allprotect - Flex cut to 17cm",
    "Allprotect - Flex cut to 20cm",
    "Allprotect - Flex cut to 25cm",
    "PP Tape",
    "סרט דבק",
    "זווית פינה קשיחה",
    "פרופיל U מוקצף 18 מ\"מ",
    "פרופיל U מוקצף 45 מ\"מ",
    "פרופיל U מוקצף 120 מ\"מ"
]
