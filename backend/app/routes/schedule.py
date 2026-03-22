from flask import Blueprint, render_template, redirect, url_for, flash, request, jsonify
from flask_login import login_required, current_user
from app import db
from app.models.schedule import BusyHours, ScheduleSession
from app.models.task import Task
from app.forms import BusyHoursForm
from app.scheduler import (schedule_tasks, schedule_recurring_tasks,
                            time_to_minutes)
import json
from datetime import date, timedelta, datetime
from app.models.mood import MoodLog, ProductivityLog
from app.productivity import calculate_daily_score, get_streak
from app.suggestions import run_suggestion_engine, get_active_suggestions, dismiss_suggestion, clear_all_suggestions


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
    if not current_user.busy_hours_set:
        flash('Please set your busy hours first.', 'warning')
        return redirect(url_for('schedule.busy_hours_setup'))

    clear_all_suggestions(current_user.id)
    schedule_tasks(current_user.id, days_ahead=14)
    schedule_recurring_tasks(current_user.id, days_ahead=14)
    run_suggestion_engine(current_user.id)

    flash('Your schedule has been generated!', 'success')
    return redirect(url_for('schedule.schedule_view'))


@schedule_bp.route('/schedule/session/<int:session_id>/toggle', methods=['POST'])
@login_required
def toggle_session(session_id):
    session = ScheduleSession.query.filter_by(
        id=session_id,
        user_id=current_user.id
    ).first_or_404()

    data         = request.get_json() or {}
    hours_worked = data.get('hours_worked', None)
    unchecking   = data.get('unchecking', False)

    # calculate this session's allocated hours
    session_minutes = (
        time_to_minutes(session.end_time) -
        time_to_minutes(session.start_time)
    )
    allocated_hours = round(session_minutes / 60, 2)

    task = Task.query.get(session.task_id)

    if unchecking:
        # reverse previously logged hours for this session
        prev_logged = session.logged_hours or allocated_hours
        task.completed_hours = round(
            max(0, (task.completed_hours or 0) - prev_logged), 2
        )
        session.is_completed  = False
        session.completed_at  = None
        session.logged_hours  = None
    else:
        # if hours_worked not provided, assume full allocated time
        actual_hours = float(hours_worked) if hours_worked is not None else allocated_hours
        actual_hours = round(min(actual_hours, allocated_hours), 2)

        # subtract old logged hours first if re-completing
        if session.logged_hours is not None:
            task.completed_hours = round(
                max(0, (task.completed_hours or 0) - session.logged_hours), 2
            )

        # add new actual hours
        task.completed_hours  = round((task.completed_hours or 0) + actual_hours, 2)
        session.is_completed  = True
        session.completed_at  = datetime.utcnow()
        session.logged_hours  = actual_hours

    # auto-complete task when all hours done
    if task.completed_hours >= task.estimated_hours:
        task.completed_hours = task.estimated_hours
        task.status          = 'done'
    else:
        all_sessions  = ScheduleSession.query.filter_by(task_id=task.id).all()
        any_completed = any(s.is_completed for s in all_sessions)
        task.status   = 'in-progress' if any_completed else 'pending'

    db.session.commit()

    log = calculate_daily_score(current_user.id, session.date)
    run_suggestion_engine(current_user.id)

    progress_pct = round(
        (task.completed_hours / task.estimated_hours) * 100, 1
    ) if task.estimated_hours > 0 else 0

    return jsonify({
        'is_completed':    session.is_completed,
        'task_status':     task.status,
        'task_id':         task.id,
        'completed_hours': task.completed_hours,
        'estimated_hours': task.estimated_hours,
        'progress_pct':    progress_pct,
        'logged_hours':    session.logged_hours,
        'allocated_hours': allocated_hours,
        'productivity':    log.score if log else 0
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


@schedule_bp.route('/mood', methods=['POST'])
@login_required
def log_mood():
    """Save today's mood score."""
    today      = date.today()
    mood_score = request.json.get('mood_score')

    if not mood_score or not (1 <= int(mood_score) <= 5):
        return jsonify({'error': 'Invalid mood score'}), 400

    mood = MoodLog.query.filter_by(
        user_id=current_user.id,
        date=today
    ).first()

    if mood:
        mood.mood_score = int(mood_score)
    else:
        mood = MoodLog(
            user_id    = current_user.id,
            date       = today,
            mood_score = int(mood_score)
        )
        db.session.add(mood)

    db.session.commit()

    # re-run suggestions after mood update
    run_suggestion_engine(current_user.id)

    return jsonify({'success': True, 'mood_score': mood.mood_score})


@schedule_bp.route('/suggestions/dismiss/<int:suggestion_id>', methods=['POST'])
@login_required
def dismiss_suggestion_route(suggestion_id):
    dismiss_suggestion(current_user.id, suggestion_id)
    return jsonify({'success': True})


