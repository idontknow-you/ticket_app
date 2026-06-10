import os, uuid
from flask import Blueprint, render_template, redirect, url_for, request, flash, current_app
from models import FormConfig, FormSubmission
from models.wiki_page import WikiPage
from sqlalchemy import case
from extensions import db
from werkzeug.utils import secure_filename
from models.carousel_item import CarouselItem
from routes.forms import get_field_validation_error

public_bp = Blueprint("public", __name__)

ALLOWED_TYPE_MAP = {
    "Images": "image/*",
    "PDF":    "application/pdf",
    "Word":   ".doc,.docx",
    "Excel":  ".xls,.xlsx",
    "Video":  "video/*",
    "Audio":  "audio/*",
    "Any":    None,
}


def _save_upload(file_obj, field_cfg):
    if not file_obj or not file_obj.filename:
        return None
    original  = secure_filename(file_obj.filename)
    ext       = os.path.splitext(original)[1]
    unique    = f"{uuid.uuid4().hex}{ext}"
    upload_dir = current_app.config["UPLOAD_FOLDER"]
    file_obj.save(os.path.join(upload_dir, unique))
    return {
        "filename":      unique,
        "original_name": original,
        "url":           f"/static/uploads/{unique}",
    }


def _get_carousel_items():
    return (
        CarouselItem.query
        .join(CarouselItem.page)
        .filter(WikiPage.is_deleted == False, WikiPage.is_published == True)
        .order_by(CarouselItem.sort_order)
        .all()
    )


@public_bp.route("/")
def index():
    forms = FormConfig.query.filter_by(is_published=True, is_deleted=False).order_by(FormConfig.order).all()
    active_slug = request.args.get("form")
    active_form = None
    if forms:
        active_form = next((f for f in forms if f.slug == active_slug), forms[0])

    active_form_id = active_form.id if active_form else None

    wiki_pages = (
        WikiPage.query
        .filter_by(is_deleted=False, is_published=True, parent_id=None)
        .order_by(
            case(
                (WikiPage.form_config_id == active_form_id, 0),
                else_=1
            ),
            WikiPage.order,
            WikiPage.title
        )
        .all()
    )

    carousel_items = _get_carousel_items()

    return render_template("public/index.html",
                           forms=forms,
                           active_form=active_form,
                           active_form_id=active_form_id,
                           wiki_pages=wiki_pages,
                           carousel_items=carousel_items)


@public_bp.route("/submit/<slug>", methods=["POST"])
def submit(slug):
    form_config = FormConfig.query.filter_by(slug=slug, is_published=True, is_deleted=False).first_or_404()

    current_ver = form_config.current_version
    fields      = current_ver.sorted_fields if current_ver else form_config.sorted_fields

    # ── collect raw values first ───────────────────────────────────────────────
    raw = {}
    for field in fields:
        fid = field["id"]
        if field["type"] == "checkbox":
            raw[fid] = request.form.getlist(fid)
        elif field["type"] == "file":
            raw[fid] = request.files.getlist(fid)
        else:
            raw[fid] = request.form.get(fid, "")

    # ── server-side validation ─────────────────────────────────────────────────
    errors = []
    for field in fields:
        fid   = field["id"]
        ftype = field["type"]

        # Skip fields that are hidden by branching conditions
        # (client already cleared them, but double-check: if all conditions
        # have empty parent values, the field was hidden)
        conditions = field.get("conditions") or []
        valid_conditions = [c for c in conditions if c.get("field_id") and c.get("value")]
        if valid_conditions:
            # Evaluate whether this field should be visible given submitted data
            def _get_val(fid_):
                v = raw.get(fid_, "")
                return v if v != "" else []
            result = _check_condition(_get_val, valid_conditions[0])
            for cond in valid_conditions[1:]:
                op = cond.get("operator", "AND")
                if op == "OR":
                    result = result or _check_condition(_get_val, cond)
                else:
                    result = result and _check_condition(_get_val, cond)
            if not result:
                # Field is hidden — skip validation and clear value
                raw[fid] = [] if ftype in ("checkbox", "file") else ""
                continue

        # Validate
        if ftype == "file":
            uploaded = [f for f in raw[fid] if f and f.filename]
            err = get_field_validation_error(field, None, uploaded_files=uploaded or None)
        else:
            err = get_field_validation_error(field, raw[fid])

        if err:
            errors.append(err)

    if errors:
        for err in errors:
            flash(err, "error")
        return redirect(url_for("public.index", form=slug))

    # ── save files and build final data dict ───────────────────────────────────
    data = {}
    for field in fields:
        fid   = field["id"]
        ftype = field["type"]
        if ftype == "file":
            uploaded_files = [f for f in raw[fid] if f and f.filename]
            data[fid] = [r for f in uploaded_files for r in [_save_upload(f, field)] if r]
        elif ftype == "phone":
            # Store only the 10 digits; display layer always prepends +91
            import re as _re
            digits = _re.sub(r"\D", "", str(raw[fid]))
            data[fid] = digits
        else:
            data[fid] = raw[fid]

    prefix    = "".join(w[0] for w in form_config.name.upper().split())[:6]
    count     = form_config.submissions.count() + 1
    ticket_id = f"{prefix}-{count:04d}"

    sub = FormSubmission(
        form_config_id=form_config.id,
        form_config_version_id=current_ver.id if current_ver else None,
        ticket_id=ticket_id,
        data=data,
    )

    # Denormalise submitter email + name for fast querying
    for field in fields:
        label_lower = field.get("label", "").lower()
        fid = field.get("id", "")
        val = data.get(fid, "")
        if isinstance(val, str):
            if "email" in label_lower and not sub.submitter_email:
                sub.submitter_email = val.strip() or None
            if any(label_lower == k for k in ("name", "full name", "your name", "full_name")) and not sub.submitter_name:
                sub.submitter_name = val.strip() or None

    db.session.add(sub)
    db.session.commit()

    # Fire mail event
    try:
        from services.mail_service import enqueue_event
        enqueue_event("ticket_submitted", submission=sub)
        db.session.commit()
    except Exception:
        pass

    return redirect(url_for("public.success", slug=slug))


def _check_condition(get_val_fn, cond):
    """Return True if a single condition is satisfied."""
    field_val  = get_val_fn(cond["field_id"])
    cond_value = cond["value"]
    if isinstance(field_val, list):
        return cond_value in field_val
    return field_val == cond_value


@public_bp.route("/success/<slug>")
def success(slug):
    form_config = FormConfig.query.filter_by(slug=slug).first_or_404()
    return render_template("public/submit_success.html", form=form_config)