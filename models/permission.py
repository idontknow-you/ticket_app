from extensions import db
from datetime import datetime


class UserPermission(db.Model):
    __tablename__ = 'user_permissions'

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False)

    can_view = db.Column(db.Boolean, default=False)
    can_create = db.Column(db.Boolean, default=False)
    can_edit = db.Column(db.Boolean, default=False)
    can_delete = db.Column(db.Boolean, default=False)
    can_assign = db.Column(db.Boolean, default=False)

    granted_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)  # always superadmin
    granted_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)

    # One permission row per user per ticket
    __table_args__ = (
        db.UniqueConstraint('user_id', 'ticket_id', name='uq_user_ticket_permission'),
    )

    user = db.relationship('User', foreign_keys=[user_id], backref='permissions', lazy=True)
    ticket = db.relationship('Ticket', backref='permissions', lazy=True)
    granter = db.relationship('User', foreign_keys=[granted_by], backref='granted_permissions', lazy=True)
