from extensions import db


class CarouselItem(db.Model):
    __tablename__ = "carousel_items"

    id             = db.Column(db.Integer, primary_key=True)
    page_id        = db.Column(db.Integer, db.ForeignKey("wiki_pages.id"), nullable=False, unique=True)
    carousel_image = db.Column(db.String(500), nullable=True)   # filename in wiki_uploads/; falls back to cover_image if None
    sort_order     = db.Column(db.Integer, default=0, nullable=False)

    page = db.relationship("WikiPage", backref=db.backref("carousel_item", uselist=False))

    def __repr__(self):
        return f"<CarouselItem page_id={self.page_id} order={self.sort_order}>"