from extensions import db
from datetime import datetime


class CarouselLog(db.Model):
    __tablename__ = "carousel_logs"

    id         = db.Column(db.Integer, primary_key=True)
    saved_at   = db.Column(db.DateTime, default=datetime.utcnow, nullable=False)
    saved_by   = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=True)

    # Diff vs previous carousel state
    # Each entry: {"title": str, "cover_image": str | None}
    added      = db.Column(db.JSON, default=list, nullable=False)
    removed    = db.Column(db.JSON, default=list, nullable=False)

    # True when page_ids are the same set but order changed (no adds/removes)
    reordered  = db.Column(db.Boolean, default=False, nullable=False)

    # Full ordered snapshot after this save
    # Each entry: {"title": str, "cover_image": str | None, "carousel_image": str | None}
    snapshot   = db.Column(db.JSON, default=list, nullable=False)

    editor = db.relationship("User", foreign_keys=[saved_by])

    def __repr__(self):
        return f"<CarouselLog id={self.id} saved_at={self.saved_at}>"