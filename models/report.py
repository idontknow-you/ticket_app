from extensions import db
from datetime import datetime


class Report(db.Model):
    __tablename__ = "reports"

    id             = db.Column(db.Integer, primary_key=True)
    form_config_id = db.Column(db.Integer, db.ForeignKey("form_configurations.id"), nullable=False)
    title          = db.Column(db.String(200), nullable=False)
    created_by     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)
    is_deleted     = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at     = db.Column(db.DateTime, nullable=True)

    config  = db.Column(db.JSON, default=dict)
    creator = db.relationship("User", foreign_keys=[created_by])

    form = db.relationship("FormConfig", foreign_keys=[form_config_id])
    is_permanently_deleted = db.Column(db.Boolean, default=False, nullable=False)
    permanently_deleted_at = db.Column(db.DateTime, nullable=True)

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = datetime.utcnow()

    def permanent_delete(self):          # ← new
        self.is_permanently_deleted = True
        self.permanently_deleted_at = datetime.utcnow()


    def __repr__(self):
        return f"<Report {self.title!r} form={self.form_config_id}>"