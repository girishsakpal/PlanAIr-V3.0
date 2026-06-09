from datetime import date, timedelta
from app.models.mood import ProductivityLog, MoodLog
from app.models.schedule import ScheduleSession
from app.models.task import Task


def get_weekly_productivity(user_id):
    """
    Returns last 7 days of productivity scores.
    Days with no log return 0.
    """
    today  = date.today()
    result = []

    for i in range(6, -1, -1):
        d   = today - timedelta(days=i)
        log = ProductivityLog.query.filter_by(
            user_id=user_id,
            date=d
        ).first()
        result.append({
            'date':  d.strftime('%a %d'),
            'score': round(log.score, 1) if log else 0
        })

    return result


def get_weekly_completion(user_id):
    """
    Returns last 7 days of session completion counts.
    """
    today  = date.today()
    result = []

    for i in range(6, -1, -1):
        d        = today - timedelta(days=i)
        sessions = ScheduleSession.query.filter_by(
            user_id=user_id,
            date=d
        ).all()
        total     = len(sessions)
        completed = sum(1 for s in sessions if s.is_completed)
        result.append({
            'date':      d.strftime('%a %d'),
            'completed': completed,
            'pending':   total - completed
        })

    return result


def get_most_productive_hours(user_id):
    """
    Finds which hours of the day have the highest completion rate.
    Returns list of (hour_label, completion_count) sorted by hour.
    """
    completed_sessions = ScheduleSession.query.filter_by(
        user_id=user_id,
        is_completed=True
    ).all()

    hour_counts = {}
    for s in completed_sessions:
        hour = s.start_time.hour
        label = f'{hour:02d}:00'
        hour_counts[label] = hour_counts.get(label, 0) + 1

    # fill in missing hours with 0
    result = []
    for h in range(6, 23):
        label = f'{h:02d}:00'
        result.append({
            'hour':  label,
            'count': hour_counts.get(label, 0)
        })

    return result


def get_quadrant_distribution(user_id):
    """
    Returns hours spent per Eisenhower quadrant this week.
    """
    today      = date.today()
    week_ago   = today - timedelta(days=7)

    sessions = ScheduleSession.query.filter(
        ScheduleSession.user_id      == user_id,
        ScheduleSession.date         >= week_ago,
        ScheduleSession.is_completed == True
    ).all()

    quadrant_hours = {
        'Do now':   0,
        'Schedule': 0,
        'Delegate': 0,
        'Avoid':    0
    }

    quadrant_map = {
        'do_now':   'Do now',
        'schedule': 'Schedule',
        'delegate': 'Delegate',
        'avoid':    'Avoid'
    }

    for s in sessions:
        task = Task.query.get(s.task_id)
        if task and task.quadrant in quadrant_map:
            minutes = (
                s.end_time.hour * 60 + s.end_time.minute -
                s.start_time.hour * 60 - s.start_time.minute
            )
            label = quadrant_map[task.quadrant]
            quadrant_hours[label] += round(minutes / 60, 2)

    return [
        {'quadrant': k, 'hours': v}
        for k, v in quadrant_hours.items()
    ]


def get_mood_trend(user_id):
    """
    Returns last 7 days of mood scores.
    """
    today  = date.today()
    result = []

    for i in range(6, -1, -1):
        d    = today - timedelta(days=i)
        mood = MoodLog.query.filter_by(user_id=user_id, date=d).first()
        result.append({
            'date':  d.strftime('%a %d'),
            'score': mood.mood_score if mood else None
        })

    return result


def get_summary_stats(user_id):
    """
    Returns high-level summary numbers for the insights header.
    """
    today    = date.today()
    week_ago = today - timedelta(days=7)

    # total tasks
    total_tasks = Task.query.filter_by(user_id=user_id).count()
    done_tasks  = Task.query.filter_by(
        user_id=user_id,
        status='done'
    ).count()

    # this week's sessions
    week_sessions = ScheduleSession.query.filter(
        ScheduleSession.user_id == user_id,
        ScheduleSession.date    >= week_ago
    ).all()
    week_completed = sum(1 for s in week_sessions if s.is_completed)
    week_total     = len(week_sessions)

    # average productivity this week
    logs = ProductivityLog.query.filter(
        ProductivityLog.user_id == user_id,
        ProductivityLog.date    >= week_ago
    ).all()
    avg_score = round(
        sum(l.score for l in logs) / len(logs), 1
    ) if logs else 0

    # total hours logged
    total_hours = sum(
        s.logged_hours or 0
        for s in ScheduleSession.query.filter_by(
            user_id=user_id,
            is_completed=True
        ).all()
    )

    # streak
    from app.productivity import get_streak
    streak = get_streak(user_id)

    return {
        'total_tasks':    total_tasks,
        'done_tasks':     done_tasks,
        'week_completed': week_completed,
        'week_total':     week_total,
        'avg_score':      avg_score,
        'total_hours':    round(total_hours, 1),
        'streak':         streak
    }


def get_plain_language_summary(stats, productive_hour):
    """
    Generates a one-line human summary of the week.
    """
    if stats['week_total'] == 0:
        return 'No sessions scheduled this week yet. Generate your schedule to get started.'

    completion_rate = (
        stats['week_completed'] / stats['week_total'] * 100
        if stats['week_total'] > 0 else 0
    )

    if completion_rate >= 80:
        quality = 'an excellent'
    elif completion_rate >= 60:
        quality = 'a solid'
    elif completion_rate >= 40:
        quality = 'a moderate'
    else:
        quality = 'a challenging'

    hour_text = (
        f' You tend to do your best work around {productive_hour}.'
        if productive_hour else ''
    )

    return (
        f'You\'ve had {quality} week completing {stats["week_completed"]} of '
        f'{stats["week_total"]} sessions with an average score of '
        f'{stats["avg_score"]}%.{hour_text}'
    )