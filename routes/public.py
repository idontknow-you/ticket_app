import os, uuid
from flask import Blueprint, render_template, redirect, url_for, request, current_app
from models import FormConfig, FormSubmission
from models.wiki_page import WikiPage
from sqlalchemy import case
from extensions import db
from werkzeug.utils import secure_filename
from models.carousel_item import CarouselItem

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


PUBLIC_ALLOWED_EXTENSIONS = {
    "jpg", "jpeg", "png", "gif", "webp",
    "pdf", "doc", "docx", "xls", "xlsx",
    "ppt", "pptx", "txt", "csv", "zip",
}


def _save_upload(file_obj, field_cfg):
    if not file_obj or not file_obj.filename:
        return None
    original  = secure_filename(file_obj.filename)
    ext_raw   = os.path.splitext(original)[1]           # e.g. ".PNG"
    ext_lower = ext_raw.lstrip(".").lower()              # e.g. "png"
    if ext_lower not in PUBLIC_ALLOWED_EXTENSIONS:
        return None
    unique    = f"{uuid.uuid4().hex}{ext_raw}"
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

    data = {}
    for field in fields:
        fid = field["id"]
        if field["type"] == "checkbox":
            data[fid] = request.form.getlist(fid)
        elif field["type"] == "file":
            uploaded_files = request.files.getlist(fid)
            saved = []
            for f in uploaded_files:
                result = _save_upload(f, field)
                if result:
                    saved.append(result)
            data[fid] = saved
        else:
            data[fid] = request.form.get(fid, "")

    prefix = "".join(w[0] for w in form_config.name.upper().split())[:6]
    # Use MAX(id) scoped to this form rather than COUNT(*) to avoid:
    #  a) race conditions under concurrent submissions
    #  b) collisions when soft-deleted submissions affect the count
    from sqlalchemy import func as _func
    max_seq = db.session.query(
        _func.max(FormSubmission.id)
    ).filter(FormSubmission.form_config_id == form_config.id).scalar() or 0
    ticket_id = f"{prefix}-{max_seq + 1:04d}"

    sub = FormSubmission(
        form_config_id=form_config.id,
        form_config_version_id=current_ver.id if current_ver else None,
        ticket_id=ticket_id,
        data=data,
    )
    db.session.add(sub)
    db.session.commit()

    # Fire mail event
    try:
        from services.mail_service import enqueue_event
        enqueue_event("ticket_submitted", submission=sub)
    except Exception:
        pass

    return redirect(url_for("public.success", slug=slug))


@public_bp.route("/success/<slug>")
def success(slug):
    form_config = FormConfig.query.filter_by(slug=slug, is_deleted=False).first_or_404()
    return render_template("public/submit_success.html", form=form_config)