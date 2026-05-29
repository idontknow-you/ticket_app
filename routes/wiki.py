from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from decorators import superadmin_required
from models import FormConfig
from services.wiki_service import (
    get_all_top_level_pages,
    get_page_or_404,
    get_page_by_slug,
    get_parent_candidates,
    get_page_history,
    create_page,
    update_page,
    toggle_publish,
    delete_page,
    save_attachment,
    save_cover_image,
    delete_attachment,
    get_attachment_or_404,
    like_page,
    add_comment,
    delete_comment,
)

wiki_bp = Blueprint("wiki", __name__, url_prefix="/wiki")


def _get_forms():
    return FormConfig.query.filter_by(is_deleted=False, is_published=True).order_by(FormConfig.order).all()


@wiki_bp.route("/")
@login_required
def index():
    pages = get_all_top_level_pages()
    forms = _get_forms()
    return render_template("wiki/index.html", pages=pages, forms=forms)


@wiki_bp.route("/article/<slug>")
def article(slug):
    page = get_page_by_slug(slug)
    return render_template("wiki/article.html", page=page)


@wiki_bp.route("/article/<slug>/like", methods=["POST"])
def like(slug):
    page = get_page_by_slug(slug)
    total = like_page(page)
    return jsonify({"likes": total})


@wiki_bp.route("/article/<slug>/comment", methods=["POST"])
def comment(slug):
    page = get_page_by_slug(slug)
    data = request.get_json() or {}
    author = data.get("author", "Anonymous").strip() or "Anonymous"
    text   = data.get("text", "").strip()
    if not text:
        return jsonify({"error": "Comment cannot be empty."}), 400
    comments = add_comment(page, author, text)
    return jsonify({"comments": comments})


@wiki_bp.route("/article/<slug>/comment/<int:comment_index>/delete", methods=["POST"])
@login_required
@superadmin_required
def delete_comment_route(slug, comment_index):
    page = get_page_by_slug(slug)
    delete_comment(page, comment_index)
    return jsonify({"success": True})


@wiki_bp.route("/create", methods=["GET", "POST"])
@login_required
@superadmin_required
def create():
    parent_pages = get_parent_candidates()
    forms = _get_forms()
    if request.method == "POST":
        title          = request.form.get("title", "").strip()
        body           = request.form.get("body_html", "").strip()
        description    = request.form.get("description", "").strip()
        parent_id      = request.form.get("parent_id") or None
        form_config_id = request.form.get("form_config_id") or None
        if form_config_id:
            form_config_id = int(form_config_id)
        is_published = bool(request.form.get("is_published"))
        cover_image  = None
        cover_file   = request.files.get("cover_image")
        if cover_file and cover_file.filename:
            try:
                cover_image = save_cover_image(cover_file)
            except ValueError as e:
                flash(str(e), "error")
                return render_template("wiki/form.html", page=None,
                                       parent_pages=parent_pages, forms=forms,
                                       form=request.form, action="create")
        try:
            page = create_page(title=title, body=body, description=description,
                               cover_image=cover_image, parent_id=parent_id,
                               is_published=is_published, created_by=current_user.id)
            page.form_config_id = form_config_id
            attachment_errors = []
            for f in request.files.getlist("attachments"):
                if f and f.filename:
                    try:
                        save_attachment(f, page.id, current_user.id)
                    except ValueError as e:
                        attachment_errors.append(str(e))
            from extensions import db
            db.session.commit()
            for err in attachment_errors:
                flash(err, "error")
            flash(f'Page "{page.title}" created.', "success")
            return redirect(url_for("wiki.index"))
        except ValueError as e:
            flash(str(e), "error")
            return render_template("wiki/form.html", page=None,
                                   parent_pages=parent_pages, forms=forms,
                                   form=request.form, action="create")
    return render_template("wiki/form.html", page=None,
                           parent_pages=parent_pages, forms=forms,
                           form={}, action="create")


@wiki_bp.route("/<int:page_id>/edit", methods=["GET", "POST"])
@login_required
@superadmin_required
def edit(page_id):
    page         = get_page_or_404(page_id)
    parent_pages = get_parent_candidates(exclude_id=page_id)
    forms        = _get_forms()
    if request.method == "POST":
        title          = request.form.get("title", "").strip()
        body           = request.form.get("body_html", "").strip()
        description    = request.form.get("description", "").strip()
        parent_id      = request.form.get("parent_id") or None
        form_config_id = request.form.get("form_config_id") or None
        if form_config_id:
            form_config_id = int(form_config_id)
        is_published = bool(request.form.get("is_published"))
        cover_image  = None
        cover_file   = request.files.get("cover_image")
        if cover_file and cover_file.filename:
            try:
                cover_image = save_cover_image(cover_file)
            except ValueError as e:
                flash(str(e), "error")
                return render_template("wiki/form.html", page=page,
                                       parent_pages=parent_pages, forms=forms,
                                       form=request.form, action="edit")
        try:
            update_page(page=page, title=title, body=body, description=description,
                        cover_image=cover_image, parent_id=parent_id,
                        is_published=is_published, updated_by=current_user.id)
            page.form_config_id = form_config_id
            attachment_errors = []
            for f in request.files.getlist("attachments"):
                if f and f.filename:
                    try:
                        save_attachment(f, page.id, current_user.id)
                    except ValueError as e:
                        attachment_errors.append(str(e))
            from extensions import db
            db.session.commit()
            for err in attachment_errors:
                flash(err, "error")
            flash(f'Page "{page.title}" updated.', "success")
            return redirect(url_for("wiki.index"))
        except ValueError as e:
            flash(str(e), "error")
            return render_template("wiki/form.html", page=page,
                                   parent_pages=parent_pages, forms=forms,
                                   form=request.form, action="edit")
    return render_template("wiki/form.html", page=page,
                           parent_pages=parent_pages, forms=forms,
                           form={}, action="edit")


@wiki_bp.route("/attachment/<int:attachment_id>/delete", methods=["POST"])
@login_required
@superadmin_required
def delete_wiki_attachment(attachment_id):
    attachment = get_attachment_or_404(attachment_id)
    page_id    = attachment.page_id
    delete_attachment(attachment)
    flash("Attachment deleted.", "success")
    return redirect(url_for("wiki.edit", page_id=page_id))


@wiki_bp.route("/<int:page_id>/toggle-publish", methods=["POST"])
@login_required
@superadmin_required
def toggle_publish_route(page_id):
    page      = get_page_or_404(page_id)
    published = toggle_publish(page)
    state     = "published" if published else "unpublished"
    flash(f'"{page.title}" {state}.', "success")
    return redirect(url_for("wiki.index"))


@wiki_bp.route("/<int:page_id>/delete", methods=["POST"])
@login_required
@superadmin_required
def delete(page_id):
    page  = get_page_or_404(page_id)
    title = page.title
    delete_page(page)
    flash(f'Page "{title}" deleted.', "success")
    return redirect(url_for("wiki.index"))


@wiki_bp.route("/<int:page_id>/history")
@login_required
def history(page_id):
    from models import User
    page      = get_page_or_404(page_id)
    snapshots = get_page_history(page_id)
    editors   = {u.id: u for u in User.query.all()}
    return render_template("wiki/history.html",
                           page=page, snapshots=snapshots, editors=editors)