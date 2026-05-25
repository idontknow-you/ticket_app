from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_login import login_required, current_user
from werkzeug.security import generate_password_hash
from extensions import db
from models.user import User
from models.permission import MODULE_AUTO_GRANTED, UserPermission, MODULES, MODULE_PERMISSION_MAP
from decorators import require_permission

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
        return dict(users_perm=None)
    if current_user.is_superadmin:
        class _All:
            can_view = can_create = can_edit = can_delete = True
        return dict(users_perm=_All())
    perm = UserPermission.query.filter_by(
        user_id=current_user.id, module='Users'
    ).first()
    return dict(users_perm=perm)


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

    allowed     = MODULE_PERMISSION_MAP[module]
    auto        = MODULE_AUTO_GRANTED[module]

    perm.can_view   = True if 'can_view'   in auto else (bool(request.form.get('can_view'))   if allowed['can_view']   else False)
    perm.can_create = True if 'can_create' in auto else (bool(request.form.get('can_create')) if allowed['can_create'] else False)
    perm.can_edit   = bool(request.form.get('can_edit'))   if allowed['can_edit']   else False
    perm.can_delete = bool(request.form.get('can_delete')) if allowed['can_delete'] else False
    perm.can_assign = bool(request.form.get('can_assign')) if allowed['can_assign'] else False

    db.session.commit()
    flash('Permissions saved.', 'success')
    return redirect(url_for('admin.permissions', user_id=user_id, module=module))


# ── Admin Panel ─────────────────────────────────────────────────────────────

@admin_bp.route('/panel')
@superadmin_required
def panel():
    user_count = User.query.filter_by(is_superadmin=False, is_active=True).count()
    module_count = len(MODULES)
    return render_template('admin/panel.html', user_count=user_count, module_count=module_count)
