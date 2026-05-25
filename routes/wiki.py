from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_required, current_user
from extensions import db
from models.wiki import WikiPage, WikiPageHistory, generate_slug
from models.permission import UserPermission
from models.user import User
from decorators import require_permission

wiki_bp = Blueprint('wiki', __name__, url_prefix='/wiki')


@wiki_bp.context_processor
def wiki_permissions():
    if not current_user.is_authenticated:
        return dict(wiki_perm=None)
    if current_user.is_superadmin:
        class _All:
            can_view = can_create = can_edit = can_delete = True
        return dict(wiki_perm=_All())
    perm = UserPermission.query.filter_by(
        user_id=current_user.id, module='Wiki'
    ).first()
    return dict(wiki_perm=perm)


@wiki_bp.route('/')
@login_required
@require_permission('Wiki', 'can_view')
def index():
    pages = WikiPage.query.filter_by(parent_id=None).order_by(WikiPage.title).all()
    return render_template('wiki/index.html', pages=pages)


@wiki_bp.route('/create', methods=['GET', 'POST'])
@login_required
@require_permission('Wiki', 'can_create')
def create():
    parent_pages = WikiPage.query.filter_by(parent_id=None).order_by(WikiPage.title).all()

    if request.method == 'POST':
        title        = request.form.get('title', '').strip()
        body         = request.form.get('body', '').strip()
        parent_id    = request.form.get('parent_id') or None
        is_published = bool(request.form.get('is_published'))

        if not title or not body:
            flash('Title and body are required.', 'error')
            return render_template('wiki/form.html', page=None, parent_pages=parent_pages,
                                   form=request.form, action='create')

        slug = generate_slug(title)
        base_slug, counter = slug, 1
        while WikiPage.query.filter_by(slug=slug).first():
            slug = f"{base_slug}-{counter}"
            counter += 1

        page = WikiPage(
            title=title,
            slug=slug,
            body=body,
            parent_id=int(parent_id) if parent_id else None,
            created_by=current_user.id,
            is_published=is_published,
        )
        db.session.add(page)
        db.session.commit()
        flash(f'Page "{title}" created.', 'success')
        return redirect(url_for('wiki.index'))

    return render_template('wiki/form.html', page=None, parent_pages=parent_pages,
                           form={}, action='create')


@wiki_bp.route('/<int:page_id>/edit', methods=['GET', 'POST'])
@login_required
@require_permission('Wiki', 'can_edit')
def edit(page_id):
    page = WikiPage.query.get_or_404(page_id)
    parent_pages = WikiPage.query.filter(
        WikiPage.parent_id == None,
        WikiPage.id != page_id
    ).order_by(WikiPage.title).all()

    if request.method == 'POST':
        title        = request.form.get('title', '').strip()
        body         = request.form.get('body', '').strip()
        parent_id    = request.form.get('parent_id') or None
        is_published = bool(request.form.get('is_published'))

        if not title or not body:
            flash('Title and body are required.', 'error')
            return render_template('wiki/form.html', page=page, parent_pages=parent_pages,
                                   form=request.form, action='edit')

        snapshot = WikiPageHistory(
            page_id=page.id,
            body_snapshot=page.body,
            edited_by=current_user.id,
        )
        db.session.add(snapshot)

        if title != page.title:
            slug = generate_slug(title)
            base_slug, counter = slug, 1
            while WikiPage.query.filter(WikiPage.slug == slug, WikiPage.id != page_id).first():
                slug = f"{base_slug}-{counter}"
                counter += 1
            page.slug = slug

        page.title        = title
        page.body         = body
        page.parent_id    = int(parent_id) if parent_id else None
        page.is_published = is_published
        page.updated_by   = current_user.id

        db.session.commit()
        flash(f'Page "{title}" updated.', 'success')
        return redirect(url_for('wiki.index'))

    return render_template('wiki/form.html', page=page, parent_pages=parent_pages,
                           form={}, action='edit')


@wiki_bp.route('/<int:page_id>/toggle-publish', methods=['POST'])
@login_required
@require_permission('Wiki', 'can_edit')
def toggle_publish(page_id):
    page = WikiPage.query.get_or_404(page_id)
    page.is_published = not page.is_published
    db.session.commit()
    state = 'published' if page.is_published else 'unpublished'
    flash(f'"{page.title}" {state}.', 'success')
    return redirect(url_for('wiki.index'))


@wiki_bp.route('/<int:page_id>/delete', methods=['POST'])
@login_required
@require_permission('Wiki', 'can_delete')
def delete(page_id):
    page = WikiPage.query.get_or_404(page_id)
    for child in page.children:
        child.parent_id = None
    db.session.delete(page)
    db.session.commit()
    flash(f'Page "{page.title}" deleted.', 'success')
    return redirect(url_for('wiki.index'))


@wiki_bp.route('/<int:page_id>/history')
@login_required
@require_permission('Wiki', 'can_view')
def history(page_id):
    page = WikiPage.query.get_or_404(page_id)
    snapshots = WikiPageHistory.query.filter_by(page_id=page_id)\
                    .order_by(WikiPageHistory.edited_at.desc()).all()
    editors = {u.id: u for u in User.query.filter_by(is_active=True).all()}
    return render_template('wiki/history.html', page=page, snapshots=snapshots, editors=editors)