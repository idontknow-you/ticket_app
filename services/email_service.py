"""
email_service.py

Handles all outbound email for the ticketing system.
Currently uses Python's smtplib. Configure SMTP settings via the
Setting model (keys: smtp_host, smtp_port, smtp_user, smtp_password,
smtp_use_tls, support_email, app_name, app_url).

Mail is logged to the MailLog model after every send attempt.
"""

import smtplib
import re
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime

from flask import current_app
from extensions import db
from models.mail import MailLog, MailTemplate
from models.settings import Setting


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _get_setting(key, default=''):
    """Fetch a single setting value from the DB."""
    row = Setting.query.filter_by(key=key).first()
    return row.value if row else default


def _render_template(template_key, variables: dict) -> tuple[str, str]:
    """
    Load a MailTemplate by key and substitute {{variable}} placeholders.
    Returns (subject, body_html).
    """
    tpl = MailTemplate.query.filter_by(key=template_key).first()
    if not tpl:
        raise ValueError(f"Mail template '{template_key}' not found in database.")

    def substitute(text):
        for k, v in variables.items():
            text = text.replace('{{' + k + '}}', str(v))
        return text

    return substitute(tpl.subject), substitute(tpl.body)


def _send_raw(to_email: str, subject: str, body_html: str) -> None:
    """
    Send a single email via SMTP. Raises on failure.
    Logs every attempt to MailLog.
    """
    smtp_host = _get_setting('smtp_host', 'localhost')
    smtp_port = int(_get_setting('smtp_port', '587'))
    smtp_user = _get_setting('smtp_user', '')
    smtp_password = _get_setting('smtp_password', '')
    use_tls = _get_setting('smtp_use_tls', 'true').lower() == 'true'
    from_email = _get_setting('support_email', 'support@example.com')
    app_name = _get_setting('app_name', 'Support')

    msg = MIMEMultipart('alternative')
    msg['Subject'] = subject
    msg['From'] = f'{app_name} <{from_email}>'
    msg['To'] = to_email
    msg.attach(MIMEText(body_html, 'html'))

    error_message = None
    status = 'sent'

    try:
        with smtplib.SMTP(smtp_host, smtp_port, timeout=10) as server:
            if use_tls:
                server.starttls()
            if smtp_user and smtp_password:
                server.login(smtp_user, smtp_password)
            server.sendmail(from_email, [to_email], msg.as_string())
    except Exception as e:
        status = 'failed'
        error_message = str(e)
        raise
    finally:
        log = MailLog(
            to_email=to_email,
            subject=subject,
            body=body_html,
            status=status,
            error_message=error_message,
            sent_at=datetime.utcnow() if status == 'sent' else None,
        )
        db.session.add(log)
        db.session.commit()


# ---------------------------------------------------------------------------
# Public senders
# ---------------------------------------------------------------------------

def send_ticket_confirmation(
    to_email: str,
    to_name: str,
    ticket_number: str,
    subject: str,
) -> None:
    """Send a submission confirmation to the person who filed the ticket."""
    app_name = _get_setting('app_name', 'Support')
    app_url = _get_setting('app_url', '')

    email_subject, body = _render_template('ticket_created', {
        'submitter_name': to_name,
        'ticket_number': ticket_number,
        'subject': subject,
        'app_name': app_name,
        'app_url': app_url,
    })

    _send_raw(to_email, email_subject, body)


def send_ticket_updated(
    to_email: str,
    to_name: str,
    ticket_number: str,
    subject: str,
    update_summary: str,
) -> None:
    """Notify submitter that their ticket was updated."""
    app_name = _get_setting('app_name', 'Support')
    app_url = _get_setting('app_url', '')

    email_subject, body = _render_template('ticket_updated', {
        'submitter_name': to_name,
        'ticket_number': ticket_number,
        'subject': subject,
        'update_summary': update_summary,
        'app_name': app_name,
        'app_url': app_url,
    })

    _send_raw(to_email, email_subject, body)


def send_ticket_assigned(
    to_email: str,
    to_name: str,
    ticket_number: str,
    subject: str,
    assigned_to_name: str,
) -> None:
    """Notify relevant parties that a ticket was assigned."""
    app_name = _get_setting('app_name', 'Support')
    app_url = _get_setting('app_url', '')

    email_subject, body = _render_template('ticket_assigned', {
        'submitter_name': to_name,
        'ticket_number': ticket_number,
        'subject': subject,
        'assigned_to_name': assigned_to_name,
        'app_name': app_name,
        'app_url': app_url,
    })

    _send_raw(to_email, email_subject, body)


def send_ticket_closed(
    to_email: str,
    to_name: str,
    ticket_number: str,
    subject: str,
) -> None:
    """Notify submitter that their ticket was closed."""
    app_name = _get_setting('app_name', 'Support')
    app_url = _get_setting('app_url', '')

    email_subject, body = _render_template('ticket_closed', {
        'submitter_name': to_name,
        'ticket_number': ticket_number,
        'subject': subject,
        'app_name': app_name,
        'app_url': app_url,
    })

    _send_raw(to_email, email_subject, body)
