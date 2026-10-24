# Host the bot for you and your friends

You set this up **once**, in about 20 minutes. After that, friends join by tapping a
link you send them; they never install anything (see
[`friends-guide.md`](friends-guide.md)).

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
Send that link to **one** friend, together with [`friends-guide.md`](friends-guide.md)
(or the short message at its top). Make a new link for each friend.

Owner commands:

| Command | What it does |
|---|---|
| `/invite` | A new one-time sign-up link |
| `/users` | Who's connected, their school, and whether their Canvas access works (never their assignments) |
| `/remove 3` | Remove user 3 from the `/users` list: the bot asks you to confirm by name, then deletes their data and tells them |

Up to 25 people can sign up; change `MAX_USERS` in `~/CanvasAssignmentTrackingBot/.env`
and run the install command again to apply it.

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

## Keep the key safe

`~/CanvasAssignmentTrackingBot/secrets/token_key.txt` encrypts everyone's Canvas
tokens. If it's lost, the bot can't read the stored tokens: it tells you, and each
person has to paste a token again through `/settings → 🔑 Canvas token`. Nothing else
is lost. The installer refuses to make a new key while old data exists. Don't share
the key, and don't copy it anywhere public.

To back up everything (the key and all data) to your computer, run in Cloud Shell:

```sh
gcloud compute ssh canvas-bot --zone=us-central1-a --command \
  'cd ~/CanvasAssignmentTrackingBot && sudo docker compose stop >/dev/null && sudo tar czf - secrets $(sudo docker volume inspect -f "{{.Mountpoint}}" canvasassignmenttrackingbot_data); sudo docker compose start >/dev/null' > canvas-bot-backup.tgz
```

(It pauses the bot for a few seconds so the copy is consistent.)

then download `canvas-bot-backup.tgz` with Cloud Shell's **⋮ → Download**. Keep it private.

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

To move: back up (above), set up the new machine with the install command, stop the
bot there, copy `secrets/` and the data back into place, and start it.

## Troubleshooting

| Problem | Fix |
|---|---|
| The installer says the bot token isn't accepted | Copy it again from @BotFather (`/mybots` → your bot → *API Token*). |
| The pairing code expired | `cd ~/CanvasAssignmentTrackingBot && sudo docker compose restart bot`, then run the install command again to see the new code. |
| `/start` does nothing | The bot only answers in a private chat with it, not in groups. Check it's running: `sudo docker compose ps` shows `healthy`. |
| The log says a file "can't be read" | Run the install command again; it fixes the file permissions. |
| A friend's token stops working | They get a 🔑 message with steps; they paste a new token via `/settings`. `/users` shows who's affected. |
