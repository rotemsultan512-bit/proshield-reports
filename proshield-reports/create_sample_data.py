#!/usr/bin/env python3
"""
Create sample data for testing
"""

import os
import sys
from datetime import datetime, timedelta
import random

# Add the current directory to path
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from app import app, db
from models import User, Report, ReportProduct, PRODUCTS

def create_sample_users():
    """Create sample users"""
    users_data = [
        {'username': 'david', 'password': 'david123', 'full_name': 'דוד כהן', 'role': 'user'},
        {'username': 'sarah', 'password': 'sarah123', 'full_name': 'שרה לוי', 'role': 'user'},
        {'username': 'moshe', 'password': 'moshe123', 'full_name': 'משה ישראלי', 'role': 'user'},
    ]

    created = []
    for data in users_data:
        if not User.query.filter_by(username=data['username']).first():
            user = User(
                username=data['username'],
                full_name=data['full_name'],
                role=data['role']
            )
            user.set_password(data['password'])
            db.session.add(user)
            created.append(data['username'])

    db.session.commit()
    return created

def create_sample_reports():
    """Create sample reports"""
    users = User.query.filter(User.role != 'admin').all()
    if not users:
        users = [User.query.filter_by(username='rotem').first()]

    addresses = [
        'רחוב הרצל 15, תל אביב',
        'שדרות רוטשילד 30, תל אביב',
        'רחוב בן יהודה 50, ירושלים',
        'רחוב המלך דוד 10, חיפה',
        'שדרות הנשיא 25, באר שבע',
        'רחוב ויצמן 100, רמת גן',
        'רחוב ז\'בוטינסקי 80, פתח תקווה',
        'שדרות ירושלים 45, אשדוד',
        'רחוב הגפן 5, רעננה',
        'רחוב הברוש 12, הרצליה',
    ]

    statuses = ['completed', 'return_required']
    report_types = ['delivery', 'installation']

    reports_created = 0

    for i in range(20):
        user = random.choice(users)
        report_type = random.choice(report_types)
        status = random.choices(statuses, weights=[0.8, 0.2])[0]  # 80% completed
        address = random.choice(addresses)

        # Random date in the last 30 days
        days_ago = random.randint(0, 30)
        timestamp = datetime.now() - timedelta(days=days_ago, hours=random.randint(0, 12))

        report = Report(
            user_id=user.id,
            report_type=report_type,
            address=address,
            status=status,
            timestamp=timestamp,
            notes=f'הערות לדוגמה #{i+1}' if random.random() > 0.5 else None
        )
        db.session.add(report)
        db.session.flush()

        # Add 2-5 random products
        num_products = random.randint(2, 5)
        selected_products = random.sample(PRODUCTS, num_products)

        for product_name in selected_products:
            quantity = round(random.uniform(1, 50), 1)
            product = ReportProduct(
                report_id=report.id,
                product_name=product_name,
                quantity=quantity
            )
            db.session.add(product)

        reports_created += 1

    db.session.commit()
    return reports_created

def main():
    print("=" * 50)
    print("  Creating Sample Data")
    print("=" * 50)

    with app.app_context():
        # Create users
        print("\n[*] Creating sample users...")
        users_created = create_sample_users()
        if users_created:
            print(f"[OK] Created users: {', '.join(users_created)}")
        else:
            print("[OK] Users already exist")

        # Create reports
        print("\n[*] Creating sample reports...")
        reports_created = create_sample_reports()
        print(f"[OK] Created {reports_created} sample reports")

        print("\n" + "=" * 50)
        print("  Sample data created successfully!")
        print("=" * 50)
        print("\nSample user logins:")
        print("  - david / david123")
        print("  - sarah / sarah123")
        print("  - moshe / moshe123")

if __name__ == '__main__':
    main()
