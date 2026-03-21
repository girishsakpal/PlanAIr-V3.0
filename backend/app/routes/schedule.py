from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.schedule import BusyHours, ScheduleSession
from app.models.task import Task
from app.forms import BusyHoursForm
from app.scheduler import schedule_tasks, schedule_recurring_tasks
import json
from datetime import date, timedelta, datetime

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
    # 24:00 is invalid — cap it at 23:59
    if h >= 24:
        h = 23
        m = 59
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


@schedule_bp.route('/schedule')
@login_required
def schedule_view():
    """Daily timeline view."""
    # get requested date or default to today
    date_str = request.args.get('date')
    try:
        view_date = date.fromisoformat(date_str) if date_str else date.today()
    except ValueError:
        view_date = date.today()

    sessions = ScheduleSession.query.filter_by(
        user_id=current_user.id,
        date=view_date
    ).order_by(ScheduleSession.start_time).all()

    # attach task info to each session
    sessions_with_tasks = []
    for s in sessions:
        task = Task.query.get(s.task_id)
        sessions_with_tasks.append({'session': s, 'task': task})

    prev_date = view_date - timedelta(days=1)
    next_date = view_date + timedelta(days=1)

    return render_template('schedule/schedule_view.html',
                           sessions=sessions_with_tasks,
                           view_date=view_date,
                           prev_date=prev_date,
                           next_date=next_date,
                           today=date.today())


@schedule_bp.route('/schedule/generate', methods=['POST'])
@login_required
def generate_schedule():
    """Trigger the scheduling engine."""
    if not current_user.busy_hours_set:
        flash('Please set your busy hours first.', 'warning')
        return redirect(url_for('schedule.busy_hours_setup'))

    schedule_tasks(current_user.id, days_ahead=14)
    schedule_recurring_tasks(current_user.id, days_ahead=14)

    flash('Your schedule has been generated!', 'success')
    return redirect(url_for('schedule.schedule_view'))


@schedule_bp.route('/schedule/session/<int:session_id>/toggle', methods=['POST'])
@login_required
def toggle_session(session_id):
    """Mark a session complete or incomplete via checkbox."""
    session = ScheduleSession.query.filter_by(
        id=session_id,
        user_id=current_user.id
    ).first_or_404()

    session.is_completed = not session.is_completed
    session.completed_at = datetime.utcnow() if session.is_completed else None

    # update parent task status
    task = Task.query.get(session.task_id)
    all_sessions = ScheduleSession.query.filter_by(task_id=task.id).all()
    completed    = [s for s in all_sessions if s.is_completed]

    if len(completed) == len(all_sessions):
        task.status = 'done'
    elif len(completed) > 0:
        task.status = 'in-progress'
    else:
        task.status = 'pending'

    db.session.commit()

    return jsonify({
        'is_completed': session.is_completed,
        'task_status':  task.status
    })


@schedule_bp.route('/schedule/week')
@login_required
def week_view():
    """7-day overview of scheduled sessions."""
    today = date.today()
    week_days = [today + timedelta(days=i) for i in range(7)]

    week_data = []
    for day in week_days:
        sessions = ScheduleSession.query.filter_by(
            user_id=current_user.id,
            date=day
        ).order_by(ScheduleSession.start_time).all()

        sessions_with_tasks = []
        for s in sessions:
            task = Task.query.get(s.task_id)
            sessions_with_tasks.append({'session': s, 'task': task})

        week_data.append({
            'date':     day,
            'sessions': sessions_with_tasks,
            'total':    len(sessions),
            'done':     sum(1 for s in sessions if s.is_completed)
        })

    return render_template('schedule/week_view.html',
                           week_data=week_data,
                           today=today)