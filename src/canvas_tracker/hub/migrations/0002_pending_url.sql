-- A new Canvas address waits here until a token for it has been checked.
ALTER TABLE users ADD COLUMN pending_base_url TEXT;
