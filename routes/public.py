from flask import Blueprint, render_template, redirect, url_for, request
from models import FormConfig, FormSubmission
from models.wiki_page import WikiPage
from sqlalchemy import case
from extensions import db

public_bp = Blueprint("public", __name__)


@public_bp.route("/")
def index():
    forms = FormConfig.query.filter_by(is_published=True, is_deleted=False).order_by(FormConfig.order).all()
    active_slug = request.args.get("form")
    active_form = None
    if forms:
        active_form = next((f for f in forms if f.slug == active_slug), forms[0])

    active_form_id = active_form.id if active_form else None

    # Tagged-to-active-form articles first, then untagged/other-form articles
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

    return render_template("public/index.html",
                           forms=forms,
                           active_form=active_form,
                           active_form_id=active_form_id,
                           wiki_pages=wiki_pages)


@public_bp.route("/submit/<slug>", methods=["POST"])
def submit(slug):
    form_config = FormConfig.query.filter_by(slug=slug, is_published=True, is_deleted=False).first_or_404()

    data = {}
    for field in form_config.fields:
        fid = field["id"]
        if field["type"] == "checkbox":
            data[fid] = request.form.getlist(fid)
        else:
            data[fid] = request.form.get(fid, "")

    prefix    = "".join(w[0] for w in form_config.name.upper().split())[:6]
    count     = form_config.submissions.count() + 1
    ticket_id = f"{prefix}-{count:04d}"

    sub = FormSubmission(form_config_id=form_config.id, ticket_id=ticket_id, data=data)
    db.session.add(sub)
    db.session.commit()

    return redirect(url_for("public.success", slug=slug))


@public_bp.route("/success/<slug>")
def success(slug):
    form_config = FormConfig.query.filter_by(slug=slug).first_or_404()
    return render_template("public/submit_success.html", form=form_config)
