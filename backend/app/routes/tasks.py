from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, jsonify)
from flask_login import login_required, current_user
from app import db
from app.models.task import Task
from app.forms import TaskForm
from datetime import datetime, date
from app.models.mood import MoodLog, ProductivityLog
from app.productivity import calculate_daily_score, get_streak
from app.suggestions import get_active_suggestions, run_suggestion_engine
from app.models.schedule import ScheduleSession


tasks_bp = Blueprint('tasks', __name__)


@tasks_bp.route('/dashboard')
@login_required
def dashboard():
    today = date.today()
    tasks = Task.query.filter_by(
        user_id=current_user.id
    ).order_by(Task.created_at.desc()).all()

    quadrants = {
        'do_now':   [t for t in tasks if t.quadrant == 'do_now'],
        'schedule': [t for t in tasks if t.quadrant == 'schedule'],
        'delegate': [t for t in tasks if t.quadrant == 'delegate'],
        'avoid':    [t for t in tasks if t.quadrant == 'avoid'],
    }

    # today's productivity
    productivity = ProductivityLog.query.filter_by(
        user_id=current_user.id,
        date=today
    ).first()

    # today's mood
    mood = MoodLog.query.filter_by(
        user_id=current_user.id,
        date=today
    ).first()

    # streak
    streak = get_streak(current_user.id)

    # active suggestions
    suggestions = get_active_suggestions(current_user.id)

    # today's sessions
    
    today_sessions = ScheduleSession.query.filter_by(
        user_id=current_user.id,
        date=today
    ).order_by(ScheduleSession.start_time).all()

    sessions_with_tasks = []
    for s in today_sessions:
        t = Task.query.get(s.task_id)
        if t:
            progress_pct = round(
                (t.completed_hours / t.estimated_hours) * 100, 1
            ) if t.estimated_hours > 0 else 0
        else:
            progress_pct = 0
        sessions_with_tasks.append({
            'session':      s,
            'task':         t,
            'progress_pct': progress_pct
        })

    # build progress map for all tasks
    task_progress = {}
    for t in tasks:
        pct = round(
            (t.completed_hours / t.estimated_hours) * 100, 1
        ) if t.estimated_hours > 0 else 0
        task_progress[t.id] = {
            'completed_hours': t.completed_hours or 0,
            'estimated_hours': t.estimated_hours,
            'pct':             pct
        }

    form = TaskForm()
    return render_template('tasks/dashboard.html',
                        tasks=tasks,
                        quadrants=quadrants,
                        productivity=productivity,
                        mood=mood,
                        streak=streak,
                        suggestions=suggestions,
                        sessions=sessions_with_tasks,
                        task_progress=task_progress,
                        today=today,
                        form=form)


@tasks_bp.route('/tasks/add', methods=['POST'])
@login_required
def add_task():
    form = TaskForm()
    if form.validate_on_submit():
        task = Task(
            user_id=current_user.id,
            title=form.title.data,
            description=form.description.data,
            urgency=int(form.urgency.data),
            importance=int(form.importance.data),
            estimated_hours=form.estimated_hours.data,
            deadline=form.deadline.data,
            is_recurring=form.is_recurring.data,
            recurrence_type=form.recurrence_type.data or None,
        )
        task.quadrant = task.compute_quadrant()
        db.session.add(task)
        db.session.commit()
        flash(f'Task "{task.title}" added successfully!', 'success')
    else:
        for field, errors in form.errors.items():
            for error in errors:
                flash(f'{error}', 'danger')

    return redirect(url_for('tasks.dashboard'))


@tasks_bp.route('/tasks/<int:task_id>/delete', methods=['POST'])
@login_required
def delete_task(task_id):
    task = Task.query.filter_by(
        id=task_id, user_id=current_user.id
    ).first_or_404()
    db.session.delete(task)
    db.session.commit()
    flash(f'Task "{task.title}" deleted.', 'info')
    return redirect(url_for('tasks.dashboard'))


@tasks_bp.route('/tasks/<int:task_id>/status', methods=['POST'])
@login_required
def update_status(task_id):
    task = Task.query.filter_by(
        id=task_id, user_id=current_user.id
    ).first_or_404()
    new_status = request.json.get('status')
    if new_status in ['pending', 'in-progress', 'done', 'delayed']:
        task.status = new_status
        db.session.commit()
        return jsonify({'success': True})
    return jsonify({'success': False}), 400


@tasks_bp.route('/tasks/<int:task_id>/edit', methods=['GET', 'POST'])
@login_required
def edit_task(task_id):
    task = Task.query.filter_by(
        id=task_id, user_id=current_user.id
    ).first_or_404()
    form = TaskForm(obj=task)

    if form.validate_on_submit():
        task.title           = form.title.data
        task.description     = form.description.data
        task.urgency         = int(form.urgency.data)
        task.importance      = int(form.importance.data)
        task.estimated_hours = form.estimated_hours.data
        task.deadline        = form.deadline.data
        task.is_recurring    = form.is_recurring.data
        task.recurrence_type = form.recurrence_type.data or None
        task.quadrant        = task.compute_quadrant()
        db.session.commit()
        flash('Task updated.', 'success')
        return redirect(url_for('tasks.dashboard'))

    return render_template('tasks/edit_task.html', form=form, task=task)


@tasks_bp.route('/matrix')
@login_required
def matrix():
    tasks = Task.query.filter_by(user_id=current_user.id).all()
    quadrants = {
        'do_now':   [t for t in tasks if t.quadrant == 'do_now'],
        'schedule': [t for t in tasks if t.quadrant == 'schedule'],
        'delegate': [t for t in tasks if t.quadrant == 'delegate'],
        'avoid':    [t for t in tasks if t.quadrant == 'avoid'],
    }
    return render_template('tasks/matrix.html', quadrants=quadrants)