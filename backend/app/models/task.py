# from flask import Blueprint

# task_bp = Blueprint('task', __name__)

from app import db
from datetime import datetime

class Task(db.Model):
    __tablename__ = 'tasks'
    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    title           = db.Column(db.String(200), nullable=False)
    description     = db.Column(db.Text, nullable=True)
    urgency         = db.Column(db.Integer, nullable=False)   # 1–4
    importance      = db.Column(db.Integer, nullable=False)   # 1–4
    estimated_hours = db.Column(db.Float, nullable=False)
    deadline        = db.Column(db.Date, nullable=True)
    is_recurring    = db.Column(db.Boolean, default=False)
    recurrence_type = db.Column(db.String(20), nullable=True) # 'daily' or 'weekly'
    preferred_time  = db.Column(db.Time, nullable=True)        # fixed time for recurring tasks
    preferred_day   = db.Column(db.Integer, nullable=True)       # 0=Mon..6=Sun for weekly tasks
    days_completed  = db.Column(db.Integer, default=0)             # streak counter for recurring tasks
    status          = db.Column(db.String(20), default='pending')
    quadrant        = db.Column(db.String(30), nullable=True)
    created_at      = db.Column(db.DateTime, default=datetime.utcnow)
    completed_hours = db.Column(db.Float, default=0.0)
    
    sessions    = db.relationship('ScheduleSession', backref='task', lazy=True,
                                cascade='all, delete-orphan')
    suggestions = db.relationship('Suggestion', backref='task', lazy=True,
                                cascade='all, delete-orphan')

    def compute_quadrant(self):
        if self.urgency >= 3 and self.importance >= 3:
            return 'do_now'
        elif self.urgency < 3 and self.importance >= 3:
            return 'schedule'
        elif self.urgency >= 3 and self.importance < 3:
            return 'delegate'
        else:
            return 'avoid'
        


class TaskDependency(db.Model):
    __tablename__ = 'task_dependencies'

    id             = db.Column(db.Integer, primary_key=True)
    user_id        = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    task_id        = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False)
    depends_on_id  = db.Column(db.Integer, db.ForeignKey('tasks.id'), nullable=False)
    created_at     = db.Column(db.DateTime, default=datetime.utcnow)

    # relationships
    task        = db.relationship('Task', foreign_keys=[task_id],
                                  backref='dependencies')
    depends_on  = db.relationship('Task', foreign_keys=[depends_on_id],
                                  backref='dependents')

    # prevent duplicate dependency entries
    __table_args__ = (
        db.UniqueConstraint('task_id', 'depends_on_id', name='unique_dependency'),
    )

class TaskHistory(db.Model):
    """
    Immutable log entry created whenever a task is completed or deleted.
    Preserves the task's key attributes at the moment of the event so
    the user can review their full task history even after deletion.
    """
    __tablename__ = 'task_history'

    id              = db.Column(db.Integer, primary_key=True)
    user_id         = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    # original task id kept for reference even after task deletion
    original_task_id = db.Column(db.Integer, nullable=True)
    title           = db.Column(db.String(200), nullable=False)
    description     = db.Column(db.Text, nullable=True)
    urgency         = db.Column(db.Integer, nullable=False)
    importance      = db.Column(db.Integer, nullable=False)
    estimated_hours = db.Column(db.Float, nullable=False)
    completed_hours = db.Column(db.Float, default=0.0)
    deadline        = db.Column(db.Date, nullable=True)
    quadrant        = db.Column(db.String(30), nullable=True)
    is_recurring    = db.Column(db.Boolean, default=False)
    preferred_time  = db.Column(db.Time, nullable=True)
    preferred_day   = db.Column(db.Integer, nullable=True)
    # 'completed' or 'deleted'
    event_type      = db.Column(db.String(20), nullable=False)
    event_at        = db.Column(db.DateTime, default=datetime.utcnow)
    task_created_at = db.Column(db.DateTime, nullable=True)
