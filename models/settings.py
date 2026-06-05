from extensions import db


class Setting(db.Model):
    __tablename__ = "settings"

    id          = db.Column(db.Integer, primary_key=True)
    key         = db.Column(db.String(80), unique=True, nullable=False)
    value       = db.Column(db.Text, default="")
    description = db.Column(db.String(200), default="")

    def __repr__(self):
        return f"<Setting {self.key}={self.value!r}>"


def get_setting(key, default=None):
    """Fetch a single setting value by key. Returns default if not found."""
    s = Setting.query.filter_by(key=key).first()
    return s.value if s else default


def set_setting(key, value):
    """Update an existing setting or create it if missing. Caller must commit."""
    s = Setting.query.filter_by(key=key).first()
    if s:
        s.value = value
    else:
        s = Setting(key=key, value=value)
        db.session.add(s)