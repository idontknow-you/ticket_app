from extensions import db
from datetime import datetime


class FormConfigVersion(db.Model):
    __tablename__ = "form_config_versions"

    id             = db.Column(db.Integer, primary_key=True)
    form_config_id = db.Column(db.Integer, db.ForeignKey("form_configurations.id"), nullable=False)
    version        = db.Column(db.Integer, nullable=False)
    fields         = db.Column(db.JSON, default=list)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    created_by     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    submissions    = db.relationship("FormSubmission", backref="form_version", lazy="dynamic")

    __table_args__ = (
        db.UniqueConstraint("form_config_id", "version", name="uq_form_version"),
    )

    @property
    def sorted_fields(self):
        return sorted(self.fields or [], key=lambda f: f.get("order", 0))

    def __repr__(self):
        return f"<FormConfigVersion form={self.form_config_id} v={self.version}>"