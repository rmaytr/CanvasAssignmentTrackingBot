# Run the personal MVP

This gets the bot running for **you**, with your own Canvas account. It takes
about 15 minutes. Nobody else ever needs your tokens, and you should never
paste them into a chat, an issue or a commit.

## 1. Check that your school allows it

Open Canvas → **Account → Settings** and look for **"+ New Access Token"**. If
the button isn't there, your school blocks student tokens; calendar-feed mode
for that case arrives in v1.0. Using your own token for your own data is the
most defensible setup, but check your school's IT policy if you're unsure.

## 2. Create a Canvas access token

1. Canvas → Account → Settings → **+ New Access Token**.
2. Purpose: `Assignment reminder bot`. Expiry: up to 120 days from today (Canvas's limit for students).
3. Copy the token **once**. Canvas won't show it again.
4. In this folder, save it to a file only you can read:
   ```sh
   mkdir -p secrets && chmod 700 secrets
   printf '%s' 'PASTE-TOKEN-HERE' > secrets/canvas_token.txt && chmod 600 secrets/canvas_token.txt
   ```

The token is as powerful as your password, and it skips Duo/MFA. If it ever
leaks, delete it in Canvas (Account → Settings → Approved Integrations)
**and any other token you don't recognize**.

## 3. Create your Telegram bot

1. In Telegram, message **@BotFather**, send `/newbot`, and pick a name.
2. Save the token it gives you:
   ```sh
   printf '%s' 'PASTE-BOT-TOKEN' > secrets/telegram_bot_token.txt && chmod 600 secrets/telegram_bot_token.txt
   ```
3. Open your new bot in Telegram and press **Start** (a bot can't message you first).

## 4. Configure

```sh
cp .env.example .env
```

Edit `.env`: set `CANVAS_BASE_URL` (your school's Canvas address, e.g.
`https://canvas.yourschool.edu`) and `TIMEZONE` (e.g. `America/Chicago`).
The defaults give an 08:00 digest, reminders every 2 hours in the last 24
hours, and quiet hours from midnight to 08:00.

## 5. Start it

With Docker:

```sh
docker compose up -d --build
docker compose logs bot | grep "pairing code"
```

Without Docker (needs Python 3.13 and [uv](https://docs.astral.sh/uv/)):

```sh
set -a; . ./.env; set +a
export CANVAS_TOKEN_FILE=secrets/canvas_token.txt TELEGRAM_BOT_TOKEN_FILE=secrets/telegram_bot_token.txt DB_PATH=./bot.db
uv run python -m canvas_tracker
```

## 6. Pair and check

1. Find the line `pairing code: send /start XXXXXXXX to your bot` in the log.
2. Send `/start XXXXXXXX` to your bot. It replies "Paired!".
3. Send `/status` to see the last sync, the next digest and the next reminder.

From now on the bot only answers you. If something looks wrong, `/sync`
checks Canvas immediately, and the logs (`docker compose logs bot`) never
contain your tokens.
