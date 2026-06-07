from flask import Blueprint, render_template, redirect, url_for, flash, request
from flask_login import login_required, current_user
from app import db
from app.models.feedback import Feedback

feedback_bp = Blueprint('feedback', __name__)


@feedback_bp.route('/feedback', methods=['GET', 'POST'])
@login_required
def submit_feedback():
    if request.method == 'POST':
        category = request.form.get('category', 'general')
        message  = request.form.get('message', '').strip()

        if not message:
            flash('Please enter a message before submitting.', 'danger')
            return redirect(url_for('feedback.submit_feedback'))

        if len(message) > 2000:
            flash('Feedback must be under 2000 characters.', 'danger')
            return redirect(url_for('feedback.submit_feedback'))

        if category not in ('bug', 'feature', 'general'):
            category = 'general'

        fb = Feedback(
            user_id  = current_user.id,
            category = category,
            message  = message
        )
        db.session.add(fb)
        db.session.commit()

        flash('Thanks for your feedback! We read every submission. 🙏', 'success')
        return redirect(url_for('tasks.dashboard'))

    return render_template('tasks/feedback.html')
