from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from decorators import superadmin_required, permission_required
from models import FormConfig
from models.wiki_page import WikiPage
from models.carousel_item import CarouselItem
from models.carousel_log import CarouselLog
from models.user import User
from extensions import db
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
    save_carousel_image,   # NEW — same pattern as save_cover_image
    delete_attachment,
    get_attachment_or_404,
    like_page,
    add_comment,
    delete_comment,
)

wiki_bp = Blueprint("wiki", __name__, url_prefix="/wiki")


def _get_forms():
    return FormConfig.query.filter_by(is_deleted=False, is_published=True).order_by(FormConfig.order).all()


def _get_carousel_items():
    """Return CarouselItem rows ordered by sort_order, with .page eagerly available."""
    return (
        CarouselItem.query
        .join(CarouselItem.page)
        .filter(WikiPage.is_deleted == False, WikiPage.is_published == True)
        .order_by(CarouselItem.sort_order)
        .all()
    )


# ── Index ─────────────────────────────────────────────────────────────────────

@wiki_bp.route("/")
@login_required
@permission_required("wiki", "can_view")
def index():
    pages           = get_all_top_level_pages()
    forms           = _get_forms()
    carousel_items  = _get_carousel_items()
    return render_template("wiki/index.html",
                           pages=pages, forms=forms,
                           carousel_items=carousel_items)


# ── Carousel admin ────────────────────────────────────────────────────────────

@wiki_bp.route("/carousel")
@login_required
@permission_required("wiki", "can_edit")
def carousel():
    carousel_items = _get_carousel_items()
    all_pages = (
        WikiPage.query
        .filter_by(is_deleted=False, is_published=True)
        .order_by(WikiPage.title)
        .all()
    )
    logs = (
        CarouselLog.query
        .order_by(CarouselLog.saved_at.desc())
        .all()
    )
    editors = {u.id: u for u in User.query.all()}
    return render_template(
        "wiki/carousel.html",
        carousel_items=carousel_items,
        all_pages=all_pages,
        logs=logs,
        editors=editors,
    )


@wiki_bp.route("/carousel/save", methods=["POST"])
@login_required
@permission_required("wiki", "can_edit")
def save_carousel():
    data = request.get_json(silent=True) or {}
    new_page_ids = [int(pid) for pid in data.get("page_ids", [])]

    if len(new_page_ids) > 8:
        return jsonify({"ok": False, "error": "Maximum 8 carousel slots allowed."}), 400

    # ── Diff old vs new ──────────────────────────────────────────────────────

    existing_items = CarouselItem.query.order_by(CarouselItem.sort_order).all()
    old_page_ids   = [item.page_id for item in existing_items]
    old_id_set     = set(old_page_ids)
    new_id_set     = set(new_page_ids)

    added_ids   = new_id_set - old_id_set
    removed_ids = old_id_set - new_id_set
    reordered   = (not added_ids and not removed_ids and old_page_ids != new_page_ids)

    # Look up page metadata for the log
    all_relevant = WikiPage.query.filter(
        WikiPage.id.in_(old_id_set | new_id_set)
    ).all()
    page_map = {p.id: p for p in all_relevant}

    def _page_stub(page_id):
        p = page_map.get(page_id)
        if not p:
            return {"title": f"[page {page_id}]", "cover_image": None}
        return {"title": p.title, "cover_image": p.cover_image}

    added_stubs   = [_page_stub(pid) for pid in added_ids]
    removed_stubs = [_page_stub(pid) for pid in removed_ids]

    # ── Update CarouselItem rows ──────────────────────────────────────────────

    # Index existing items by page_id so we can preserve carousel_image overrides
    existing_map = {item.page_id: item for item in existing_items}

    # Remove items that are no longer in the list
    for pid in removed_ids:
        item = existing_map.get(pid)
        if item:
            db.session.delete(item)

    # Add or update items, setting sort_order from the new list position
    for sort_order, page_id in enumerate(new_page_ids):
        if page_id in existing_map:
            existing_map[page_id].sort_order = sort_order
        else:
            db.session.add(CarouselItem(
                page_id=page_id,
                carousel_image=None,
                sort_order=sort_order,
            ))

    # ── Build snapshot for the log ────────────────────────────────────────────

    # Flush so we can read the final carousel_image values from updated items
    db.session.flush()

    updated_items = CarouselItem.query.order_by(CarouselItem.sort_order).all()
    updated_map   = {item.page_id: item for item in updated_items}

    snapshot = []
    for pid in new_page_ids:
        p    = page_map.get(pid)
        item = updated_map.get(pid)
        snapshot.append({
            "title":           p.title         if p    else f"[page {pid}]",
            "cover_image":     p.cover_image   if p    else None,
            "carousel_image":  item.carousel_image if item else None,
        })

    # ── Write log entry ───────────────────────────────────────────────────────

    log = CarouselLog(
        saved_by  = current_user.id,
        added     = added_stubs,
        removed   = removed_stubs,
        reordered = reordered,
        snapshot  = snapshot,
    )
    db.session.add(log)
    db.session.commit()

    return jsonify({"ok": True})


# ── Article ───────────────────────────────────────────────────────────────────

@wiki_bp.route("/article/<slug>")
@login_required
@permission_required("wiki", "can_view")
def article(slug):
    page = get_page_by_slug(slug)
    return render_template("wiki/article.html", page=page)


@wiki_bp.route("/article/<slug>/like", methods=["POST"])
@login_required
@permission_required("wiki", "can_view")
def like(slug):
    page  = get_page_by_slug(slug)
    total = like_page(page)
    return jsonify({"likes": total})


@wiki_bp.route("/article/<slug>/comment", methods=["POST"])
@login_required
@permission_required("wiki", "can_view")
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
@permission_required("wiki", "can_edit")
def delete_comment_route(slug, comment_index):
    page = get_page_by_slug(slug)
    delete_comment(page, comment_index)
    return jsonify({"success": True})


# ── Create / Edit ─────────────────────────────────────────────────────────────

@wiki_bp.route("/create", methods=["GET", "POST"])
@login_required
@permission_required("wiki", "can_create")
def create():
    parent_pages = get_parent_candidates()
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

        # Cover image
        cover_image = None
        cover_file  = request.files.get("cover_image")
        if cover_file and cover_file.filename:
            try:
                cover_image = save_cover_image(cover_file)
            except ValueError as e:
                flash(str(e), "error")
                return render_template("wiki/form.html", page=None,
                                       parent_pages=parent_pages, forms=forms,
                                       form=request.form, action="create")

        # Carousel image (optional override)
        carousel_image = None
        carousel_file  = request.files.get("carousel_image")
        if carousel_file and carousel_file.filename:
            try:
                carousel_image = save_carousel_image(carousel_file)
            except ValueError as e:
                flash(str(e), "error")
                return render_template("wiki/form.html", page=None,
                                       parent_pages=parent_pages, forms=forms,
                                       form=request.form, action="create")

        try:
            page = create_page(title=title, body=body, description=description,
                               cover_image=cover_image, parent_id=parent_id,
                               is_published=is_published, created_by=current_user.id)
            page.form_config_id    = form_config_id
            page.carousel_image    = carousel_image

            attachment_errors = []
            for f in request.files.getlist("attachments"):
                if f and f.filename:
                    try:
                        save_attachment(f, page.id, current_user.id)
                    except ValueError as e:
                        attachment_errors.append(str(e))

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
@permission_required("wiki", "can_edit")
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

        # Cover image
        cover_image = None
        cover_file  = request.files.get("cover_image")
        if cover_file and cover_file.filename:
            try:
                cover_image = save_cover_image(cover_file)
            except ValueError as e:
                flash(str(e), "error")
                return render_template("wiki/form.html", page=page,
                                       parent_pages=parent_pages, forms=forms,
                                       form=request.form, action="edit")

        # Carousel image — new upload, removal checkbox, or leave unchanged
        carousel_file   = request.files.get("carousel_image")
        remove_carousel = bool(request.form.get("remove_carousel_image"))

        if remove_carousel:
            page.carousel_image = None
        elif carousel_file and carousel_file.filename:
            try:
                page.carousel_image = save_carousel_image(carousel_file)
            except ValueError as e:
                flash(str(e), "error")
                return render_template("wiki/form.html", page=page,
                                       parent_pages=parent_pages, forms=forms,
                                       form=request.form, action="edit")
        # else: leave page.carousel_image unchanged

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


# ── Attachments / publish / delete / history (unchanged) ─────────────────────

@wiki_bp.route("/attachment/<int:attachment_id>/delete", methods=["POST"])
@login_required
@permission_required("wiki", "can_edit")
def delete_wiki_attachment(attachment_id):
    attachment = get_attachment_or_404(attachment_id)
    page_id    = attachment.page_id
    delete_attachment(attachment)
    flash("Attachment deleted.", "success")
    return redirect(url_for("wiki.edit", page_id=page_id))


@wiki_bp.route("/<int:page_id>/toggle-publish", methods=["POST"])
@login_required
@permission_required("wiki", "can_edit")
def toggle_publish_route(page_id):
    page      = get_page_or_404(page_id)
    published = toggle_publish(page)
    state     = "published" if published else "unpublished"
    flash(f'"{page.title}" {state}.', "success")
    return redirect(url_for("wiki.index"))


@wiki_bp.route("/<int:page_id>/delete", methods=["POST"])
@login_required
@permission_required("wiki", "can_delete")
def delete(page_id):
    page  = get_page_or_404(page_id)
    title = page.title
    delete_page(page)
    flash(f'Page "{title}" deleted.', "success")
    return redirect(url_for("wiki.index"))


@wiki_bp.route("/<int:page_id>/history")
@login_required
@permission_required("wiki", "can_view")
def history(page_id):
    page      = get_page_or_404(page_id)
    snapshots = get_page_history(page_id)
    editors   = {u.id: u for u in User.query.all()}
    return render_template("wiki/history.html",
                           page=page, snapshots=snapshots, editors=editors)