from datetime import date, timedelta
from app.models.schedule import ScheduleSession
from app.models.task import Task
from app.models.mood import ProductivityLog, MoodLog
from app import db


# ── scoring weights ───────────────────────────────────────────────────────────

WEIGHT_COMPLETION   = 0.40   # % of sessions completed today
WEIGHT_IMPORTANT    = 0.30   # % of important sessions completed
WEIGHT_ADHERENCE    = 0.20   # sessions completed on their scheduled day
WEIGHT_BONUS        = 0.10   # streak bonus


def calculate_daily_score(user_id, target_date=None):
    """
    Calculates and saves the productivity score for a given day.
    Called whenever a session is toggled or at end of day.
    Returns the ProductivityLog object.
    """
    if target_date is None:
        target_date = date.today()

    sessions = ScheduleSession.query.filter_by(
        user_id=user_id,
        date=target_date
    ).all()

    if not sessions:
        return None

    total       = len(sessions)
    completed   = [s for s in sessions if s.is_completed]
    n_completed = len(completed)

    # completion score
    completion_score = (n_completed / total) * 100 * WEIGHT_COMPLETION

    # important sessions (do_now and schedule quadrants)
    important_sessions = []
    important_completed = 0
    for s in sessions:
        task = Task.query.get(s.task_id)
        if task and task.quadrant in ('do_now', 'schedule'):
            important_sessions.append(s)
            if s.is_completed:
                important_completed += 1

    if important_sessions:
        important_score = (important_completed / len(important_sessions)) * 100 * WEIGHT_IMPORTANT
    else:
        important_score = 100 * WEIGHT_IMPORTANT  # no important tasks = full marks

    # adherence: sessions completed on their correct scheduled day
    adherence = (n_completed / total) if total > 0 else 0
    adherence_score = adherence * 100 * WEIGHT_ADHERENCE

    # streak bonus
    streak      = get_streak(user_id, target_date)
    bonus_score = min(streak * 2, 10) * WEIGHT_BONUS * 10

    final_score = min(
        round(completion_score + important_score + adherence_score + bonus_score, 1),
        100.0
    )

    # upsert productivity log
    log = ProductivityLog.query.filter_by(
        user_id=user_id,
        date=target_date
    ).first()

    if log:
        log.score               = final_score
        log.sessions_completed  = n_completed
        log.sessions_total      = total
        log.important_completed = important_completed
        log.schedule_adherence  = round(adherence * 100, 1)
    else:
        log = ProductivityLog(
            user_id             = user_id,
            date                = target_date,
            score               = final_score,
            sessions_completed  = n_completed,
            sessions_total      = total,
            important_completed = important_completed,
            schedule_adherence  = round(adherence * 100, 1)
        )
        db.session.add(log)

    db.session.commit()
    return log


def get_streak(user_id, up_to_date=None):
    """
    Returns the number of consecutive days the user
    completed at least one session, up to and including up_to_date.
    """
    if up_to_date is None:
        up_to_date = date.today()

    streak  = 0
    check   = up_to_date - timedelta(days=1)  # start from yesterday

    while True:
        log = ProductivityLog.query.filter_by(
            user_id=user_id,
            date=check
        ).first()

        if log and log.sessions_completed > 0:
            streak += 1
            check  -= timedelta(days=1)
        else:
            break

    return streak


def get_weekly_scores(user_id):
    """Returns list of (date, score) for the past 7 days."""
    today  = date.today()
    result = []

    for i in range(6, -1, -1):
        d   = today - timedelta(days=i)
        log = ProductivityLog.query.filter_by(user_id=user_id, date=d).first()
        result.append({
            'date':  d.strftime('%d %b'),
            'score': log.score if log else 0
        })

    return result