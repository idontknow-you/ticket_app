import os
import uuid
from werkzeug.utils import secure_filename
from extensions import db
from models.wiki_page import WikiPage, WikiAttachment, WikiHistory

UPLOAD_FOLDER = os.path.join(os.path.dirname(__file__), "..", "static", "wiki_uploads")
ALLOWED_EXTENSIONS = {
    "pdf", "doc", "docx", "xls", "xlsx", "ppt", "pptx",
    "png", "jpg", "jpeg", "gif", "webp", "zip", "txt", "csv",
}
MAX_SIZE = 16 * 1024 * 1024  # 16 MB


# ── Queries ────────────────────────────────────────────────────────────────────

def get_all_top_level_pages():
    return (
        WikiPage.query
        .filter_by(is_deleted=False, parent_id=None)
        .order_by(WikiPage.order, WikiPage.title)
        .all()
    )


def get_published_pages():
    return (
        WikiPage.query
        .filter_by(is_deleted=False, is_published=True, parent_id=None)
        .order_by(WikiPage.order, WikiPage.title)
        .all()
    )


def get_page_or_404(page_id):
    page = WikiPage.query.filter_by(id=page_id, is_deleted=False).first_or_404()
    return page


def get_page_by_slug(slug):
    return WikiPage.query.filter_by(slug=slug, is_deleted=False, is_published=True).first_or_404()


def get_parent_candidates(exclude_id=None):
    q = WikiPage.query.filter_by(is_deleted=False, parent_id=None)
    if exclude_id:
        q = q.filter(WikiPage.id != exclude_id)
    return q.order_by(WikiPage.title).all()


def get_page_history(page_id):
    return WikiHistory.query.filter_by(page_id=page_id).order_by(WikiHistory.saved_at.desc()).all()


def get_attachment_or_404(attachment_id):
    att = WikiAttachment.query.get_or_404(attachment_id)
    return att


# ── Mutations ──────────────────────────────────────────────────────────────────

def _unique_slug(base, exclude_id=None):
    slug, n = base, 1
    while True:
        q = WikiPage.query.filter_by(slug=slug, is_deleted=False)
        if exclude_id:
            q = q.filter(WikiPage.id != exclude_id)
        if not q.first():
            return slug
        slug, n = f"{base}-{n}", n + 1


def create_page(title, body, parent_id, is_published, created_by,
                description="", cover_image=None):
    if not title:
        raise ValueError("Title is required.")
    slug = _unique_slug(WikiPage.slugify(title))
    order = (db.session.query(db.func.max(WikiPage.order)).scalar() or 0) + 1
    page = WikiPage(
        title=title,
        slug=slug,
        body=body,
        description=description,
        cover_image=cover_image,
        parent_id=int(parent_id) if parent_id else None,
        is_published=is_published,
        order=order,
        created_by=created_by,
        updated_by=created_by,
    )
    db.session.add(page)
    db.session.commit()
    return page


def update_page(page, title, body, parent_id, is_published, updated_by,
                description=None, cover_image=None):
    if not title:
        raise ValueError("Title is required.")

    # snapshot history before overwriting
    snap = WikiHistory(page_id=page.id, title=page.title, body=page.body, saved_by=updated_by)
    db.session.add(snap)

    if title != page.title:
        page.slug = _unique_slug(WikiPage.slugify(title), exclude_id=page.id)

    page.title       = title
    page.body        = body
    page.parent_id   = int(parent_id) if parent_id else None
    page.is_published = is_published
    page.updated_by  = updated_by
    if description is not None:
        page.description = description
    if cover_image is not None:
        page.cover_image = cover_image

    db.session.commit()
    return page


def toggle_publish(page):
    page.is_published = not page.is_published
    db.session.commit()
    return page.is_published


def delete_page(page):
    page.soft_delete()
    db.session.commit()


# ── Attachments ────────────────────────────────────────────────────────────────

def save_attachment(file_storage, page_id, uploaded_by):
    original = secure_filename(file_storage.filename)
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in ALLOWED_EXTENSIONS:
        raise ValueError(f"'{original}' — file type not allowed.")

    file_storage.seek(0, 2)
    size = file_storage.tell()
    file_storage.seek(0)
    if size > MAX_SIZE:
        raise ValueError(f"'{original}' exceeds the 16 MB limit.")

    stored_name = f"{uuid.uuid4().hex}.{ext}"
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    file_storage.save(os.path.join(UPLOAD_FOLDER, stored_name))

    att = WikiAttachment(
        page_id=page_id,
        filename=stored_name,
        original_name=original,
        uploaded_by=uploaded_by,
    )
    db.session.add(att)
    return att


def save_cover_image(file_storage):
    """Save a cover image and return the stored filename."""
    original = secure_filename(file_storage.filename)
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in {"png", "jpg", "jpeg", "gif", "webp"}:
        raise ValueError(f"'{original}' — only image files allowed for cover.")
    file_storage.seek(0, 2)
    size = file_storage.tell()
    file_storage.seek(0)
    if size > MAX_SIZE:
        raise ValueError(f"Cover image exceeds 16 MB.")
    stored_name = f"cover_{uuid.uuid4().hex}.{ext}"
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    file_storage.save(os.path.join(UPLOAD_FOLDER, stored_name))
    return stored_name


def delete_attachment(attachment):
    path = os.path.join(UPLOAD_FOLDER, attachment.filename)
    if os.path.exists(path):
        os.remove(path)
    db.session.delete(attachment)
    db.session.commit()


# ── Likes & Comments ───────────────────────────────────────────────────────────

def like_page(page):
    page.likes = (page.likes or 0) + 1
    db.session.commit()
    return page.likes


def add_comment(page, author, text):
    from datetime import datetime
    comments = list(page.comments or [])
    comments.append({"author": author, "text": text, "at": datetime.utcnow().isoformat()})
    page.comments = comments
    db.session.commit()
    return comments

def delete_comment(page: WikiPage, index: int):
    page.delete_comment(index)
    db.session.commit()