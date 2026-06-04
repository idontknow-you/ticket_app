from extensions import db
from datetime import datetime


class MailTemplate(db.Model):
    """
    Mail template config.

    scope: "global" (form_config_id=None) or "form" (form_config_id=<id>).
    The form-level record overrides global defaults for that specific form.

    Structure of `templates` JSON:
    {
      "ticket_submitted": {
        "enabled": true,
        "subject": "Your ticket {{ticket_id}} has been received",
        "body": "<p>Hi {{submitter_name}}...</p>",
        "recipients": {
          "submitter": true,
          "assigned_agent": false,
          "all_admins": false,
          "field_email_field_id": null,
          "custom": ["ops@example.com"]
        }
      },
      ...
    }
    """

    __tablename__ = "mail_templates"

    id             = db.Column(db.Integer, primary_key=True)
    scope          = db.Column(db.String(20), default="global", nullable=False)
    form_config_id = db.Column(db.Integer, db.ForeignKey("form_configurations.id"), nullable=True, unique=True)
    updated_at     = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted     = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at     = db.Column(db.DateTime, nullable=True)

    templates      = db.Column(db.JSON, default=dict)
    mail_enabled   = db.Column(db.Boolean, default=True, nullable=False)
    reply_to       = db.Column(db.String(200), nullable=True)
    from_name      = db.Column(db.String(120), nullable=True)

    form           = db.relationship("FormConfig", foreign_keys=[form_config_id])

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = datetime.utcnow()

    def get_event_cfg(self, event: str) -> dict:
        defaults = {
            "enabled": False,
            "subject": "",
            "body": "",
            "recipients": {
                "submitter": True,
                "assigned_agent": False,
                "all_admins": False,
                "field_email_field_id": None,
                "custom": [],
            },
        }
        cfg = (self.templates or {}).get(event, {})
        merged = {**defaults, **cfg}
        merged["recipients"] = {**defaults["recipients"], **cfg.get("recipients", {})}
        return merged

    def __repr__(self):
        return f"<MailTemplate scope={self.scope} form={self.form_config_id}>"
