#!/usr/bin/env bash
# Install or update the Canvas Assignment Tracker Bot on a Debian/Ubuntu server.
#
#   curl -fsSL https://raw.githubusercontent.com/rmaytr/CanvasAssignmentTrackingBot/HEAD/deploy/install.sh | bash
#
# First run: installs Docker, downloads the bot, asks for your Telegram bot token,
# creates the encryption key and starts the bot. Running it again updates the bot
# and keeps your token, key and everyone's data.
set -euo pipefail

REPO_URL="https://github.com/rmaytr/CanvasAssignmentTrackingBot.git"
DIR="${CANVAS_BOT_DIR:-$HOME/CanvasAssignmentTrackingBot}"
SECRETS="$DIR/secrets"

say() { printf '\n\033[1m%s\033[0m\n' "$*"; }
fail() { printf '\n\033[31m%s\033[0m\n' "$*" >&2; exit 1; }

command -v apt-get >/dev/null || fail "This installer needs Debian or Ubuntu (apt-get)."
[ -r /dev/tty ] || fail "Run this in an interactive terminal (e.g. the SSH button in Google Cloud)."

# Small free servers (1 GB RAM) need some swap to build the image comfortably.
if [ "$(awk '/MemTotal/ {print $2}' /proc/meminfo)" -lt 1500000 ] && [ "$(awk 'NR>1' /proc/swaps | wc -l)" -eq 0 ]; then
  say "Adding 1 GB of swap (this server has little memory)…"
  sudo fallocate -l 1G /swapfile
  sudo chmod 600 /swapfile
  sudo mkswap /swapfile >/dev/null
  sudo swapon /swapfile
  grep -q '^/swapfile ' /etc/fstab || echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab >/dev/null
fi

if ! command -v git >/dev/null || ! command -v curl >/dev/null; then
  say "Installing git and curl…"
  sudo apt-get update -qq
  sudo apt-get install -y -qq git curl >/dev/null
fi

if ! command -v docker >/dev/null; then
  say "Installing Docker (takes a minute or two)…"
  curl -fsSL https://get.docker.com | sudo sh >/dev/null
fi

if [ -d "$DIR/.git" ]; then
  say "Updating the bot's code…"
  git -C "$DIR" pull --ff-only -q
else
  say "Downloading the bot…"
  git clone -q "$REPO_URL" "$DIR"
fi
cd "$DIR"

mkdir -p "$SECRETS"
chmod 700 "$SECRETS"

if ! sudo test -s "$SECRETS/telegram_bot_token.txt"; then
  say "Paste your Telegram bot token from @BotFather (it stays hidden), then press Enter:"
  while true; do
    IFS= read -rs BOT_TOKEN < /dev/tty
    BOT_TOKEN="$(printf '%s' "$BOT_TOKEN" | tr -d '[:space:]')"
    if [[ ! "$BOT_TOKEN" =~ ^[0-9]{5,}:[A-Za-z0-9_-]{30,}$ ]]; then
      echo "That doesn't look like a bot token (it looks like 123456789:ABC…). Try again:"
      continue
    fi
    # The URL goes to curl on stdin, so the token never shows up in the process list.
    if ! ME="$(printf 'url = "https://api.telegram.org/bot%s/getMe"\n' "$BOT_TOKEN" | curl -fsS -K - 2>/dev/null)"; then
      echo "Telegram didn't accept that token. Copy it again from @BotFather and paste it:"
      continue
    fi
    break
  done
  BOT_NAME="$(printf '%s' "$ME" | sed -n 's/.*"username":"\([^"]*\)".*/\1/p')"
  printf '%s' "$BOT_TOKEN" > "$SECRETS/telegram_bot_token.txt"
  unset BOT_TOKEN
  echo "✓ Token works for @${BOT_NAME}."
fi

if ! sudo test -s "$SECRETS/token_key.txt"; then
  if sudo docker volume inspect "$(basename "$DIR" | tr '[:upper:]' '[:lower:]')_data" >/dev/null 2>&1 \
    && [ "${CANVAS_BOT_NEW_KEY:-}" != "yes" ]; then
    fail "secrets/token_key.txt is missing, but the bot already has data. Put the old key back
(from your backup) and run this again. A new key would make every stored Canvas token
unreadable; if you really want that, run again with CANVAS_BOT_NEW_KEY=yes."
  fi
  say "Creating the encryption key for everyone's Canvas tokens…"
  # 32 random bytes, URL-safe base64: the Fernet key format.
  head -c 32 /dev/urandom | base64 | tr '+/' '-_' > "$SECRETS/token_key.txt"
fi

# The bot runs as user 10001 inside its container and must be able to read these.
sudo chown 10001:10001 "$SECRETS"/*.txt
sudo chmod 600 "$SECRETS"/*.txt

[ -f .env ] || cp .env.example .env

say "Building and starting the bot (the first time takes a few minutes)…"
sudo docker compose up -d --build

say "Waiting for the bot to start…"
CODE=""
for _ in $(seq 1 60); do
  LOGS="$(sudo docker compose logs bot 2>/dev/null || true)"
  CODE="$(printf '%s' "$LOGS" | sed -n 's/.*send \/start \([A-Z0-9]\{8\}\) to your bot.*/\1/p' | tail -1)"
  if [ -n "$CODE" ] || printf '%s' "$LOGS" | grep -q '"msg": "started"'; then
    break
  fi
  sleep 3
done

if [ -n "$CODE" ]; then
  say "✅ The bot is running. Claim it as the owner now (the code works for 15 minutes):"
  echo "   Open your bot in Telegram and send:   /start $CODE"
  echo "   The bot then walks you through connecting your own Canvas account."
  echo "   Code expired? Run:  cd $DIR && sudo docker compose restart bot  and run this script again."
elif printf '%s' "${LOGS:-}" | grep -q '"msg": "started"'; then
  say "✅ The bot is running and already has an owner. In Telegram, send /invite to it for a friend link."
else
  say "The bot didn't report in yet. Check it with:  cd $DIR && sudo docker compose logs bot"
fi
