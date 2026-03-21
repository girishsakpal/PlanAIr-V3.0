from datetime import date, time, timedelta, datetime, timezone
from app.models.schedule import BusyHours, ScheduleSession
from app.models.task import Task
from app import db
from app.models.mood import MoodLog


# ── helpers ──────────────────────────────────────────────────────────────────

def get_today_mood(user_id):
    """Returns today's mood score (1–5) or 3 (neutral) if not set."""
    mood = MoodLog.query.filter_by(
        user_id=user_id,
        date=date.today()
    ).first()
    return mood.mood_score if mood else 3

def time_to_minutes(t):
    """Convert a time object to total minutes since midnight."""
    return t.hour * 60 + t.minute


def minutes_to_time(m):
    """Convert total minutes since midnight to a time object."""
    m = min(m, 23 * 60 + 59)
    return time(m // 60, m % 60)


def get_free_slots(user_id, target_date):
    """
    Returns a list of free (start_min, end_min) tuples for a given day,
    after subtracting all busy blocks for that day of the week.
    For today, slots before the current time are excluded.
    """
    day_of_week   = target_date.weekday()
    working_start = 6 * 60    # 06:00
    working_end   = 23 * 60   # 23:00

    # if scheduling for today, start from current time (rounded up to next 15 min)
    if target_date == date.today():
        now         = datetime.now()
        now_minutes = now.hour * 60 + now.minute
        # round up to next 15 minute boundary
        now_minutes = ((now_minutes + 14) // 15) * 15
        working_start = max(working_start, now_minutes)

    busy_blocks = BusyHours.query.filter_by(
        user_id=user_id,
        day_of_week=day_of_week
    ).all()

    busy = sorted([
        (time_to_minutes(b.start_time), time_to_minutes(b.end_time))
        for b in busy_blocks
    ])

    free = []
    cursor = working_start

    for b_start, b_end in busy:
        if cursor < b_start:
            free.append((cursor, b_start))
        cursor = max(cursor, b_end)

    if cursor < working_end:
        free.append((cursor, working_end))

    # filter out slots that are too small to be useful (less than 30 min)
    free = [(s, e) for s, e in free if e - s >= 30]

    return free

def free_minutes_on_day(user_id, target_date):
    """Returns total free minutes available on a given date."""
    return sum(end - start for start, end in get_free_slots(user_id, target_date))


def get_scheduled_minutes_on_day(user_id, target_date):
    """Returns total minutes consumed (session + break buffer) on a given date."""
    sessions = ScheduleSession.query.filter_by(
        user_id=user_id,
        date=target_date
    ).all()
    return sum(
        (time_to_minutes(s.end_time) - time_to_minutes(s.start_time)) + BREAK_MINUTES
        for s in sessions
    )


def get_available_minutes_on_day(user_id, target_date):
    """Free minutes minus already-scheduled minutes."""
    free    = free_minutes_on_day(user_id, target_date)
    booked  = get_scheduled_minutes_on_day(user_id, target_date)
    return max(0, free - booked)


BREAK_MINUTES = 15

def find_next_slot(user_id, target_date, duration_minutes):
    """
    Finds the first available time slot of at least duration_minutes
    on target_date. Adds a 15 min break after every existing session.
    """
    free_slots = get_free_slots(user_id, target_date)

    existing = ScheduleSession.query.filter_by(
        user_id=user_id,
        date=target_date
    ).order_by(ScheduleSession.start_time).all()

    # add break buffer after each session
    booked = sorted([
        (time_to_minutes(s.start_time),
         time_to_minutes(s.end_time) + BREAK_MINUTES)  # ← buffer added here
        for s in existing
    ])

    for slot_start, slot_end in free_slots:
        cursor = slot_start

        for b_start, b_end in booked:
            if b_end <= cursor:
                continue
            if b_start >= slot_end:
                break
            if b_start - cursor >= duration_minutes:
                return (
                    minutes_to_time(cursor),
                    minutes_to_time(cursor + duration_minutes)
                )
            cursor = b_end

        if slot_end - cursor >= duration_minutes:
            return (
                minutes_to_time(cursor),
                minutes_to_time(cursor + duration_minutes)
            )

    return None


# ── priority sorting ──────────────────────────────────────────────────────────

def priority_score(task):
    """
    Higher score = schedule first.
    Factors: quadrant weight + deadline urgency.
    """
    quadrant_weights = {
        'do_now':   100,
        'schedule':  70,
        'delegate':  40,
        'avoid':     10,
    }
    score = quadrant_weights.get(task.quadrant, 10)

    # boost score if deadline is close
    if task.deadline:
        days_left = (task.deadline - date.today()).days
        if days_left <= 1:
            score += 50
        elif days_left <= 3:
            score += 30
        elif days_left <= 7:
            score += 15

    return score


# ── main scheduler ────────────────────────────────────────────────────────────

def schedule_tasks(user_id, days_ahead=14):
    today = date.today()

    # delete future unfinished sessions
    ScheduleSession.query.filter(
        ScheduleSession.user_id == user_id,
        ScheduleSession.date >= today,
        ScheduleSession.is_completed == False
    ).delete(synchronize_session=False)
    db.session.flush()

    tasks = Task.query.filter(
        Task.user_id == user_id,
        Task.status.in_(['pending', 'in-progress'])
    ).all()

    if not tasks:
        db.session.commit()
        return []

    tasks = sorted(tasks, key=priority_score, reverse=True)

    # ── mood-based adjustment ──────────────────────────
    mood = get_today_mood(user_id)

    if mood <= 2:
        # low mood: only schedule do_now tasks today,
        # reduce max session length to 45 min
        max_session_minutes = 45
        tasks_today_only = ['do_now']
    elif mood == 3:
        # neutral: normal scheduling
        max_session_minutes = 120
        tasks_today_only = None
    else:
        # good mood (4–5): allow longer sessions
        max_session_minutes = 150
        tasks_today_only = None
    # ──────────────────────────────────────────────────

    min_session_minutes = 30
    scheduled = []

    for task in tasks:
        remaining_minutes = int(task.estimated_hours * 60)
        session_number    = 1
        search_date       = today
        days_searched     = 0

        while remaining_minutes >= min_session_minutes and days_searched < days_ahead:

            if task.deadline and search_date > task.deadline:
                break

            # low mood: skip non-critical tasks for today
            if (tasks_today_only and
                search_date == today and
                task.quadrant not in tasks_today_only):
                search_date   = search_date + timedelta(days=1)
                days_searched += 1
                continue

            available = get_available_minutes_on_day(user_id, search_date)

            if available >= min_session_minutes:
                session_minutes = min(remaining_minutes, max_session_minutes, available)
                session_minutes = max(session_minutes, min_session_minutes)

                slot = find_next_slot(user_id, search_date, session_minutes)

                if slot:
                    start_t, end_t = slot
                    total_sessions = max(1, round(
                        task.estimated_hours * 60 / max_session_minutes
                    ))
                    label = (
                        f'{task.title}: Part {session_number} of {total_sessions}'
                        if task.estimated_hours > (max_session_minutes / 60)
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

                    remaining_minutes -= session_minutes
                    session_number    += 1

            search_date   = search_date + timedelta(days=1)
            days_searched += 1

        if remaining_minutes >= min_session_minutes and task.status == 'pending':
            task.status = 'delayed'

    db.session.commit()
    return scheduled


def schedule_recurring_tasks(user_id, days_ahead=14):
    """
    Separately handles recurring tasks.
    Places one session per day (daily) or one per week (weekly)
    within the scheduling window.
    """
    today = date.today()

    recurring_tasks = Task.query.filter_by(
        user_id=user_id,
        is_recurring=True
    ).filter(Task.status.in_(['pending', 'in-progress'])).all()

    for task in recurring_tasks:
        session_minutes = min(int(task.estimated_hours * 60), 120)
        session_minutes = max(session_minutes, 30)

        for day_offset in range(days_ahead):
            target_date = today + timedelta(days=day_offset)

            # daily: place every day
            # weekly: place only on same weekday as today
            if task.recurrence_type == 'weekly':
                if target_date.weekday() != today.weekday():
                    continue

            # skip if already scheduled on this day
            existing = ScheduleSession.query.filter_by(
                user_id=user_id,
                task_id=task.id,
                date=target_date
            ).first()
            if existing:
                continue

            slot = find_next_slot(user_id, target_date, session_minutes)
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