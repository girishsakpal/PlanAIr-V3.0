import os
from functools import wraps
from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, session)
from app import db
from app.models.user import User
from app.models.feedback import Feedback

admin_bp = Blueprint('admin', __name__, url_prefix='/admin')

# ── auth guard ────────────────────────────────────────────────────────────────

def admin_login_required(f):
    """Decorator: blocks access unless admin session is active."""
    @wraps(f)
    def decorated(*args, **kwargs):
        if not session.get('admin_logged_in'):
            return redirect(url_for('admin.login'))
        return f(*args, **kwargs)
    return decorated


# ── login / logout ────────────────────────────────────────────────────────────

@admin_bp.route('/login', methods=['GET', 'POST'])
def login():
    """Separate admin login — credentials come from env vars only."""
    if session.get('admin_logged_in'):
        return redirect(url_for('admin.panel'))

    error = None
    if request.method == 'POST':
        username = request.form.get('username', '').strip()
        password = request.form.get('password', '').strip()

        admin_user = os.environ.get('ADMIN_USERNAME', '')
        admin_pass = os.environ.get('ADMIN_PASSWORD', '')

        if username == admin_user and password == admin_pass and admin_user:
            session['admin_logged_in'] = True
            session.permanent = False          # session dies when browser closes
            return redirect(url_for('admin.panel'))
        else:
            error = 'Invalid credentials.'

    return render_template('admin/login.html', error=error)


@admin_bp.route('/logout')
def logout():
    session.pop('admin_logged_in', None)
    return redirect(url_for('admin.login'))


# ── main panel ────────────────────────────────────────────────────────────────

@admin_bp.route('/panel')
@admin_login_required
def panel():
    users = (User.query
             .order_by(User.created_at.desc())
             .all())

    feedbacks = (Feedback.query
                 .join(User, Feedback.user_id == User.id)
                 .order_by(Feedback.created_at.desc())
                 .all())

    unread_count = Feedback.query.filter_by(is_read=False).count()

    return render_template('admin/panel.html',
                           users=users,
                           feedbacks=feedbacks,
                           unread_count=unread_count)


# ── mark feedback read ────────────────────────────────────────────────────────

@admin_bp.route('/feedback/<int:feedback_id>/read', methods=['POST'])
@admin_login_required
def mark_read(feedback_id):
    fb = Feedback.query.get_or_404(feedback_id)
    fb.is_read = True
    db.session.commit()
    return redirect(url_for('admin.panel') + '#feedback')


@admin_bp.route('/feedback/<int:feedback_id>/delete', methods=['POST'])
@admin_login_required
def delete_feedback(feedback_id):
    fb = Feedback.query.get_or_404(feedback_id)
    db.session.delete(fb)
    db.session.commit()
    flash('Feedback deleted.', 'info')
    return redirect(url_for('admin.panel') + '#feedback')
