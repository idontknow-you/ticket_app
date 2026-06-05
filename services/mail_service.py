"""
ticketing_app/services/mail_service.py

Handles:
 - resolving the effective template for an event (form override > global)
 - rendering {{variables}} in subject + body
 - resolving recipient list
 - enqueuing mails into MailQueue
 - processing the queue (send + retry + log)
"""
import re
from datetime import datetime
from extensions import db
from models.mail import MailTemplate
from models.mail_queue import MailQueue, MailLog, MAIL_EVENTS
from models.settings import get_setting
from utils.mail import send_email


# ─────────────────────────────────────────────────────────────────────────────
# Variable substitution
# ─────────────────────────────────────────────────────────────────────────────

def render_template_str(text: str, variables: dict) -> str:
    """Replace {{key}} placeholders in text with values from variables dict."""
    if not text:
        return text or ""

    def replacer(m):
        key = m.group(1).strip()
        return str(variables.get(key, m.group(0)))

    return re.sub(r"\{\{(.+?)\}\}", replacer, text)


def build_variables(submission=None, event: str = "", extra: dict = None) -> dict:
    """Build the variables dict available to templates."""
    vars_ = {
        "system_name": get_setting("smtp_from_name", "Support System"),
        "event": event,
    }

    if submission:
        form = submission.form
        assignee = submission.assignee

        vars_.update({
            "ticket_id":       submission.ticket_id,
            "ticket_status":   submission.status,
            "ticket_priority": submission.priority or "—",
            "form_name":       form.name if form else "",
            "form_slug":       form.slug if form else "",
            "assigned_agent":  assignee.username if assignee else "Unassigned",
            "submitted_at":    submission.submitted_at.strftime("%d %b %Y %H:%M") if submission.submitted_at else "",
        })

        # Flatten all form field values as {{field_<id>}} and {{field_<label>}}
        for field in (submission.version_fields or []):
            fid   = field.get("id", "")
            label = field.get("label", "").lower().replace(" ", "_")
            val   = submission.data.get(fid, "")
            if isinstance(val, list):
                val = ", ".join(str(v) for v in val if isinstance(v, str))
            vars_[f"field_{fid}"]   = val
            vars_[f"field_{label}"] = val

        # Submitter email / name — look for common field labels
        for field in (submission.version_fields or []):
            label_lower = field.get("label", "").lower()
            fid = field.get("id", "")
            if any(k in label_lower for k in ("email",)):
                vars_.setdefault("submitter_email", submission.data.get(fid, ""))
            if any(k in label_lower for k in ("name", "full name", "your name")):
                vars_.setdefault("submitter_name", submission.data.get(fid, ""))

        vars_.setdefault("submitter_email", "")
        vars_.setdefault("submitter_name",  "")

    if extra:
        vars_.update(extra)

    return vars_


# ─────────────────────────────────────────────────────────────────────────────
# Template resolution
# ─────────────────────────────────────────────────────────────────────────────

def get_effective_template(form_config_id=None) -> MailTemplate | None:
    """
    Return the effective MailTemplate for a form:
      1. form-specific template (if exists and not deleted)
      2. global template
    Returns None if neither exists.
    """
    if form_config_id:
        t = MailTemplate.query.filter_by(
            form_config_id=form_config_id, is_deleted=False
        ).first()
        if t:
            return t

    return MailTemplate.query.filter_by(
        scope="global", form_config_id=None, is_deleted=False
    ).first()


# ─────────────────────────────────────────────────────────────────────────────
# Recipient resolution
# ─────────────────────────────────────────────────────────────────────────────

def resolve_recipients(event_cfg: dict, submission=None) -> list[dict]:
    """
    Return a list of {"email": ..., "name": ...} dicts for an event.
    """
    from models import User

    recip_cfg = event_cfg.get("recipients", {})
    results   = []
    seen      = set()

    def _add(email, name=""):
        if email and email not in seen:
            seen.add(email)
            results.append({"email": email, "name": name or ""})

    # 1. Submitter
    if recip_cfg.get("submitter") and submission:
        email = ""
        name  = ""
        for field in (submission.version_fields or []):
            label_lower = field.get("label", "").lower()
            fid = field.get("id", "")
            if "email" in label_lower:
                email = submission.data.get(fid, "")
            if any(k in label_lower for k in ("name", "full name")):
                name = submission.data.get(fid, "")
        if email:
            _add(email, name)

    # 2. Assigned agent
    if recip_cfg.get("assigned_agent") and submission and submission.assignee:
        if submission.assignee.email:
            _add(submission.assignee.email, submission.assignee.name or submission.assignee.username)

    # 3. All admins
    if recip_cfg.get("all_admins"):
        for u in User.query.filter_by(is_active=True, is_deleted=False).all():
            if u.email:
                _add(u.email, u.name or u.username)

    # 4. Field-based email
    field_id = recip_cfg.get("field_email_field_id")
    if field_id and submission:
        val = submission.data.get(field_id, "")
        if val and isinstance(val, str):
            _add(val)

    # 5. Custom static list
    for addr in (recip_cfg.get("custom") or []):
        if isinstance(addr, str):
            _add(addr)
        elif isinstance(addr, dict):
            _add(addr.get("email", ""), addr.get("name", ""))

    return results


# ─────────────────────────────────────────────────────────────────────────────
# Enqueue
# ─────────────────────────────────────────────────────────────────────────────

def enqueue_event(event: str, submission=None, extra_vars: dict = None,
                  form_config_id: int = None) -> list[MailQueue]:
    """
    Build and enqueue mail(s) for an event. Returns list of created MailQueue rows.
    Does nothing if mail is disabled or event is disabled.
    """
    if event not in MAIL_EVENTS:
        return []

    fid = form_config_id or (submission.form_config_id if submission else None)
    tmpl = get_effective_template(fid)
    if not tmpl or not tmpl.mail_enabled:
        return []

    event_cfg = tmpl.get_event_cfg(event)
    if not event_cfg.get("enabled"):
        return []

    variables = build_variables(submission=submission, event=event, extra=extra_vars)
    subject   = render_template_str(event_cfg.get("subject", ""), variables)
    body      = render_template_str(event_cfg.get("body", ""), variables)
    recipients = resolve_recipients(event_cfg, submission=submission)

    queued = []
    for r in recipients:
        q = MailQueue(
            to_email=r["email"],
            to_name=r.get("name", ""),
            subject=subject,
            html_body=body,
            event=event,
            form_config_id=fid,
            submission_id=submission.id if submission else None,
            status="queued",
        )
        db.session.add(q)
        queued.append(q)

    if queued:
        db.session.commit()

    return queued


# ─────────────────────────────────────────────────────────────────────────────
# Queue processor
# ─────────────────────────────────────────────────────────────────────────────

def process_queue(limit: int = 50) -> dict:
    """
    Process pending queued items. Call this from a background job or
    manually via the admin UI.
    Returns {"sent": N, "failed": N, "skipped": N}
    """
    pending = (
        MailQueue.query
        .filter(MailQueue.status == "queued")
        .filter(MailQueue.retry_count < MailQueue.max_retries)
        .order_by(MailQueue.created_at)
        .limit(limit)
        .all()
    )

    sent = failed = skipped = 0

    for item in pending:
        item.status = "sending"
        item.last_attempt_at = datetime.utcnow()
        db.session.commit()

        try:
            _send_queue_item(item)
            item.mark_sent()
            _log(item, "sent")
            sent += 1
        except Exception as e:
            item.mark_failed(str(e))
            _log(item, "failed", error=str(e))
            if item.status == "failed":
                failed += 1
            else:
                skipped += 1

        db.session.commit()

    return {"sent": sent, "failed": failed, "skipped": skipped}


def send_queue_item_now(queue_id: int) -> tuple[bool, str]:
    """Manually send a specific queued/failed item. Returns (success, error)."""
    item = db.session.get(MailQueue, queue_id)
    if not item:
        return False, "Queue item not found"

    item.status = "sending"
    item.last_attempt_at = datetime.utcnow()
    db.session.commit()

    try:
        _send_queue_item(item)
        item.mark_sent()
        _log(item, "sent")
        db.session.commit()
        return True, None
    except Exception as e:
        item.retry_count = item.max_retries  # force to failed on manual send
        item.status = "failed"
        item.last_error = str(e)
        _log(item, "failed", error=str(e))
        db.session.commit()
        return False, str(e)


def _send_queue_item(item: MailQueue):
    """
    Actually send a MailQueue item via SMTP.
    Also sends to any extra_recipients attached.
    Raises on failure.
    """
    all_recipients = [{"email": item.to_email, "name": item.to_name or ""}]
    for er in (item.extra_recipients or []):
        if er.get("email"):
            all_recipients.append(er)

    body = item.html_body
    if item.extra_note:
        body = body + f'<hr><p style="color:#666;font-size:13px;"><em>{item.extra_note}</em></p>'

    errors = []
    for r in all_recipients:
        ok, err = send_email(r["email"], item.subject, body)
        if not ok:
            errors.append(f"{r['email']}: {err}")

    if errors:
        raise Exception("; ".join(errors))


def _log(item: MailQueue, status: str, error: str = None):
    log = MailLog(
        to_email=item.to_email,
        to_name=item.to_name,
        subject=item.subject,
        html_body=item.html_body,
        event=item.event,
        form_config_id=item.form_config_id,
        submission_id=item.submission_id,
        queue_id=item.id,
        status=status,
        error=error,
        retry_count=item.retry_count,
    )
    db.session.add(log)