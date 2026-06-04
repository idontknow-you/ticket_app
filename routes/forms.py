import re, uuid, json
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_login import login_required, current_user
from models import FormConfig, FormConfigVersion
from extensions import db

forms_bp = Blueprint("forms", __name__, url_prefix="/forms")

FIELD_TYPES = ["text", "textarea", "email", "number", "date", "select", "radio", "checkbox", "file"]


def _slugify(text):
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9]+", "-", text)
    return text.strip("-")[:80]


def _unique_slug(base, exclude_id=None):
    slug, n = base, 1
    while True:
        q = FormConfig.query.filter_by(slug=slug, is_deleted=False)
        if exclude_id:
            q = q.filter(FormConfig.id != exclude_id)
        if not q.first():
            return slug
        slug, n = f"{base}-{n}", n + 1


def _other_forms(exclude_id=None):
    """Return a list of dicts for all published forms except the current one,
    used by the builder to populate the Import from form selector."""
    q = FormConfig.query.filter_by(is_deleted=False, is_published=True)
    if exclude_id:
        q = q.filter(FormConfig.id != exclude_id)
    return [
        {"id": f.id, "name": f.name, "fields": f.sorted_fields}
        for f in q.order_by(FormConfig.order).all()
    ]


def _can_view():
    return current_user.is_superadmin or current_user.has_permission("forms", "can_view")

def _can_create():
    return current_user.is_superadmin or current_user.has_permission("forms", "can_create")

def _can_edit():
    return current_user.is_superadmin or current_user.has_permission("forms", "can_edit")

def _can_delete():
    return current_user.is_superadmin or current_user.has_permission("forms", "can_delete")


@forms_bp.route("/")
@login_required
def list_forms():
    if not _can_view():
        abort(403)
    forms = FormConfig.query.filter_by(is_deleted=False).order_by(FormConfig.order).all()
    return render_template("forms/list.html", forms=forms)


@forms_bp.route("/new", methods=["GET", "POST"])
@login_required
def new_form():
    if not _can_create():
        abort(403)
    if request.method == "POST":
        return _save(None)
    return render_template(
        "forms/builder.html",
        form=None,
        field_types=FIELD_TYPES,
        other_forms=_other_forms(),
    )


@forms_bp.route("/<int:form_id>/edit", methods=["GET", "POST"])
@login_required
def edit_form(form_id):
    if not _can_edit():
        abort(403)
    form = FormConfig.query.filter_by(id=form_id, is_deleted=False).first_or_404()
    if request.method == "POST":
        return _save(form)
    versions = (
        FormConfigVersion.query
        .filter_by(form_config_id=form_id)
        .order_by(FormConfigVersion.version.desc())
        .all()
    )
    return render_template(
        "forms/builder.html",
        form=form,
        field_types=FIELD_TYPES,
        versions=versions,
        other_forms=_other_forms(exclude_id=form_id),
    )


@forms_bp.route("/<int:form_id>/publish", methods=["POST"])
@login_required
def toggle_publish(form_id):
    if not _can_edit():
        abort(403)
    form = FormConfig.query.filter_by(id=form_id, is_deleted=False).first_or_404()
    form.is_published = not form.is_published
    db.session.commit()
    state = "published" if form.is_published else "unpublished"
    flash(f'"{form.name}" {state}.', "success")
    return redirect(request.referrer or url_for("forms.list_forms"))


@forms_bp.route("/<int:form_id>/delete", methods=["POST"])
@login_required
def delete_form(form_id):
    if not _can_delete():
        abort(403)
    form = FormConfig.query.filter_by(id=form_id, is_deleted=False).first_or_404()
    name = form.name
    form.soft_delete()
    db.session.commit()
    flash(f'"{name}" deleted.', "success")
    return redirect(url_for("forms.list_forms"))


def _save(existing):
    name        = request.form.get("name", "").strip()
    description = request.form.get("description", "").strip()
    fields_raw  = request.form.get("fields_json", "[]")

    if not name:
        flash("Form name is required.", "error")
        return redirect(request.url)

    try:
        fields = json.loads(fields_raw)
    except json.JSONDecodeError:
        flash("Invalid field data.", "error")
        return redirect(request.url)

    for i, f in enumerate(fields):
        if not f.get("id"):
            f["id"] = uuid.uuid4().hex[:8]
        f["order"] = i

    created_by = current_user.id if current_user.is_authenticated else None

    if existing:
        existing.name        = name
        existing.description = description
        ver = existing.publish_new_version(fields=fields, created_by=created_by)
        db.session.commit()
        flash(f'Form saved as revision {ver.version}.', "success")
        return redirect(url_for("forms.edit_form", form_id=existing.id))
    else:
        slug  = _unique_slug(_slugify(name))
        order = (db.session.query(db.func.max(FormConfig.order)).scalar() or 0) + 1
        form  = FormConfig(name=name, slug=slug, description=description, order=order)
        db.session.add(form)
        db.session.flush()
        form.publish_new_version(fields=fields, created_by=created_by)
        db.session.commit()
        flash(f'"{name}" created. Add fields and publish when ready.', "success")
        return redirect(url_for("forms.edit_form", form_id=form.id))