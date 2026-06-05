"""
migration/__initdb__.py

Run standalone:   python migration/__initdb__.py
Called by app.py: init_db(app) on startup
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


def _add_column_if_missing(db, table, column, col_type):
    """Add a column to an existing SQLite table if it doesn't already exist."""
    try:
        rows = db.session.execute(db.text(f"PRAGMA table_info({table})")).fetchall()
        existing = [r[1] for r in rows]
        if column not in existing:
            db.session.execute(db.text(f"ALTER TABLE {table} ADD COLUMN {column} {col_type}"))
            db.session.commit()
            print(f"  ↳ added column {table}.{column}")
    except Exception as e:
        print(f"  ↳ skipped {table}.{column}: {e}")


def _backfill_submitter_fields(db, FormSubmission, FormConfigVersion, FormConfig):
    """
    Back-fill submitter_email / submitter_name on existing submissions
    that pre-date the denormalised columns.
    """
    from sqlalchemy.orm.attributes import flag_modified

    orphans = FormSubmission.query.filter(
        FormSubmission.submitter_email.is_(None)
    ).all()

    updated = 0
    for sub in orphans:
        fields = []
        if sub.form_config_version_id:
            ver = FormConfigVersion.query.get(sub.form_config_version_id)
            if ver:
                fields = ver.sorted_fields
        if not fields:
            form = FormConfig.query.get(sub.form_config_id)
            if form:
                fields = form.sorted_fields

        for field in fields:
            label_lower = field.get("label", "").lower()
            fid = field.get("id", "")
            val = sub.data.get(fid, "")
            if isinstance(val, str):
                if "email" in label_lower and not sub.submitter_email:
                    sub.submitter_email = val.strip() or None
                if any(label_lower == k for k in ("name", "full name", "your name", "full_name")) and not sub.submitter_name:
                    sub.submitter_name = val.strip() or None
        updated += 1

    if updated:
        db.session.commit()
        print(f"  ↳ back-filled submitter fields on {updated} submission(s)")


def _backfill_mail_templates(db):
    """
    Fix MailTemplate rows that were created with templates={} or with
    per-event dicts that have no subject/body/recipients.
    Imports the same default builder used by the mail route.
    """
    try:
        from models.mail import MailTemplate
        from routes.mail import _default_templates_dict, MAIL_EVENTS

        templates = MailTemplate.query.filter_by(is_deleted=False).all()
        patched = 0
        for tmpl in templates:
            existing = tmpl.templates or {}
            changed  = False
            defaults = _default_templates_dict()

            for event in MAIL_EVENTS:
                evt = existing.get(event, {})
                # Patch if subject/body/recipients are all missing
                if not evt.get("subject") and not evt.get("body") and not evt.get("recipients"):
                    existing[event] = defaults[event]
                    changed = True
                # Patch if recipients dict is missing entirely
                elif not evt.get("recipients"):
                    existing[event]["recipients"] = defaults[event]["recipients"]
                    changed = True

            if changed:
                tmpl.templates = existing
                patched += 1

        if patched:
            db.session.commit()
            print(f"  ↳ patched {patched} mail template(s) with default subjects/bodies/recipients")
    except Exception as e:
        print(f"  ↳ skipped mail template backfill: {e}")


def init_db(app=None):
    if app is None:
        from app import create_app
        app = create_app()

    with app.app_context():
        from extensions import db
        from models import User, FormConfigVersion, FormConfig, FormSubmission
        from models.report import Report
        from models.mail import MailTemplate
        from models.mail_queue import MailQueue, MailLog

        db.create_all()

        # ── Add new columns to existing DBs if not present ────────────────────
        _add_column_if_missing(db, "form_submissions", "submitter_email", "VARCHAR(200)")
        _add_column_if_missing(db, "form_submissions", "submitter_name",  "VARCHAR(200)")
        _add_column_if_missing(db, "mail_templates",   "use_global_template", "BOOLEAN DEFAULT 1")

        # ── Seed: migrate any FormConfig rows that have no version yet ────────
        # (handles first run on an existing DB that has the old `fields` column)
        _seed_versions(db, FormConfig, FormConfigVersion, FormSubmission)

        # ── Back-fill submitter_email / submitter_name ────────────────────────
        _backfill_submitter_fields(db, FormSubmission, FormConfigVersion, FormConfig)

        # ── Patch mail templates that were created with empty templates={} ────
        _backfill_mail_templates(db)

        # ── Superadmin ────────────────────────────────────────────────────────
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