from extensions import db
from datetime import datetime

PREFIX_MAP = {
    'Issue': 'I',
    'Bug':   'B',
    'Other': 'O',
}

class Ticket(db.Model):
    __tablename__ = 'tickets'

    id = db.Column(db.Integer, primary_key=True)
    ticket_number = db.Column(db.String(20), unique=True, nullable=False)
    subject = db.Column(db.String(200), nullable=False)
    description = db.Column(db.Text, nullable=False)
    status = db.Column(db.String(20), nullable=False, default='Open')
    priority = db.Column(db.String(20), nullable=False, default='Low')
    type = db.Column(db.String(20), nullable=False)
    module = db.Column(db.String(50), nullable=False)
    submitter_name = db.Column(db.String(100), nullable=False)
    submitter_email = db.Column(db.String(120), nullable=False)
    assigned_to = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    closed_at = db.Column(db.DateTime, nullable=True)
    attachments = db.relationship('TicketAttachment', backref='ticket', lazy=True)

    assignee = db.relationship('User', backref='assigned_tickets', lazy=True)
    field_values = db.relationship('TicketFieldValue', backref='ticket', lazy=True)
    comments = db.relationship('TicketComment', backref='ticket', lazy=True)
    history = db.relationship('TicketHistory', backref='ticket', lazy=True)


class TicketFieldDefinition(db.Model):
    __tablename__ = 'ticket_field_definitions'

    id = db.Column(db.Integer, primary_key=True)
    field_label = db.Column(db.String(100), nullable=False)
    field_key = db.Column(db.String(100), unique=True, nullable=False)
    field_type = db.Column(db.String(20), nullable=False)
    field_options = db.Column(db.Text, nullable=True)
    is_required = db.Column(db.Boolean, default=False)
    is_active = db.Column(db.Boolean, default=True)
    display_order = db.Column(db.Integer, default=0)


class TicketFieldValue(db.Model):
    __tablename__ = 'ticket_field_values'

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False)
    field_key = db.Column(db.String(100), nullable=False)
    field_value = db.Column(db.Text, nullable=True)


class TicketComment(db.Model):
    __tablename__ = 'ticket_comments'

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False)
    user_id = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    body = db.Column(db.Text, nullable=False)
    is_internal = db.Column(db.Boolean, default=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)

    author = db.relationship('User', backref='comments', lazy=True)


class TicketHistory(db.Model):
    __tablename__ = 'ticket_history'

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False)
    changed_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    field_changed = db.Column(db.String(100), nullable=False)
    old_value = db.Column(db.Text, nullable=True)
    new_value = db.Column(db.Text, nullable=True)
    changed_at = db.Column(db.DateTime, default=datetime.utcnow)

    editor = db.relationship('User', backref='ticket_changes', lazy=True)


class TicketAttachment(db.Model):
    __tablename__ = 'ticket_attachments'

    id = db.Column(db.Integer, primary_key=True)
    ticket_id = db.Column(db.Integer, db.ForeignKey('tickets.id'), nullable=False)
    uploaded_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    file_name = db.Column(db.String(200), nullable=False)
    file_path = db.Column(db.String(500), nullable=False)
    file_type = db.Column(db.String(50), nullable=False)
    file_size = db.Column(db.Integer, nullable=False)
    uploaded_at = db.Column(db.DateTime, default=datetime.utcnow)

    uploader = db.relationship('User', backref='attachments', lazy=True)
