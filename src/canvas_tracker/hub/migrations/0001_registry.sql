-- Bot-wide registry for friends mode. Each user's assignments live in their own
-- database file; this one only knows who the users are and how to reach Canvas.
CREATE TABLE users (
    telegram_id INTEGER PRIMARY KEY,
    status TEXT NOT NULL CHECK (status IN ('onboarding', 'active')),
    step TEXT,
    display_name TEXT NOT NULL DEFAULT '',
    is_owner INTEGER NOT NULL DEFAULT 0,
    canvas_base_url TEXT,
    token_sealed BLOB,          -- Fernet ciphertext, never the token itself
    tz TEXT,
    suggested_tz TEXT,          -- the time zone Canvas reported during sign-up
    digest_time TEXT,           -- HH:MM local
    quiet TEXT NOT NULL DEFAULT '00:00-08:00',  -- HH:MM-HH:MM local, or 'off'
    created_at TEXT NOT NULL
);

CREATE TABLE invites (
    code_hash TEXT PRIMARY KEY, -- SHA-256 of the code; the code itself is only in the link
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    used_by INTEGER,
    used_at TEXT
);

CREATE TABLE state (
    key TEXT PRIMARY KEY,
    value TEXT
);
