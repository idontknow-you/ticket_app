from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from models.permission import UserPermission
from models.user import User
from decorators import require_permission
from services.wiki_service import (
    get_all_top_level_pages,
    get_page_or_404,
    get_parent_candidates,
    get_page_history,
    create_page,
    update_page,
    toggle_publish,
    delete_page,
    save_attachment,
    delete_attachment,
    get_attachment_or_404,
)


wiki_bp = Blueprint('wiki', __name__, url_prefix='/wiki')


def _wiki_perm():
    """Return current user's Wiki permission, or synthetic _All for superadmin."""
    if current_user.is_superadmin:
        class _All:
            can_view = can_create = can_edit = can_delete = True
        return _All()
    return UserPermission.query.filter_by(
        user_id=current_user.id, module='Wiki'
    ).first()


@wiki_bp.context_processor
def wiki_permissions():
    if not current_user.is_authenticated:
        return dict(wiki_perm=None)
    return dict(wiki_perm=_wiki_perm())


@wiki_bp.route('/')
@login_required
@require_permission('Wiki', 'can_view')
def index():
    pages = get_all_top_level_pages()
    return render_template('wiki/index.html', pages=pages)


@wiki_bp.route('/create', methods=['GET', 'POST'])
@login_required
@require_permission('Wiki', 'can_create')
def create():
    parent_pages = get_parent_candidates()

    if request.method == 'POST':
        title        = request.form.get('title', '').strip()
        body         = request.form.get('body_html', '').strip()
        parent_id    = request.form.get('parent_id') or None
        is_published = bool(request.form.get('is_published'))

        try:
            page = create_page(
                title=title,
                body=body,
                parent_id=parent_id,
                is_published=is_published,
                created_by=current_user.id,
            )

            # Save any uploaded attachments now that we have a page.id
            uploaded_files = request.files.getlist('attachments')
            for f in uploaded_files:
                if f and f.filename:
                    try:
                        save_attachment(f, page.id, current_user.id)
                    except ValueError as e:
                        flash(str(e), 'error')

            flash(f'Page "{page.title}" created.', 'success')
            return redirect(url_for('wiki.index'))

        except ValueError as e:
            flash(str(e), 'error')
            return render_template('wiki/form.html', page=None,
                                   parent_pages=parent_pages,
                                   form=request.form, action='create')

    return render_template('wiki/form.html', page=None,
                           parent_pages=parent_pages,
                           form={}, action='create')


@wiki_bp.route('/<int:page_id>/edit', methods=['GET', 'POST'])
@login_required
@require_permission('Wiki', 'can_edit')
def edit(page_id):
    page         = get_page_or_404(page_id)
    parent_pages = get_parent_candidates(exclude_id=page_id)

    if request.method == 'POST':
        title        = request.form.get('title', '').strip()
        body         = request.form.get('body_html', '').strip()
        parent_id    = request.form.get('parent_id') or None
        is_published = bool(request.form.get('is_published'))

        try:
            update_page(
                page=page,
                title=title,
                body=body,
                parent_id=parent_id,
                is_published=is_published,
                updated_by=current_user.id,
            )

            # Save any newly uploaded attachments
            uploaded_files = request.files.getlist('attachments')
            for f in uploaded_files:
                if f and f.filename:
                    try:
                        save_attachment(f, page.id, current_user.id)
                    except ValueError as e:
                        flash(str(e), 'error')

            flash(f'Page "{page.title}" updated.', 'success')
            return redirect(url_for('wiki.index'))

        except ValueError as e:
            flash(str(e), 'error')
            return render_template('wiki/form.html', page=page,
                                   parent_pages=parent_pages,
                                   form=request.form, action='edit')

    return render_template('wiki/form.html', page=page,
                           parent_pages=parent_pages,
                           form={}, action='edit')


@wiki_bp.route('/attachment/<int:attachment_id>/delete', methods=['POST'])
@login_required
@require_permission('Wiki', 'can_delete')
def delete_wiki_attachment(attachment_id):
    attachment = get_attachment_or_404(attachment_id)
    page_id    = attachment.page_id
    delete_attachment(attachment)
    flash('Attachment deleted.', 'success')
    return redirect(url_for('wiki.edit', page_id=page_id))


@wiki_bp.route('/<int:page_id>/toggle-publish', methods=['POST'])
@login_required
@require_permission('Wiki', 'can_edit')
def toggle_publish_route(page_id):
    page      = get_page_or_404(page_id)
    published = toggle_publish(page)
    state     = 'published' if published else 'unpublished'
    flash(f'"{page.title}" {state}.', 'success')
    return redirect(url_for('wiki.index'))


@wiki_bp.route('/<int:page_id>/delete', methods=['POST'])
@login_required
@require_permission('Wiki', 'can_delete')
def delete(page_id):
    page  = get_page_or_404(page_id)
    title = page.title
    delete_page(page)
    flash(f'Page "{title}" deleted.', 'success')
    return redirect(url_for('wiki.index'))


@wiki_bp.route('/<int:page_id>/history')
@login_required
@require_permission('Wiki', 'can_view')
def history(page_id):
    page      = get_page_or_404(page_id)
    snapshots = get_page_history(page_id)
    # Load ALL users (including deactivated) so history editor names resolve
    editors   = {u.id: u for u in User.query.all()}
    return render_template('wiki/history.html',
                           page=page, snapshots=snapshots, editors=editors)
