# from flask import Blueprint

# schedule_bp = Blueprint('schedule', __name__)

from app import db
from datetime import datetime

class ScheduleSession(db.Model):
    __tablename__ = 'schedule_sessions'
    id            = db.Column(db.Integer, primary_key=True)
    user_id       = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    task_id       = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False)
    date          = db.Column(db.Date, nullable=False)
    start_time    = db.Column(db.Time, nullable=False)
    end_time      = db.Column(db.Time, nullable=False)
    session_label = db.Column(db.String(60), nullable=True)
    is_completed  = db.Column(db.Boolean, default=False)
    completed_at  = db.Column(db.DateTime, nullable=True)

class BusyHours(db.Model):
    __tablename__ = 'busy_hours'
    id          = db.Column(db.Integer, primary_key=True)
    user_id     = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    day_of_week = db.Column(db.Integer, nullable=False)  # 0=Mon, 6=Sun
    start_time  = db.Column(db.Time, nullable=False)
    end_time    = db.Column(db.Time, nullable=False)
    label       = db.Column(db.String(60), nullable=True)