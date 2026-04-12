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