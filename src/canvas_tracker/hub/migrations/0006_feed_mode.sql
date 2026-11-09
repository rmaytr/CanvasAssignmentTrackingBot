-- How the bot reads each user's Canvas: with an access token (the default, and what
-- every existing user has) or with their private calendar feed link, which needs no
-- token. The feed link is a secret like a token, so only its Fernet ciphertext is kept.
ALTER TABLE users ADD COLUMN mode TEXT NOT NULL DEFAULT 'token' CHECK (mode IN ('token', 'feed'));
ALTER TABLE users ADD COLUMN feed_sealed BLOB;
