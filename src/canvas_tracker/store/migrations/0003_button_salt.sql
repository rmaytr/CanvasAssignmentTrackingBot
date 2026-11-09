-- Item buttons carry a random salt that belongs to this database file, so a button
-- from an earlier sign-up (whose file was deleted by /disconnect, and whose item ids
-- start again at 1) can't act on an item in the new file.
--
-- Buttons sent before this migration have no salt. A database that already had data
-- keeps accepting them (they can only refer to its own items); a brand-new database
-- refuses them.
INSERT INTO state (key, value)
SELECT 'buttons_unsalted_ok', '1'
WHERE EXISTS (SELECT 1 FROM items)
   OR EXISTS (SELECT 1 FROM notifications)
   OR EXISTS (SELECT 1 FROM state);
INSERT INTO state (key, value) VALUES ('button_salt', lower(hex(randomblob(4))))
ON CONFLICT (key) DO NOTHING;
