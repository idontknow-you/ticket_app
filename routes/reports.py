from flask import Blueprint, render_template, request, redirect, url_for, flash, jsonify
from flask_login import login_required, current_user
from extensions import db
from models import FormConfig, FormSubmission, FormConfigVersion
from models.report import Report
from decorators import permission_required
from datetime import datetime, timedelta
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


def _compute_chart_data(report: Report):
    """
    Crunch submission data according to report.config.
    Returns a dict ready to be JSON-serialised for Chart.js.
    """
    cfg = report.config or {}
    form_id     = cfg.get("form_config_id") or report.form_config_id
    group_by    = cfg.get("group_by", "__status__")
    f_status    = cfg.get("filter_status", "")
    f_priority  = cfg.get("filter_priority", "")
    date_range  = int(cfg.get("date_range", 0))   # 0 = all time, else days

    q = FormSubmission.query.filter_by(form_config_id=form_id, is_deleted=False)
    if f_status:
        q = q.filter_by(status=f_status)
    if f_priority:
        q = q.filter_by(priority=f_priority)
    if date_range:
        since = datetime.utcnow() - timedelta(days=date_range)
        q = q.filter(FormSubmission.submitted_at >= since)

    subs = q.all()

    counts: Counter = Counter()
    for sub in subs:
        if group_by == "__status__":
            key = (sub.status or "unknown").replace("_", " ").title()
        elif group_by == "__priority__":
            key = (sub.priority or "none").title()
        else:
            # field value from submission data JSON
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
        "#111111", "#3b82f6", "#10b981", "#f59e0b",
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
    forms = FormConfig.query.filter_by(is_deleted=False, is_published=True).order_by(FormConfig.order).all()
    return render_template(
        "reports/index.html",
        reports=reports,
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
        title       = request.form.get("title", "").strip()
        form_id     = request.form.get("form_config_id", type=int)
        group_by    = request.form.get("group_by", "__status__")
        chart_type  = request.form.get("chart_type", "bar")
        f_status    = request.form.get("filter_status", "")
        f_priority  = request.form.get("filter_priority", "")
        date_range  = request.form.get("date_range", "0")

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
                "form_config_id": form_id,
                "chart_type":     chart_type,
                "group_by":       group_by,
                "filter_status":  f_status,
                "filter_priority": f_priority,
                "date_range":     int(date_range),
            },
        )
        db.session.add(r)
        db.session.commit()
        flash("Report created.", "success")
        return redirect(url_for("reports.view", report_id=r.id))

    # Pre-select form if passed via query string (e.g. from index page)
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
    chart_data = _compute_chart_data(report)
    return render_template(
        "reports/view.html",
        report=report,
        chart_data_json=json.dumps(chart_data),
        chart_type=report.config.get("chart_type", "bar"),
        can_delete=_can_delete(),
    )


@reports_bp.route("/<int:report_id>/chart-data")
@login_required
@permission_required("reports", "can_view")
def chart_data(report_id):
    """AJAX endpoint — returns fresh chart data (used by the refresh button)."""
    report = Report.query.filter_by(id=report_id, is_deleted=False).first_or_404()
    return jsonify(_compute_chart_data(report))


@reports_bp.route("/fields")
@login_required
@permission_required("reports", "can_create")
def form_fields():
    """AJAX: return groupable fields for a given form_config_id (used in create form)."""
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
    flash("Report deleted.", "success")
    return redirect(url_for("reports.index"))