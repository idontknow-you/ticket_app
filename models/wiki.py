from extensions import db
from datetime import datetime


class Wiki(db.Model):
    __tablename__ = "wiki"

    id             = db.Column(db.Integer, primary_key=True)
    form_config_id = db.Column(db.Integer, db.ForeignKey("form_configurations.id"), nullable=False, unique=True)
    updated_at     = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    updated_by     = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    is_deleted     = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at     = db.Column(db.DateTime, nullable=True)

    pages  = db.Column(db.JSON, default=list)
    editor = db.relationship("User", foreign_keys=[updated_by])

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = datetime.utcnow()

    def __repr__(self):
        return f"<Wiki form={self.form_config_id}>"