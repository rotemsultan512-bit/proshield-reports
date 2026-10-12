"""Create the first administrator without storing a shared password in source code."""

from getpass import getpass

from app import app, init_db
from models import db, User


def main():
    init_db()
    with app.app_context():
        if User.query.filter_by(role='admin').first():
            raise SystemExit('An administrator already exists. Use the app to manage accounts.')

        username = input('Admin username: ').strip()
        full_name = input('Full name: ').strip()
        password = getpass('New password (12+ characters): ')
        confirmation = getpass('Confirm password: ')

        if not username or not full_name or len(password) < 12 or password != confirmation:
            raise SystemExit('Account not created: check the name and password requirements.')
        if User.query.filter_by(username=username).first():
            raise SystemExit('Account not created: username already exists.')

        admin = User(username=username, full_name=full_name, role='admin')
        admin.set_password(password)
        db.session.add(admin)
        db.session.commit()
        print('Administrator created. Remove any temporary shell access used for setup.')


if __name__ == '__main__':
    main()
