from flask import (Blueprint, render_template, redirect, url_for,
                   flash, request, jsonify)
from flask_login import login_required, current_user
from app import db
from app.models.task import Task, TaskDependency, TaskHistory
from app.forms import TaskForm
from datetime import datetime, date
from app.models.mood import MoodLog, ProductivityLog
from app.productivity import calculate_daily_score, get_streak
from app.suggestions import get_active_suggestions, run_suggestion_engine
from app.models.schedule import ScheduleSession


tasks_bp = Blueprint('tasks', __name__)


@tasks_bp.route('/home')
@login_required
def home():
    from app.models.user import User
    from app.models.schedule import ScheduleSession as SS
    total_users = User.query.count()
    total_tasks = Task.query.count()
    total_sessions = SS.query.filter_by(is_completed=True).count()
    streak = get_streak(current_user.id)
    return render_template('tasks/home.html',
                           total_users=total_users,
                           total_tasks=total_tasks,
                           total_sessions=total_sessions,
                           streak=streak)


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
            user_id         = current_user.id,
            title           = form.title.data.strip(),
            description     = form.description.data.strip() if form.description.data else None,
            urgency         = int(form.urgency.data),
            importance      = int(form.importance.data),
            estimated_hours = form.estimated_hours.data,
            deadline        = form.deadline.data,
            is_recurring    = form.is_recurring.data,
            recurrence_type = form.recurrence_type.data or None,
            preferred_time  = form.preferred_time.data if form.is_recurring.data else None,
            preferred_day   = int(form.preferred_day.data) if (form.is_recurring.data and form.preferred_day.data) else None,
        )
        task.quadrant = task.compute_quadrant()
        db.session.add(task)
        db.session.commit()
        return jsonify({'success': True, 'message': f'Task "{task.title}" added!'})
    else:
        # return field-level errors as JSON so the modal can show them inline
        field_errors = {}
        for field_name, msgs in form.errors.items():
            field_errors[field_name] = msgs[0]   # first message per field
        return jsonify({'success': False, 'errors': field_errors}), 400


@tasks_bp.route('/tasks/<int:task_id>/delete', methods=['POST'])
@login_required
def delete_task(task_id):
    task = Task.query.filter_by(
        id=task_id, user_id=current_user.id
    ).first_or_404()
    # snapshot into history before deleting
    history = TaskHistory(
        user_id          = current_user.id,
        original_task_id = task.id,
        title            = task.title,
        description      = task.description,
        urgency          = task.urgency,
        importance       = task.importance,
        estimated_hours  = task.estimated_hours,
        completed_hours  = task.completed_hours or 0,
        deadline         = task.deadline,
        quadrant         = task.quadrant,
        is_recurring     = task.is_recurring,
        event_type       = 'deleted',
        task_created_at  = task.created_at,
    )
    db.session.add(history)
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
        prev_status = task.status
        task.status = new_status
        # snapshot when task transitions TO done for the first time
        if new_status == 'done' and prev_status != 'done':
            history = TaskHistory(
                user_id          = current_user.id,
                original_task_id = task.id,
                title            = task.title,
                description      = task.description,
                urgency          = task.urgency,
                importance       = task.importance,
                estimated_hours  = task.estimated_hours,
                completed_hours  = task.completed_hours or 0,
                deadline         = task.deadline,
                quadrant         = task.quadrant,
                is_recurring     = task.is_recurring,
                event_type       = 'completed',
                task_created_at  = task.created_at,
            )
            db.session.add(history)
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

    # pre-populate preferred_time / preferred_day for recurring tasks on GET
    if request.method == 'GET':
        if task.preferred_time:
            form.preferred_time.data = task.preferred_time
        if task.preferred_day is not None:
            form.preferred_day.data = str(task.preferred_day)

    if form.validate_on_submit():
        task.title           = form.title.data
        task.description     = form.description.data
        task.urgency         = int(form.urgency.data)
        task.importance      = int(form.importance.data)
        task.estimated_hours = form.estimated_hours.data
        task.deadline        = form.deadline.data
        task.is_recurring    = form.is_recurring.data
        task.recurrence_type = form.recurrence_type.data or None
        task.preferred_time  = form.preferred_time.data if form.is_recurring.data else None
        task.preferred_day   = int(form.preferred_day.data) if (form.is_recurring.data and form.preferred_day.data) else None
        task.quadrant        = task.compute_quadrant()

        # ── recheck completion status after hours change ──────────────
        completed = task.completed_hours or 0

        if completed >= task.estimated_hours and task.estimated_hours > 0:
            # still fully done
            task.status = 'done'
        elif completed > 0:
            # partially done — reopen as in-progress
            task.status = 'in-progress'
        else:
            # nothing logged yet
            task.status = 'pending'
        # ─────────────────────────────────────────────────────────────

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


@tasks_bp.route('/tasks/<int:task_id>/sessions', methods=['GET'])
@login_required
def get_task_sessions(task_id):
    task = Task.query.filter_by(
        id=task_id,
        user_id=current_user.id
    ).first_or_404()

    from app.models.schedule import ScheduleSession
    from datetime import date

    sessions = ScheduleSession.query.filter_by(
        task_id=task_id
    ).order_by(ScheduleSession.date.desc(), ScheduleSession.start_time).all()

    sessions_data = []
    for s in sessions:
        allocated_minutes = (
            s.end_time.hour * 60 + s.end_time.minute -
            s.start_time.hour * 60 - s.start_time.minute
        )
        sessions_data.append({
            'id':              s.id,
            'date':            s.date.strftime('%d %b %Y'),
            'date_raw':        str(s.date),
            'start_time':      s.start_time.strftime('%H:%M'),
            'end_time':        s.end_time.strftime('%H:%M'),
            'session_label':   s.session_label or task.title,
            'is_completed':    s.is_completed,
            'logged_hours':    s.logged_hours,
            'allocated_hours': round(allocated_minutes / 60, 2),
            'is_past':         s.date <= date.today()
        })

    return jsonify({
        'task_title':      task.title,
        'task_id':         task.id,
        'estimated_hours': task.estimated_hours,
        'completed_hours': task.completed_hours or 0,
        'sessions':        sessions_data
    })


@tasks_bp.route('/tasks/<int:task_id>/dependencies', methods=['GET'])
@login_required
def get_dependencies(task_id):
    """Returns all tasks this task depends on + all tasks that depend on it."""
    task = Task.query.filter_by(
        id=task_id, user_id=current_user.id
    ).first_or_404()

    # tasks this task is blocked by
    blocked_by = []
    for dep in task.dependencies:
        blocker = dep.depends_on
        blocked_by.append({
            'dependency_id': dep.id,
            'task_id':       blocker.id,
            'title':         blocker.title,
            'status':        blocker.status,
            'quadrant':      blocker.quadrant,
            'is_done':       blocker.status == 'done'
        })

    # tasks that are blocked by this task
    blocking = []
    for dep in task.dependents:
        blocked_task = dep.task
        blocking.append({
            'dependency_id': dep.id,
            'task_id':       blocked_task.id,
            'title':         blocked_task.title,
            'status':        blocked_task.status,
            'quadrant':      blocked_task.quadrant,
        })

    # all other tasks available to link
    all_tasks = Task.query.filter(
        Task.user_id == current_user.id,
        Task.id != task_id,
        Task.status != 'done'
    ).all()

    # exclude already linked tasks
    linked_ids = {d.depends_on_id for d in task.dependencies}
    linked_ids.update({d.task_id for d in task.dependents})

    available = [
        {'id': t.id, 'title': t.title, 'quadrant': t.quadrant}
        for t in all_tasks
        if t.id not in linked_ids
    ]

    return jsonify({
        'task_title': task.title,
        'task_id':    task_id,
        'blocked_by': blocked_by,
        'blocking':   blocking,
        'available':  available
    })


@tasks_bp.route('/tasks/<int:task_id>/dependencies/add', methods=['POST'])
@login_required
def add_dependency(task_id):
    """Mark task_id as depending on depends_on_id."""
    task = Task.query.filter_by(
        id=task_id, user_id=current_user.id
    ).first_or_404()

    depends_on_id = request.json.get('depends_on_id')
    if not depends_on_id:
        return jsonify({'error': 'depends_on_id required'}), 400

    # validate the target task belongs to this user
    target = Task.query.filter_by(
        id=depends_on_id, user_id=current_user.id
    ).first_or_404()

    # prevent self-dependency
    if depends_on_id == task_id:
        return jsonify({'error': 'A task cannot depend on itself'}), 400

    # prevent circular dependency
    if _would_create_cycle(task_id, depends_on_id):
        return jsonify({'error': 'This would create a circular dependency'}), 400

    # check if already exists
    existing = TaskDependency.query.filter_by(
        task_id=task_id,
        depends_on_id=depends_on_id
    ).first()

    if existing:
        return jsonify({'error': 'Dependency already exists'}), 400

    dep = TaskDependency(
        user_id=current_user.id,
        task_id=task_id,
        depends_on_id=depends_on_id
    )
    db.session.add(dep)
    db.session.commit()

    return jsonify({
        'success':       True,
        'dependency_id': dep.id,
        'blocker_title': target.title,
        'blocker_status': target.status,
        'is_done':       target.status == 'done'
    })


@tasks_bp.route('/tasks/dependencies/<int:dep_id>/remove', methods=['POST'])
@login_required
def remove_dependency(dep_id):
    """Remove a dependency link."""
    dep = TaskDependency.query.filter_by(
        id=dep_id,
        user_id=current_user.id
    ).first_or_404()
    db.session.delete(dep)
    db.session.commit()
    return jsonify({'success': True})




@tasks_bp.route('/tasks/<int:task_id>/complete-recurring', methods=['POST'])
@login_required
def complete_recurring(task_id):
    """Permanently retire a recurring task — mark done and add to history."""
    task = Task.query.filter_by(
        id=task_id, user_id=current_user.id
    ).first_or_404()

    if not task.is_recurring:
        return jsonify({'error': 'Not a recurring task'}), 400

    task.status = 'done'
    history = TaskHistory(
        user_id          = current_user.id,
        original_task_id = task.id,
        title            = task.title,
        description      = task.description,
        urgency          = task.urgency,
        importance       = task.importance,
        estimated_hours  = task.estimated_hours,
        completed_hours  = task.completed_hours or 0,
        deadline         = task.deadline,
        quadrant         = task.quadrant,
        is_recurring     = True,
        event_type       = 'completed',
        task_created_at  = task.created_at,
    )
    db.session.add(history)
    db.session.commit()
    return jsonify({'success': True})


@tasks_bp.route('/history')
@login_required
def task_history():
    """Chronological log of all completed and deleted tasks."""
    entries = TaskHistory.query.filter_by(
        user_id=current_user.id
    ).order_by(TaskHistory.event_at.desc()).all()
    return render_template('tasks/history.html', entries=entries)


def _would_create_cycle(task_id, new_depends_on_id):
    """
    Check if adding task_id -> new_depends_on_id would create a cycle.
    Uses DFS to check if new_depends_on_id is reachable FROM task_id
    through existing dependencies. If it is, adding the reverse link
    would create a cycle.
    """
    visited = set()
    stack   = [task_id]

    while stack:
        current = stack.pop()
        if current in visited:
            continue
        visited.add(current)

        # get what current task depends on
        deps = TaskDependency.query.filter_by(task_id=current).all()
        for dep in deps:
            if dep.depends_on_id == new_depends_on_id:
                return True
            stack.append(dep.depends_on_id)

    return False