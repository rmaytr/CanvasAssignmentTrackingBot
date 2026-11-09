-- The reminder interval a cycle was opened with. Each user can now choose their own
-- interval, and slot numbers only mean something for the interval they were counted
-- with, so a cycle whose interval no longer matches is restarted instead of reused.
-- NULL (cycles opened before this migration) is filled in with the bot-wide default
-- when the user's tenant starts, because that is the interval every cycle used then.
ALTER TABLE cycles ADD COLUMN interval_minutes INTEGER;
