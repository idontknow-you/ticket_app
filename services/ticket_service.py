"""
ticket_service.py

Business logic for ticket operations.
"""

from datetime import datetime
from extensions import db
from models.ticket import Ticket


def generate_ticket_number(ticket_type: str) -> str:
    """
    Generate a unique ticket number like I-0001, B-0042, O-0007.
    Uses the DB to find the last ticket of the same type so numbers
    are sequential per type and never reused.
    """
    PREFIX_MAP = {
        'Issue': 'I',
        'Bug':   'B',
        'Other': 'O',
    }
    prefix = PREFIX_MAP.get(ticket_type, 'X')
    last = (
        Ticket.query
        .filter(Ticket.type == ticket_type)   # use == to avoid the filter_by/type builtin clash
        .order_by(Ticket.id.desc())
        .first()
    )
    if last and last.ticket_number:
        try:
            last_number = int(last.ticket_number.split('-')[1])
        except (IndexError, ValueError):
            last_number = 0
        next_number = last_number + 1
    else:
        next_number = 1
    return f"{prefix}-{str(next_number).zfill(4)}"


def set_closed_at(ticket):
    """
    Set or clear closed_at on a ticket based on its current status.
    Call after updating ticket.status and before committing.
    """
    if ticket.status == 'Closed' and ticket.closed_at is None:
        ticket.closed_at = datetime.utcnow()
    elif ticket.status != 'Closed':
        ticket.closed_at = None
