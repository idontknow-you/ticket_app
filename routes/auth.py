from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import check_password_hash, generate_password_hash
from models.user import User
from extensions import db

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        return redirect(url_for('public.submit'))

    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '')

        if not username or not password:
            flash('Username and password are required.', 'error')
            return render_template('auth/login.html')

        user = User.query.filter_by(username=username).first()

        if not user or not check_password_hash(user.password_hash, password):
            flash('Invalid username or password.', 'error')
            return render_template('auth/login.html')

        login_user(user)
        next_page = request.args.get('next')
        return redirect(url_for('public.submit'))

    return render_template('auth/login.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))


@auth_bp.route('/change-password', methods=['POST'])
@login_required
def change_password():
    current_password = request.form.get('current_password', '')
    new_password = request.form.get('new_password', '').strip()
    confirm_password = request.form.get('confirm_password', '').strip()

    if not current_password or not new_password or not confirm_password:
        flash('All fields are required.', 'error')
        return redirect(url_for('auth.profile'))

    if not check_password_hash(current_user.password_hash, current_password):
        flash('Current password is incorrect.', 'error')
        return redirect(url_for('auth.profile'))

    if new_password != confirm_password:
        flash('New passwords do not match.', 'error')
        return redirect(url_for('auth.profile'))

    if len(new_password) < 8:
        flash('New password must be at least 8 characters.', 'error')
        return redirect(url_for('auth.profile'))

    current_user.password_hash = generate_password_hash(new_password)
    db.session.commit()
    flash('Password changed successfully.', 'success')
    return redirect(url_for('auth.profile'))


@auth_bp.route('/profile')
@login_required
def profile():
    return render_template('auth/profile.html')


@auth_bp.route('/admin/reset-password/<int:user_id>', methods=['POST'])
@login_required
def reset_password(user_id):
    if not current_user.is_superadmin:
        flash('Access denied.', 'error')
        return redirect(url_for('public.submit'))

    user = User.query.get_or_404(user_id)
    new_password = request.form.get('new_password', '').strip()
    confirm_password = request.form.get('confirm_password', '').strip()

    if not new_password or not confirm_password:
        flash('All fields are required.', 'error')
        return redirect(url_for('admin.edit_user', user_id=user_id))

    if new_password != confirm_password:
        flash('Passwords do not match.', 'error')
        return redirect(url_for('admin.edit_user', user_id=user_id))

    if len(new_password) < 8:
        flash('Password must be at least 8 characters.', 'error')
        return redirect(url_for('admin.edit_user', user_id=user_id))

    user.password_hash = generate_password_hash(new_password)
    db.session.commit()
    flash(f'Password for {user.username} has been reset.', 'success')
    return redirect(url_for('admin.edit_user', user_id=user_id))
