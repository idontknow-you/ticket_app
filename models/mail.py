from extensions import db
from datetime import datetime


class MailTemplate(db.Model):
    __tablename__ = "mail_templates"

    id             = db.Column(db.Integer, primary_key=True)
    form_config_id = db.Column(db.Integer, db.ForeignKey("form_configurations.id"), nullable=False, unique=True)
    updated_at     = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted     = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at     = db.Column(db.DateTime, nullable=True)

    templates      = db.Column(db.JSON, default=dict)
    reply_to       = db.Column(db.String(200), nullable=True)
    from_name      = db.Column(db.String(120), nullable=True)

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = datetime.utcnow()

    def __repr__(self):
        return f"<MailTemplate form={self.form_config_id}>"