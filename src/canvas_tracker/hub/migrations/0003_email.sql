-- Optional email copies. Addresses are Fernet-encrypted like the Canvas token; the
-- confirmation code is only kept as a hash.
ALTER TABLE users ADD COLUMN email_sealed BLOB;          -- confirmed address
ALTER TABLE users ADD COLUMN email_pending_sealed BLOB;  -- address waiting for its code
ALTER TABLE users ADD COLUMN email_code_hash TEXT;
ALTER TABLE users ADD COLUMN email_code_expires_at TEXT;
ALTER TABLE users ADD COLUMN email_code_sent_at TEXT;
ALTER TABLE users ADD COLUMN email_code_attempts INTEGER NOT NULL DEFAULT 0;
