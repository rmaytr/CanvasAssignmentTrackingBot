-- How many parts of a split message were delivered, so a retry resumes
-- after them instead of re-sending (review I5).
ALTER TABLE notifications ADD COLUMN parts_sent INTEGER NOT NULL DEFAULT 0;
