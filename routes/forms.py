import re, uuid, json
from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required
from models import FormConfig
from extensions import db
from decorators import superadmin_required

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


@forms_bp.route("/")
@login_required
def list_forms():
    forms = FormConfig.query.filter_by(is_deleted=False).order_by(FormConfig.order).all()
    return render_template("forms/list.html", forms=forms)


@forms_bp.route("/new", methods=["GET", "POST"])
@login_required
@superadmin_required
def new_form():
    if request.method == "POST":
        return _save(None)
    return render_template("forms/builder.html", form=None, field_types=FIELD_TYPES)


@forms_bp.route("/<int:form_id>/edit", methods=["GET", "POST"])
@login_required
@superadmin_required
def edit_form(form_id):
    form = FormConfig.query.filter_by(id=form_id, is_deleted=False).first_or_404()
    if request.method == "POST":
        return _save(form)
    return render_template("forms/builder.html", form=form, field_types=FIELD_TYPES)


@forms_bp.route("/<int:form_id>/publish", methods=["POST"])
@login_required
@superadmin_required
def toggle_publish(form_id):
    form = FormConfig.query.filter_by(id=form_id, is_deleted=False).first_or_404()
    form.is_published = not form.is_published
    db.session.commit()
    state = "published" if form.is_published else "unpublished"
    flash(f'"{form.name}" {state}.', "success")
    return redirect(request.referrer or url_for("forms.list_forms"))


@forms_bp.route("/<int:form_id>/delete", methods=["POST"])
@login_required
@superadmin_required
def delete_form(form_id):
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

    if existing:
        existing.name        = name
        existing.description = description
        existing.fields      = fields
        db.session.commit()
        flash("Form saved.", "success")
        return redirect(url_for("forms.edit_form", form_id=existing.id))
    else:
        slug = _unique_slug(_slugify(name))
        order = (db.session.query(db.func.max(FormConfig.order)).scalar() or 0) + 1
        form = FormConfig(name=name, slug=slug, description=description, order=order, fields=fields)
        db.session.add(form)
        db.session.commit()
        flash(f'"{name}" created. Add fields and publish when ready.', "success")
        return redirect(url_for("forms.edit_form", form_id=form.id))