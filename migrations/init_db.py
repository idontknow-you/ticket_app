import sys
import os
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from extensions import db
from models.user import User
from models.ticket import Ticket, TicketFieldDefinition, TicketFieldValue, TicketComment, TicketHistory, TicketAttachment
from models.permission import UserPermission
from models.wiki import WikiPage, WikiPageHistory
from models.settings import Setting
from models.mail import MailLog, MailTemplate
from werkzeug.security import generate_password_hash
from datetime import datetime


def seed_superadmin():
    existing = User.query.filter_by(username='superadmin').first()
    if existing:
        print('  [skip] Superadmin already exists.')
        return

    superadmin = User(
        name='Superadmin',
        username='superadmin',
        email='superadmin@superadmin.com',
        password_hash=generate_password_hash('superadmin123'),
        is_superadmin=True,
        created_at=datetime.utcnow()
    )
    db.session.add(superadmin)
    db.session.commit()
    print('  [ok] Superadmin created.')


def seed_settings():
    defaults = [
        {
            'key': 'app_name',
            'value': 'Support Ticketing System',
            'description': 'The name of the application, shown in the UI and emails.'
        },
        {
            'key': 'app_url',
            'value': 'http://localhost:5000',
            'description': 'Base URL of the application, used in email links.'
        },
        {
            'key': 'support_email',
            'value': 'support@example.com',
            'description': 'The email address used as the sender for outgoing emails.'
        },
    ]

    for item in defaults:
        existing = Setting.query.filter_by(key=item['key']).first()
        if existing:
            print(f"  [skip] Setting '{item['key']}' already exists.")
            continue
        db.session.add(Setting(**item))
        print(f"  [ok] Setting '{item['key']}' created.")

    db.session.commit()


def seed_mail_templates():
    templates = [
        {
            'template_key': 'ticket_created',
            'subject': 'Your ticket {{ticket_number}} has been received',
            'body_html': '''<p>Hi {{submitter_name}},</p>
<p>Thank you for reaching out. Your ticket has been received and is being reviewed.</p>
<p><strong>Ticket:</strong> {{ticket_number}}<br>
<strong>Subject:</strong> {{subject}}<br>
<strong>Status:</strong> {{status}}</p>
<p>We will get back to you as soon as possible.</p>
<p>— {{app_name}}</p>''',
            'body_text': '''Hi {{submitter_name}},

Thank you for reaching out. Your ticket has been received and is being reviewed.

Ticket: {{ticket_number}}
Subject: {{subject}}
Status: {{status}}

We will get back to you as soon as possible.

— {{app_name}}''',
            'description': 'Sent to the submitter when a new ticket is created.'
        },
        {
            'template_key': 'ticket_updated',
            'subject': 'Your ticket {{ticket_number}} has been updated',
            'body_html': '''<p>Hi {{submitter_name}},</p>
<p>There has been an update on your ticket.</p>
<p><strong>Ticket:</strong> {{ticket_number}}<br>
<strong>Subject:</strong> {{subject}}<br>
<strong>Status:</strong> {{status}}</p>
<p>You can reply to this email to add more information.</p>
<p>— {{app_name}}</p>''',
            'body_text': '''Hi {{submitter_name}},

There has been an update on your ticket.

Ticket: {{ticket_number}}
Subject: {{subject}}
Status: {{status}}

You can reply to this email to add more information.

— {{app_name}}''',
            'description': 'Sent to the submitter when a ticket status or details are updated.'
        },
        {
            'template_key': 'ticket_assigned',
            'subject': 'You have been assigned ticket {{ticket_number}}',
            'body_html': '''<p>Hi {{agent_name}},</p>
<p>You have been assigned a support ticket.</p>
<p><strong>Ticket:</strong> {{ticket_number}}<br>
<strong>Subject:</strong> {{subject}}<br>
<strong>Priority:</strong> {{priority}}<br>
<strong>Submitted by:</strong> {{submitter_name}}</p>
<p>Please log in to review and respond.</p>
<p>— {{app_name}}</p>''',
            'body_text': '''Hi {{agent_name}},

You have been assigned a support ticket.

Ticket: {{ticket_number}}
Subject: {{subject}}
Priority: {{priority}}
Submitted by: {{submitter_name}}

Please log in to review and respond.

— {{app_name}}''',
            'description': 'Sent to an agent when a ticket is assigned to them.'
        },
        {
            'template_key': 'ticket_closed',
            'subject': 'Your ticket {{ticket_number}} has been closed',
            'body_html': '''<p>Hi {{submitter_name}},</p>
<p>Your support ticket has been closed.</p>
<p><strong>Ticket:</strong> {{ticket_number}}<br>
<strong>Subject:</strong> {{subject}}</p>
<p>If you feel your issue has not been resolved, please submit a new ticket.</p>
<p>— {{app_name}}</p>''',
            'body_text': '''Hi {{submitter_name}},

Your support ticket has been closed.

Ticket: {{ticket_number}}
Subject: {{subject}}

If you feel your issue has not been resolved, please submit a new ticket.

— {{app_name}}''',
            'description': 'Sent to the submitter when a ticket is closed.'
        },
    ]

    for item in templates:
        existing = MailTemplate.query.filter_by(template_key=item['template_key']).first()
        if existing:
            print(f"  [skip] Mail template '{item['template_key']}' already exists.")
            continue
        db.session.add(MailTemplate(**item))
        print(f"  [ok] Mail template '{item['template_key']}' created.")

    db.session.commit()


def init_db():
    app = create_app()

    with app.app_context():
        print('\n[1/4] Creating tables...')
        db.create_all()
        print('  [ok] All tables created.')

        print('\n[2/4] Seeding superadmin...')
        seed_superadmin()

        print('\n[3/4] Seeding settings...')
        seed_settings()

        print('\n[4/4] Seeding mail templates...')
        seed_mail_templates()

        print('\n[done] Database initialised successfully.\n')


if __name__ == '__main__':
    init_db()
