from flask import Blueprint, render_template, redirect, session, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from urllib.parse import urlparse, urljoin
from extensions import db
from models import User


def _is_safe_url(target):
    ref_url  = urlparse(request.host_url)
    test_url = urlparse(urljoin(request.host_url, target))
    return test_url.scheme in ("http", "https") and ref_url.netloc == test_url.netloc

auth_bp = Blueprint("auth", __name__)


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    if current_user.is_authenticated:
        return redirect(url_for("tickets.dashboard"))

    if request.method == "POST":
        username = request.form.get("username", "").strip()
        password = request.form.get("password", "")

        if not username or not password:
            flash("Please enter both username and password.", "error")
            return render_template("auth/login.html")

        user = User.query.filter_by(username=username, is_active=True).first()
        if user and user.check_password(password):
            login_user(user)
            next_page = request.args.get("next")
            if next_page and not _is_safe_url(next_page):
                next_page = None
            return redirect(next_page or url_for("tickets.dashboard"))

        flash("Invalid username or password.", "error")

    return render_template("auth/login.html")


@auth_bp.route("/logout")
@login_required
def logout():
    logout_user()
    session.clear()
    response = redirect(url_for("auth.login"))
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@auth_bp.after_request
def add_no_cache(response):
    if not current_user.is_authenticated:
        response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
        response.headers['Pragma'] = 'no-cache'
        response.headers['Expires'] = '0'
    return response


@auth_bp.route("/no-access")
@login_required
def no_access():
    return render_template("auth/no_access.html")


@auth_bp.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    # Find user with this token
    user = User.query.filter_by(reset_token=token).first()

    if not user or not user.is_reset_token_valid(token):
        flash("This reset link is invalid or has expired.", "error")
        return redirect(url_for("auth.login"))

    if request.method == "POST":
        password  = request.form.get("password", "")
        confirm   = request.form.get("confirm_password", "")

        if not password or len(password) < 6:
            flash("Password must be at least 6 characters.", "error")
            return render_template("auth/reset_password.html", token=token)

        if password != confirm:
            flash("Passwords do not match.", "error")
            return render_template("auth/reset_password.html", token=token)

        user.set_password(password)
        user.clear_reset_token()
        db.session.commit()

        flash("Your password has been reset. Please sign in.", "success")
        return redirect(url_for("auth.login"))

    return render_template("auth/reset_password.html", token=token, user=user)