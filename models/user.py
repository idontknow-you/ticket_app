from extensions import db
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime
import secrets


class User(UserMixin, db.Model):
    __tablename__ = "users"

    id                  = db.Column(db.Integer, primary_key=True)
    name                = db.Column(db.String(120), nullable=False, default="")
    username            = db.Column(db.String(80), unique=True, nullable=False)
    email               = db.Column(db.String(200), unique=True, nullable=True)
    password_hash       = db.Column(db.String(256), nullable=False)
    is_superadmin       = db.Column(db.Boolean, default=False, nullable=False)
    is_active           = db.Column(db.Boolean, default=True,  nullable=False)
    created_at          = db.Column(db.DateTime, default=datetime.utcnow)
    is_deleted          = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at          = db.Column(db.DateTime, nullable=True)

    reset_token         = db.Column(db.String(100), nullable=True, index=True)
    reset_token_expiry  = db.Column(db.DateTime, nullable=True)

    permissions         = db.Column(db.JSON, default=dict)
    column_prefs        = db.Column(db.JSON, default=dict)

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    def soft_delete(self):
        self.is_deleted = True
        self.is_active  = False
        self.deleted_at = datetime.utcnow()

    def has_permission(self, module, action="can_view"):
        if self.is_superadmin:
            return True
        return self.permissions.get(module, {}).get(action, False)

    def get_column_prefs(self, form_slug):
        return self.column_prefs.get(form_slug, {})

    def set_column_prefs(self, form_slug, prefs: dict):
        current = dict(self.column_prefs or {})
        current[form_slug] = prefs
        self.column_prefs = current

    def generate_reset_token(self):
        from datetime import timedelta
        self.reset_token = secrets.token_urlsafe(32)
        self.reset_token_expiry = datetime.utcnow() + timedelta(hours=24)
        return self.reset_token

    def clear_reset_token(self):
        self.reset_token = None
        self.reset_token_expiry = None

    def is_reset_token_valid(self, token):
        if not self.reset_token or not self.reset_token_expiry:
            return False
        if self.reset_token != token:
            return False
        return datetime.utcnow() < self.reset_token_expiry

    def __repr__(self):
        return f"<User {self.username}>"