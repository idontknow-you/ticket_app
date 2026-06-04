from extensions import db
from datetime import datetime


MAIL_EVENTS = [
    "ticket_submitted",
    "ticket_assigned",
    "ticket_status_changed",
    "ticket_reply_added",
    "ticket_closed",
    "password_reset",
]

QUEUE_STATUSES = ["queued", "sending", "sent", "failed"]


class MailQueue(db.Model):
    __tablename__ = "mail_queue"

    id                 = db.Column(db.Integer, primary_key=True)
    created_at         = db.Column(db.DateTime, default=datetime.utcnow, index=True)
    scheduled_at       = db.Column(db.DateTime, default=datetime.utcnow)
    sent_at            = db.Column(db.DateTime, nullable=True)

    # recipients
    to_email           = db.Column(db.String(255), nullable=False)
    to_name            = db.Column(db.String(200), nullable=True)

    # content (may be edited pre-send)
    subject            = db.Column(db.Text, nullable=False)
    html_body          = db.Column(db.Text, nullable=False)
    text_body          = db.Column(db.Text, nullable=True)

    # extra recipients added via pre-send popup
    extra_recipients   = db.Column(db.JSON, default=list)   # [{"email":..,"name":..}]
    extra_note         = db.Column(db.Text, nullable=True)

    # context
    event              = db.Column(db.String(60), nullable=False)
    form_config_id     = db.Column(db.Integer, db.ForeignKey("form_configurations.id"), nullable=True)
    submission_id      = db.Column(db.Integer, db.ForeignKey("form_submissions.id"), nullable=True)

    # queue state
    status             = db.Column(db.String(20), default="queued", index=True)
    retry_count        = db.Column(db.Integer, default=0)
    max_retries        = db.Column(db.Integer, default=3)
    last_error         = db.Column(db.Text, nullable=True)
    last_attempt_at    = db.Column(db.DateTime, nullable=True)

    # relationships
    form               = db.relationship("FormConfig", foreign_keys=[form_config_id])
    submission         = db.relationship("FormSubmission", foreign_keys=[submission_id])

    def mark_sent(self):
        self.status = "sent"
        self.sent_at = datetime.utcnow()
        self.last_error = None

    def mark_failed(self, error):
        self.retry_count += 1
        self.last_error = str(error)
        self.last_attempt_at = datetime.utcnow()
        if self.retry_count >= self.max_retries:
            self.status = "failed"
        else:
            self.status = "queued"

    def __repr__(self):
        return f"<MailQueue id={self.id} to={self.to_email} event={self.event} status={self.status}>"


class MailLog(db.Model):
    __tablename__ = "mail_log"

    id              = db.Column(db.Integer, primary_key=True)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow, index=True)

    to_email        = db.Column(db.String(255), nullable=False)
    to_name         = db.Column(db.String(200), nullable=True)
    subject         = db.Column(db.Text, nullable=False)
    html_body       = db.Column(db.Text, nullable=True)

    event           = db.Column(db.String(60), nullable=False, index=True)
    form_config_id  = db.Column(db.Integer, db.ForeignKey("form_configurations.id"), nullable=True)
    submission_id   = db.Column(db.Integer, db.ForeignKey("form_submissions.id"), nullable=True)
    queue_id        = db.Column(db.Integer, db.ForeignKey("mail_queue.id"), nullable=True)

    status          = db.Column(db.String(20), nullable=False, index=True)  # sent / failed
    error           = db.Column(db.Text, nullable=True)
    retry_count     = db.Column(db.Integer, default=0)

    # relationships
    form            = db.relationship("FormConfig", foreign_keys=[form_config_id])
    submission      = db.relationship("FormSubmission", foreign_keys=[submission_id])

    def __repr__(self):
        return f"<MailLog id={self.id} to={self.to_email} status={self.status}>"
