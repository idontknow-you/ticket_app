"""
routes/mail.py

/mail/templates              – global template editor
/mail/templates/<form>       – per-form template editor
/mail/logs                   – log viewer with filters
/mail/queue                  – queue viewer + manual send
/mail/queue/<id>/send        – manual send
/mail/queue/<id>/edit        – pre-send edit popup (POST)
/mail/process                – trigger queue processing (superadmin)
/mail/preview                – preview rendered template (AJAX)

/mail/custom/list            – list custom templates (JSON)
/mail/custom/save            – create or update custom template (JSON POST)
/mail/custom/<id>/send       – queue a custom template for sending (POST)
/mail/custom/<id>/delete     – delete a custom template (POST)
/mail/users/search           – search users by name/email (JSON)
/mail/submitters/<form_id>   – unique submitter emails for a form (JSON)
"""
import json
from flask import (Blueprint, render_template, redirect, url_for,
                   request, flash, jsonify)
from flask_login import login_required, current_user
from decorators import superadmin_required, permission_required
from extensions import db
from models import FormConfig, User
from models.mail import MailTemplate
from models.mail_queue import MailQueue, MailLog, MAIL_EVENTS
from models.mail_custom import CustomMailTemplate          # ← new model (see below)
from models.form_submission import FormSubmission
from services.mail_service import (
    get_effective_template, build_variables, render_template_str,
    resolve_recipients, process_queue, send_queue_item_now, enqueue_event
)
from utils.mail import send_email
from models.settings import get_setting

mail_bp = Blueprint("mail", __name__, url_prefix="/mail")


# ─────────────────────────────────────────────────────────────────────────────
# Helpers
# ─────────────────────────────────────────────────────────────────────────────

EVENT_LABELS = {
    "ticket_submitted":      "Ticket Submitted",
    "ticket_assigned":       "Ticket Assigned",
    "ticket_status_changed": "Status Changed",
    "ticket_reply_added":    "Reply / Note Added",
    "ticket_closed":         "Ticket Closed",
    "password_reset":        "Password Reset",
}

DEFAULT_SUBJECTS = {
    "ticket_submitted":      "We received your request — Ticket {{ticket_id}}",
    "ticket_assigned":       "Ticket {{ticket_id}} has been assigned to you",
    "ticket_status_changed": "Your ticket {{ticket_id}} status has been updated",
    "ticket_reply_added":    "New reply on your ticket {{ticket_id}}",
    "ticket_closed":         "Your ticket {{ticket_id}} has been closed",
    "password_reset":        "Reset your password",
}

DEFAULT_BODIES = {
    "ticket_submitted": """<div style="font-family:sans-serif;max-width:520px;margin:0 auto;color:#111">
  <h2 style="font-size:18px">We received your request</h2>
  <p style="color:#555;font-size:14px">Hi {{submitter_name}},</p>
  <p style="color:#555;font-size:14px">
    Your ticket has been created and our team will be in touch shortly.
  </p>
  <p style="color:#999;font-size:12px;margin-top:16px">
    Reference number: {{ticket_id}} &nbsp;·&nbsp; Submitted: {{submitted_at}}
  </p>
</div>""",

    "ticket_assigned": """<div style="font-family:sans-serif;max-width:520px;margin:0 auto;color:#111">
  <h2 style="font-size:18px">A ticket has been assigned to you</h2>
  <p style="color:#555;font-size:14px">Hi {{assigned_agent}},</p>
  <p style="color:#555;font-size:14px">
    Ticket {{ticket_id}} from {{form_name}} has been assigned to you.<br>
    Priority: {{ticket_priority}}
  </p>
</div>""",

    "ticket_status_changed": """<div style="font-family:sans-serif;max-width:520px;margin:0 auto;color:#111">
  <h2 style="font-size:18px">Your ticket status has been updated</h2>
  <p style="color:#555;font-size:14px">
    The status of ticket {{ticket_id}} has been changed to <strong>{{ticket_status}}</strong>.
  </p>
</div>""",

    "ticket_reply_added": """<div style="font-family:sans-serif;max-width:520px;margin:0 auto;color:#111">
  <h2 style="font-size:18px">You have a new reply</h2>
  <p style="color:#555;font-size:14px">
    A new note has been added to ticket {{ticket_id}}.
  </p>
</div>""",

    "ticket_closed": """<div style="font-family:sans-serif;max-width:520px;margin:0 auto;color:#111">
  <h2 style="font-size:18px">Your ticket has been closed</h2>
  <p style="color:#555;font-size:14px">Hi {{submitter_name}},</p>
  <p style="color:#555;font-size:14px">
    Ticket {{ticket_id}} has been resolved and closed. Thank you for reaching out!
  </p>
</div>""",

    "password_reset": """<div style="font-family:sans-serif;max-width:520px;margin:0 auto;color:#111">
  <h2 style="font-size:18px">Reset your password</h2>
  <p style="color:#555;font-size:14px">
    Click the button below to reset your password. This link expires in 24 hours.
  </p>
  <a href="{{reset_url}}" style="display:inline-block;background:#0b0380;color:#fff;
     text-decoration:none;font-size:14px;padding:10px 24px;border-radius:8px;margin-top:8px">
    Reset Password
  </a>
</div>""",
}

ALL_VARIABLES = [
    ("ticket_id",       "Ticket ID"),
    ("ticket_status",   "Status"),
    ("ticket_priority", "Priority"),
    ("form_name",       "Form Name"),
    ("submitter_name",  "Submitter Name"),
    ("submitter_email", "Submitter Email"),
    ("assigned_agent",  "Assigned Agent"),
    ("submitted_at",    "Submitted At"),
    ("system_name",     "System Name"),
    ("reset_url",       "Password Reset URL"),
]


def _get_or_create_global() -> MailTemplate:
    t = MailTemplate.query.filter_by(scope="global", form_config_id=None, is_deleted=False).first()
    if not t:
        t = MailTemplate(scope="global", templates=_default_templates_dict(), mail_enabled=True)
        db.session.add(t)
        db.session.commit()
    return t


def _default_templates_dict() -> dict:
    """
    Full default template config for all events.
    Used when creating a fresh global or form-level template so every event
    has subjects, bodies, and recipients out of the box.
    """
    default_recipients = {
        "submitter":            True,
        "assigned_agent":       False,
        "all_admins":           False,
        "field_email_field_id": None,
        "custom":               [],
    }
    agent_recipients = {**default_recipients, "submitter": False, "assigned_agent": True}
    both_recipients  = {**default_recipients, "assigned_agent": True}

    return {
        event: {
            "enabled":    True,
            "subject":    DEFAULT_SUBJECTS.get(event, ""),
            "body":       DEFAULT_BODIES.get(event, ""),
            "recipients": agent_recipients if event == "ticket_assigned" else default_recipients,
        }
        for event in MAIL_EVENTS
    }


def _get_or_create_form_template(form: FormConfig) -> MailTemplate:
    t = MailTemplate.query.filter_by(form_config_id=form.id, is_deleted=False).first()
    if not t:
        t = MailTemplate(scope="form", form_config_id=form.id,
                         templates=_default_templates_dict(), mail_enabled=True)
        db.session.add(t)
        db.session.commit()
    return t


# ─────────────────────────────────────────────────────────────────────────────
# Template editor — global
# ─────────────────────────────────────────────────────────────────────────────

@mail_bp.route("/templates", methods=["GET"])
@login_required
@permission_required("mails", "can_view")
def templates_global():
    tmpl            = _get_or_create_global()
    forms           = FormConfig.query.filter_by(is_deleted=False).order_by(FormConfig.order).all()
    custom_templates = CustomMailTemplate.query.filter_by(is_deleted=False).order_by(
                          CustomMailTemplate.updated_at.desc()).all()
    return render_template(
        "mail/templates.html",
        tmpl=tmpl,
        scope="global",
        form=None,
        forms=forms,
        forms_json=[{"id": f.id, "name": f.name} for f in forms],
        events=MAIL_EVENTS,
        event_labels=EVENT_LABELS,
        default_subjects=DEFAULT_SUBJECTS,
        default_bodies=DEFAULT_BODIES,
        all_variables=ALL_VARIABLES,
        custom_templates=custom_templates,
    )


@mail_bp.route("/templates", methods=["POST"])
@login_required
@permission_required("mails", "can_edit")
def templates_global_save():
    tmpl = _get_or_create_global()
    _save_template_from_form(tmpl, request.form)
    flash("Global mail templates saved.", "success")
    return redirect(url_for("mail.templates_global"))


# ─────────────────────────────────────────────────────────────────────────────
# Template editor — per form
# ─────────────────────────────────────────────────────────────────────────────

@mail_bp.route("/templates/<int:form_id>", methods=["GET"])
@login_required
@permission_required("mails", "can_view")
def templates_form(form_id):
    form  = FormConfig.query.filter_by(id=form_id, is_deleted=False).first_or_404()
    tmpl  = _get_or_create_form_template(form)
    forms = FormConfig.query.filter_by(is_deleted=False).order_by(FormConfig.order).all()
    custom_templates = CustomMailTemplate.query.filter_by(is_deleted=False).order_by(
                          CustomMailTemplate.updated_at.desc()).all()

    email_fields = [
        f for f in (form.sorted_fields or [])
        if f.get("type") in ("email", "text") and "email" in f.get("label", "").lower()
    ]

    return render_template(
        "mail/templates.html",
        tmpl=tmpl,
        scope="form",
        form=form,
        forms=forms,
        forms_json=[{"id": f.id, "name": f.name} for f in forms],
        events=MAIL_EVENTS,
        event_labels=EVENT_LABELS,
        default_subjects=DEFAULT_SUBJECTS,
        default_bodies=DEFAULT_BODIES,
        all_variables=ALL_VARIABLES,
        email_fields=email_fields,
        custom_templates=custom_templates,
    )


@mail_bp.route("/templates/<int:form_id>", methods=["POST"])
@login_required
@permission_required("mails", "can_edit")
def templates_form_save(form_id):
    form = FormConfig.query.filter_by(id=form_id, is_deleted=False).first_or_404()
    tmpl = _get_or_create_form_template(form)
    _save_template_from_form(tmpl, request.form)
    flash(f'Mail templates for "{form.name}" saved.', "success")
    return redirect(url_for("mail.templates_form", form_id=form_id))


def _save_template_from_form(tmpl: MailTemplate, form_data):
    """Parse the submitted form and update the MailTemplate record."""
    tmpl.mail_enabled         = form_data.get("mail_enabled") == "on"
    tmpl.reply_to             = form_data.get("reply_to", "").strip() or None
    tmpl.from_name            = form_data.get("from_name", "").strip() or None
    tmpl.use_global_template  = form_data.get("use_global_template") == "on"

    templates = {}
    for event in MAIL_EVENTS:
        enabled  = form_data.get(f"{event}__enabled") == "on"
        subject  = form_data.get(f"{event}__subject", "").strip()
        body     = form_data.get(f"{event}__body", "").strip()

        custom_raw = form_data.get(f"{event}__custom_recipients", "")
        custom = [e.strip() for e in custom_raw.splitlines() if e.strip()]

        recipients = {
            "submitter":            form_data.get(f"{event}__recip_submitter") == "on",
            "assigned_agent":       form_data.get(f"{event}__recip_agent") == "on",
            "all_admins":           form_data.get(f"{event}__recip_admins") == "on",
            "field_email_field_id": form_data.get(f"{event}__recip_field") or None,
            "custom":               custom,
        }

        templates[event] = {
            "enabled":    enabled,
            "subject":    subject,
            "body":       body,
            "recipients": recipients,
        }

    tmpl.templates = templates
    db.session.commit()


# ─────────────────────────────────────────────────────────────────────────────
# Preview (AJAX)
# ─────────────────────────────────────────────────────────────────────────────

@mail_bp.route("/preview", methods=["POST"])
@login_required
@permission_required("mails", "can_view")
def preview():
    data    = request.get_json()
    subject = data.get("subject", "")
    body    = data.get("body", "")

    sample = {
        "ticket_id":       "SUP-0042",
        "ticket_status":   "In Progress",
        "ticket_priority": "High",
        "form_name":       "IT Support",
        "submitter_name":  "Jane Smith",
        "submitter_email": "jane@example.com",
        "assigned_agent":  "Agent007",
        "submitted_at":    "01 Jun 2025 09:30",
        "system_name":     get_setting("smtp_from_name", "Support System"),
        "reset_url":       "https://example.com/reset/token123",
        "event":           "preview",
    }

    return jsonify({
        "subject": render_template_str(subject, sample),
        "body":    render_template_str(body, sample),
    })


# ─────────────────────────────────────────────────────────────────────────────
# Send test email
# ─────────────────────────────────────────────────────────────────────────────

@mail_bp.route("/test-send", methods=["POST"])
@login_required
@permission_required("mails", "can_edit")
def test_send():
    to_email = request.form.get("test_email", "").strip()
    subject  = request.form.get("subject", "Test email")
    body     = request.form.get("body", "<p>Test email from your support system.</p>")
    redirect_to = request.form.get("redirect_to", url_for("mail.templates_global"))

    if not to_email:
        flash("Enter a test email address.", "error")
        return redirect(redirect_to)

    sample = {
        "ticket_id": "SUP-0042", "ticket_status": "Open",
        "form_name": "Test Form", "submitter_name": "Test User",
        "submitter_email": to_email, "assigned_agent": "Agent",
        "submitted_at": "01 Jun 2025",
        "system_name": get_setting("smtp_from_name", "Support System"),
    }
    rendered_subject = render_template_str(subject, sample)
    rendered_body    = render_template_str(body, sample)

    ok, err = send_email(to_email, rendered_subject, rendered_body)
    if ok:
        flash(f"Test email sent to {to_email}.", "success")
    else:
        flash(f"Failed: {err}", "error")

    return redirect(redirect_to)


# ─────────────────────────────────────────────────────────────────────────────
# Mail Logs
# ─────────────────────────────────────────────────────────────────────────────

@mail_bp.route("/logs")
@login_required
@permission_required("mails", "can_view")
def logs():
    f_event  = request.args.get("event", "")
    f_status = request.args.get("status", "")
    f_form   = request.args.get("form", "")
    f_date   = request.args.get("date", "")

    q = MailLog.query
    if f_event:
        q = q.filter(MailLog.event == f_event)
    if f_status:
        q = q.filter(MailLog.status == f_status)
    if f_form:
        fc = FormConfig.query.filter_by(slug=f_form, is_deleted=False).first()
        if fc:
            q = q.filter(MailLog.form_config_id == fc.id)
    if f_date:
        from datetime import datetime as dt
        try:
            day = dt.strptime(f_date, "%Y-%m-%d")
            from datetime import timedelta
            q = q.filter(MailLog.created_at >= day, MailLog.created_at < day + timedelta(days=1))
        except ValueError:
            pass

    logs_list = q.order_by(MailLog.created_at.desc()).limit(500).all()
    forms     = FormConfig.query.filter_by(is_deleted=False).order_by(FormConfig.order).all()

    return render_template(
        "mail/logs.html",
        logs=logs_list,
        forms=forms,
        events=MAIL_EVENTS,
        event_labels=EVENT_LABELS,
        f_event=f_event,
        f_status=f_status,
        f_form=f_form,
        f_date=f_date,
    )


@mail_bp.route("/logs/<int:log_id>/body")
@login_required
@permission_required("mails", "can_view")
def log_body(log_id):
    log = MailLog.query.get_or_404(log_id)
    return jsonify({"body": log.html_body or "<em>No body stored.</em>"})


# ─────────────────────────────────────────────────────────────────────────────
# Queue
# ─────────────────────────────────────────────────────────────────────────────

@mail_bp.route("/queue")
@login_required
@permission_required("mails", "can_view")
def queue():
    f_status = request.args.get("status", "")
    q = MailQueue.query
    if f_status:
        q = q.filter(MailQueue.status == f_status)
    items = q.order_by(MailQueue.created_at.desc()).limit(200).all()
    return render_template("mail/queue.html", items=items, f_status=f_status)


@mail_bp.route("/queue/<int:item_id>/send", methods=["POST"])
@login_required
@permission_required("mails", "can_edit")
def queue_send(item_id):
    ok, err = send_queue_item_now(item_id)
    if ok:
        flash("Email sent successfully.", "success")
    else:
        flash(f"Send failed: {err}", "error")
    return redirect(url_for("mail.queue"))


@mail_bp.route("/queue/<int:item_id>/edit", methods=["GET"])
@login_required
@permission_required("mails", "can_view")
def queue_edit(item_id):
    item = MailQueue.query.get_or_404(item_id)
    return jsonify({
        "id":               item.id,
        "to_email":         item.to_email,
        "subject":          item.subject,
        "html_body":        item.html_body,
        "extra_recipients": item.extra_recipients or [],
        "extra_note":       item.extra_note or "",
        "event":            item.event,
        "status":           item.status,
        "retry_count":      item.retry_count,
        "submission_id":    item.submission_id,
        "form_name":        item.form.name if item.form else "",
    })


@mail_bp.route("/queue/<int:item_id>/save", methods=["POST"])
@login_required
@permission_required("mails", "can_edit")
def queue_save(item_id):
    item = MailQueue.query.get_or_404(item_id)
    data = request.get_json()

    item.subject    = data.get("subject", item.subject)
    item.html_body  = data.get("html_body", item.html_body)
    item.extra_note = data.get("extra_note", "")

    extra = []
    for r in (data.get("extra_recipients") or []):
        if r.get("email"):
            extra.append({"email": r["email"], "name": r.get("name", "")})
    item.extra_recipients = extra

    if item.status == "failed":
        item.status = "queued"
        item.retry_count = 0

    db.session.commit()
    return jsonify({"ok": True})


@mail_bp.route("/process", methods=["POST"])
@login_required
@permission_required("mails", "can_edit")
def process():
    result = process_queue()
    flash(f"Processed queue — sent: {result['sent']}, failed: {result['failed']}, retrying: {result['skipped']}.", "success")
    return redirect(url_for("mail.queue"))


# ─────────────────────────────────────────────────────────────────────────────
# Custom Templates — list
# ─────────────────────────────────────────────────────────────────────────────

@mail_bp.route("/custom/list")
@login_required
@permission_required("mails", "can_view")
def custom_list():
    templates = CustomMailTemplate.query.filter_by(is_deleted=False).order_by(
        CustomMailTemplate.updated_at.desc()).all()
    return jsonify([t.to_dict() for t in templates])


# ─────────────────────────────────────────────────────────────────────────────
# Custom Templates — save (create or update)
# ─────────────────────────────────────────────────────────────────────────────

@mail_bp.route("/custom/save", methods=["POST"])
@login_required
@permission_required("mails", "can_edit")
def custom_save():
    data = request.get_json()

    name    = (data.get("name") or "").strip()
    subject = (data.get("subject") or "").strip()
    body    = (data.get("body") or "").strip()
    recips  = data.get("recipients") or []   # [{email, name}, ...]
    send_now = bool(data.get("send_now", False))
    tmpl_id  = data.get("id")

    if not name:
        return jsonify({"ok": False, "error": "Template name is required."}), 400

    if tmpl_id:
        tmpl = CustomMailTemplate.query.filter_by(id=tmpl_id, is_deleted=False).first()
        if not tmpl:
            return jsonify({"ok": False, "error": "Template not found."}), 404
    else:
        tmpl = CustomMailTemplate()
        db.session.add(tmpl)

    tmpl.name       = name
    tmpl.subject    = subject
    tmpl.body       = body
    tmpl.recipients = recips          # stored as JSON list
    db.session.commit()

    if send_now and recips:
        _enqueue_custom(tmpl)

    return jsonify({"ok": True, "id": tmpl.id})


# ─────────────────────────────────────────────────────────────────────────────
# Custom Templates — send now
# ─────────────────────────────────────────────────────────────────────────────

@mail_bp.route("/custom/<int:tmpl_id>/send", methods=["POST"])
@login_required
@permission_required("mails", "can_edit")
def custom_send(tmpl_id):
    tmpl = CustomMailTemplate.query.filter_by(id=tmpl_id, is_deleted=False).first_or_404()
    if not tmpl.recipients:
        return jsonify({"ok": False, "error": "No recipients saved on this template."}), 400
    queued = _enqueue_custom(tmpl)
    return jsonify({"ok": True, "queued": queued})


def _enqueue_custom(tmpl: "CustomMailTemplate") -> int:
    """Push one MailQueue item per recipient for a custom template."""
    count = 0
    for r in (tmpl.recipients or []):
        email = (r.get("email") or "").strip()
        if not email:
            continue
        item = MailQueue(
            event        = "custom",
            to_email     = email,
            subject      = tmpl.subject or "(no subject)",
            html_body    = tmpl.body or "",
            status       = "queued",
            extra_note   = f"Custom template: {tmpl.name}",
        )
        db.session.add(item)
        count += 1
    db.session.commit()
    return count


# ─────────────────────────────────────────────────────────────────────────────
# Custom Templates — delete
# ─────────────────────────────────────────────────────────────────────────────

@mail_bp.route("/custom/<int:tmpl_id>/delete", methods=["POST"])
@login_required
@permission_required("mails", "can_edit")
def custom_delete(tmpl_id):
    tmpl = CustomMailTemplate.query.filter_by(id=tmpl_id, is_deleted=False).first_or_404()
    tmpl.soft_delete()
    db.session.commit()
    return jsonify({"ok": True})


# ─────────────────────────────────────────────────────────────────────────────
# User search  (for recipient picker)
# ─────────────────────────────────────────────────────────────────────────────

@mail_bp.route("/users/search")
@login_required
@permission_required("mails", "can_view")
def users_search():
    q = (request.args.get("q") or "").strip()
    if len(q) < 2:
        return jsonify([])

    like = f"%{q}%"
    users = (User.query
             .filter(
                 User.is_deleted == False,
                 db.or_(
                     User.email.ilike(like),
                     User.name.ilike(like),
                 )
             )
             .order_by(User.name)
             .limit(20)
             .all())

    return jsonify([
        {"email": u.email, "name": u.name or ""}
        for u in users
        if u.email
    ])


# ─────────────────────────────────────────────────────────────────────────────
# Form submitters  (unique emails from submissions)
# ─────────────────────────────────────────────────────────────────────────────

@mail_bp.route("/submitters/<int:form_id>")
@login_required
@permission_required("mails", "can_view")
def submitters(form_id):
    form = FormConfig.query.filter_by(id=form_id, is_deleted=False).first_or_404()

    # Collect unique (email, name) pairs from all submissions for this form.
    # Adjust field names to match your FormSubmission model.
    subs = (FormSubmission.query
            .filter_by(form_config_id=form.id)
            .with_entities(FormSubmission.submitter_email, FormSubmission.submitter_name)
            .distinct()
            .limit(200)
            .all())

    seen = set()
    results = []
    for email, name in subs:
        email = (email or "").strip().lower()
        if email and email not in seen:
            seen.add(email)
            results.append({"email": email, "name": name or ""})

    return jsonify(results)