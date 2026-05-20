"""
ticket_service.py

Business logic for ticket operations.
"""

import random
import string
from datetime import datetime

from models.ticket import Ticket


def generate_ticket_number() -> str:
    """
    Generate a unique ticket number in the format TKT-YYYYMMDD-XXXXX.
    Retries up to 10 times to avoid collisions (extremely unlikely).
    """
    date_str = datetime.utcnow().strftime('%Y%m%d')
    for _ in range(10):
        suffix = ''.join(random.choices(string.ascii_uppercase + string.digits, k=5))
        ticket_number = f'TKT-{date_str}-{suffix}'
        if not Ticket.query.filter_by(ticket_number=ticket_number).first():
            return ticket_number
    raise RuntimeError('Could not generate a unique ticket number after 10 attempts.')
