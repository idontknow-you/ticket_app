from extensions import db
from datetime import datetime


class FormSubmission(db.Model):
    __tablename__ = "form_submissions"

    id                     = db.Column(db.Integer, primary_key=True)
    form_config_id         = db.Column(db.Integer, db.ForeignKey("form_configurations.id"), nullable=False)
    # snapshot: which exact version was live when this ticket was submitted
    form_config_version_id = db.Column(db.Integer, db.ForeignKey("form_config_versions.id"), nullable=True)

    ticket_id              = db.Column(db.String(40), nullable=False, index=True)
    submitted_at           = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at             = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted             = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at             = db.Column(db.DateTime, nullable=True)

    status                 = db.Column(db.String(20), default="open")
    priority               = db.Column(db.String(20), default=None, nullable=True)
    assigned_to            = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    data                   = db.Column(db.JSON, default=dict)
    notes                  = db.Column(db.JSON, default=list)

    assignee = db.relationship("User", foreign_keys=[assigned_to], backref="assigned_tickets")

    # ------------------------------------------------------------------ helpers

    @property
    def version_fields(self):
        """
        The field schema that was in effect when this ticket was created.
        Falls back to the form's current fields for legacy submissions that
        pre-date versioning.
        """
        if self.form_version:
            return self.form_version.sorted_fields
        if self.form:
            return self.form.sorted_fields
        return []

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = datetime.utcnow()

    def __repr__(self):
        return f"<FormSubmission {self.ticket_id} v={self.form_config_version_id} status={self.status}>"