import sys
import os
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from flask import Flask
from extensions import db, login_manager


def create_app():
    app = Flask(__name__)
    app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///tickets.db'
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['SECRET_KEY'] = 'change-this-in-production'

    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'error'

    with app.app_context():
        from models.user import User
        from models.ticket import (
            Ticket, TicketFieldDefinition, TicketFieldValue,
            TicketComment, TicketHistory, TicketAttachment,
        )
        from models.permission import UserPermission
        from models.wiki import WikiPage, WikiPageHistory
        from models.settings import Setting
        from models.mail import MailLog, MailTemplate

        db.create_all()

        from werkzeug.security import generate_password_hash

        if not User.query.filter_by(username='superadmin').first():
            admin_user = User(
                name='Superadmin',
                username='superadmin',
                email='superadmin@superadmin.com',
                password_hash=generate_password_hash('superadmin123'),
                is_superadmin=True,
            )
            db.session.add(admin_user)
            db.session.commit()

        from routes.auth import auth_bp
        from routes.public import public_bp
        from routes.tickets import tickets_bp
        from routes.admin import admin_bp
        from routes.wiki import wiki_bp

        app.register_blueprint(auth_bp)
        app.register_blueprint(public_bp)
        app.register_blueprint(tickets_bp)
        app.register_blueprint(admin_bp)
        app.register_blueprint(wiki_bp)

    @login_manager.user_loader
    def load_user(user_id):
        from models.user import User
        return User.query.get(int(user_id))

    return app


app = create_app()

@app.after_request
def add_no_cache(response):
    response.headers['Cache-Control'] = 'no-cache, no-store, must-revalidate'
    response.headers['Pragma'] = 'no-cache'
    response.headers['Expires'] = '0'
    return response

@app.route('/auth-check')
def auth_check():
    from flask_login import current_user
    from flask import jsonify
    return jsonify({'authenticated': current_user.is_authenticated})

if __name__ == '__main__':
    app.run(debug=True)