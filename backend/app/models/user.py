# from flask import Blueprint

# user_bp = Blueprint('user', __name__)

from app import db, login_manager
from flask_login import UserMixin
from datetime import datetime
from werkzeug.security import generate_password_hash, check_password_hash


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


class User(db.Model, UserMixin):
    __tablename__ = 'users'

    id             = db.Column(db.Integer, primary_key=True)
    username       = db.Column(db.String(80), unique=True, nullable=False)
    email          = db.Column(db.String(120), unique=True, nullable=False)
    password_hash  = db.Column(db.String(256), nullable=False)
    dark_mode      = db.Column(db.Boolean, default=False)
    busy_hours_set = db.Column(db.Boolean, default=False)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    # relationships
    busy_hours        = db.relationship('BusyHours', backref='user',
                                        lazy=True, cascade='all, delete-orphan')
    tasks             = db.relationship('Task', backref='user',
                                        lazy=True, cascade='all, delete-orphan')
    schedule_sessions = db.relationship('ScheduleSession', backref='user',
                                        lazy=True, cascade='all, delete-orphan')
    productivity_logs = db.relationship('ProductivityLog', backref='user',
                                        lazy=True, cascade='all, delete-orphan')
    mood_logs         = db.relationship('MoodLog', backref='user',
                                        lazy=True, cascade='all, delete-orphan')
    suggestions       = db.relationship('Suggestion', backref='user',
                                        lazy=True, cascade='all, delete-orphan')

    # --- password ---

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    # --- preferences ---

    def toggle_dark_mode(self):
        self.dark_mode = not self.dark_mode
        db.session.commit()

    def mark_busy_hours_set(self):
        self.busy_hours_set = True
        db.session.commit()

    # --- utilities ---

    def is_new_user(self):
        """Returns True if user has never set their busy hours."""
        return not self.busy_hours_set

    def days_since_joined(self):
        return (datetime.utcnow() - self.created_at).days

    def __repr__(self):
        return f'<User {self.username}>'