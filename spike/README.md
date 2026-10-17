# M0 spike scripts (owner only)

Throwaway scripts that check how **your** Canvas and Telegram behave, so the
bot's design questions (S1–S8 in `docs/PRD.md` §17) are settled with real data.

- Run them **on your own computer**. Never paste tokens into chat, issues or commits.
- Secrets are read from files you pass with `--token-file` / `--feed-file`, never
  from command-line arguments.
- Raw output goes to `spike/out/`, which git ignores.
- Before committing anything, scrub it:
  `uv run python spike/scrub.py --host canvas.yourschool.edu spike/out tests/fixtures/canvas`
  and check the result by eye. It only copies `planner_items*.json` and
  `assignment_groups_*.json`; your profile and token list never leave `spike/out/`.
- Record what you learned in `docs/spike-notes.md`.

Scripts:

| Script | Answers |
|---|---|
| `probe_canvas.py --base-url https://canvas.yourschool.edu --token-file PATH` | S3–S7 |
| `probe_ical.py --feed-file PATH` | S1 (run before and after submitting an assignment) |
| `probe_telegram.py --token-file PATH --chat-id N` | S8 |

S2 (when a New Quiz counts as submitted) is manual: submit a New Quiz, then run
`probe_canvas.py` again and look at that item's `submissions` in
`spike/out/planner_items.json`.
