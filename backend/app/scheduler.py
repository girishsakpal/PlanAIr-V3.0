from datetime import date, time, timedelta, datetime, timezone
from app.models.schedule import BusyHours, ScheduleSession
from app.models.task import Task
from app import db


# ── helpers ──────────────────────────────────────────────────────────────────

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
    Working window is 06:00 – 23:00 (1020 minutes available max).
    """
    day_of_week = target_date.weekday()  # 0=Mon, 6=Sun
    working_start = 6 * 60   # 06:00
    working_end   = 23 * 60  # 23:00

    busy_blocks = BusyHours.query.filter_by(
        user_id=user_id,
        day_of_week=day_of_week
    ).all()

    # build list of busy minute ranges
    busy = sorted([
        (time_to_minutes(b.start_time), time_to_minutes(b.end_time))
        for b in busy_blocks
    ])

    # subtract busy from working window
    free = []
    cursor = working_start

    for b_start, b_end in busy:
        if cursor < b_start:
            free.append((cursor, b_start))
        cursor = max(cursor, b_end)

    if cursor < working_end:
        free.append((cursor, working_end))

    return free


def free_minutes_on_day(user_id, target_date):
    """Returns total free minutes available on a given date."""
    return sum(end - start for start, end in get_free_slots(user_id, target_date))


def get_scheduled_minutes_on_day(user_id, target_date):
    """Returns total minutes already scheduled for a user on a given date."""
    sessions = ScheduleSession.query.filter_by(
        user_id=user_id,
        date=target_date
    ).all()
    return sum(
        time_to_minutes(s.end_time) - time_to_minutes(s.start_time)
        for s in sessions
    )


def get_available_minutes_on_day(user_id, target_date):
    """Free minutes minus already-scheduled minutes."""
    free    = free_minutes_on_day(user_id, target_date)
    booked  = get_scheduled_minutes_on_day(user_id, target_date)
    return max(0, free - booked)


def find_next_slot(user_id, target_date, duration_minutes):
    """
    Finds the first available time slot of at least duration_minutes
    on target_date that doesn't overlap existing sessions or busy hours.
    Returns (start_time, end_time) or None if no slot found.
    """
    free_slots = get_free_slots(user_id, target_date)

    existing = ScheduleSession.query.filter_by(
        user_id=user_id,
        date=target_date
    ).order_by(ScheduleSession.start_time).all()

    booked = sorted([
        (time_to_minutes(s.start_time), time_to_minutes(s.end_time))
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
                return minutes_to_time(cursor), minutes_to_time(cursor + duration_minutes)
            cursor = b_end

        # check remaining space in this free slot
        if slot_end - cursor >= duration_minutes:
            return minutes_to_time(cursor), minutes_to_time(cursor + duration_minutes)

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
    """
    Main scheduling function.
    - Fetches all pending/in-progress tasks for the user
    - Sorts by priority
    - Splits each task into sessions across available free days
    - Writes sessions to schedule_sessions table
    - Skips days with no availability
    """

    # delete all future unfinished sessions for this user
    # (reschedule from scratch on each call)
    today = date.today()
    ScheduleSession.query.filter(
        ScheduleSession.user_id == user_id,
        ScheduleSession.date >= today,
        ScheduleSession.is_completed == False
    ).delete(synchronize_session=False)
    db.session.flush()

    # fetch tasks that still need scheduling
    tasks = Task.query.filter(
        Task.user_id == user_id,
        Task.status.in_(['pending', 'in-progress'])
    ).all()

    if not tasks:
        db.session.commit()
        return []

    # sort by priority descending
    tasks = sorted(tasks, key=priority_score, reverse=True)

    scheduled = []

    for task in tasks:
        remaining_minutes = int(task.estimated_hours * 60)
        session_number    = 1
        search_date       = today

        # cap: how many sessions to split into (max 1 per day, min 30 min)
        max_session_minutes = 120   # max 2 hours per session block
        min_session_minutes = 30    # don't schedule less than 30 min

        days_searched = 0

        while remaining_minutes >= min_session_minutes and days_searched < days_ahead:

            # respect deadline — don't schedule past it
            if task.deadline and search_date > task.deadline:
                break

            available = get_available_minutes_on_day(user_id, search_date)

            if available >= min_session_minutes:
                # how much to schedule on this day
                session_minutes = min(remaining_minutes, max_session_minutes, available)
                session_minutes = max(session_minutes, min_session_minutes)

                slot = find_next_slot(user_id, search_date, session_minutes)

                if slot:
                    start_t, end_t = slot
                    total_sessions = max(1, round(task.estimated_hours * 60 / max_session_minutes))

                    label = (
                        f'Part {session_number} of {total_sessions}'
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

        # mark task as delayed if we couldn't fit it all
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