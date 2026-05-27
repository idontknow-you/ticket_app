import os
import uuid
from flask import Blueprint, render_template, request, redirect, url_for, flash, current_app
from extensions import db
from models.ticket import Ticket, TicketAttachment
from services.ticket_service import generate_ticket_number
from services.wiki_service import get_published_top_level_pages
from services.email_service import send_ticket_confirmation
from services.form_service import get_form_config, CONFIGURABLE_FIELDS

public_bp = Blueprint('public', __name__)

MODULES = [
    'Module A', 'Module B', 'Module C', 'Module D', 'Module E',
    'Module F', 'Module G', 'Module H', 'Module I', 'Module J',
    'Module K', 'Module L', 'Module M', 'Module N', 'Module O',
    'Module P', 'Module Q', 'Module R', 'Module S', 'Module T',
    'Module U', 'Module V', 'Module W', 'Module X', 'Module Y',
    'Module Z',
]

TYPES = ['Issue', 'Bug', 'Other']

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp', 'pdf'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def save_attachment(file, ticket_id):
    upload_dir = os.path.join(current_app.root_path, 'uploads', str(ticket_id))
    os.makedirs(upload_dir, exist_ok=True)

    original_filename = file.filename
    ext = original_filename.rsplit('.', 1)[1].lower()
    stored_filename = f"{uuid.uuid4().hex}.{ext}"
    file_path = os.path.join(upload_dir, stored_filename)
    file.save(file_path)
    file_size = os.path.getsize(file_path)
    file_type = file.content_type or 'application/octet-stream'

    return TicketAttachment(
        ticket_id=ticket_id,
        file_name=original_filename,
        file_path=file_path,
        file_type=file_type,
        file_size=file_size,
        uploaded_by=None,
    )


def get_wiki_pages():
    return get_published_top_level_pages()


@public_bp.route('/', methods=['GET', 'POST'])
def submit():
    form_config = get_form_config()

    if request.method == 'POST':
        submitter_name  = request.form.get('submitter_name', '').strip()
        submitter_email = request.form.get('submitter_email', '').strip()
        subject         = request.form.get('subject', '').strip()
        description     = request.form.get('description', '').strip()
        files           = request.files.getlist('attachments')
        ticket_type     = request.form.get('type', '').strip()
        module          = request.form.get('module', '').strip()
        department      = request.form.get('department', '').strip()

        errors = []

        if not submitter_name:
            errors.append('Your name is required.')
        if not submitter_email or '@' not in submitter_email:
            errors.append('A valid email address is required.')

        if form_config['subject']['visible'] and form_config['subject']['required'] and not subject:
            errors.append('Subject is required.')
        if form_config['description']['visible'] and form_config['description']['required'] and not description:
            errors.append('Please describe your issue.')
        if form_config['type']['visible'] and form_config['type']['required'] and not ticket_type:
            errors.append('Type is required.')
        if form_config['module']['visible'] and form_config['module']['required'] and not module:
            errors.append('Module is required.')
        if form_config['department']['visible'] and form_config['department']['required'] and not department:
            errors.append('Department is required.')

        valid_files = []
        if form_config['attachments']['visible']:
            for f in files:
                if f and f.filename:
                    if not allowed_file(f.filename):
                        errors.append(f'"{f.filename}" is not allowed. Only images and PDFs are accepted.')
                    else:
                        f.seek(0, os.SEEK_END)
                        size = f.tell()
                        f.seek(0)
                        if size > MAX_FILE_SIZE:
                            errors.append(f'"{f.filename}" exceeds the 10MB limit.')
                        else:
                            valid_files.append(f)

        if errors:
            for error in errors:
                flash(error, 'error')
            return render_template('public/submit_form.html',
                                   modules=MODULES, types=TYPES,
                                   form=request.form,
                                   form_config=form_config,
                                   wiki_pages=get_wiki_pages())

        ticket_number = generate_ticket_number(ticket_type or 'Other')
        ticket = Ticket(
            ticket_number=ticket_number,
            submitter_name=submitter_name,
            submitter_email=submitter_email,
            subject=subject or '(no subject)',
            description=description or '',
            status='Open',
            priority='Low',
            type=ticket_type or 'Other',
            module=module or '',
        )
        db.session.add(ticket)
        db.session.flush()

        for f in valid_files:
            attachment = save_attachment(f, ticket.id)
            db.session.add(attachment)

        db.session.commit()

        try:
            send_ticket_confirmation(
                to_email=submitter_email,
                to_name=submitter_name,
                ticket_number=ticket_number,
                subject=subject or '(no subject)',
            )
        except Exception as e:
            current_app.logger.error(f'Failed to send confirmation email: {e}')

        return redirect(url_for('public.confirmation', ticket_number=ticket_number))

    return render_template('public/submit_form.html',
                           modules=MODULES, types=TYPES,
                           form={},
                           form_config=form_config,
                           wiki_pages=get_wiki_pages())


@public_bp.route('/confirmation/<ticket_number>')
def confirmation(ticket_number):
    ticket = Ticket.query.filter_by(ticket_number=ticket_number).first_or_404()
    return render_template('public/submit_success.html', ticket=ticket, wiki_pages=get_wiki_pages())
