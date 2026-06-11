import os
from flask import Flask
from extensions import db, login_manager


def create_app():
    app = Flask(__name__)

    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY", "dev-secret-change-me")
    app.config["SQLALCHEMY_DATABASE_URI"] = os.environ.get("DATABASE_URL", "sqlite:///ticketing.db")
    app.config["SQLALCHEMY_TRACK_MODIFICATIONS"] = False

    upload_folder = os.path.join(app.root_path, "static", "uploads")
    os.makedirs(upload_folder, exist_ok=True)
    app.config["UPLOAD_FOLDER"] = upload_folder

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"
    login_manager.login_message = "Please sign in to continue."
    login_manager.login_message_category = "error"

    @login_manager.user_loader
    def load_user(user_id):
        from models import User
        return User.query.get(int(user_id))

    # ── IST Jinja filter ──────────────────────────────────────────────────────
    from utils import to_ist

    @app.template_filter("to_ist")
    def to_ist_filter(dt):
        return to_ist(dt)

    @app.template_filter("ist_fmt")
    def ist_fmt_filter(dt, fmt="%d %b %Y %H:%M IST"):
        """Convert a UTC datetime to IST and format it. Usage: {{ dt | ist_fmt }}"""
        converted = to_ist(dt)
        if converted is None:
            return ""
        return converted.strftime(fmt)
    
    @app.after_request
    def no_cache(response):
        response.headers["Cache-Control"] = "no-store, no-cache, must-revalidate, max-age=0"
        response.headers["Pragma"] = "no-cache"
        response.headers["Expires"] = "0"
        return response

    from routes import auth_bp, public_bp, tickets_bp, admin_bp, forms_bp, wiki_bp, mail_bp, reports_bp
    app.register_blueprint(auth_bp)
    app.register_blueprint(public_bp)
    app.register_blueprint(tickets_bp)
    app.register_blueprint(admin_bp)
    app.register_blueprint(forms_bp)
    app.register_blueprint(wiki_bp)
    app.register_blueprint(mail_bp)
    app.register_blueprint(reports_bp)

    from migration import init_db
    init_db(app)

    # ── Mail queue background processor ──────────────────────────────────────
    _start_mail_scheduler(app)

    return app


def _start_mail_scheduler(app):
    """
    Run process_queue() every 2 minutes in a background thread.
    Uses APScheduler's BackgroundScheduler so no separate worker process is needed.
    Guard against double-start in Flask's reloader (which forks the process).
    """
    import os
    # Werkzeug's reloader runs two processes: a parent file-watcher and a child
    # that actually serves requests. WERKZEUG_RUN_MAIN is set to "true" only in
    # the child. Start the scheduler only there (or in production where the var
    # is absent entirely) so we never run two scheduler instances side-by-side.
    run_main = os.environ.get("WERKZEUG_RUN_MAIN")
    if run_main is not None and run_main != "true":
        return

    try:
        from apscheduler.schedulers.background import BackgroundScheduler

        def _job():
            with app.app_context():
                try:
                    from services.mail_service import process_queue
                    result = process_queue(limit=50)
                    if result["sent"] or result["failed"]:
                        app.logger.info(
                            f"[mail queue] sent={result['sent']} "
                            f"failed={result['failed']} skipped={result['skipped']}"
                        )
                except Exception as e:
                    app.logger.error(f"[mail queue] scheduler error: {e}")

        scheduler = BackgroundScheduler(daemon=True)
        scheduler.add_job(_job, "interval", seconds=30, id="mail_queue_processor")
        scheduler.start()
        app.logger.info("[mail queue] scheduler started — runs every 2 minutes")

    except Exception as e:
        app.logger.warning(f"[mail queue] could not start scheduler: {e}")



if __name__ == "__main__":
    app = create_app()
    app.run(debug=True)