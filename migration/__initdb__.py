"""
migration/__initdb__.py

Run standalone:   python migration/__initdb__.py
Called by app.py: init_db(app) on startup
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def init_db(app=None):
    if app is None:
        from app import create_app
        app = create_app()

    with app.app_context():
        from extensions import db
        from models import User, FormConfig, FormSubmission

        db.create_all()

        # ── Superadmin ────────────────────────────────────────────────────
        if not User.query.filter_by(username="superadmin").first():
            admin = User(
                username="superadmin",
                is_superadmin=True,
                is_active=True,
                permissions={},
                column_prefs={},
            )
            admin.set_password("superadmin123")
            db.session.add(admin)
            db.session.commit()
            print("✓ Superadmin created  →  superadmin / superadmin123")

        print("✓ Database initialised successfully.")


if __name__ == "__main__":
    init_db()