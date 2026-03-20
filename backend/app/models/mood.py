# from flask import Blueprint

# mood_bp = Blueprint('mood', __name__)

from app import db
from datetime import datetime

class MoodLog(db.Model):
    __tablename__ = 'mood_logs'
    __table_args__ = (db.UniqueConstraint('user_id', 'date'),)
    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date       = db.Column(db.Date, nullable=False)
    mood_score = db.Column(db.Integer, nullable=False)  # 1–5
    note       = db.Column(db.String(200), nullable=True)

class ProductivityLog(db.Model):
    __tablename__ = 'productivity_logs'
    __table_args__ = (db.UniqueConstraint('user_id', 'date'),)
    id                  = db.Column(db.Integer, primary_key=True)
    user_id             = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    date                = db.Column(db.Date, nullable=False)
    score               = db.Column(db.Float, nullable=False)
    sessions_completed  = db.Column(db.Integer, default=0)
    sessions_total      = db.Column(db.Integer, default=0)
    important_completed = db.Column(db.Integer, default=0)
    schedule_adherence  = db.Column(db.Float, nullable=True)

class Suggestion(db.Model):
    __tablename__ = 'suggestions'
    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    suggestion_type = db.Column(db.String(40), nullable=False)
    message         = db.Column(db.String(300), nullable=False)
    is_dismissed    = db.Column(db.Boolean, default=False)
    related_task_id = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=True)