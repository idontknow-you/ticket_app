from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from extensions import db
from models.ticket import Ticket, TicketComment, TicketHistory
from models.user import User
from models.permission import UserPermission
from services.ticket_service import set_closed_at

tickets_bp = Blueprint('tickets', __name__)


def _ticket_perm():
    """Return current user's Tickets permission row, or synthetic _All for superadmin."""
    if current_user.is_superadmin:
        class _All:
            can_view = can_create = can_edit = can_delete = can_assign = True
        return _All()
    return UserPermission.query.filter_by(
        user_id=current_user.id, module='Tickets'
    ).first()


@tickets_bp.route('/dashboard')
@login_required
def dashboard():
    status_filter   = request.args.get('status', 'all')
    priority_filter = request.args.get('priority', 'all')
    type_filter     = request.args.get('type', 'all')
    search          = request.args.get('search', '').strip()

    query = Ticket.query

    if status_filter != 'all':
        query = query.filter(Ticket.status == status_filter)
    if priority_filter != 'all':
        query = query.filter(Ticket.priority == priority_filter)
    if type_filter != 'all':
        query = query.filter(Ticket.type == type_filter)
    if search:
        query = query.filter(
            db.or_(
                Ticket.subject.ilike(f'%{search}%'),
                Ticket.ticket_number.ilike(f'%{search}%'),
                Ticket.submitter_name.ilike(f'%{search}%'),
                Ticket.submitter_email.ilike(f'%{search}%'),
            )
        )

    # Sort: status (open > in_progress > closed) > priority (urgent > high > medium > low) > type (Issue > Bug > Other)
    from sqlalchemy import case
    status_order   = case({'open': 0, 'in_progress': 1, 'closed': 2}, value=Ticket.status,   else_=3)
    priority_order = case({'urgent': 0, 'high': 1, 'medium': 2, 'low': 3}, value=Ticket.priority, else_=4)
    type_order     = case({'Issue': 0, 'Bug': 1, 'Other': 2}, value=Ticket.type, else_=3)
    tickets = query.order_by(status_order, priority_order, type_order).all()

    total       = Ticket.query.count()
    open_count  = Ticket.query.filter(Ticket.status == 'open').count()
    in_progress = Ticket.query.filter(Ticket.status == 'in_progress').count()
    closed      = Ticket.query.filter(Ticket.status == 'closed').count()

    return render_template(
        'tickets/dashboard.html',
        tickets=tickets,
        status_filter=status_filter,
        priority_filter=priority_filter,
        type_filter=type_filter,
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
    ticket_perm = _ticket_perm()
    return render_template('tickets/view_ticket.html',
                           ticket=ticket, users=users, ticket_perm=ticket_perm)


@tickets_bp.route('/tickets/<int:ticket_id>/update', methods=['POST'])
@login_required
def update_ticket(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    perm = _ticket_perm()

    if not perm or not (perm.can_edit or perm.can_assign):
        flash('You do not have permission to update tickets.', 'error')
        return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))

    editable_fields  = ['status', 'priority'] if (perm and perm.can_edit) else []
    assignable_fields = ['assigned_to'] if (perm and perm.can_assign) else []
    allowed_fields = editable_fields + assignable_fields

    for field in allowed_fields:
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

    # Keep closed_at in sync with status
    set_closed_at(ticket)

    db.session.commit()
    flash('Ticket updated.', 'success')
    return redirect(url_for('tickets.view_ticket', ticket_id=ticket_id))


@tickets_bp.route('/tickets/<int:ticket_id>/comment', methods=['POST'])
@login_required
def add_comment(ticket_id):
    ticket = Ticket.query.get_or_404(ticket_id)
    body = request.form.get('body', '').strip()
    perm = _ticket_perm()

    # Only allow internal notes for users with can_edit
    is_internal = (request.form.get('is_internal') == 'on') and bool(perm and perm.can_edit)

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
