from datetime import date, time, timedelta, datetime
from app.models.schedule import BusyHours, ScheduleSession
from app.models.task import Task
from app.models.mood import MoodLog
from app import db


BREAK_MINUTES     = 15
MIN_SESSION_MIN   = 30
MAX_SESSION_MIN   = 120
WORKING_START_HR  = 6   # 06:00
WORKING_END_HR    = 23  # 23:00


# ── time utilities ────────────────────────────────────────────────────────────

def time_to_minutes(t):
    return t.hour * 60 + t.minute


def minutes_to_time(m):
    m = max(0, min(m, 23 * 60 + 59))
    return time(m // 60, m % 60)


# ── free slot calculation ─────────────────────────────────────────────────────

def get_free_slots(user_id, target_date):
    """
    Returns list of (start_min, end_min) free blocks for the day.
    For today, clips to current time rounded up to next 15 min.
    """
    day_of_week   = target_date.weekday()
    working_start = WORKING_START_HR * 60
    working_end   = WORKING_END_HR * 60

    # for today, don't schedule in the past
    if target_date == date.today():
        now         = datetime.now()
        now_minutes = now.hour * 60 + now.minute
        now_minutes = ((now_minutes + 14) // 15) * 15
        working_start = max(working_start, now_minutes)

    # if working window has collapsed (e.g. it's 11pm), return empty
    if working_start >= working_end:
        return []

    busy_blocks = BusyHours.query.filter_by(
        user_id=user_id,
        day_of_week=day_of_week
    ).all()

    busy = sorted([
        (time_to_minutes(b.start_time), time_to_minutes(b.end_time))
        for b in busy_blocks
    ])

    free   = []
    cursor = working_start

    for b_start, b_end in busy:
        if b_end <= cursor:
            continue
        if b_start > cursor:
            free.append((cursor, b_start))
        cursor = max(cursor, b_end)

    if cursor < working_end:
        free.append((cursor, working_end))

    # only return slots large enough to be useful
    free = [(s, e) for s, e in free if e - s >= MIN_SESSION_MIN]

    return free


def get_booked_blocks(user_id, target_date):
    """
    Returns sorted list of (start_min, end_min + break) for
    already scheduled sessions on a date.
    """
    existing = ScheduleSession.query.filter_by(
        user_id=user_id,
        date=target_date
    ).order_by(ScheduleSession.start_time).all()

    return sorted([
        (
            time_to_minutes(s.start_time),
            time_to_minutes(s.end_time) + BREAK_MINUTES
        )
        for s in existing
    ])


def find_next_slot(user_id, target_date, duration_minutes):
    """
    Finds first gap of at least duration_minutes on target_date
    that fits within a free slot and doesn't overlap booked sessions.
    Returns (start_time, end_time) or None.
    """
    free_slots = get_free_slots(user_id, target_date)
    if not free_slots:
        return None

    booked = get_booked_blocks(user_id, target_date)

    for slot_start, slot_end in free_slots:
        # available space within this free slot
        cursor = slot_start

        for b_start, b_end in booked:
            # booked block is entirely before this slot
            if b_end <= slot_start:
                continue
            # booked block is entirely after this slot
            if b_start >= slot_end:
                break
            # gap before this booked block
            if b_start > cursor:
                gap = min(b_start, slot_end) - cursor
                if gap >= duration_minutes:
                    return (
                        minutes_to_time(cursor),
                        minutes_to_time(cursor + duration_minutes)
                    )
            cursor = max(cursor, b_end)

        # remaining space after all booked blocks in this slot
        remaining = slot_end - cursor
        if remaining >= duration_minutes:
            return (
                minutes_to_time(cursor),
                minutes_to_time(cursor + duration_minutes)
            )

    return None


def get_available_minutes_on_day(user_id, target_date):
    """
    Returns total schedulable minutes on a day —
    free time minus already booked time (including breaks).
    Does NOT add break after the last session since there's
    nothing after it.
    """
    free_total = sum(
        e - s for s, e in get_free_slots(user_id, target_date)
    )

    existing = ScheduleSession.query.filter_by(
        user_id=user_id,
        date=target_date
    ).all()

    if not existing:
        return free_total

    # only add break buffer between sessions, not after the last one
    booked_total = sum(
        time_to_minutes(s.end_time) - time_to_minutes(s.start_time)
        for s in existing
    )
    # add breaks between sessions (n-1 breaks for n sessions)
    breaks_total = (len(existing) - 1) * BREAK_MINUTES

    return max(0, free_total - booked_total - breaks_total)


# ── priority scoring ──────────────────────────────────────────────────────────

def priority_score(task):
    """
    All quadrants get scheduled — priority only affects ORDER.
    do_now first, then schedule, then delegate, then avoid.
    Deadline proximity adds urgency boost.
    """
    quadrant_weights = {
        'do_now':   100,
        'schedule':  75,
        'delegate':  50,
        'avoid':     25,   # still gets scheduled, just last
    }
    score = quadrant_weights.get(task.quadrant or 'avoid', 25)

    if task.deadline:
        days_left = (task.deadline - date.today()).days
        if days_left <= 1:
            score += 50
        elif days_left <= 3:
            score += 30
        elif days_left <= 7:
            score += 15

    return score


# ── mood adjustment ───────────────────────────────────────────────────────────

def get_today_mood(user_id):
    mood = MoodLog.query.filter_by(
        user_id=user_id,
        date=date.today()
    ).first()
    return mood.mood_score if mood else 3


def get_mood_settings(user_id):
    """
    Returns (max_session_minutes, skip_quadrants_today) based on mood.
    Low mood: shorter sessions, skip avoid+delegate today.
    Good mood: allow longer sessions.
    """
    mood = get_today_mood(user_id)

    if mood <= 2:
        return 45, ['delegate', 'avoid']
    elif mood == 3:
        return MAX_SESSION_MIN, []
    else:
        return 150, []


# ── main scheduler ────────────────────────────────────────────────────────────

def schedule_tasks(user_id, days_ahead=14):
    from app.models.user import User
    user = User.query.get(user_id)
    if not user or not user.busy_hours_set:
        return []

    today = date.today()

    # clear future unfinished sessions
    ScheduleSession.query.filter(
        ScheduleSession.user_id      == user_id,
        ScheduleSession.date         >= today,
        ScheduleSession.is_completed == False
    ).delete(synchronize_session=False)
    db.session.flush()

    tasks = Task.query.filter(
        Task.user_id == user_id,
        Task.status.in_(['pending', 'in-progress', 'delayed'])
    ).all()

    tasks = [t for t in tasks if t.estimated_hours and t.estimated_hours > 0]

    if not tasks:
        db.session.commit()
        return []

    # ── deadline-first sort ───────────────────────────────────────────────────
    # primary:   tasks WITH deadlines, sorted by deadline ascending (soonest first)
    # secondary: tasks WITHOUT deadlines, sorted by priority score descending
    def sort_key(task):
        if task.deadline:
            days_until = (task.deadline - today).days
            # negative so sooner deadlines sort first
            return (0, days_until, -priority_score(task))
        else:
            return (1, 0, -priority_score(task))

    tasks = sorted(tasks, key=sort_key)
    # ─────────────────────────────────────────────────────────────────────────

    max_session_min, skip_today = get_mood_settings(user_id)
    scheduled = []

    for task in tasks:
        remaining_min = int(task.estimated_hours * 60)
        already_done  = int((task.completed_hours or 0) * 60)
        remaining_min = max(0, remaining_min - already_done)

        if remaining_min <= 0:
            task.status = 'done'
            continue

        # for deadline tasks: only search up to the deadline date
        if task.deadline:
            deadline_days = (task.deadline - today).days + 1
            search_window = min(deadline_days, days_ahead)
        else:
            search_window = days_ahead

        session_number = 1
        search_date    = today
        days_searched  = 0
        total_sessions = max(1, round(remaining_min / max_session_min))

        while remaining_min >= MIN_SESSION_MIN and days_searched < search_window:

            if task.deadline and search_date > task.deadline:
                break

            if (skip_today
                    and search_date == today
                    and task.quadrant in skip_today):
                search_date   += timedelta(days=1)
                days_searched += 1
                continue

            available = get_available_minutes_on_day(user_id, search_date)

            if available >= MIN_SESSION_MIN:
                session_min = min(remaining_min, max_session_min, available)
                session_min = max(session_min, MIN_SESSION_MIN)

                slot = find_next_slot(user_id, search_date, session_min)

                if slot:
                    start_t, end_t = slot

                    label = (
                        f'{task.title} — Part {session_number} of {total_sessions}'
                        if total_sessions > 1
                        else task.title
                    )

                    session = ScheduleSession(
                        user_id       = user_id,
                        task_id       = task.id,
                        date          = search_date,
                        start_time    = start_t,
                        end_time      = end_t,
                        session_label = label,
                        is_completed  = False
                    )
                    db.session.add(session)
                    scheduled.append(session)

                    remaining_min  -= session_min
                    session_number += 1

            search_date   += timedelta(days=1)
            days_searched += 1

    db.session.commit()
    return scheduled


def schedule_recurring_tasks(user_id, days_ahead=14):
    """Handles recurring tasks — one session per day or week."""
    today = date.today()

    recurring = Task.query.filter_by(
        user_id=user_id,
        is_recurring=True
    ).filter(Task.status.in_(['pending', 'in-progress'])).all()

    for task in recurring:
        session_min = min(int(task.estimated_hours * 60), MAX_SESSION_MIN)
        session_min = max(session_min, MIN_SESSION_MIN)

        for day_offset in range(days_ahead):
            target_date = today + timedelta(days=day_offset)

            if task.recurrence_type == 'weekly':
                if target_date.weekday() != today.weekday():
                    continue

            existing = ScheduleSession.query.filter_by(
                user_id=user_id,
                task_id=task.id,
                date=target_date
            ).first()
            if existing:
                continue

            slot = find_next_slot(user_id, target_date, session_min)
            if slot:
                start_t, end_t = slot
                session = ScheduleSession(
                    user_id       = user_id,
                    task_id       = task.id,
                    date          = target_date,
                    start_time    = start_t,
                    end_time      = end_t,
                    session_label = task.title,
                    is_completed  = False
                )
                db.session.add(session)

    db.session.commit()