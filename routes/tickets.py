import json
from flask import Blueprint, render_template, redirect, url_for, request, flash, jsonify
from flask_login import login_required, current_user
from models import FormConfig, FormSubmission, User
from extensions import db
from datetime import datetime
from decorators import permission_required

tickets_bp = Blueprint("tickets", __name__, url_prefix="/tickets")

STATUSES   = ["open", "in_progress", "closed"]
PRIORITIES = ["low", "medium", "high", "urgent"]


@tickets_bp.route("/")
@login_required
@permission_required("tickets", "can_view")
def dashboard():
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

    if f_search:
        term = f_search.lower()
        submissions = [
            s for s in submissions
            if term in s.ticket_id.lower()
            or term in json.dumps(s.data).lower()
        ]

    forms = FormConfig.query.filter_by(is_deleted=False).order_by(FormConfig.order).all()

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
@permission_required("tickets", "can_view")
def save_col_prefs():
    data = request.get_json()
    slug  = data.get("slug", "")
    prefs = data.get("prefs", {})
    if slug:
        current_user.set_column_prefs(slug, prefs)
        db.session.commit()
    return jsonify({"ok": True})


@tickets_bp.route("/<int:submission_id>")
@login_required
@permission_required("tickets", "can_view")
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
@permission_required("tickets", "can_view")
def update(submission_id):
    sub = FormSubmission.query.filter_by(id=submission_id, is_deleted=False).first_or_404()

    can_edit   = current_user.is_superadmin or current_user.has_permission("tickets", "can_edit")
    can_assign = current_user.is_superadmin or current_user.has_permission("tickets", "can_assign")

    # Must have at least one of these to POST changes
    if not can_edit and not can_assign:
        flash("You don't have permission to update tickets.", "error")
        return redirect(url_for("tickets.detail", submission_id=submission_id))

    new_status   = request.form.get("status")
    new_priority = request.form.get("priority")
    new_assigned = request.form.get("assigned_to")
    note_text    = request.form.get("note", "").strip()

    changes      = []
    status_event = None
    assigned_event = None

    if can_edit:
        if new_status and new_status in STATUSES and new_status != sub.status:
            changes.append(f"Status: {sub.status} → {new_status}")
            sub.status = new_status
            status_event = "ticket_closed" if new_status == "closed" else "ticket_status_changed"

        if new_priority and new_priority in PRIORITIES and new_priority != sub.priority:
            changes.append(f"Priority: {sub.priority or '—'} → {new_priority}")
            sub.priority = new_priority

        if note_text:
            pass  # handled below in log entry

    if can_assign:
        if new_assigned is not None:
            aid = int(new_assigned) if new_assigned else None
            if aid != sub.assigned_to:
                agent = db.session.get(User, aid) if aid else None
                changes.append(f"Assigned to: {agent.username if agent else 'nobody'}")
                sub.assigned_to = aid
                assigned_event = "ticket_assigned"

    if note_text or changes:
        log_entry = {
            "at":     datetime.utcnow().isoformat(),
            "by_id":  current_user.id,
            "by":     current_user.username,
            "action": "; ".join(changes) if changes else "",
            "note":   note_text if can_edit else "",
        }
        notes = list(sub.notes or [])
        notes.append(log_entry)
        sub.notes = notes

    db.session.commit()

    # ── Fire mail events ──────────────────────────────────────────────────────
    # extra_note comes from the pre-send popup (agent's personal message).
    # send_mail=0 means the agent explicitly chose to skip the mail.
    send_mail  = request.form.get("send_mail", "1") != "0"
    extra_note = request.form.get("extra_note", "").strip()

    if send_mail:
        try:
            from services.mail_service import enqueue_event
            extra = {
                "changed_by": current_user.username,
                "note_text":  note_text,
                "extra_note": extra_note,
            }
            queued = []
            if status_event:
                queued += enqueue_event(status_event, submission=sub, extra_vars=extra)
            if assigned_event:
                queued += enqueue_event(assigned_event, submission=sub, extra_vars=extra)
            if note_text and can_edit and not status_event and not assigned_event:
                queued += enqueue_event("ticket_reply_added", submission=sub, extra_vars=extra)

            # Attach the agent's personal note to every queued item
            if extra_note and queued:
                for q in queued:
                    q.extra_note = extra_note
                db.session.commit()

        except Exception:
            pass  # never break the ticket flow due to mail errors

    flash("Ticket updated.", "success")
    return redirect(url_for("tickets.detail", submission_id=submission_id))


@tickets_bp.route("/<int:submission_id>/delete", methods=["POST"])
@login_required
@permission_required("tickets", "can_delete")
def delete(submission_id):
    sub = FormSubmission.query.filter_by(id=submission_id, is_deleted=False).first_or_404()
    sub.is_deleted = True
    db.session.commit()
    flash("Ticket deleted.", "success")
    return redirect(url_for("tickets.dashboard"))