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
        from models import User, FormConfigVersion, FormConfig, FormSubmission
        from models.mail import MailTemplate
        from models.mail_queue import MailQueue, MailLog

        db.create_all()

        # ── Seed: migrate any FormConfig rows that have no version yet ────────
        # (handles first run on an existing DB that has the old `fields` column)
        _seed_versions(db, FormConfig, FormConfigVersion, FormSubmission)

        # ── Superadmin ────────────────────────────────────────────────────────
        if not User.query.filter_by(username="superadmin").first():
            admin = User(
                username="superadmin",
                email="idkwhyihv123@gmail.com",
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


def _seed_versions(db, FormConfig, FormConfigVersion, FormSubmission):
    """
    One-time migration for existing databases:
    - For every FormConfig that has no FormConfigVersion rows yet, create v1
      using whatever `fields` data is available on the config row.
    - For every FormSubmission with no form_config_version_id, point it at
      v1 of its parent form.
    """
    forms_without_versions = (
        FormConfig.query
        .filter(
            ~FormConfig.id.in_(
                db.session.query(FormConfigVersion.form_config_id).distinct()
            )
        )
        .all()
    )

    for form in forms_without_versions:
        # Try to read fields from the legacy column if it still exists on the row
        raw_fields = []
        try:
            # Access the raw column if still present (old schema)
            raw_fields = db.session.execute(
                db.text("SELECT fields FROM form_configurations WHERE id = :id"),
                {"id": form.id},
            ).scalar() or []
            if isinstance(raw_fields, str):
                import json
                raw_fields = json.loads(raw_fields)
        except Exception:
            pass

        ver = FormConfigVersion(
            form_config_id=form.id,
            version=1,
            fields=raw_fields,
        )
        db.session.add(ver)
        db.session.flush()
        form.current_version_id = ver.id
        print(f"  ↳ seeded version 1 for form '{form.name}' (id={form.id})")

    if forms_without_versions:
        db.session.commit()

    # Back-fill submissions that have no version pinned
    orphan_subs = FormSubmission.query.filter(
        FormSubmission.form_config_version_id.is_(None)
    ).all()

    for sub in orphan_subs:
        v1 = FormConfigVersion.query.filter_by(
            form_config_id=sub.form_config_id, version=1
        ).first()
        if v1:
            sub.form_config_version_id = v1.id

    if orphan_subs:
        db.session.commit()
        print(f"  ↳ back-filled version FK on {len(orphan_subs)} existing submission(s)")


if __name__ == "__main__":
    init_db()