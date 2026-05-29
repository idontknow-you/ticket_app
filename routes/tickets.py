import json
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from models import FormConfig, FormSubmission, User
from extensions import db
from datetime import datetime

tickets_bp = Blueprint("tickets", __name__, url_prefix="/tickets")

STATUSES   = ["open", "in_progress", "closed"]
PRIORITIES = ["low", "medium", "high", "urgent"]


@tickets_bp.route("/")
@login_required
def dashboard():
    # ── Filters from query string ─────────────────────────────────────────────
    f_form     = request.args.get("form", "")
    f_status   = request.args.get("status", "")
    f_priority = request.args.get("priority", "")
    f_search   = request.args.get("q", "").strip()

    query = FormSubmission.query.filter_by(is_deleted=False)

    if f_form:
        fc = FormConfig.query.filter_by(slug=f_form, is_deleted=False).first()
        if fc:
            query = query.filter(FormSubmission.form_config_id == fc.id)

    if f_status:
        query = query.filter(FormSubmission.status == f_status)

    if f_priority:
        query = query.filter(FormSubmission.priority == f_priority)

    submissions = query.order_by(FormSubmission.submitted_at.desc()).all()

    # Simple text search over ticket_id and JSON data (string match)
    if f_search:
        term = f_search.lower()
        submissions = [
            s for s in submissions
            if term in s.ticket_id.lower()
            or term in json.dumps(s.data).lower()
        ]

    forms = FormConfig.query.filter_by(is_deleted=False).order_by(FormConfig.order).all()

    # ── Column prefs for the active form ─────────────────────────────────────
    active_form = None
    if f_form:
        active_form = FormConfig.query.filter_by(slug=f_form, is_deleted=False).first()

    col_prefs = {}
    if active_form:
        col_prefs = current_user.get_column_prefs(active_form.slug)
    return render_template(
        "tickets/dashboard.html",
        submissions=submissions,
        forms=forms,
        statuses=STATUSES,
        priorities=PRIORITIES,
        f_form=f_form,
        f_status=f_status,
        f_priority=f_priority,
        f_search=f_search,
        active_form=active_form,
        col_prefs=col_prefs,
    )


@tickets_bp.route("/col-prefs", methods=["POST"])
@login_required
def save_col_prefs():
    """AJAX: save column visibility for a form slug."""
    data = request.get_json()
    slug  = data.get("slug", "")
    prefs = data.get("prefs", {})
    if slug:
        current_user.set_column_prefs(slug, prefs)
        db.session.commit()
    return jsonify({"ok": True})


@tickets_bp.route("/<int:submission_id>")
@login_required
def detail(submission_id):
    submission = FormSubmission.query.filter_by(id=submission_id, is_deleted=False).first_or_404()
    agents = User.query.filter_by(is_active=True, is_deleted=False).all()
    return render_template(
        "tickets/detail.html",
        submission=submission,
        statuses=STATUSES,
        priorities=PRIORITIES,
        agents=agents,
    )


@tickets_bp.route("/<int:submission_id>/update", methods=["POST"])
@login_required
def update(submission_id):
    sub = FormSubmission.query.filter_by(id=submission_id, is_deleted=False).first_or_404()

    new_status   = request.form.get("status")
    new_priority = request.form.get("priority")
    new_assigned = request.form.get("assigned_to")
    note_text    = request.form.get("note", "").strip()

    changes = []

    if new_status and new_status in STATUSES and new_status != sub.status:
        changes.append(f"Status: {sub.status} → {new_status}")
        sub.status = new_status

    if new_priority and new_priority in PRIORITIES and new_priority != sub.priority:
        changes.append(f"Priority: {sub.priority or '—'} → {new_priority}")
        sub.priority = new_priority

    if new_assigned is not None:
        aid = int(new_assigned) if new_assigned else None
        if aid != sub.assigned_to:
            agent = User.query.get(aid) if aid else None
            changes.append(f"Assigned to: {agent.username if agent else 'nobody'}")
            sub.assigned_to = aid

    if note_text or changes:
        log_entry = {
            "at":     datetime.utcnow().isoformat(),
            "by_id":  current_user.id,
            "by":     current_user.username,
            "action": "; ".join(changes) if changes else "",
            "note":   note_text,
        }
        notes = list(sub.notes or [])
        notes.append(log_entry)
        sub.notes = notes

    db.session.commit()
    flash("Ticket updated.", "success")
    return redirect(url_for("tickets.detail", submission_id=submission_id))