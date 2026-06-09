from datetime import date, timedelta, datetime
from app.models.task import Task
from app.models.schedule import ScheduleSession
from app.models.mood import MoodLog, ProductivityLog, Suggestion
from app import db


# ── internal helpers ──────────────────────────────────────────────────────────

def _already_suggested_today(user_id, suggestion_type, related_task_id=None):
    """
    Prevents duplicate suggestions of the same type on the same day.
    Checks both task-specific and general suggestions.
    """
    today     = date.today()
    today_start = datetime.combine(today, datetime.min.time())

    q = Suggestion.query.filter(
        Suggestion.user_id         == user_id,
        Suggestion.suggestion_type == suggestion_type,
        Suggestion.created_at      >= today_start,
        Suggestion.is_dismissed    == False
    )
    if related_task_id:
        q = q.filter(Suggestion.related_task_id == related_task_id)

    return q.first() is not None


def _add_suggestion(user_id, suggestion_type, message, related_task_id=None):
    """Only adds suggestion if one of the same type hasn't been added today."""
    if _already_suggested_today(user_id, suggestion_type, related_task_id):
        return
    s = Suggestion(
        user_id         = user_id,
        suggestion_type = suggestion_type,
        message         = message,
        related_task_id = related_task_id
    )
    db.session.add(s)


def _days_since_joined(user_id):
    """Returns how many days since the user created their account."""
    from app.models.user import User
    user = User.query.get(user_id)
    if not user:
        return 0
    return (date.today() - user.created_at.date()).days


def _task_age_days(task):
    """Returns how many days since a task was created."""
    return (date.today() - task.created_at.date()).days


def _sessions_completed_count(user_id):
    """Total sessions ever completed by this user."""
    return ScheduleSession.query.filter_by(
        user_id=user_id,
        is_completed=True
    ).count()


# ── suggestion rules ──────────────────────────────────────────────────────────

def _check_overdue_tasks(user_id, today):
    """
    Only flag tasks that are past deadline AND at least 1 day old.
    Avoids flagging tasks created today with a past deadline.
    """
    overdue = Task.query.filter(
        Task.user_id  == user_id,
        Task.deadline <  today,
        Task.status.in_(['pending', 'in-progress', 'delayed'])
    ).all()

    for task in overdue:
        # skip if task was just created today
        if _task_age_days(task) < 1:
            continue

        days_overdue = (today - task.deadline).days
        if days_overdue == 1:
            msg = f'"{task.title}" was due yesterday reschedule or update its deadline.'
        elif days_overdue <= 3:
            msg = f'"{task.title}" is {days_overdue} days overdue. Worth tackling soon.'
        else:
            msg = f'"{task.title}" has been overdue for {days_overdue} days. Consider breaking it into smaller steps.'

        _add_suggestion(user_id, 'reschedule', msg, related_task_id=task.id)


def _check_overload(user_id, today):
    """
    Only warn about overload if more than 6 hours scheduled today
    AND the user has been using the app for at least 2 days.
    """
    if _days_since_joined(user_id) < 2:
        return

    sessions = ScheduleSession.query.filter_by(
        user_id=user_id,
        date=today
    ).all()

    if not sessions:
        return

    total_minutes = sum(
        (s.end_time.hour * 60 + s.end_time.minute) -
        (s.start_time.hour * 60 + s.start_time.minute)
        for s in sessions
    )

    if total_minutes > 360:
        hours = round(total_minutes / 60, 1)
        _add_suggestion(
            user_id,
            'reduce_load',
            f'You have {hours}h of work scheduled today that\'s a heavy load. '
            f'Consider moving 1–2 lower priority tasks to tomorrow.'
        )


def _check_neglected_important(user_id, today):
    """
    Only flag important tasks that:
    - are at least 4 days old (so new users aren't immediately nagged)
    - haven't had ANY session completed in the last 3 days
    - have actually been scheduled at least once (meaning the user knows about it)
    - limit to max 2 suggestions at a time so it's not overwhelming
    """
    if _days_since_joined(user_id) < 4:
        return

    three_days_ago = today - timedelta(days=3)

    important_tasks = Task.query.filter(
        Task.user_id   == user_id,
        Task.quadrant.in_(['do_now', 'schedule']),
        Task.status.in_(['pending', 'in-progress'])
    ).all()

    count = 0
    for task in important_tasks:
        if count >= 2:  # max 2 neglect suggestions at once
            break

        # skip brand new tasks
        if _task_age_days(task) < 4:
            continue

        # check the task has been scheduled at least once
        ever_scheduled = ScheduleSession.query.filter_by(
            task_id=task.id
        ).first()
        if not ever_scheduled:
            continue

        # check no completed session in last 3 days
        recent_completed = ScheduleSession.query.filter(
            ScheduleSession.task_id      == task.id,
            ScheduleSession.date         >= three_days_ago,
            ScheduleSession.is_completed == True
        ).first()

        if not recent_completed:
            days_since = _task_age_days(task)
            if task.deadline:
                days_left = (task.deadline - today).days
                if days_left <= 3:
                    msg = (f'"{task.title}" is important and due in {days_left} day'
                           f'{"s" if days_left != 1 else ""} it needs your attention today.')
                else:
                    msg = (f'"{task.title}" hasn\'t been worked on recently. '
                           f'Even 30 minutes today would make a difference.')
            else:
                msg = (f'"{task.title}" has been sitting idle. '
                       f'Schedule some time for it this week.')

            _add_suggestion(
                user_id,
                'focus_reminder',
                msg,
                related_task_id=task.id
            )
            count += 1


def _check_mood(user_id, today):
    """
    Only suggest lighter day for low mood (1–2).
    Don't suggest this if already suggested today.
    """
    mood = MoodLog.query.filter_by(user_id=user_id, date=today).first()

    if not mood:
        return

    if mood.mood_score == 1:
        msg = ('Rough day that\'s okay. Focus on just one critical task '
               'and give yourself permission to take it easy.')
    elif mood.mood_score == 2:
        msg = ('Feeling low today. Consider tackling your most important task '
               'first thing, then reassess how you feel.')
    else:
        return  # mood 3–5 doesn't need a suggestion

    _add_suggestion(user_id, 'low_mood', msg)


def _check_streak(user_id, today):
    """
    Only fire streak suggestion at meaningful milestones.
    Don't repeat if already shown today.
    """
    from app.productivity import get_streak
    streak = get_streak(user_id, today)

    milestones = {
        3:  'You\'ve been consistent for 3 days straight great start!',
        5:  '5-day streak! You\'re building a solid habit.',
        7:  'One full week of consistency. That\'s genuinely impressive.',
        14: 'Two weeks strong. Your schedule is becoming second nature.',
        21: '21 days habit formation territory. Keep going.',
        30: '30-day streak. You\'ve mastered the system.'
    }

    if streak in milestones:
        _add_suggestion(user_id, 'streak', milestones[streak])


def _check_partial_completions(user_id, today):
    """
    New rule: if user has logged partial hours 3+ times this week,
    suggest adjusting their session length to be more realistic.
    Only fires after 7 days of usage.
    """
    if _days_since_joined(user_id) < 7:
        return

    week_ago = today - timedelta(days=7)

    completed_sessions = ScheduleSession.query.filter(
        ScheduleSession.user_id      == user_id,
        ScheduleSession.date         >= week_ago,
        ScheduleSession.is_completed == True,
        ScheduleSession.logged_hours != None
    ).all()

    if len(completed_sessions) < 3:
        return

    # count sessions where logged hours < 80% of allocated
    partial_count = 0
    for s in completed_sessions:
        allocated = round(
            (s.end_time.hour * 60 + s.end_time.minute -
             s.start_time.hour * 60 - s.start_time.minute) / 60, 2
        )
        if s.logged_hours and s.logged_hours < allocated * 0.8:
            partial_count += 1

    if partial_count >= 3:
        _add_suggestion(
            user_id,
            'reduce_load',
            'You\'ve been logging partial hours several times this week. '
            'Your sessions might be too long consider reducing estimated '
            'hours on your tasks to better match your actual pace.'
        )


def _check_all_done(user_id, today):
    """
    Positive suggestion when all of today's sessions are completed.
    Only fires once per day.
    """
    sessions = ScheduleSession.query.filter_by(
        user_id=user_id,
        date=today
    ).all()

    if not sessions:
        return

    all_done = all(s.is_completed for s in sessions)
    if all_done:
        _add_suggestion(
            user_id,
            'streak',
            'All done for today! Take a proper break '
            'you\'ve earned it.'
        )


# ── public API ────────────────────────────────────────────────────────────────

def clear_all_suggestions(user_id):
    """Dismisses all active suggestions for a user."""
    Suggestion.query.filter_by(
        user_id=user_id,
        is_dismissed=False
    ).update({'is_dismissed': True}, synchronize_session=False)
    db.session.commit()


def run_suggestion_engine(user_id):
    """
    Runs all suggestion rules for the user.
    Called after schedule generation, session toggle, and mood update.
    """
    today = date.today()

    # dismiss stale suggestions that are now resolved
    _auto_dismiss_resolved(user_id, today)

    _check_overdue_tasks(user_id, today)
    _check_overload(user_id, today)
    _check_neglected_important(user_id, today)
    _check_mood(user_id, today)
    _check_streak(user_id, today)
    _check_partial_completions(user_id, today)
    _check_all_done(user_id, today)

    db.session.commit()


def _auto_dismiss_resolved(user_id, today):
    """
    Auto-dismiss suggestions that are no longer relevant.
    - overdue tasks that are now done
    - low_mood suggestions from previous days
    - streak suggestions from previous days
    - all_done suggestions from previous days
    """
    from datetime import datetime
    today_start = datetime.combine(today, datetime.min.time())

    # dismiss old day-specific suggestions
    stale_types = ['low_mood', 'streak', 'reduce_load']
    Suggestion.query.filter(
        Suggestion.user_id         == user_id,
        Suggestion.suggestion_type.in_(stale_types),
        Suggestion.created_at      <  today_start,
        Suggestion.is_dismissed    == False
    ).update({'is_dismissed': True}, synchronize_session=False)

    # dismiss reschedule suggestions for tasks now marked done
    done_task_ids = [
        t.id for t in Task.query.filter_by(
            user_id=user_id,
            status='done'
        ).all()
    ]
    if done_task_ids:
        Suggestion.query.filter(
            Suggestion.user_id         == user_id,
            Suggestion.suggestion_type == 'reschedule',
            Suggestion.related_task_id.in_(done_task_ids),
            Suggestion.is_dismissed    == False
        ).update({'is_dismissed': True}, synchronize_session=False)

    # dismiss focus_reminder for tasks now done
    if done_task_ids:
        Suggestion.query.filter(
            Suggestion.user_id         == user_id,
            Suggestion.suggestion_type == 'focus_reminder',
            Suggestion.related_task_id.in_(done_task_ids),
            Suggestion.is_dismissed    == False
        ).update({'is_dismissed': True}, synchronize_session=False)


def get_active_suggestions(user_id):
    """
    Returns active suggestions, newest first.
    Caps at 5 so the dashboard never looks overwhelming.
    """
    return Suggestion.query.filter_by(
        user_id=user_id,
        is_dismissed=False
    ).order_by(Suggestion.created_at.desc()).limit(5).all()


def dismiss_suggestion(user_id, suggestion_id):
    """Marks a suggestion as dismissed."""
    s = Suggestion.query.filter_by(
        id=suggestion_id,
        user_id=user_id
    ).first()
    if s:
        s.is_dismissed = True
        db.session.commit()
    return s