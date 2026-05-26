"""
services/form_service.py

Shared form-field configuration helpers.
Imported by both routes/public.py and routes/admin.py to avoid circular imports.
"""

from models.settings import Setting

# Fields that admins can toggle visibility/required on.
# name and email are always on and are NOT in this list.
CONFIGURABLE_FIELDS = ['subject', 'description', 'department', 'module', 'type', 'attachments']

# Fallback defaults used when no Setting row exists yet (fresh install)
_DEFAULTS = {
    'subject':     {'visible': True,  'required': True},
    'description': {'visible': True,  'required': True},
    'department':  {'visible': False, 'required': False},
    'module':      {'visible': True,  'required': True},
    'type':        {'visible': True,  'required': True},
    'attachments': {'visible': True,  'required': False},
}


def get_form_config() -> dict:
    """
    Read per-field visibility and required flags from the Setting EAV table.

    Returns a dict keyed by field name:
      {
        'subject':     {'visible': True,  'required': True},
        'description': {'visible': True,  'required': True},
        'department':  {'visible': False, 'required': False},
        'module':      {'visible': True,  'required': True},
        'type':        {'visible': True,  'required': True},
        'attachments': {'visible': True,  'required': False},
      }

    A hidden field is never required, even if the DB row says otherwise.
    """
    config = {}
    for field in CONFIGURABLE_FIELDS:
        vis_row = Setting.query.filter_by(key=f'form_field_{field}_visible').first()
        req_row = Setting.query.filter_by(key=f'form_field_{field}_required').first()

        visible  = (vis_row.value == 'true') if vis_row else _DEFAULTS[field]['visible']
        required = (req_row.value == 'true') if req_row else _DEFAULTS[field]['required']

        config[field] = {
            'visible':  visible,
            'required': required and visible,  # hidden → never required
        }

    return config
