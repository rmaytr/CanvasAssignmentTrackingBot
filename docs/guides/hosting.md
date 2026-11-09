# Hosting guide

> Set up your own copy of the bot for you and your friends.

You set this up **once**, in about 20 minutes. After that, friends join by tapping a
link you send them; they never install anything (see
[`joining.md`](joining.md)).

What you need: a Telegram account, a Google account and a payment card (Google
requires one to verify you; see "Cost" below).

## 1. Create your Telegram bot (2 minutes)

1. In Telegram, open **@BotFather** and send `/newbot`.
2. Pick a display name (e.g. `Canvas Reminders`) and a username that ends in `bot`
   (e.g. `ana_canvas_bot`).
3. BotFather replies with a **token** like `123456789:AAH…`. Keep that chat open;
   you'll paste the token in step 3. Treat it like a password.

## 2. Create a free server on Google Cloud (10 minutes)

1. Go to <https://console.cloud.google.com>, sign in, and accept the terms.
   If it offers the **free trial**, start it (you get $300 of credit for 90 days).
2. Create a project: the project picker at the top → **New project** →
   name it `canvas-bot` → **Create**, then select it.
3. Open **Cloud Shell**: the `>_` icon at the top right. A terminal opens at the bottom.
4. Paste this and press Enter (answer `y` if it asks to enable the Compute API):

   ```sh
   gcloud compute instances create canvas-bot \
     --zone=us-central1-a --machine-type=e2-micro \
     --image-family=debian-12 --image-project=debian-cloud \
     --boot-disk-size=30GB --boot-disk-type=pd-standard
   ```

   This is the always-free machine: an `e2-micro` in a free region, with the free
   "standard" disk. (If you create it by clicking through the console instead, pick
   region `us-central1`, `us-west1` or `us-east1`, machine `e2-micro`, and change the
   boot disk to **Standard persistent disk**; the default "Balanced" disk isn't free.)
5. Connect to it:

   ```sh
   gcloud compute ssh canvas-bot --zone=us-central1-a
   ```

   Press Enter at the questions about an SSH key (no passphrase is fine). You're now
   in a terminal **on your server** (the prompt changes to `…@canvas-bot`).

## 3. Install the bot (one command, about 5 minutes)

On the server, paste:

```sh
curl -fsSL https://raw.githubusercontent.com/rmaytr/CanvasAssignmentTrackingBot/HEAD/deploy/install.sh | bash
```

It installs Docker, downloads the bot and asks for your **bot token** from step 1:
paste it and press Enter (it stays hidden). It then creates the encryption key for
everyone's Canvas tokens, builds the bot and starts it. At the end it prints:

```
Open your bot in Telegram and send:   /start K7M2QX9A
```

## 4. Claim the bot and connect your Canvas (2 minutes)

1. Open your bot in Telegram (search for its username) and send the `/start …`
   line the installer printed. The code works for 15 minutes.
2. The bot says you're the owner and walks you through your own sign-up, the same
   one your friends will see: Canvas address → access token → time zone → morning
   time → quiet hours.

## 5. Invite friends

Send `/invite` to the bot. It replies with a one-time link that expires in 7 days.
Send that link to **one** friend, together with [`joining.md`](joining.md)
(or the short message at its top). Make a new link for each friend.

Owner commands:

| Command | What it does |
|---|---|
| `/invite` | A new one-time sign-up link |
| `/users` | Who's connected, their school, whether their Canvas access works and whether they get email (yes/no; never their assignments or address) |
| `/remove 3` | Remove user 3 from the `/users` list: the bot asks you to confirm by name, then deletes their data and tells them |
| `/health` | How the server is doing: uptime, version, users, the last check, free disk space, email and how many people have sync problems (see *Monitoring*) |

When someone sends `/feedback …`, the bot forwards it to you as a 💬 message with their
Telegram name, ID and @username (never anything from their Canvas). Friends can send
5 an hour, even while still signing up, so a stuck sign-up can reach you. You need to
have messaged the bot yourself for it to reach you.

Up to 25 people can sign up; change `MAX_USERS` in `~/CanvasAssignmentTrackingBot/.env`
and run the install command again to apply it. A sign-up that's left unfinished for 7 days
is cleared automatically (the person is told to ask you for a new link), so it doesn't
keep a spot.

## Day to day

Connect to the server any time with `gcloud compute ssh canvas-bot --zone=us-central1-a`
(in Cloud Shell), or the **SSH** button next to the VM under
*Compute Engine → VM instances*. Then:

| To… | Run on the server |
|---|---|
| Update to the latest version | the same `curl … install.sh \| bash` command as in step 3 |
| See what it's doing | `cd ~/CanvasAssignmentTrackingBot && sudo docker compose logs --tail 50 bot` |
| Restart it | `cd ~/CanvasAssignmentTrackingBot && sudo docker compose restart bot` |
| Stop it | `cd ~/CanvasAssignmentTrackingBot && sudo docker compose stop` |

The bot restarts by itself after a crash or a server reboot. Logs never contain
anyone's tokens.

## Monitoring

The bot watches the server for you and messages you in Telegram when something needs
attention. Each problem is reported at most once a day, and a short ✅ note follows
when it clears. The messages carry only names and Telegram IDs (as `/users` does), never
anyone's assignments, tokens or email addresses.

| ⚠️ Message | What it means | What to do |
|---|---|---|
| Canvas sync for *name* has failed for 6 h | Their school's Canvas can't be reached or answers oddly (not a token problem: those go to the person themselves) | Usually a Canvas outage that fixes itself. If it lasts, check their address in `/users` and ask them. |
| The last 3 emails couldn't be sent | The mail server refuses the bot | See *Optional: email* and the log (`docker compose logs --tail 50 bot`) for the error kind. |
| The data volume is nearly full | Under 200 MB or 5% free on the disk that holds the data | Free space: `sudo docker system prune` removes old images; `df -h` shows what's left. |
| The check for *name* has been running for 10 min | Their Canvas hangs; nobody else is held up | Usually clears by itself. If it keeps coming back, restart the bot. |

You need to have messaged the bot yourself for alerts to reach you (claiming it as the
owner counts). `/health` shows the same picture on demand:

```text
🩺 Health
Version: 0.2.0
Up for: 3 d 4 h
Users: 5 active, 1 signing up (max 25)
Last check: today 9:41 AM (0 m ago)
Disk: 8.2 GB free of 9.7 GB (85%)
Email: set up
Sync problems: none
Open alerts: 0
```

Once an hour the log also gets one `hourly summary` line with counts only (users, messages
sent by kind, failures, sync problems, free disk space), which is handy for
`sudo docker compose logs bot | grep "hourly summary"`. The container's own health check
(`docker compose ps` shows `healthy`) fails if the bot stops checking for 3 minutes.

## Reminder defaults

`.env` holds the reminder rhythm everyone starts with: `REMINDER_INTERVAL_MINUTES`
(120), `REMINDER_WINDOW_HOURS` (24) and `DIGEST_LOOKAHEAD_DAYS` (14). Each person can
choose their own in `/settings → ⏰ Reminders`; a person who never does follows these
defaults, including after you change them.

## Optional: email

People can also get the morning list by email, plus one email 2 hours before each
deadline (`/email you@school.edu` in the chat, confirmed with a code). It works with
any SMTP provider. You need an account with one:

- **Brevo** (free, 300 emails a day). Best with a domain you own: verify the domain
  in Brevo (*Senders, Domains & Dedicated IPs*) so mail isn't marked as spam. Under
  *SMTP & API → SMTP*, create an SMTP key.
  Host `smtp-relay.brevo.com`, port `587`, username = the SMTP login Brevo shows.
- **Gmail** (free, about 500 a day, no domain needed). Make a new Google account for
  the bot, turn on 2-Step Verification, then create an *App password*.
  Host `smtp.gmail.com`, port `587`, username = the Gmail address.

On the server:

```sh
cd ~/CanvasAssignmentTrackingBot
read -rsp "SMTP password or key: " P && printf '%s' "$P" | sudo tee secrets/smtp_password.txt >/dev/null; unset P; echo
nano .env   # fill in SMTP_HOST, SMTP_USERNAME and EMAIL_FROM (see .env.example)
```

Then run the install command again (it fixes file permissions and restarts the bot),
or run `sudo docker compose up -d --force-recreate`. `EMAIL_FROM` must be an address
your provider lets you send from: the Gmail address, or one on your verified domain.

Test it by sending `/email` plus your own address to the bot. If the code doesn't
arrive, check spam, then `sudo docker compose logs --tail 50 bot`. The logs show the
kind of error (for example `SMTPAuthenticationError`) but never addresses or passwords.

## Keep the key safe

`~/CanvasAssignmentTrackingBot/secrets/token_key.txt` encrypts everyone's Canvas
tokens. If it's lost, the bot can't read the stored tokens: it tells you, and each
person has to paste a token again through `/settings → 🔑 Canvas token`. Nothing else
is lost. The installer refuses to make a new key while old data exists. Don't share
the key, and don't copy it anywhere public.

## Back up and restore

To back up everything to your computer, run in Cloud Shell:

```sh
gcloud compute ssh canvas-bot --zone=us-central1-a --command \
  'cd ~/CanvasAssignmentTrackingBot && sudo docker compose stop >/dev/null && sudo tar czf - .env secrets $(sudo docker volume inspect -f "{{.Mountpoint}}" canvasassignmenttrackingbot_data); sudo docker compose start >/dev/null' > canvas-bot-backup.tgz
```

It pauses the bot for a few seconds so the copy is consistent. Then download
`canvas-bot-backup.tgz` with Cloud Shell's **⋮ → Download**.

The archive holds `.env` (your settings), all data, and `secrets/`: the encryption
key, the Telegram bot token and, if you set up email, `secrets/smtp_password.txt`.
Anyone with it can run your bot and read everyone's Canvas tokens, so keep it private
(not in a shared folder or a repository). Make a new one after you change any secret.

To restore, on a fresh server or the same one:

1. Stop the old bot if it still runs (two copies with one bot token fight over messages).
2. Copy `canvas-bot-backup.tgz` to the server's home folder (Cloud Shell: **⋮ → Upload**,
   then `gcloud compute scp canvas-bot-backup.tgz canvas-bot:~ --zone=us-central1-a`).
3. Run the install command from step 3 and paste the same bot token when asked. Ignore
   the pairing code it shows; the restored data already has you as the owner.
4. Put the backup in place and start again:

   ```sh
   cd ~/CanvasAssignmentTrackingBot && sudo docker compose stop
   VOL="$(sudo docker volume inspect -f '{{.Mountpoint}}' canvasassignmenttrackingbot_data)"
   sudo find "$VOL" -mindepth 1 -delete           # the empty data from step 3
   sudo tar xzf ~/canvas-bot-backup.tgz .env secrets   # backups from before this guide: just `secrets`
   sudo tar xzf ~/canvas-bot-backup.tgz -C / "${VOL#/}"
   ```

5. Run the install command once more. It keeps the restored key, fixes file
   permissions and starts the bot; `/health` and `/users` should show everyone again.

## Cost

- **During the 90-day free trial: $0.** The trial credit covers everything.
- **After the trial:** the machine and disk stay free, but since 2024 Google charges
  for the server's public internet (IPv4) address: about **$3.65 a month**. To keep
  running after the trial you must upgrade the account to a paid one (you keep the
  free machine). If you'd rather pay nothing, move the bot before the trial ends:

### $0 alternatives

The same install command works on any always-on Debian or Ubuntu machine:

- **Oracle Cloud "Always Free"**: two small VMs and their public addresses are free
  with no time limit. Create an *Always Free* `VM.Standard.E2.1.Micro` (or Ampere A1)
  instance with Ubuntu, then SSH in and run the install command. **Upgrade the account
  to "Pay As You Go"** (you still pay nothing within the Always Free limits); otherwise
  Oracle may stop instances that look idle, and this bot is idle most of the time.
  Sign-up sometimes rejects cards or has no capacity in a region; try another region.
- **A computer at home that's always on** (an old laptop or a Raspberry Pi 4/5 with
  64-bit Raspberry Pi OS): run the install command in its terminal. It only works
  while that computer is on and online.

To move: back up, then restore on the new machine (see *Back up and restore*).

## Troubleshooting

| Problem | Fix |
|---|---|
| The installer says the bot token isn't accepted | Copy it again from @BotFather (`/mybots` → your bot → *API Token*). |
| The pairing code expired | `cd ~/CanvasAssignmentTrackingBot && sudo docker compose restart bot`, then run the install command again to see the new code. |
| `/start` does nothing | The bot only answers in a private chat with it, not in groups. Check it's running: `sudo docker compose ps` shows `healthy`. |
| The log says a file "can't be read" | Run the install command again; it fixes the file permissions. |
| `/email` says email isn't set up | `SMTP_HOST` is empty in `.env`. See *Optional: email*. |
| `/email` says it couldn't send | Check `SMTP_USERNAME`, `secrets/smtp_password.txt` and `EMAIL_FROM`, then the log for the error kind. |
| A friend's token stops working | They get a 🔑 message with steps; they paste a new token via `/settings`. `/users` shows who's affected. |
| You got a ⚠️ alert from the bot | See *Monitoring* for what each one means; `/health` shows what's still open. |
| No alerts ever arrive | Alerts go to the owner's chat: send the bot any message (e.g. `/health`) so Telegram lets it write to you. |
| `/health` says "Last check" was minutes ago | The tick loop is stuck or restarting: `sudo docker compose ps` and `sudo docker compose logs --tail 50 bot`, then `sudo docker compose restart bot`. |
| The disk is full | `df -h` and `sudo docker system prune` (old images); the bot's data itself stays small. |
| After a restore, the bot says users "couldn't be started" | `secrets/token_key.txt` isn't the one from the backup: restore `secrets` again (step 4 of *Back up and restore*) and run the install command. |
