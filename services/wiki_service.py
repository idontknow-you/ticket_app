"""
wiki_service.py

Business logic for wiki page operations.
Extracted from routes/wiki.py so the blueprint stays thin.
"""
import os, uuid
from extensions import db
from models.wiki import WikiPage, WikiPageHistory, generate_slug, WikiAttachment
from werkzeug.utils import secure_filename
from extensions import db

# ── Queries ──────────────────────────────────────────────────────────────────

def get_all_top_level_pages():
    """All root pages (no parent), ordered by title."""
    return WikiPage.query.filter_by(parent_id=None).order_by(WikiPage.title).all()


def get_published_top_level_pages():
    """Published root pages only — used by the public wiki panel."""
    return (
        WikiPage.query
        .filter_by(is_published=True, parent_id=None)
        .order_by(WikiPage.title)
        .all()
    )


def get_page_or_404(page_id):
    """Fetch a WikiPage by id or raise 404."""
    return WikiPage.query.get_or_404(page_id)


def get_parent_candidates(exclude_id=None):
    """
    Top-level pages suitable for use as a parent in the form dropdown.
    Excludes the page being edited (can't be its own parent).
    """
    q = WikiPage.query.filter_by(parent_id=None).order_by(WikiPage.title)
    if exclude_id is not None:
        q = q.filter(WikiPage.id != exclude_id)
    return q.all()


def get_page_history(page_id):
    """All history snapshots for a page, newest first."""
    return (
        WikiPageHistory.query
        .filter_by(page_id=page_id)
        .order_by(WikiPageHistory.edited_at.desc())
        .all()
    )


# ── Slug helpers ─────────────────────────────────────────────────────────────

def unique_slug(title, exclude_id=None):
    """
    Generate a URL slug from *title* that does not already exist in the DB.
    When editing, pass the current page's id as *exclude_id* so we don't
    collide with the page itself.
    """
    base = generate_slug(title)
    slug = base
    counter = 1
    while True:
        q = WikiPage.query.filter(WikiPage.slug == slug)
        if exclude_id is not None:
            q = q.filter(WikiPage.id != exclude_id)
        if not q.first():
            break
        slug = f"{base}-{counter}"
        counter += 1
    return slug


# ── Write operations ──────────────────────────────────────────────────────────

def create_page(title, body, parent_id, is_published, created_by):
    """
    Create a new WikiPage.
    Returns the saved WikiPage instance.
    Raises ValueError if title or body are blank.
    """
    title = title.strip()
    body = body.strip()
    if not title or not body:
        raise ValueError("Title and body are required.")

    slug = unique_slug(title)
    page = WikiPage(
        title=title,
        slug=slug,
        body=body,
        parent_id=int(parent_id) if parent_id else None,
        created_by=created_by,
        is_published=is_published,
    )
    db.session.add(page)
    db.session.commit()
    return page


def update_page(page, title, body, parent_id, is_published, updated_by):
    """
    Update an existing WikiPage.
    Saves a history snapshot of the *previous* body before writing.
    Returns the updated WikiPage instance.
    Raises ValueError if title or body are blank.
    """
    title = title.strip()
    body = body.strip()
    if not title or not body:
        raise ValueError("Title and body are required.")

    # Snapshot the current body before overwriting
    snapshot = WikiPageHistory(
        page_id=page.id,
        body_snapshot=page.body,
        edited_by=updated_by,
    )
    db.session.add(snapshot)

    # Only regenerate slug when the title actually changes
    if title != page.title:
        page.slug = unique_slug(title, exclude_id=page.id)

    page.title = title
    page.body = body
    page.parent_id = int(parent_id) if parent_id else None
    page.is_published = is_published
    page.updated_by = updated_by

    db.session.commit()
    return page


def toggle_publish(page):
    """
    Flip the is_published flag on *page*.
    Returns the new boolean state.
    """
    page.is_published = not page.is_published
    db.session.commit()
    return page.is_published


def delete_page(page):
    """
    Hard-delete *page*.  Any child pages are re-parented to None (top-level)
    so they are not orphaned.
    """
    for child in page.children:
        child.parent_id = None
    db.session.delete(page)
    db.session.commit()

WIKI_UPLOAD_FOLDER = os.path.join('static', 'wiki_uploads')
ALLOWED_EXTENSIONS = {
    'pdf', 'doc', 'docx', 'xls', 'xlsx', 'ppt', 'pptx',
    'txt', 'md', 'csv', 'zip', 'png', 'jpg', 'jpeg', 'gif', 'webp'
}

def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_attachment(file, page_id, uploader_id):
    """Persist an uploaded file and return the new WikiAttachment (not yet committed)."""
    if not allowed_file(file.filename):
        raise ValueError(f"File type not allowed.")

    original_name = secure_filename(file.filename)
    ext           = original_name.rsplit('.', 1)[1].lower()
    stored_name   = f"{uuid.uuid4().hex}.{ext}"

    os.makedirs(WIKI_UPLOAD_FOLDER, exist_ok=True)
    file.save(os.path.join(WIKI_UPLOAD_FOLDER, stored_name))

    attachment = WikiAttachment(
        page_id       = page_id,
        filename      = stored_name,
        original_name = original_name,
        uploaded_by   = uploader_id,
    )
    db.session.add(attachment)
    return attachment


def delete_attachment(attachment):
    """Remove file from disk and delete the DB row."""
    path = os.path.join(WIKI_UPLOAD_FOLDER, attachment.filename)
    if os.path.exists(path):
        os.remove(path)
    db.session.delete(attachment)
    db.session.commit()


def get_attachment_or_404(attachment_id):
    return WikiAttachment.query.get_or_404(attachment_id)