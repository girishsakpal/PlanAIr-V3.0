# PlanAIr 3.0: Database Schema Notes

## Decisions
- Database: SQLite (dev) → can migrate to PostgreSQL for production
- ORM: Flask-SQLAlchemy
- All times stored as TIME objects (not strings)
- All dates stored as DATE objects (not strings)
- Passwords hashed via werkzeug, never stored plain
- quadrant field on Task is computed + stored on save (not recalculated live)

---

## Table 1: users
Primary table. All other tables FK back to this.

| Column         | Type         | Constraints             | Notes                          |
|----------------|--------------|-------------------------|--------------------------------|
| id             | INTEGER      | PK, autoincrement       |                                |
| username       | VARCHAR(80)  | NOT NULL, UNIQUE        | displayed in UI                |
| email          | VARCHAR(120) | NOT NULL, UNIQUE        | used for login                 |
| password_hash  | VARCHAR(256) | NOT NULL                | werkzeug hash, never plain     |
| dark_mode      | BOOLEAN      | DEFAULT False           | persists UI preference         |
| busy_hours_set | BOOLEAN      | DEFAULT False           | first-login gate               |
| created_at     | DATETIME     | DEFAULT utcnow          |                                |

Relationships (one-to-many from users):
  users → busy_hours        (cascade delete)
  users → tasks             (cascade delete)
  users → schedule_sessions (cascade delete)
  users → productivity_logs (cascade delete)
  users → mood_logs         (cascade delete)
  users → suggestions       (cascade delete)

---

## Table 2: busy_hours
Stores user's unavailable time blocks.
Scheduler reads this to find free slots before placing sessions.

| Column      | Type        | Constraints       | Notes                    |
|-------------|-------------|-------------------|--------------------------|
| id          | INTEGER     | PK, autoincrement |                          |
| user_id     | INTEGER     | FK → users.id     |                          |
| day_of_week | INTEGER     | NOT NULL          | 0=Mon, 1=Tue, ... 6=Sun  |
| start_time  | TIME        | NOT NULL          | e.g. 09:00               |
| end_time    | TIME        | NOT NULL          | e.g. 17:00               |
| label       | VARCHAR(60) | NULLABLE          | e.g. "College", "Work"   |

Example: College Mon–Fri 9am–5pm = 5 rows
User can have multiple blocks per day (e.g. 9–12 and 14–17)

---

## Table 3: tasks
Core task definition. No scheduling data here, that lives in schedule_sessions.

| Column          | Type         | Constraints       | Notes                                    |
|-----------------|--------------|-------------------|------------------------------------------|
| id              | INTEGER      | PK, autoincrement |                                          |
| user_id         | INTEGER      | FK → users.id     |                                          |
| title           | VARCHAR(200) | NOT NULL          |                                          |
| description     | TEXT         | NULLABLE          |                                          |
| urgency         | INTEGER      | NOT NULL          | 1–4 scale (3–4 = urgent)                 |
| importance      | INTEGER      | NOT NULL          | 1–4 scale (3–4 = important)              |
| estimated_hours | FLOAT        | NOT NULL          | user's estimate of total work            |
| deadline        | DATE         | NULLABLE          | hard deadline if applicable              |
| is_recurring    | BOOLEAN      | DEFAULT False     |                                          |
| recurrence_type | VARCHAR(20)  | NULLABLE          | 'daily' or 'weekly'                      |
| status          | VARCHAR(20)  | DEFAULT 'pending' | pending/in-progress/done/delayed         |
| quadrant        | VARCHAR(30)  | NULLABLE          | computed from urgency+importance on save |
| created_at      | DATETIME     | DEFAULT utcnow    |                                          |

Quadrant logic:
  urgency >= 3 AND importance >= 3  →  'do_now'     (Urgent + Important)
  urgency <  3 AND importance >= 3  →  'schedule'   (Important, Not Urgent)
  urgency >= 3 AND importance <  3  →  'delegate'   (Urgent, Not Important)
  urgency <  3 AND importance <  3  →  'avoid'      (Neither)

Status transitions:
  pending → in-progress → done
  pending → delayed
  delayed → in-progress → done

---

## Table 4: schedule_sessions
One row per scheduled work block.
A 6-hour task split across 3 days = 3 rows.

| Column        | Type        | Constraints       | Notes                        |
|---------------|-------------|-------------------|------------------------------|
| id            | INTEGER     | PK, autoincrement |                              |
| user_id       | INTEGER     | FK → users.id     | for fast per-user queries    |
| task_id       | INTEGER     | FK → tasks.id     |                              |
| date          | DATE        | NOT NULL          | which day this session is on |
| start_time    | TIME        | NOT NULL          |                              |
| end_time      | TIME        | NOT NULL          |                              |
| session_label | VARCHAR(60) | NULLABLE          | e.g. "Part 2 of 4"          |
| is_completed  | BOOLEAN     | DEFAULT False     | driven by checkbox in UI     |
| completed_at  | DATETIME    | NULLABLE          | set when is_completed → True |

Key rule: sessions are only placed inside free time blocks (not overlapping busy_hours).
Key rule: no day should be overloaded, max session hours = available free hours that day.

---

## Table 5: productivity_logs
One row per user per day.
Updated whenever a session checkbox is ticked, or recalculated at end of day.

| Column              | Type    | Constraints                    | Notes                          |
|---------------------|---------|--------------------------------|--------------------------------|
| id                  | INTEGER | PK, autoincrement              |                                |
| user_id             | INTEGER | FK → users.id                  |                                |
| date                | DATE    | NOT NULL                       |                                |
| score               | FLOAT   | NOT NULL                       | 0.0 – 100.0                    |
| sessions_completed  | INTEGER | DEFAULT 0                      |                                |
| sessions_total      | INTEGER | DEFAULT 0                      |                                |
| important_completed | INTEGER | DEFAULT 0                      | sessions from do_now/schedule  |
| schedule_adherence  | FLOAT   | NULLABLE                       | % sessions done on correct day |

UNIQUE constraint: (user_id, date), one log per user per day

Scoring formula (Phase 4):
  base        = (sessions_completed / sessions_total) * 40
  important   = (important_completed / max(important_total, 1)) * 30
  adherence   = schedule_adherence * 20
  bonus       = up to 10 (streak, focus sessions)
  score       = base + important + adherence + bonus  →  capped at 100

---

## Table 6: mood_logs
One row per user per day. Lightweight, just a number and optional note.

| Column     | Type         | Constraints                    | Notes              |
|------------|--------------|--------------------------------|--------------------|
| id         | INTEGER      | PK, autoincrement              |                    |
| user_id    | INTEGER      | FK → users.id                  |                    |
| date       | DATE         | NOT NULL                       |                    |
| mood_score | INTEGER      | NOT NULL                       | 1–5 scale          |
| note       | VARCHAR(200) | NULLABLE                       | optional free text |

UNIQUE constraint: (user_id, date), one mood entry per user per day

Mood → scheduling impact (Phase 4):
  1–2  →  reduce today's workload, suggest deferring low-priority tasks
  3    →  normal scheduling
  4–5  →  normal scheduling, positive suggestion shown

---

## Table 7: suggestions
Stores rule-generated suggestions. Persisted so they survive page reloads.
Dismissed suggestions are kept (is_dismissed=True) for analytics later.

| Column          | Type         | Constraints       | Notes                              |
|-----------------|--------------|-------------------|------------------------------------|
| id              | INTEGER      | PK, autoincrement |                                    |
| user_id         | INTEGER      | FK → users.id     |                                    |
| created_at      | DATETIME     | DEFAULT utcnow    |                                    |
| suggestion_type | VARCHAR(40)  | NOT NULL          | see types below                    |
| message         | VARCHAR(300) | NOT NULL          | text shown to user                 |
| is_dismissed    | BOOLEAN      | DEFAULT False     |                                    |
| related_task_id | INTEGER      | FK → tasks.id     | NULLABLE, if about a specific task|

Suggestion types:
  'reschedule'     →  task is overdue, suggest moving it
  'reduce_load'    →  today is overloaded, suggest distributing
  'focus_reminder' →  important task untouched for 3+ days
  'take_break'     →  heavy workload detected
  'low_mood'       →  mood score 1–2, suggest lighter day
  'streak'         →  5+ consistent days, positive reinforcement

---

## Relationships Summary

users ──< busy_hours           (one user → many busy blocks)
users ──< tasks                (one user → many tasks)
users ──< schedule_sessions    (one user → many sessions)
users ──< productivity_logs    (one user → one log per day)
users ──< mood_logs            (one user → one mood per day)
users ──< suggestions          (one user → many suggestions)
tasks ──< schedule_sessions    (one task → many sessions if split)
tasks ──< suggestions          (one task → many suggestions about it)

---

## Phase Build Order (which tables are needed when)

Phase 1  →  users
Phase 2  →  busy_hours, tasks
Phase 3  →  schedule_sessions
Phase 4  →  mood_logs, productivity_logs, suggestions
Phase 5  →  all tables (read-only for insights charts)