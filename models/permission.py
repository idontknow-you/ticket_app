from extensions import db
from datetime import datetime


MODULES = ['Tickets', 'Wiki', 'Users', 'Settings', 'Reports']

# Which permissions apply to each module (True = checkbox, False = N/A)
MODULE_PERMISSION_MAP = {
    'Tickets':  {'can_view': True, 'can_create': True, 'can_edit': True, 'can_delete': True, 'can_assign': True},
    'Wiki':     {'can_view': True, 'can_create': True, 'can_edit': True, 'can_delete': True, 'can_assign': False},
    'Users':    {'can_view': True, 'can_create': True, 'can_edit': True, 'can_delete': True, 'can_assign': False},
    'Settings': {'can_view': True, 'can_create': False, 'can_edit': True, 'can_delete': False, 'can_assign': False},
    'Reports':  {'can_view': True, 'can_create': False, 'can_edit': False, 'can_delete': False, 'can_assign': False},
}


class UserPermission(db.Model):
    __tablename__ = 'user_permissions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    module = db.Column(db.String(50), nullable=False)  # e.g. 'Tickets', 'Wiki'

    can_view   = db.Column(db.Boolean, default=False)
    can_create = db.Column(db.Boolean, default=False)
    can_edit   = db.Column(db.Boolean, default=False)
    can_delete = db.Column(db.Boolean, default=False)
    can_assign = db.Column(db.Boolean, default=False)

    granted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    granted_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # One row per user per module
    __table_args__ = (
        db.UniqueConstraint('user_id', 'module', name='uq_user_module_permission'),
    )

    user    = db.relationship('User', foreign_keys=[user_id], backref='permissions', lazy=True)
    granter = db.relationship('User', foreign_keys=[granted_by], backref='granted_permissions', lazy=True)
