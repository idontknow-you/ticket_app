import secrets
import string
from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify, abort
from flask_login import login_required, current_user
from decorators import superadmin_required
from extensions import db
from models import FormConfig, User
from models.settings import get_setting, set_setting, Setting
from models.wiki_page import WikiPage
from utils.mail import send_password_reset_email
import copy
from sqlalchemy.orm.attributes import flag_modified

admin_bp = Blueprint("admin", __name__, url_prefix="/admin")

SMTP_KEYS = [
    ("smtp_host",       "SMTP Host",       "smtp.gmail.com",  "text"),
    ("smtp_port",       "SMTP Port",       "587",             "number"),
    ("smtp_username",   "SMTP Username",   "you@gmail.com",   "text"),
    ("smtp_password",   "SMTP Password",   "",                "password"),
    ("smtp_from_email", "From Email",      "you@gmail.com",   "email"),
    ("smtp_from_name",  "From Name",       "Support System",  "text"),
    ("smtp_use_tls",    "Use TLS",         "true",            "select"),
]

PERMISSION_MODULES = ["tickets","forms","user","wiki", "mails", "reports", "settings" ]
PERMISSION_ACTIONS = ["can_view", "can_create", "can_edit", "can_assign", "can_delete"]
MODULE_ACTIONS ={
    "tickets": ["can_view", "can_edit","can_assign", "can_delete"],
    "forms": ["can_view", "can_create", "can_edit", "can_delete"],
    "user": ["can_view", "can_create","can_edit", "can_delete"],
    "wiki": ["can_view", "can_create", "can_edit", "can_delete"],
    "mails": ["can_view", "can_edit"],
    "reports": ["can_view"],
    "settings": ["can_view", "can_edit"]
}
DEFAULT_PERMISSIONS = {
    "tickets": {"can_view": True},
}

@admin_bp.route("/")
@login_required
@superadmin_required
def panel():
    tab = request.args.get("tab", "users")
    forms = FormConfig.query.order_by(FormConfig.order).all()
    users = User.query.filter_by(is_deleted=False).order_by(User.created_at.desc()).all()
    wiki_pages = WikiPage.query.filter_by(is_deleted=False).order_by(WikiPage.id.desc()).all()
    smtp_settings = {key: get_setting(key, default) for key, _, default, _ in SMTP_KEYS}
    return render_template(
        "admin/panel.html",
        forms=forms, users=users, tab=tab,
        wiki_pages=wiki_pages,
        smtp_keys=SMTP_KEYS, smtp_settings=smtp_settings,
        permission_modules=PERMISSION_MODULES,
        permission_actions=PERMISSION_ACTIONS,
        module_actions=MODULE_ACTIONS,

    )


# ── Users ─────────────────────────────────────────────────────────────────────

@admin_bp.route("/users/create", methods=["POST"])
@login_required
def create_user():
    if not current_user.is_superadmin and not current_user.has_permission("user", "can_create"):
        abort(403)

    name          = request.form.get("name", "").strip()
    username      = request.form.get("username", "").strip()
    email         = request.form.get("email", "").strip() or None
    password      = request.form.get("password", "").strip()
    is_superadmin = request.form.get("is_superadmin") == "on"

    if not name or not username or not password:
        flash("Name, username and password are required.", "error")
        return redirect(url_for("admin.panel", tab="users"))

    if User.query.filter_by(username=username).first():
        flash(f"Username '{username}' is already taken.", "error")
        return redirect(url_for("admin.panel", tab="users"))

    if email and User.query.filter_by(email=email).first():
        flash(f"Email '{email}' is already in use.", "error")
        return redirect(url_for("admin.panel", tab="users"))

    default_permissions = copy.deepcopy(DEFAULT_PERMISSIONS)

    user = User(name=name, username=username, email=email,
                is_superadmin=is_superadmin, is_active=True,
                permissions=default_permissions)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    flash(f"User '{username}' created successfully.", "success")
    return redirect(url_for("admin.panel", tab="users"))


@admin_bp.route("/users/<int:user_id>/toggle", methods=["POST"])
@login_required
@superadmin_required
def toggle_user(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("You cannot deactivate your own account.", "error")
        return redirect(url_for("admin.panel", tab="users"))
    user.is_active = not user.is_active
    db.session.commit()
    state = "activated" if user.is_active else "deactivated"
    flash(f"User '{user.username}' {state}.", "success")
    return redirect(url_for("admin.panel", tab="users"))


@admin_bp.route("/users/<int:user_id>/delete", methods=["POST"])
@login_required
def delete_user(user_id):
    if not current_user.is_superadmin and not current_user.has_permission("user", "can_delete"):
        abort(403)

    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("You cannot delete your own account.", "error")
        return redirect(url_for("admin.panel", tab="users"))
    username = user.username
    user.soft_delete()
    db.session.commit()
    flash(f"User '{username}' deleted.", "success")
    return redirect(url_for("admin.panel", tab="users"))


@admin_bp.route("/users/<int:user_id>/send-reset", methods=["POST"])
@login_required
def send_reset(user_id):
    if not current_user.is_superadmin and not current_user.has_permission("user", "can_edit"):
        abort(403)

    user = User.query.get_or_404(user_id)
    if not user.email:
        flash(f"User '{user.username}' has no email address.", "error")
        return redirect(url_for("admin.panel", tab="users"))

    token = user.generate_reset_token()
    db.session.commit()

    reset_url = url_for("auth.reset_password", token=token, _external=True)
    success, error = send_password_reset_email(user, reset_url)

    if success:
        flash(f"Password reset email sent to {user.email}.", "success")
    else:
        flash(f"Failed to send email: {error}", "error")

    return redirect(url_for("admin.panel", tab="users"))


@admin_bp.route("/users/<int:user_id>/toggle-superadmin", methods=["POST"])
@login_required
@superadmin_required
def toggle_superadmin(user_id):
    user = User.query.get_or_404(user_id)
    if user.id == current_user.id:
        flash("You cannot change your own superadmin status.", "error")
        return redirect(url_for("admin.panel", tab="users"))
    user.is_superadmin = not user.is_superadmin
    db.session.commit()
    state = "granted" if user.is_superadmin else "revoked"
    flash(f"Superadmin {state} for '{user.username}'.", "success")
    return redirect(url_for("admin.panel", tab="users"))


# ── Permissions ───────────────────────────────────────────────────────────────

@admin_bp.route("/users/<int:user_id>/permissions", methods=["POST"])
@login_required
@superadmin_required
def save_permission(user_id):
    user = User.query.get_or_404(user_id)
    if user.is_superadmin:
        return jsonify({"ok": False, "error": "Superadmins always have full access."}), 400

    data   = request.get_json(force=True)
    module = data.get("module")
    action = data.get("action")
    value  = bool(data.get("value"))

    if module not in MODULE_ACTIONS:
        return jsonify({"ok": False, "error": "Invalid module."}), 400
    if action not in MODULE_ACTIONS[module]:
        return jsonify({"ok": False, "error": "Invalid action."}), 400

    # Make a deep copy so SQLAlchemy sees a new object
    perms = copy.deepcopy(user.permissions or {})

    if module not in perms:
        perms[module] = {a: False for a in MODULE_ACTIONS[module]}

    perms[module][action] = value
    user.permissions = perms

    # Tell SQLAlchemy this JSON column was mutated
    flag_modified(user, "permissions")

    db.session.commit()
    return jsonify({"ok": True})


# ── Settings ──────────────────────────────────────────────────────────────────

@admin_bp.route("/settings/smtp", methods=["POST"])
@login_required
def save_smtp():
    if not current_user.is_superadmin and not current_user.has_permission("settings", "can_edit"):
        abort(403)

    for key, _, _, _ in SMTP_KEYS:
        value = request.form.get(key, "").strip()
        set_setting(key, value)
    flash("SMTP settings saved.", "success")
    return redirect(url_for("admin.panel", tab="settings"))


@admin_bp.route("/settings/smtp/test", methods=["POST"])
@login_required
def test_smtp():
    if not current_user.is_superadmin and not current_user.has_permission("settings", "can_view"):
        abort(403)

    from utils.mail import send_email
    to_email = request.form.get("test_email", "").strip()
    if not to_email:
        flash("Enter a test email address.", "error")
        return redirect(url_for("admin.panel", tab="settings"))

    success, error = send_email(
        to_email,
        subject="SMTP Test — Support System",
        html_body="<p>Your SMTP configuration is working correctly.</p>",
        text_body="Your SMTP configuration is working correctly.",
    )
    if success:
        flash(f"Test email sent to {to_email}.", "success")
    else:
        flash(f"Test failed: {error}", "error")

    return redirect(url_for("admin.panel", tab="settings"))