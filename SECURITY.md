# Security

Canvas access tokens skip multi-factor sign-in and carry the full permissions of the student who created them, so this project treats them like passwords. This page covers how to report a problem, what the bot stores, and the threats it's designed against.

## Reporting a vulnerability

**Please don't open a public issue for security problems.** Use GitHub's private reporting: the **Security** tab → **Report a vulnerability**, on [this repository](https://github.com/rmaytr/CanvasAssignmentTrackingBot/security/advisories/new).

Please include what you found, how to reproduce it, and its impact. You'll get a reply within 7 days. Fixes for confirmed issues are released as soon as possible and credited in the [changelog](CHANGELOG.md) unless you'd rather stay anonymous.

| Version | Supported |
|---|---|
| 0.2.x (friends mode) | ✅ |
| 0.1.x (single-user MVP) | ❌, please upgrade |

## What the bot stores

| Data | Where | Protection | Retention |
|---|---|---|---|
| Canvas access token | `registry.db` | **Fernet-encrypted** (AES-128-CBC + HMAC-SHA256); key in a separate Docker secret | Until `/disconnect`, `/remove`, or replaced |
| Telegram bot token, encryption key | `secrets/*.txt` on the host → Docker secrets | File mode 600, owned by the container user; never in env vars, logs or the database | Owner-managed |
| Canvas address, time zone, morning time, quiet hours, display name | `registry.db` | Server disk | Until the user leaves |
| Assignment titles, due dates, status, course names, grade weights | `users/<telegram id>.db` (one file per user) | Server disk, readable only by that user's tenant | Items purged 30 days past due |
| Message history (keys, timestamps, item references) | Same per-user file | No message text is stored | 60 days |
| Invite codes | `registry.db` | Only the **SHA-256 hash** is stored; one-time use; 7-day expiry | Kept as a record of use |

**Not stored:** names, emails or IDs from the Canvas profile (only its time zone is read, and only during sign-up), grades or scores, submission contents, or the text of any message.

## Threat model

| # | Threat | Mitigations | Tested by |
|---|---|---|---|
| T1 | **One user reads or changes another user's data** | Separate database file and tenant per user; every update routed by the sender's Telegram ID; button callbacks resolved only in the sender's own file; `/users` exposes sync health only | `test_friends_only_see_and_touch_their_own_items` |
| T2 | **A stranger uses the bot** | Invite-only: one-time 96-bit codes stored as hashes, 7-day expiry, `MAX_USERS` cap; private chats only; unknown users' messages dropped without a reply; owner pairing code limited to 5 tries and 15 minutes | `test_gate_drops_strangers…`, `test_strangers_need_an_invite…` |
| T3 | **A token leaks through the chat** | The message containing a token is deleted at **any** step; the bot says so only if deletion worked; the bot never repeats a token | `test_a_token_pasted_at_any_step_is_deleted`, `test_failed_delete_is_not_claimed` |
| T4 | **A token leaks through logs or errors** | Redaction of known secrets, tokens learned at runtime and token-shaped patterns (in messages, arguments and tracebacks); `httpx`/`httpcore` logs at WARNING; startup errors never echo values | `test_pasted_token_never_leaks`, `test_secrets_never_leak` (sentinel tokens through the whole stack) |
| T5 | **The database is copied** | Tokens are Fernet ciphertext; the key is a separate secret outside the data volume | `test_round_trip_and_ciphertext_hides_the_token`, leak tests scan every `.db` file |
| T6 | **The token is sent somewhere other than Canvas** | Client is GET-only to `/api/v1/` on one pinned host; redirects refused; cross-host pagination refused; HTTPS port 443 only | `test_canvas_client.py` |
| T7 | **The bot is pointed at internal hosts (SSRF)** | IP literals, `localhost`, `.local`/`.internal`/`.lan` and non-443 ports rejected; the host must resolve only to public addresses at sign-up | `test_canvas_url_rejects…`, `test_bad_addresses_are_refused` |
| T8 | **Container escape or tampering** | Non-root UID 10001, read-only root filesystem, `cap_drop: ALL`, `no-new-privileges`, memory cap, no inbound ports | Verified by running the image under `compose.yaml` |
| T9 | **Supply-chain compromise** | `uv.lock` with hashes; base image pinned by digest; GitHub Actions pinned to commit SHAs; `pip-audit` in CI; Dependabot | CI `audit` job |
| T10 | **Lost or replaced encryption key** | Detected at start-up; the owner is told; users are asked to re-paste instead of being told Canvas rejected them; the installer refuses to create a new key while old data exists | `test_wrong_token_key_is_not_reported…` |
| T11 | **One user degrades service for others** | Per-tenant ticks never wait on each other; per-request and per-sync timeouts; concurrent update handling with per-user ordering | `test_slow_friend_does_not_hold_up_the_others` |

### Known limitations

- **The owner can technically read tokens.** Whoever runs the bot holds both the database and the key. Friends are told this plainly during sign-up. A public release would need per-user key wrapping and a hosted key service.
- **DNS rebinding:** the address check runs at sign-up; a host that later re-points to a private address isn't re-checked on every request. Impact is limited: HTTPS with certificate verification, no response content is echoed, and nothing listens inside the container.
- **No rate limit** yet on token attempts or `/sync` per user.
- **Canvas API policy:** asking other people to paste personal tokens into a shared app conflicts with Instructure's API policy (see the [README](README.md#canvas-api-policy)). Friends mode is limited to a small, invite-only beta for that reason.

## If a token leaks

1. **The user:** in Canvas, go to *Account → Settings → Approved Integrations* and delete the token (and any you don't recognize). Then create a new one and paste it via `/settings → 🔑 Canvas token`.
2. **The owner:** if the database **and** `secrets/token_key.txt` may have been copied together, treat every token as leaked. Ask everyone to delete and replace theirs, then rotate the key (stop the bot, back up, generate a new key, and have users re-paste).
3. **A Telegram bot token leak:** send `/revoke` to @BotFather, put the new token in `secrets/telegram_bot_token.txt` and restart.
