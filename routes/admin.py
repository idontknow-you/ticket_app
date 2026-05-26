from flask import Blueprint, render_template, redirect, url_for, request, flash, abort, jsonify
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from extensions import db
from models.user import User
from models.permission import MODULE_AUTO_GRANTED, UserPermission, MODULES, MODULE_PERMISSION_MAP
from models.settings import Setting
from decorators import require_permission
from datetime import datetime, timedelta
from sqlalchemy import func
from models.ticket import Ticket
from services.form_service import get_form_config, CONFIGURABLE_FIELDS

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')


def superadmin_required(f):
    from functools import wraps
    @wraps(f)
    def decorated(*args, **kwargs):
        if not current_user.is_authenticated or not current_user.is_superadmin:
            abort(403)
        return f(*args, **kwargs)
    return decorated


@admin_bp.context_processor
def admin_permissions():
    if not current_user.is_authenticated:
        return dict(
            users_perm=None,
            settings_perm=None,
            form_settings_perm=None,
            reports_perm=None,
        )

    if current_user.is_superadmin:
        class _All:
            can_view = can_create = can_edit = can_delete = can_assign = True

        return dict(
            users_perm=_All(),
            settings_perm=_All(),
            form_settings_perm=_All(),
            reports_perm=_All(),
        )

    def _perm(module):
        return UserPermission.query.filter_by(
            user_id=current_user.id, module=module
        ).first()

    return dict(
        users_perm=_perm('Users'),
        settings_perm=_perm('Settings'),
        form_settings_perm=_perm('Form Settings'),
        reports_perm=_perm('Reports'),
    )


# ── Users ──────────────────────────────────────────────────────────────────

@admin_bp.route('/users')
@login_required
@require_permission('Users', 'can_view')
def users():
    all_users = User.query.filter_by(is_superadmin=False, is_active=True).order_by(User.created_at.desc()).all()
    return render_template('admin/users.html', users=all_users)


@admin_bp.route('/users/<int:user_id>/delete', methods=['POST'])
@login_required
@require_permission('Users', 'can_delete')
def delete_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_superadmin:
        flash('Cannot delete superadmin.', 'error')
        return redirect(url_for('admin.users'))
    if user.id == current_user.id:
        flash('You cannot delete your own account.', 'error')
        return redirect(url_for('admin.users'))
    user.is_active = False
    db.session.commit()
    flash(f'User "{user.name}" removed.', 'success')
    return redirect(url_for('admin.users'))


@admin_bp.route('/users/create', methods=['POST'])
@login_required
@require_permission('Users', 'can_create')
def create_user():
    name     = request.form.get('name', '').strip()
    username = request.form.get('username', '').strip()
    email    = request.form.get('email', '').strip()
    password = request.form.get('password', '').strip()

    if not all([name, username, email, password]):
        flash('All fields are required.', 'error')
        return redirect(url_for('admin.users'))

    if User.query.filter_by(username=username, is_active=True).first():
        flash('Username already taken.', 'error')
        return redirect(url_for('admin.users'))

    if User.query.filter_by(email=email, is_active=True).first():
        flash('Email already registered.', 'error')
        return redirect(url_for('admin.users'))

    user = User(
        name=name,
        username=username,
        email=email,
        password_hash=generate_password_hash(password),
        is_superadmin=False,
    )
    db.session.add(user)
    db.session.commit()
    flash(f'User "{name}" created successfully.', 'success')
    return redirect(url_for('admin.users'))


# ── Permissions ─────────────────────────────────────────────────────────────

@admin_bp.route('/permissions')
@login_required
@superadmin_required
def permissions():
    users = User.query.filter_by(is_superadmin=False, is_active=True).order_by(User.name).all()

    selected_user_id = request.args.get('user_id', type=int)
    selected_module  = request.args.get('module', '')

    selected_user = None
    perm_row      = None

    if selected_user_id:
        selected_user = User.query.get(selected_user_id)

    if selected_user and selected_module:
        perm_row = UserPermission.query.filter_by(
            user_id=selected_user_id,
            module=selected_module
        ).first()

    return render_template(
        'admin/permissions.html',
        users=users,
        modules=MODULES,
        module_map=MODULE_PERMISSION_MAP,
        selected_user=selected_user,
        selected_user_id=selected_user_id,
        selected_module=selected_module,
        perm_row=perm_row,
    )


@admin_bp.route('/permissions/save', methods=['POST'])
@login_required
@superadmin_required
def save_permissions():
    user_id = request.form.get('user_id', type=int)
    module  = request.form.get('module', '').strip()

    if not user_id or not module:
        flash('Select a user and module.', 'error')
        return redirect(url_for('admin.permissions'))

    if module not in MODULES:
        flash('Invalid module.', 'error')
        return redirect(url_for('admin.permissions'))

    perm = UserPermission.query.filter_by(user_id=user_id, module=module).first()
    if not perm:
        perm = UserPermission(user_id=user_id, module=module, granted_by=current_user.id)
        db.session.add(perm)

    allowed = MODULE_PERMISSION_MAP[module]
    auto    = MODULE_AUTO_GRANTED[module]

    perm.can_view   = True if 'can_view'   in auto else (bool(request.form.get('can_view'))   if allowed['can_view']   else False)
    perm.can_create = True if 'can_create' in auto else (bool(request.form.get('can_create')) if allowed['can_create'] else False)
    perm.can_edit   = bool(request.form.get('can_edit'))   if allowed['can_edit']   else False
    perm.can_delete = bool(request.form.get('can_delete')) if allowed['can_delete'] else False
    perm.can_assign = bool(request.form.get('can_assign')) if allowed['can_assign'] else False

    db.session.commit()
    flash('Permissions saved.', 'success')
    return redirect(url_for('admin.permissions', user_id=user_id, module=module))


@admin_bp.route('/permissions/autosave', methods=['POST'])
@login_required
@superadmin_required
def autosave_permission():
    """AJAX endpoint — called on checkbox toggle, no page reload needed."""
    data     = request.get_json(force=True)
    user_id  = data.get('user_id')
    module   = data.get('module', '').strip()
    perm_key = data.get('perm_key', '').strip()
    value    = bool(data.get('value'))

    if not user_id or not module or not perm_key:
        return jsonify(ok=False, error='Missing fields'), 400

    if module not in MODULES:
        return jsonify(ok=False, error='Invalid module'), 400

    allowed_keys = {'can_view', 'can_create', 'can_edit', 'can_delete', 'can_assign'}
    if perm_key not in allowed_keys:
        return jsonify(ok=False, error='Invalid permission key'), 400

    perm = UserPermission.query.filter_by(user_id=user_id, module=module).first()
    if not perm:
        perm = UserPermission(user_id=user_id, module=module, granted_by=current_user.id)
        db.session.add(perm)

    setattr(perm, perm_key, value)
    db.session.commit()
    return jsonify(ok=True)


# ── Settings ────────────────────────────────────────────────────────────────

SETTINGS_KEYS = [
    'smtp_host',
    'smtp_port',
    'smtp_user',
    'smtp_password',
    'smtp_use_tls',
    'support_email',
    'app_name',
    'app_url',
]


@admin_bp.route('/settings')
@login_required
@require_permission('Settings', 'can_view')
def settings():
    rows = {s.key: s for s in Setting.query.filter(Setting.key.in_(SETTINGS_KEYS)).all()}
    values = {k: (rows[k].value if k in rows else '') for k in SETTINGS_KEYS}
    return render_template('admin/settings.html', values=values)


@admin_bp.route('/settings/save', methods=['POST'])
@login_required
@require_permission('Settings', 'can_edit')
def save_settings():
    rows = {s.key: s for s in Setting.query.filter(Setting.key.in_(SETTINGS_KEYS)).all()}
    for key in SETTINGS_KEYS:
        if key == 'smtp_use_tls':
            value = 'true' if request.form.get(key) else 'false'
        else:
            value = request.form.get(key, '').strip()

        if key in rows:
            rows[key].value = value
        else:
            db.session.add(Setting(key=key, value=value))

    db.session.commit()
    flash('Settings saved successfully.', 'success')
    return redirect(url_for('admin.settings'))


@admin_bp.route('/settings/autosave', methods=['POST'])
@login_required
@require_permission('Settings', 'can_edit')
def autosave_setting():
    """AJAX endpoint for auto-saving a single SMTP / email-defaults setting."""
    data  = request.get_json(force=True)
    key   = data.get('key', '').strip()
    value = data.get('value', '')

    if key not in SETTINGS_KEYS:
        return jsonify(ok=False, error='Invalid key'), 400

    row = Setting.query.filter_by(key=key).first()
    if row:
        row.value = value
    else:
        db.session.add(Setting(key=key, value=value))

    db.session.commit()
    return jsonify(ok=True)


# ── Form Settings ─────────────────────────────────────────────────────────────

@admin_bp.route('/form-settings')
@login_required
@require_permission('Form Settings', 'can_view')
def form_settings():
    form_field_config = get_form_config()
    return render_template('admin/form_settings.html', form_field_config=form_field_config)


@admin_bp.route('/form-settings/save', methods=['POST'])
@login_required
@require_permission('Form Settings', 'can_edit')
def save_form_settings():
    for field in CONFIGURABLE_FIELDS:
        visible  = 'true' if request.form.get(f'form_field_{field}_visible')  else 'false'
        required = 'true' if request.form.get(f'form_field_{field}_required') else 'false'

        if visible == 'false':
            required = 'false'

        for suffix, val in [('visible', visible), ('required', required)]:
            key = f'form_field_{field}_{suffix}'
            row = Setting.query.filter_by(key=key).first()
            if row:
                row.value = val
            else:
                db.session.add(Setting(key=key, value=val,
                                       description=f'Public form field: {field} {suffix}'))

    db.session.commit()
    flash('Form settings saved.', 'success')
    return redirect(url_for('admin.form_settings'))


@admin_bp.route('/form-settings/autosave', methods=['POST'])
@login_required
@require_permission('Form Settings', 'can_edit')
def autosave_form_field():
    """AJAX endpoint — called on checkbox toggle for form field visibility/required."""
    data   = request.get_json(force=True)
    field  = data.get('field', '').strip()
    suffix = data.get('suffix', '').strip()
    value  = bool(data.get('value'))

    if field not in CONFIGURABLE_FIELDS:
        return jsonify(ok=False, error='Invalid field'), 400
    if suffix not in ('visible', 'required'):
        return jsonify(ok=False, error='Invalid suffix'), 400

    key     = f'form_field_{field}_{suffix}'
    str_val = 'true' if value else 'false'

    row = Setting.query.filter_by(key=key).first()
    if row:
        row.value = str_val
    else:
        db.session.add(Setting(key=key, value=str_val,
                               description=f'Public form field: {field} {suffix}'))

    # If hiding a field, also force required=false
    if suffix == 'visible' and not value:
        req_key = f'form_field_{field}_required'
        req_row = Setting.query.filter_by(key=req_key).first()
        if req_row:
            req_row.value = 'false'
        else:
            db.session.add(Setting(key=req_key, value='false',
                                   description=f'Public form field: {field} required'))

    db.session.commit()
    return jsonify(ok=True)


# ── Admin Panel ─────────────────────────────────────────────────────────────

@admin_bp.route('/panel')
@login_required
@superadmin_required
def panel():
    user_count = User.query.filter_by(is_superadmin=False, is_active=True).count()
    module_count = len(MODULES)
    return render_template('admin/panel.html', user_count=user_count, module_count=module_count)


# ── Reports ─────────────────────────────────────────────────────────────────

@admin_bp.route('/reports')
@login_required
@require_permission('Reports', 'can_view')
def reports():
    thirty_days_ago = datetime.utcnow() - timedelta(days=30)
    daily_volume = (
        db.session.query(
            func.date(Ticket.created_at).label('day'),
            func.count(Ticket.id).label('count')
        )
        .filter(Ticket.created_at >= thirty_days_ago)
        .group_by(func.date(Ticket.created_at))
        .order_by(func.date(Ticket.created_at))
        .all()
    )

    by_status = (
        db.session.query(Ticket.status, func.count(Ticket.id))
        .group_by(Ticket.status)
        .all()
    )

    by_priority = (
        db.session.query(Ticket.priority, func.count(Ticket.id))
        .group_by(Ticket.priority)
        .all()
    )

    by_type = (
        db.session.query(Ticket.type, func.count(Ticket.id))
        .group_by(Ticket.type)
        .all()
    )

    closed_tickets = Ticket.query.filter(
        Ticket.status == 'Closed',
        Ticket.closed_at.isnot(None)
    ).all()

    if closed_tickets:
        total_seconds = sum(
            (t.closed_at - t.created_at).total_seconds()
            for t in closed_tickets
            if t.closed_at and t.created_at
        )
        avg_resolution_hours = round(total_seconds / len(closed_tickets) / 3600, 1)
    else:
        avg_resolution_hours = None

    per_assignee = (
        db.session.query(
            User.username,
            func.count(Ticket.id).label('count')
        )
        .join(Ticket, Ticket.assigned_to == User.id)
        .filter(User.is_active == True)
        .group_by(User.id, User.username)
        .order_by(func.count(Ticket.id).desc())
        .all()
    )

    total_tickets = Ticket.query.count()
    open_tickets = Ticket.query.filter(Ticket.status != 'Closed').count()
    closed_tickets_count = Ticket.query.filter(Ticket.status == 'Closed').count()

    return render_template(
        'admin/reports.html',
        daily_volume=daily_volume,
        by_status=by_status,
        by_priority=by_priority,
        by_type=by_type,
        avg_resolution_hours=avg_resolution_hours,
        per_assignee=per_assignee,
        total_tickets=total_tickets,
        open_tickets=open_tickets,
        closed_tickets_count=closed_tickets_count,
    )
