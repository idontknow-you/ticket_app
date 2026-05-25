from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from extensions import db
from models.ticket import Ticket, TicketComment, TicketHistory
from models.user import User

tickets_bp = Blueprint('tickets', __name__)


@tickets_bp.route('/dashboard')
@login_required
def dashboard():
    status_filter = request.args.get('status', 'all')
    priority_filter = request.args.get('priority', 'all')
    search = request.args.get('search', '').strip()

    query = Ticket.query

    if status_filter != 'all':
        query = query.filter_by(status=status_filter)
    if priority_filter != 'all':
        query = query.filter_by(priority=priority_filter)
    if search:
        query = query.filter(
            db.or_(
                Ticket.subject.ilike(f'%{search}%'),
                Ticket.ticket_number.ilike(f'%{search}%'),
                Ticket.submitter_name.ilike(f'%{search}%'),
                Ticket.submitter_email.ilike(f'%{search}%'),
            )
        )

    tickets = query.order_by(Ticket.created_at.desc()).all()

    total       = Ticket.query.count()
    open_count  = Ticket.query.filter_by(status='open').count()
    in_progress = Ticket.query.filter_by(status='in_progress').count()
    closed      = Ticket.query.filter_by(status='closed').count()

    return render_template(
        'tickets/dashboard.html',
        tickets=tickets,
        status_filter=status_filter,
        priority_filter=priority_filter,
        search=search,
        total=total,
        open_count=open_count,
        in_progress=in_progress,
        closed=closed,
    )


@tickets_bp.route('/tickets/<int:ticket_id>')
@login_required
def view_ticket(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    users = User.query.filter_by(is_active=True).order_by(User.name).all()
    return render_template('tickets/view_ticket.html', ticket=ticket, users=users)

@tickets_bp.after_request
def add_no_cache(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@tickets_bp.route('/tickets/<int:ticket_id>/update', methods=['POST'])
@login_required
def update_ticket(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)

    fields = ['status', 'priority', 'assigned_to']
    for field in fields:
        new_val = request.form.get(field)
        if new_val is not None:
            old_val = str(getattr(ticket, field) or '')
            if new_val != old_val:
                history = TicketHistory(
                    ticket_id=ticket.id,
                    changed_by=current_user.id,
                    field_changed=field,
                    old_value=old_val,
                    new_value=new_val,
                )
                db.session.add(history)
                if field == 'assigned_to':
                    setattr(ticket, field, int(new_val) if new_val else None)
                else:
                    setattr(ticket, field, new_val)

    db.session.commit()
    flash('Ticket updated.', 'success')
    return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))


@tickets_bp.route('/tickets/<int:ticket_id>/comment', methods=['POST'])
@login_required
def add_comment(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    body = request.form.get('body', '').strip()
    is_internal = request.form.get('is_internal') == 'on'

    if not body:
        flash('Comment cannot be empty.', 'error')
        return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))

    comment = TicketComment(
        ticket_id=ticket.id,
        user_id=current_user.id,
        body=body,
        is_internal=is_internal,
    )
    db.session.add(comment)
    db.session.commit()
    flash('Comment added.', 'success')
    return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))
