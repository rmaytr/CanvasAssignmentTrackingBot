CREATE TABLE items (
    id INTEGER PRIMARY KEY,
    plannable_type TEXT NOT NULL,
    plannable_id INTEGER NOT NULL,
    title TEXT NOT NULL,
    type TEXT NOT NULL,
    course_id INTEGER,
    course_name TEXT NOT NULL DEFAULT '',
    assignment_id INTEGER,
    due_at TEXT,
    lock_at TEXT,
    html_url TEXT,
    points_possible REAL,
    submission_types TEXT NOT NULL DEFAULT '[]',
    assignment_group_id INTEGER,
    omit_from_final_grade INTEGER NOT NULL DEFAULT 0,
    submitted INTEGER NOT NULL DEFAULT 0,
    excused INTEGER NOT NULL DEFAULT 0,
    graded INTEGER NOT NULL DEFAULT 0,
    late INTEGER NOT NULL DEFAULT 0,
    missing INTEGER NOT NULL DEFAULT 0,
    redo_request INTEGER NOT NULL DEFAULT 0,
    marked_complete INTEGER,
    bot_done_at TEXT,
    bot_done_due_at TEXT,
    snoozed_until TEXT,
    stop_reminders INTEGER NOT NULL DEFAULT 0,
    done_seen_at TEXT,
    gone_at TEXT,
    enriched INTEGER NOT NULL DEFAULT 0,
    UNIQUE (plannable_type, plannable_id)
);
CREATE INDEX items_due_at ON items (due_at);
CREATE INDEX items_assignment_id ON items (assignment_id);

CREATE TABLE courses (
    id INTEGER PRIMARY KEY,
    code TEXT NOT NULL,
    name TEXT NOT NULL,
    apply_group_weights INTEGER NOT NULL DEFAULT 0,
    total_points REAL NOT NULL DEFAULT 0
);

CREATE TABLE assignment_groups (
    id INTEGER PRIMARY KEY,
    course_id INTEGER NOT NULL,
    name TEXT NOT NULL,
    group_weight REAL NOT NULL,
    total_points REAL NOT NULL
);

CREATE TABLE cycles (
    id INTEGER PRIMARY KEY,
    anchor_utc TEXT NOT NULL,
    closed_at_utc TEXT
);

CREATE TABLE notifications (
    key TEXT PRIMARY KEY,
    kind TEXT NOT NULL,
    status TEXT NOT NULL CHECK (status IN ('pending', 'sent', 'failed')),
    item_refs TEXT NOT NULL DEFAULT '[]',
    claimed_at TEXT NOT NULL,
    sent_at TEXT,
    message_id INTEGER,
    error TEXT
);

CREATE TABLE state (
    key TEXT PRIMARY KEY,
    value TEXT
);
