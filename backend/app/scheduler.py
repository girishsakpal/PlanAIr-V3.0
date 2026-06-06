from datetime import date, time, timedelta, datetime
from app.models.schedule import BusyHours, ScheduleSession
from app.models.task import Task, TaskDependency
from app.models.mood import MoodLog
from app import db


BREAK_MINUTES     = 15
MIN_SESSION_MIN   = 30
MAX_SESSION_MIN   = 120
WORKING_START_HR  = 6    # 06:00
WORKING_END_HR    = 23   # 23:00


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
        now           = datetime.now()
        now_minutes   = now.hour * 60 + now.minute
        now_minutes   = ((now_minutes + 14) // 15) * 15
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
        cursor = slot_start

        for b_start, b_end in booked:
            if b_end <= slot_start:
                continue
            if b_start >= slot_end:
                break
            if b_start > cursor:
                gap = min(b_start, slot_end) - cursor
                if gap >= duration_minutes:
                    return (
                        minutes_to_time(cursor),
                        minutes_to_time(cursor + duration_minutes)
                    )
            cursor = max(cursor, b_end)

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
    Does NOT add break after the last session.
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

    booked_total = sum(
        time_to_minutes(s.end_time) - time_to_minutes(s.start_time)
        for s in existing
    )
    breaks_total = (len(existing) - 1) * BREAK_MINUTES

    return max(0, free_total - booked_total - breaks_total)


# ── priority scoring ──────────────────────────────────────────────────────────

def priority_score(task):
    """
    Deadline proximity is the PRIMARY scheduling driver.
    Quadrant weight acts as a tiebreaker within the same deadline band.

    Score bands (higher score = scheduled earlier):
      overdue / due today  -> 1000 + quadrant_weight
      due tomorrow         ->  800 + quadrant_weight  (beats any 2-day task)
      due in 2 days        ->  600 + quadrant_weight
      due in 3-4 days      ->  400 + quadrant_weight
      due in 5-7 days      ->  200 + quadrant_weight
      due in 8-14 days     ->  100 + quadrant_weight
      no deadline          ->    0 + quadrant_weight  (lowest tier)
    """
    quadrant_weights = {
        'do_now':   80,
        'schedule': 60,
        'delegate': 40,
        'avoid':    20,
    }
    qw = quadrant_weights.get(task.quadrant or 'avoid', 20)

    if task.deadline:
        days_left = (task.deadline - date.today()).days
        if days_left <= 0:
            deadline_score = 1000
        elif days_left == 1:
            deadline_score = 800
        elif days_left == 2:
            deadline_score = 600
        elif days_left <= 4:
            deadline_score = 400
        elif days_left <= 7:
            deadline_score = 200
        else:
            deadline_score = 100
    else:
        deadline_score = 0

    return deadline_score + qw


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
    """
    mood = get_today_mood(user_id)
    if mood <= 2:
        return 45, ['delegate', 'avoid']
    elif mood == 3:
        return MAX_SESSION_MIN, []
    else:
        return 150, []


# ── dependency ordering ───────────────────────────────────────────────────────

def get_dependency_order(tasks, user_id):
    """
    Topological sort of tasks based on dependencies using Kahn's algorithm.

    Rules:
    - Tasks with no blockers are scheduled first.
    - A task blocked by another task in the current set is placed
      after its blocker in the schedule.
    - A task blocked by a task NOT in the current set (e.g. not
      pending/in-progress) that is also not done is considered
      externally blocked and skipped this run.

    Returns:
        ordered_tasks  — list of tasks in safe scheduling order
        blocked_ids    — set of task IDs blocked by external undone tasks
    """
    task_ids  = {t.id for t in tasks}
    task_map  = {t.id: t for t in tasks}

    # in_degree[task_id] = number of unresolved blockers within our set
    in_degree = {t.id: 0 for t in tasks}

    # graph[blocker_id] -> [task_ids that depend on it]
    graph = {t.id: [] for t in tasks}

    # tasks blocked by an external undone task (can't schedule at all this run)
    blocked_ids = set()

    for task in tasks:
        deps = TaskDependency.query.filter_by(task_id=task.id).all()
        for dep in deps:
            blocker_id = dep.depends_on_id
            blocker    = Task.query.get(blocker_id)

            if blocker is None:
                # blocker was deleted — ignore this dependency
                continue

            if blocker.status == 'done':
                # blocker already done — no constraint needed
                continue

            if blocker_id in task_ids:
                # blocker is in our schedulable set — add a graph edge
                # blocker must come before task
                graph[blocker_id].append(task.id)
                in_degree[task.id] += 1
            else:
                # blocker exists, is not done, and is not being scheduled
                # this task is fully blocked this run
                blocked_ids.add(task.id)

    # remove externally blocked tasks from consideration
    schedulable = [t for t in tasks if t.id not in blocked_ids]

    # Kahn's algorithm
    # start with all tasks that have no unresolved blockers
    queue  = [t for t in schedulable if in_degree[t.id] == 0]
    result = []

    while queue:
        # among ready tasks, sort by priority + deadline so highest
        # priority tasks get the best time slots
        queue.sort(key=_dep_sort_key, reverse=True)
        task = queue.pop(0)
        result.append(task)

        # unblock tasks that were waiting for this one
        for neighbor_id in graph.get(task.id, []):
            in_degree[neighbor_id] -= 1
            if in_degree[neighbor_id] == 0:
                neighbor = task_map.get(neighbor_id)
                if neighbor and neighbor.id not in blocked_ids:
                    queue.append(neighbor)

    return result, blocked_ids


def _dep_sort_key(task):
    """
    Sort key used inside the topological sort queue.
    Combines deadline urgency and quadrant priority.
    Higher = schedule sooner.
    """
    score = priority_score(task)
    # also factor in deadline — sooner deadline = higher urgency
    if task.deadline:
        days_until = (task.deadline - date.today()).days
        # invert so closer deadline = higher score
        score += max(0, 30 - days_until)
    return score


# ── main scheduler ────────────────────────────────────────────────────────────

def schedule_tasks(user_id, days_ahead=14):
    """
    Main scheduling function.
    1. Fetches all pending/in-progress/delayed tasks.
    2. Resolves dependency order — tasks are scheduled after their blockers.
    3. Applies deadline-first + priority sort within the dependency order.
    4. Distributes sessions across free time, respecting busy hours,
       breaks, mood settings, and deadlines.
    """
    from app.models.user import User
    user = User.query.get(user_id)
    if not user or not user.busy_hours_set:
        return []

    today = date.today()

    # clear all future unfinished sessions for a clean reschedule
    ScheduleSession.query.filter(
        ScheduleSession.user_id      == user_id,
        ScheduleSession.date         >= today,
        ScheduleSession.is_completed == False
    ).delete(synchronize_session=False)
    db.session.flush()

    # fetch tasks that need scheduling
    tasks = Task.query.filter(
        Task.user_id == user_id,
        Task.status.in_(['pending', 'in-progress', 'delayed'])
    ).all()

    # skip tasks with no valid estimated hours
    tasks = [t for t in tasks if t.estimated_hours and t.estimated_hours > 0]

    if not tasks:
        db.session.commit()
        return []

    # ── step 1: resolve dependency order ─────────────────────────────────────
    ordered_tasks, blocked_ids = get_dependency_order(tasks, user_id)

    # mark externally blocked tasks so the dashboard can show them
    for task in tasks:
        if task.id in blocked_ids:
            task.status = 'delayed'

    # ── step 2: within dependency order, apply deadline-first sort ───────────
    # Tasks at the same dependency level are sorted by deadline proximity
    # first, then by priority score. This preserves topological order
    # because the dependency graph already determines which tasks can run
    # first — we only re-sort tasks that are at the same "level".
    def deadline_sort_key(task):
        if task.deadline:
            days_until = (task.deadline - today).days
            return (0, days_until, -priority_score(task))
        else:
            return (1, 0, -priority_score(task))

    # re-sort within dependency-safe order
    # we do a stable sort pass on the ordered list to apply deadline priority
    # while respecting the topological order as much as possible
    ordered_tasks = _stable_deadline_sort(ordered_tasks, today)
    # ─────────────────────────────────────────────────────────────────────────

    max_session_min, skip_today = get_mood_settings(user_id)
    scheduled = []

    for task in ordered_tasks:
        remaining_min = int(task.estimated_hours * 60)
        already_done  = int((task.completed_hours or 0) * 60)
        remaining_min = max(0, remaining_min - already_done)

        if remaining_min <= 0:
            task.status = 'done'
            continue

        # determine search window
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

            # don't schedule past deadline
            if task.deadline and search_date > task.deadline:
                break

            # mood skip: defer low-priority tasks on a bad day
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
                slot        = find_next_slot(user_id, search_date, session_min)

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


def _stable_deadline_sort(ordered_tasks, today):
    """
    Applies deadline-first priority within the dependency-ordered list
    without breaking dependency constraints.

    Strategy: tasks that have all their dependencies already resolved
    (i.e. their blockers appear earlier in the list) can be reordered
    among themselves freely. Tasks that still depend on something later
    in the list cannot be moved before their blocker.

    This is implemented by doing a greedy pass:
    - maintain a set of 'resolved' task IDs (already placed in output)
    - at each step, pick the highest-priority task whose blockers
      are all in the resolved set
    """
    task_map    = {t.id: t for t in ordered_tasks}
    resolved    = set()
    result      = []
    remaining   = list(ordered_tasks)

    while remaining:
        # find all tasks whose blockers are fully resolved
        ready = []
        for task in remaining:
            deps = TaskDependency.query.filter_by(task_id=task.id).all()
            blocker_ids = set()
            for dep in deps:
                blocker = Task.query.get(dep.depends_on_id)
                if blocker and blocker.status != 'done':
                    blocker_ids.add(dep.depends_on_id)

            # a task is ready if all its in-set blockers are resolved
            in_set_blockers = blocker_ids & {t.id for t in ordered_tasks}
            if in_set_blockers.issubset(resolved):
                ready.append(task)

        if not ready:
            # shouldn't happen if topological sort was correct,
            # but as a safety net just append remaining tasks as-is
            result.extend(remaining)
            break

        # among ready tasks, pick the one with the best deadline sort key
        ready.sort(key=lambda t: (
            (0, (t.deadline - today).days, -priority_score(t))
            if t.deadline else
            (1, 0, -priority_score(t))
        ))

        chosen = ready[0]
        result.append(chosen)
        resolved.add(chosen.id)
        remaining.remove(chosen)

    return result


# ── recurring tasks ───────────────────────────────────────────────────────────

def schedule_recurring_tasks(user_id, days_ahead=14):
    """
    Handles recurring tasks — places one session per day (daily)
    or one per week (weekly) within the scheduling window.
    Recurring tasks are not subject to dependency ordering.
    """
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
                # use user's chosen day; fall back to today's weekday if not set
                target_weekday = task.preferred_day if task.preferred_day is not None else today.weekday()
                if target_date.weekday() != target_weekday:
                    continue

            existing = ScheduleSession.query.filter_by(
                user_id=user_id,
                task_id=task.id,
                date=target_date
            ).first()
            if existing:
                continue

            # --- preferred time pinning ---
            if task.preferred_time:
                pref_start_min = time_to_minutes(task.preferred_time)
                pref_end_min   = pref_start_min + session_min

                # for today: if preferred time has already passed, skip today only
                if target_date == date.today():
                    now_min = datetime.now().hour * 60 + datetime.now().minute
                    if pref_start_min < now_min:
                        continue   # skip today, will schedule from tomorrow onward

                # check against busy-hours blocks for this weekday
                busy_blocks = BusyHours.query.filter_by(
                    user_id=user_id,
                    day_of_week=target_date.weekday()
                ).all()
                busy_conflict = any(
                    not (pref_end_min <= time_to_minutes(b.start_time)
                         or pref_start_min >= time_to_minutes(b.end_time))
                    for b in busy_blocks
                )

                # check against other already-booked sessions on this date
                # (raw session times, no break padding — recurring tasks own their fixed slot)
                other_sessions = ScheduleSession.query.filter(
                    ScheduleSession.user_id == user_id,
                    ScheduleSession.date    == target_date,
                    ScheduleSession.task_id != task.id
                ).all()
                session_conflict = any(
                    not (pref_end_min <= time_to_minutes(s.start_time)
                         or pref_start_min >= time_to_minutes(s.end_time))
                    for s in other_sessions
                )

                if not busy_conflict and not session_conflict                         and pref_end_min <= WORKING_END_HR * 60:
                    start_t = minutes_to_time(pref_start_min)
                    end_t   = minutes_to_time(pref_end_min)
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
                # if the preferred slot is genuinely blocked, skip this day
                # (don't fall back — the user wants a fixed time)
            else:
                # no preferred time — find the next available slot as before
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