"""
models/mail_custom.py

Stores user-created ("custom") mail templates that are not tied to a
system event.  Each record holds a name, subject, HTML body, and a JSON
list of recipients so the template can be re-sent at any time.
"""
from datetime import datetime
from extensions import db


class CustomMailTemplate(db.Model):
    __tablename__ = "custom_mail_templates"

    id         = db.Column(db.Integer, primary_key=True)
    name       = db.Column(db.String(255), nullable=False)
    subject    = db.Column(db.String(500), nullable=False, default="")
    body       = db.Column(db.Text,        nullable=False, default="")

    # JSON array: [{"email": "...", "name": "..."}, ...]
    recipients = db.Column(db.JSON, default=list, nullable=False)

    is_deleted = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at = db.Column(db.DateTime, nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow,
                           onupdate=datetime.utcnow, nullable=False)

    # ── soft delete (matches MailTemplate convention) ────────────────────────

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = datetime.utcnow()

    # ── serialiser ───────────────────────────────────────────────────────────

    def to_dict(self):
        return {
            "id":         self.id,
            "name":       self.name,
            "subject":    self.subject,
            "body":       self.body,
            "recipients": self.recipients or [],
            "updated_at": self.updated_at.strftime("%d %b %Y %H:%M") if self.updated_at else "",
        }

    def __repr__(self):
        return f"<CustomMailTemplate id={self.id} name={self.name!r}>"