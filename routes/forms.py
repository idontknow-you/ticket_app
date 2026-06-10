import re, uuid, json
from datetime import date
from flask import Blueprint, render_template, redirect, url_for, request, flash, abort
from flask_login import login_required, current_user
from models import FormConfig, FormConfigVersion
from extensions import db

forms_bp = Blueprint("forms", __name__, url_prefix="/forms")

FIELD_TYPES = ["text", "textarea", "email", "phone", "number", "date", "select", "radio", "checkbox", "file"]


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


# ─────────────────────────────────────────────────────────────────────────────
# Validation utility  —  imported by public.py submit route
# ─────────────────────────────────────────────────────────────────────────────

def get_field_validation_error(field: dict, value, uploaded_files=None) -> str | None:
    """
    Validate a single submitted field value against its type rules.

    Parameters
    ----------
    field          : field dict from FormConfigVersion.fields
    value          : submitted string value (or list for checkbox)
    uploaded_files : list of werkzeug FileStorage objects for 'file' fields

    Returns a human-readable error string, or None if valid.
    """
    ftype    = field.get("type", "text")
    label    = field.get("label", "This field")
    required = field.get("required", False)

    # ── required check ────────────────────────────────────────────────────────
    empty = (
        (not value and value != 0)
        or (isinstance(value, list) and len(value) == 0)
        or (ftype == "file" and not uploaded_files)
    )
    if required and empty:
        return f"{label} is required."
    if empty:
        return None  # optional + empty → nothing to validate

    # ── type-specific rules ───────────────────────────────────────────────────

    if ftype == "text":
        # Letters, spaces and hyphens only (names, subjects, etc.)
        if not re.fullmatch(r"[A-Za-z\s\-]+", str(value)):
            return f"{label} must contain letters only (no numbers or special characters)."

    elif ftype == "email":
        pattern = r"^[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}$"
        if not re.fullmatch(pattern, str(value).strip()):
            return f"{label} must be a valid email address."

    elif ftype == "phone":
        # Strip any non-digit characters the client may have sent, then check exactly 10
        digits = re.sub(r"\D", "", str(value))
        if len(digits) != 10:
            return f"{label} must be exactly 10 digits (no country code)."

    elif ftype == "number":
        try:
            float(str(value))
        except ValueError:
            return f"{label} must be a valid number."

    elif ftype == "date":
        # No future dates
        try:
            submitted = date.fromisoformat(str(value))
            if submitted > date.today():
                return f"{label} cannot be a future date."
        except ValueError:
            return f"{label} must be a valid date."

    elif ftype in ("select", "radio"):
        allowed = field.get("options", [])
        if str(value) not in allowed:
            return f"{label} contains an invalid selection."

    elif ftype == "checkbox":
        allowed = set(field.get("options", []))
        submitted_vals = value if isinstance(value, list) else [value]
        for v in submitted_vals:
            if v not in allowed:
                return f"{label} contains an invalid option."

    elif ftype == "file":
        files         = uploaded_files or []
        max_files     = int(field.get("max_files") or 1)
        max_size_v    = field.get("max_size_value")
        max_size_u    = field.get("max_size_unit", "MB")
        allowed_types = field.get("allowed_types", [])

        # Count
        if len(files) > max_files:
            return f"{label}: maximum {max_files} file(s) allowed."

        # Size
        size_multipliers = {"KB": 1024, "MB": 1024 ** 2, "GB": 1024 ** 3}
        if max_size_v:
            max_bytes = int(max_size_v) * size_multipliers.get(max_size_u, 1024 ** 2)
            for f_obj in files:
                f_obj.seek(0, 2)
                size = f_obj.tell()
                f_obj.seek(0)
                if size > max_bytes:
                    return f"{label}: each file must be under {max_size_v}{max_size_u}."

        # Type
        if allowed_types and "*" not in allowed_types:
            import mimetypes
            for f_obj in files:
                filename = f_obj.filename or ""
                mime_type, _ = mimetypes.guess_type(filename)
                ext = ("." + filename.rsplit(".", 1)[-1].lower()) if "." in filename else ""
                accepted = False
                for rule in allowed_types:
                    if rule == "*":
                        accepted = True; break
                    if rule.endswith("/*"):
                        category = rule.split("/")[0]
                        if mime_type and mime_type.startswith(category + "/"):
                            accepted = True; break
                    elif rule.startswith(".") or "," in rule:
                        if ext and ext in rule.split(","):
                            accepted = True; break
                    else:
                        if mime_type == rule:
                            accepted = True; break
                if not accepted:
                    return f"{label}: file type not allowed for \"{filename}\"."

    return None


# ─────────────────────────────────────────────────────────────────────────────
# Routes
# ─────────────────────────────────────────────────────────────────────────────

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