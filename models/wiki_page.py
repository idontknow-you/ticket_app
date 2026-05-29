from extensions import db
from datetime import datetime
import re


class WikiPage(db.Model):
    __tablename__ = "wiki_pages"

    id          = db.Column(db.Integer, primary_key=True)
    parent_id   = db.Column(db.Integer, db.ForeignKey("wiki_pages.id"), nullable=True)
    form_config_id = db.Column(db.Integer, db.ForeignKey("form_configurations.id"), nullable=True)
    title       = db.Column(db.String(255), nullable=False)
    slug        = db.Column(db.String(255), nullable=False, unique=True)
    body        = db.Column(db.Text, default="")
    description = db.Column(db.String(500), default="")   # short excerpt shown on cards
    cover_image = db.Column(db.String(500), nullable=True) # filename in wiki_uploads/
    is_published = db.Column(db.Boolean, default=False, nullable=False)
    order       = db.Column(db.Integer, default=0)
    likes       = db.Column(db.Integer, default=0)
    comments    = db.Column(db.JSON, default=list)         # [{author, text, at}]
    created_by  = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    updated_by  = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    created_at  = db.Column(db.DateTime, default=datetime.utcnow)
    updated_at  = db.Column(db.DateTime, default=datetime.utcnow, onupdate=datetime.utcnow)
    is_deleted  = db.Column(db.Boolean, default=False, nullable=False)
    deleted_at  = db.Column(db.DateTime, nullable=True)

    # relationships
    children    = db.relationship(
        "WikiPage",
        backref=db.backref("parent", remote_side=[id]),
        lazy="dynamic",
        foreign_keys="WikiPage.parent_id",
    )
    attachments = db.relationship(
        "WikiAttachment",
        backref="page",
        lazy="dynamic",
        cascade="all, delete-orphan",
    )
    history     = db.relationship(
        "WikiHistory",
        backref="page",
        lazy="dynamic",
        cascade="all, delete-orphan",
        order_by="WikiHistory.saved_at.desc()",
    )
    author      = db.relationship("User", foreign_keys=[created_by])
    editor      = db.relationship("User", foreign_keys=[updated_by])
    form_config = db.relationship(
        "FormConfig",
        backref=db.backref("wiki_pages", lazy="dynamic"),
        foreign_keys=[form_config_id],
        lazy="joined",
    )

    def soft_delete(self):
        self.is_deleted = True
        self.deleted_at = datetime.utcnow()

    def delete_comment(self, index: int):
        comments = list(self.comments or [])
        if 0 <= index < len(comments):
            comments[index] = {**comments[index], "is_deleted": True}
            self.comments = comments

    @staticmethod
    def slugify(text):
        text = text.lower().strip()
        text = re.sub(r"[^a-z0-9]+", "-", text)
        return text.strip("-")[:80]

    def __repr__(self):
        return f"<WikiPage {self.slug}>"


class WikiAttachment(db.Model):
    __tablename__ = "wiki_attachments"

    id            = db.Column(db.Integer, primary_key=True)
    page_id       = db.Column(db.Integer, db.ForeignKey("wiki_pages.id"), nullable=False)
    filename      = db.Column(db.String(255), nullable=False)   # uuid-based stored name
    original_name = db.Column(db.String(255), nullable=False)
    uploaded_by   = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    uploaded_at   = db.Column(db.DateTime, default=datetime.utcnow)


class WikiHistory(db.Model):
    __tablename__ = "wiki_history"

    id       = db.Column(db.Integer, primary_key=True)
    page_id  = db.Column(db.Integer, db.ForeignKey("wiki_pages.id"), nullable=False)
    title    = db.Column(db.String(255))
    body     = db.Column(db.Text)
    saved_by = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)
    saved_at = db.Column(db.DateTime, default=datetime.utcnow)