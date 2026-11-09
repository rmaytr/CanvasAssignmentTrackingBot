-- Each user's own reminder rhythm, chosen in /settings → ⏰ Reminders. NULL means
-- "use the bot-wide default from the environment", so existing users keep exactly the
-- behaviour they had.
ALTER TABLE users ADD COLUMN reminder_interval_minutes INTEGER;  -- 0: no repeating reminders
ALTER TABLE users ADD COLUMN reminder_window_hours INTEGER;
ALTER TABLE users ADD COLUMN digest_lookahead_days INTEGER;
