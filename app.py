from flask import Flask, render_template, request, redirect, url_for
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
        #Models
        from models.user import User
        from models.ticket import Ticket, TicketFieldDefinition, TicketFieldValue, TicketComment, TicketHistory, TicketAttachment
        from models.permission import UserPermission
        from models.wiki import WikiPage, WikiPageHistory
        from models.settings import Setting
        from models.mail import MailLog, MailTemplate

        #Bluprints
        from routes.auth import auth_bp
        from routes.public import public_bp
        app.register_blueprint(public_bp, url_prefix='/')

        app.register_blueprint(auth_bp)

    @login_manager.user_loader
    def load_user(user_id):
        from models.user import User
        return User.query.get(int(user_id))


    return app

app = create_app()

if __name__ == '__main__':
    app.run(debug=True)
