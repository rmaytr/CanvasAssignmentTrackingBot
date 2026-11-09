-- When an onboarding user last answered a sign-up step. Sign-ups that stall for 7 days
-- are removed so they stop holding a MAX_USERS slot. Users already part-way through
-- sign-up when this runs get a full 7 days from now (same fixed-width UTC text as the
-- application writes).
ALTER TABLE users ADD COLUMN last_seen_at TEXT;
UPDATE users SET last_seen_at = strftime('%Y-%m-%dT%H:%M:%f', 'now') || '000Z'
WHERE status = 'onboarding';
