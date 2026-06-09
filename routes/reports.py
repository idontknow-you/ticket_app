from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from extensions import db
from models import FormConfig, FormSubmission, FormConfigVersion
from models.report import Report
from decorators import permission_required
from datetime import datetime, timedelta, date
from collections import Counter
import json

reports_bp = Blueprint("reports", __name__, url_prefix="/reports")

# ── Helpers ───────────────────────────────────────────────────────────────────

def _can_view():
    return current_user.is_superadmin or current_user.has_permission("reports", "can_view")

def _can_create():
    return current_user.is_superadmin or current_user.has_permission("reports", "can_create")

def _can_delete():
    return current_user.is_superadmin or current_user.has_permission("reports", "can_delete")


def _groupable_fields(form: FormConfig):
    """Return fields that make sense as group-by dimensions."""
    GROUPABLE = {"select", "radio", "checkbox"}
    return [f for f in form.sorted_fields if f.get("type") in GROUPABLE]


def _parse_date_range(args: dict):
    """
    Read date-range params from a plain dict (pass request.args or a dict directly).
    Returns (since, until, date_range_days, preset, date_from, date_to)
    """
    preset     = args.get("date_range", "0")
    date_from  = args.get("date_from", "")
    date_to    = args.get("date_to", "")

    since = until = None
    date_range_days = 0

    if preset == "custom":
        try:
            if date_from:
                since = datetime.strptime(date_from, "%Y-%m-%d")
            if date_to:
                until = datetime.strptime(date_to, "%Y-%m-%d") + timedelta(days=1)
        except ValueError:
            pass
    else:
        try:
            days = int(preset)
            if days > 0:
                since = datetime.utcnow() - timedelta(days=days)
                date_range_days = days
        except (ValueError, TypeError):
            pass

    return since, until, date_range_days, preset, date_from, date_to


def _build_submission_query(form_id, since, until):
    q = FormSubmission.query.filter_by(form_config_id=form_id, is_deleted=False)
    if since:
        q = q.filter(FormSubmission.submitted_at >= since)
    if until:
        q = q.filter(FormSubmission.submitted_at < until)
    return q


def _flatten_submission(sub, field_labels: dict) -> dict:
    """
    Convert a FormSubmission into a flat dict suitable for PivotTable.js.
    System fields + all data-bag fields are included.
    """
    row = {
        "ticket_id":       sub.ticket_id,
        "status":          (sub.status or "unknown").replace("_", " ").title(),
        "priority":        (sub.priority or "none").title(),
        "submitted_at":    sub.submitted_at.strftime("%Y-%m-%d") if sub.submitted_at else "",
        "submitter_name":  sub.submitter_name or "",
        "submitter_email": sub.submitter_email or "",
    }
    for key, val in (sub.data or {}).items():
        label = field_labels.get(key, key)
        if isinstance(val, list):
            row[label] = ", ".join(str(v) for v in val)
        else:
            row[label] = str(val) if val is not None else ""
    return row


def _get_field_labels(form: FormConfig) -> dict:
    """Return {field_id: field_label} for all fields on a form."""
    return {
        f["id"]: f.get("label", f["id"])
        for f in (form.sorted_fields or [])
    }


def _compute_chart_data(report: Report, since=None, until=None):
    """
    Crunch submission data according to report.config.
    Returns a dict ready to be JSON-serialised for Chart.js / legacy use.
    """
    cfg = report.config or {}
    form_id    = cfg.get("form_config_id") or report.form_config_id
    group_by   = cfg.get("group_by", "__status__")
    f_status   = cfg.get("filter_status", "")
    f_priority = cfg.get("filter_priority", "")

    q = _build_submission_query(form_id, since, until)
    if f_status:
        q = q.filter_by(status=f_status)
    if f_priority:
        q = q.filter_by(priority=f_priority)

    subs = q.all()

    counts: Counter = Counter()
    for sub in subs:
        if group_by == "__status__":
            key = (sub.status or "unknown").replace("_", " ").title()
        elif group_by == "__priority__":
            key = (sub.priority or "none").title()
        else:
            val = sub.data.get(group_by)
            if isinstance(val, list):
                for v in val:
                    counts[str(v) or "(blank)"] += 1
                continue
            key = str(val).strip() if val else "(blank)"
        counts[key] += 1

    labels = list(counts.keys())
    values = [counts[l] for l in labels]

    PALETTE = [
        "#0b0380", "#3b82f6", "#10b981", "#f59e0b",
        "#ef4444", "#8b5cf6", "#06b6d4", "#f97316",
        "#84cc16", "#ec4899",
    ]
    colors = [PALETTE[i % len(PALETTE)] for i in range(len(labels))]

    return {
        "labels": labels,
        "values": values,
        "colors": colors,
        "total":  len(subs),
    }


# ── Routes ────────────────────────────────────────────────────────────────────

@reports_bp.route("/")
@login_required
@permission_required("reports", "can_view")
def index():
    reports = (
        Report.query
        .filter_by(is_deleted=False)
        .order_by(Report.created_at.desc())
        .all()
    )
    deleted_reports = []
    if _can_delete():
        deleted_reports = (
            Report.query
            .filter_by(is_deleted=True)
            .order_by(Report.deleted_at.desc())
            .all()
        )
    forms = FormConfig.query.filter_by(is_deleted=False, is_published=True).order_by(FormConfig.order).all()
    return render_template(
        "reports/index.html",
        reports=reports,
        deleted_reports=deleted_reports,
        forms=forms,
        can_create=_can_create(),
        can_delete=_can_delete(),
    )


@reports_bp.route("/new", methods=["GET", "POST"])
@login_required
@permission_required("reports", "can_create")
def create():
    forms = FormConfig.query.filter_by(is_deleted=False, is_published=True).order_by(FormConfig.order).all()

    if request.method == "POST":
        title      = request.form.get("title", "").strip()
        form_id    = request.form.get("form_config_id", type=int)
        group_by   = request.form.get("group_by", "__status__")
        f_status   = request.form.get("filter_status", "")
        f_priority = request.form.get("filter_priority", "")
        date_range = request.form.get("date_range", "0")
        date_from  = request.form.get("date_from", "")
        date_to    = request.form.get("date_to", "")

        if not title:
            flash("Title is required.", "error")
            return redirect(request.url)
        if not form_id:
            flash("Please select a form.", "error")
            return redirect(request.url)

        r = Report(
            title=title,
            form_config_id=form_id,
            created_by=current_user.id,
            config={
                "form_config_id":  form_id,
                "group_by":        group_by,
                "filter_status":   f_status,
                "filter_priority": f_priority,
                "date_range":      date_range,
                "date_from":       date_from,
                "date_to":         date_to,
                "pivot":           {},
            },
        )
        db.session.add(r)
        db.session.commit()
        flash("Report created.", "success")
        return redirect(url_for("reports.view", report_id=r.id))

    selected_form_id = request.args.get("form_id", type=int)
    selected_form    = None
    groupable_fields = []
    if selected_form_id:
        selected_form    = db.session.get(FormConfig, selected_form_id)
        groupable_fields = _groupable_fields(selected_form) if selected_form else []

    return render_template(
        "reports/create.html",
        forms=forms,
        selected_form=selected_form,
        groupable_fields=groupable_fields,
    )


@reports_bp.route("/<int:report_id>")
@login_required
@permission_required("reports", "can_view")
def view(report_id):
    report = Report.query.filter_by(id=report_id, is_deleted=False).first_or_404()
    cfg    = report.config or {}

    if "date_range" in request.args:
        since, until, _, active_preset, date_from, date_to = _parse_date_range(request.args)
    else:
        saved_args = {
            "date_range": str(cfg.get("date_range", "0")),
            "date_from":  cfg.get("date_from", ""),
            "date_to":    cfg.get("date_to", ""),
        }
        since, until, _, active_preset, date_from, date_to = _parse_date_range(saved_args)

    form         = db.session.get(FormConfig, report.form_config_id)
    field_labels = _get_field_labels(form) if form else {}
    subs         = _build_submission_query(report.form_config_id, since, until).all()
    pivot_rows   = [_flatten_submission(s, field_labels) for s in subs]

    form_fields_json = json.dumps([
        {"id": f["id"], "label": f.get("label", f["id"])}
        for f in (form.sorted_fields if form else [])
    ])

    return render_template(
        "reports/view.html",
        report=report,
        pivot_rows_json=json.dumps(pivot_rows),
        saved_pivot_config=json.dumps(cfg.get("pivot", {})),
        form_fields_json=form_fields_json,
        active_preset=active_preset,
        date_from=date_from,
        date_to=date_to,
        total=len(subs),
        can_delete=_can_delete(),
        can_create=_can_create(),
    )


@reports_bp.route("/<int:report_id>/save-layout", methods=["POST"])
@login_required
@permission_required("reports", "can_create")
def save_layout(report_id):
    report = Report.query.filter_by(id=report_id, is_deleted=False).first_or_404()
    payload = request.get_json(silent=True) or {}

    pivot_cfg = {
        "rows":        payload.get("rows", []),
        "cols":        payload.get("cols", []),
        "aggregator":  payload.get("aggregator", "count"),
        "renderer":    payload.get("renderer", "table"),
        "filters":     payload.get("filters", {}),
    }

    cfg = dict(report.config or {})
    cfg["pivot"] = pivot_cfg

    if "date_range" in payload:
        cfg["date_range"] = payload["date_range"]
        cfg["date_from"]  = payload.get("date_from", "")
        cfg["date_to"]    = payload.get("date_to", "")

    report.config = cfg
    db.session.commit()
    return jsonify({"ok": True})


@reports_bp.route("/<int:report_id>/chart-data")
@login_required
@permission_required("reports", "can_view")
def chart_data(report_id):
    report = Report.query.filter_by(id=report_id, is_deleted=False).first_or_404()
    since, until, *_ = _parse_date_range(request.args)
    return jsonify(_compute_chart_data(report, since, until))


@reports_bp.route("/fields")
@login_required
@permission_required("reports", "can_create")
def form_fields():
    form_id = request.args.get("form_id", type=int)
    if not form_id:
        return jsonify([])
    form = FormConfig.query.filter_by(id=form_id, is_deleted=False).first()
    if not form:
        return jsonify([])
    fields = [
        {"id": f["id"], "label": f.get("label", f["id"])}
        for f in _groupable_fields(form)
    ]
    return jsonify(fields)


@reports_bp.route("/<int:report_id>/delete", methods=["POST"])
@login_required
@permission_required("reports", "can_delete")
def delete(report_id):
    report = Report.query.filter_by(id=report_id, is_deleted=False).first_or_404()
    report.soft_delete()
    db.session.commit()
    flash("Report moved to trash.", "success")
    return redirect(url_for("reports.index"))


@reports_bp.route("/clear-trash", methods=["POST"])
@login_required
@permission_required("reports", "can_delete")
def clear_trash():
    trashed = Report.query.filter_by(is_deleted=True).all()
    for r in trashed:
        db.session.delete(r)
    db.session.commit()
    flash(f"Trash cleared ({len(trashed)} report{'s' if len(trashed) != 1 else ''} deleted).", "success")
    return redirect(url_for("reports.index"))


@reports_bp.route("/<int:report_id>/restore", methods=["POST"])
@login_required
@permission_required("reports", "can_delete")
def restore(report_id):
    report = Report.query.filter_by(id=report_id, is_deleted=True).first_or_404()
    report.is_deleted = False
    report.deleted_at = None
    db.session.commit()
    flash("Report restored.", "success")
    return redirect(url_for("reports.index"))