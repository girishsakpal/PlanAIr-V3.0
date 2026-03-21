from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager
from flask_wtf.csrf import CSRFProtect
from .config import Config

db = SQLAlchemy()
login_manager = LoginManager()
csrf = CSRFProtect()

def create_app(config_class=Config):
    app = Flask(__name__)
    app.config.from_object(config_class)

    db.init_app(app)
    login_manager.init_app(app)
    csrf.init_app(app)

    login_manager.login_view = 'auth.login'
    login_manager.login_message = 'Please log in to access this page.'
    login_manager.login_message_category = 'info'

    from .routes.auth import auth_bp
    from .routes.tasks import tasks_bp
    from .routes.schedule import schedule_bp
    from .routes.insights import insights_bp

    app.register_blueprint(auth_bp)
    app.register_blueprint(tasks_bp)
    app.register_blueprint(schedule_bp)
    app.register_blueprint(insights_bp)

    with app.app_context():
        from .models import user, task, schedule, mood
        db.create_all()

    app.jinja_env.filters['enumerate'] = enumerate

    return app