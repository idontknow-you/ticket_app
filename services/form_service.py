"""
services/form_service.py

Shared form-field configuration helpers.
Imported by both routes/public.py and routes/admin.py to avoid circular imports.
"""

from models.settings import Setting

CONFIGURABLE_FIELDS = ['subject', 'description', 'department', 'module', 'type', 'attachments']

_DEFAULTS = {
    'subject':     {'visible': True,  'required': True},
    'description': {'visible': True,  'required': True},
    'department':  {'visible': False, 'required': False},
    'module':      {'visible': True,  'required': True},
    'type':        {'visible': True,  'required': True},
    'attachments': {'visible': True,  'required': False},
}


class FieldConfig:
    """
    Wraps a field's visible/required flags as object attributes so that
    Jinja2 dot notation (form_config.attachments.visible) works correctly.
    Plain nested dicts fail silently with dot access in Jinja2 templates.
    """
    def __init__(self, visible, required):
        self.visible  = visible
        self.required = required and visible  # hidden field is never required


def get_form_config() -> dict:
    """
    Read per-field visibility and required flags from the Setting EAV table.
    Returns a dict of FieldConfig objects keyed by field name, e.g.:
      {
        'subject':     FieldConfig(visible=True,  required=True),
        'attachments': FieldConfig(visible=True,  required=False),
        ...
      }
    Falls back to _DEFAULTS if no DB row exists yet.
    """
    config = {}
    for field in CONFIGURABLE_FIELDS:
        vis_row = Setting.query.filter_by(key=f'form_field_{field}_visible').first()
        req_row = Setting.query.filter_by(key=f'form_field_{field}_required').first()

        visible  = (vis_row.value == 'true') if vis_row else _DEFAULTS[field]['visible']
        required = (req_row.value == 'true') if req_row else _DEFAULTS[field]['required']

        config[field] = FieldConfig(visible=visible, required=required)

    return config
