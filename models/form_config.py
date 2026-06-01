from extensions import db
from datetime import datetime
from models.form_config_version import FormConfigVersion

class FormConfig(db.Model):
    __tablename__ = "form_configurations"

    id                 = db.Column(db.Integer, primary_key=True)
    name               = db.Column(db.String(120), nullable=False)
    slug               = db.Column(db.String(120), unique=True, nullable=False)
    description        = db.Column(db.Text, default="")
    is_published       = db.Column(db.Boolean, default=False, nullable=False)
    order              = db.Column(db.Integer, default=0)
    created_at         = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at         = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted         = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at         = db.Column(db.DateTime, nullable=True)

    current_version_id = db.Column(
        db.Integer,
        db.ForeignKey("form_config_versions.id", use_alter=True, name="fk_form_current_version"),
        nullable=True,
    )

    versions = db.relationship(
        "FormConfigVersion",
        foreign_keys="FormConfigVersion.form_config_id",
        backref="form",
        lazy="dynamic",
        order_by="FormConfigVersion.version",
    )

    current_version = db.relationship(
        "FormConfigVersion",
        foreign_keys="FormConfig.current_version_id",
        post_update=True,
    )

    submissions = db.relationship(
        "FormSubmission",
        foreign_keys="FormSubmission.form_config_id",
        backref="form",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )

    # ------------------------------------------------------------------ helpers

    @property
    def fields(self):
        return self.current_version.fields if self.current_version else []

    @property
    def sorted_fields(self):
        return sorted(self.fields, key=lambda f: f.get("order", 0))

    def publish_new_version(self, fields: list, created_by: int = None) -> "FormConfigVersion":
        """
        Create the next version, make it current, and return it.
        Caller must call db.session.commit() after this.
        """
        # Query the max version number directly from the DB rather than using
        # the relationship — avoids stale in-memory data causing duplicate version numbers.
        max_ver = db.session.query(
            db.func.max(FormConfigVersion.version)
        ).filter(
            FormConfigVersion.form_config_id == self.id
        ).scalar()

        next_num = (max_ver + 1) if max_ver is not None else 1

        ver = FormConfigVersion(
            form_config_id=self.id,
            version=next_num,
            fields=fields,
            created_by=created_by,
        )
        db.session.add(ver)
        db.session.flush()          # populate ver.id before updating FK

        self.current_version_id = ver.id
        self.updated_at = datetime.utcnow()
        return ver

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = datetime.utcnow()

    def __repr__(self):
        return f"<FormConfig {self.name!r} v={self.current_version_id}>"