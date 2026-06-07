from app import db
from datetime import datetime


class Feedback(db.Model):
    __tablename__ = 'feedback'

    id         = db.Column(db.Integer, primary_key=True)
    user_id    = db.Column(db.Integer, db.ForeignKey('users.id'), nullable=False)
    category   = db.Column(db.String(40), nullable=False)   # 'bug' | 'feature' | 'general'
    message    = db.Column(db.Text, nullable=False)
    created_at = db.Column(db.DateTime, default=datetime.utcnow)
    is_read    = db.Column(db.Boolean, default=False)

    user = db.relationship('User', backref=db.backref('feedbacks', lazy=True,
                                                       cascade='all, delete-orphan'))

    def __repr__(self):
        return f'<Feedback {self.id} from user {self.user_id}>'
