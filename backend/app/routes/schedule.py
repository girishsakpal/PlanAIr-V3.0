from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.schedule import BusyHours
from app.forms import BusyHoursForm
import json

schedule_bp = Blueprint('schedule', __name__)


@schedule_bp.route('/setup/busy-hours', methods=['GET', 'POST'])
@login_required
def busy_hours_setup():
    form = BusyHoursForm()

    if request.method == 'POST':
        # busy hours come in as JSON from the grid UI
        raw = request.form.get('busy_hours_data', '[]')
        try:
            blocks = json.loads(raw)
        except (ValueError, TypeError):
            flash('Invalid schedule data. Please try again.', 'danger')
            return redirect(url_for('schedule.busy_hours_setup'))

        # delete existing blocks first (handles edit scenario)
        BusyHours.query.filter_by(user_id=current_user.id).delete()

        for block in blocks:
            bh = BusyHours(
                user_id=current_user.id,
                day_of_week=int(block['day']),
                start_time=_parse_time(block['start']),
                end_time=_parse_time(block['end']),
                label=block.get('label', '')
            )
            db.session.add(bh)

        current_user.busy_hours_set = True
        db.session.commit()
        flash('Your schedule has been saved!', 'success')
        return redirect(url_for('tasks.dashboard'))

    # pre-load existing blocks for edit mode
    existing = BusyHours.query.filter_by(user_id=current_user.id).all()
    existing_data = [
        {
            'day': b.day_of_week,
            'start': b.start_time.strftime('%H:%M'),
            'end': b.end_time.strftime('%H:%M'),
            'label': b.label or ''
        }
        for b in existing
    ]

    return render_template('schedule/busy_hours.html',
                           form=form,
                           existing_data=existing_data,
                           is_edit=current_user.busy_hours_set)


def _parse_time(time_str):
    """Convert 'HH:MM' string to Python time object."""
    from datetime import time
    h, m = map(int, time_str.split(':'))
    return time(h, m)


@schedule_bp.route('/api/busy-hours', methods=['GET'])
@login_required
def get_busy_hours():
    blocks = BusyHours.query.filter_by(user_id=current_user.id).all()
    return jsonify([
        {
            'day': b.day_of_week,
            'start': b.start_time.strftime('%H:%M'),
            'end': b.end_time.strftime('%H:%M'),
            'label': b.label or ''
        }
        for b in blocks
    ])