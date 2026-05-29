from extensions import db
from datetime import datetime


class FormConfig(db.Model):
    __tablename__ = "form_configurations"

    id           = db.Column(db.Integer, primary_key=True)
    name         = db.Column(db.String(120), nullable=False)
    slug         = db.Column(db.String(120), unique=True, nullable=False)
    description  = db.Column(db.Text, default="")
    is_published = db.Column(db.Boolean, default=False, nullable=False)
    order        = db.Column(db.Integer, default=0)
    created_at   = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at   = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted   = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at   = db.Column(db.DateTime, nullable=True)

    fields = db.Column(db.JSON, default=list)

    submissions = db.relationship("FormSubmission", backref="form", lazy="dynamic", cascade="all, delete-orphan")

    @property
    def sorted_fields(self):
        return sorted(self.fields or [], key=lambda f: f.get("order", 0))

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = datetime.utcnow()

    def __repr__(self):
        return f"<FormConfig {self.name!r}>"