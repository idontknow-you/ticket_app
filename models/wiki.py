from extensions import db
from datetime import datetime
import re

def generate_slug(title):
    slug = title.lower().strip()
    slug = re.sub(r'[^\w\s-]', '', slug)
    slug = re.sub(r'[\s_-]+', '-', slug)
    slug = re.sub(r'^-+|-+$', '', slug)
    return slug

class WikiPage(db.Model):
    __tablename__ = 'wiki_pages'

    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(200), nullable=False)
    slug = db.Column(db.String(200), unique=True, nullable=False)
    body = db.Column(db.Text, nullable=False)
    parent_id = db.Column(db.Integer, db.ForeignKey('wiki_pages.id'), nullable=True)
    created_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    updated_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=True)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_published = db.Column(db.Boolean, default=False)

    children = db.relationship('WikiPage', backref=db.backref('parent', remote_side=[id]), lazy=True)
    history = db.relationship('WikiPageHistory', backref='page', lazy=True)

class WikiPageHistory(db.Model):
    __tablename__ = 'wiki_page_history'

    id = db.Column(db.Integer, primary_key=True)
    page_id = db.Column(db.Integer, db.ForeignKey('wiki_pages.id'), nullable=False)
    body_snapshot = db.Column(db.Text, nullable=False)
    edited_by = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    edited_at = db.Column(db.DateTime, default=datetime.utcnow)