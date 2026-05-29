from .auth import auth_bp
from .public import public_bp
from .tickets import tickets_bp
from .admin import admin_bp
from .forms import forms_bp
from .wiki import wiki_bp

__all__ = ["auth_bp", "public_bp", "tickets_bp", "admin_bp", "forms_bp", "wiki_bp"]