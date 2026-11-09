# Joining guide

> For students who got an invite link from whoever runs the bot.

**Short version to send a friend** (with your invite link):

> I set up a Telegram bot that sends you a ranked list of what's due on Canvas every
> morning, and reminds you every 2 hours before anything is due within 24 hours,
> until you submit it. Tap this link (it works once, for 7 days): LINK
> It'll ask for your Canvas address and a Canvas "access token" (it explains how,
> about 2 minutes). Your token is stored encrypted on my server, and /disconnect
> deletes everything.

## What you do (about 2 minutes)

1. **Tap the invite link** and press **Start** in Telegram.
2. **Send your school's Canvas address**: what you see in the browser's address bar
   on Canvas, e.g. `school.instructure.com`.
3. **Make an access token** in Canvas (the bot sends a button that opens the page):
   *Account → Settings → Approved Integrations → + New Access Token*.
   Purpose: `Reminder bot`; for the expiry, pick the latest date Canvas allows.
   Copy the token and **paste it into the chat**. The bot deletes your message right away
   and checks that the token works.
   *No "+ New Access Token" button?* Your school doesn't allow tokens, so the bot can't
   work for you yet.
4. **Pick your time zone** (a button, or type your city), **the time for your morning
   list** (any time up to 8 PM), and **quiet hours** when the bot never messages you.

That's it: "✅ All set!".

## Using it

- **Morning list**: everything due in the next 14 days, ranked by urgency and how
  much of your grade it's worth. Tap ✅ to mark something done that Canvas can't
  see (paper or in-class work).
- **Reminders**: every 2 hours while something is due within 24 hours and not
  submitted. Submitting in Canvas stops them by themselves (within about 10
  minutes). Buttons: ✅ Done, 💤 2h snooze, 🔗 open in Canvas.
- **Announcements and events**: a 📢 message when a course posts an announcement,
  and a 📅 heads-up an hour before a calendar event. They also appear in the morning
  list under *Announcements & events*. They're never treated as homework, so no
  reminders or "overdue" messages.
- **Email (optional, if the person running the bot set it up)**: send
  `/email you@school.edu`, then send back the 6-digit code from the email. You then
  also get the morning list by email, and one email 2 hours before each deadline.
  Assignments due at the same time come in one email. Like reminders, it waits until
  your quiet hours end, and it doesn't come while reminders are paused.
- **Commands** (also in the menu next to the message box):

| Command | What it does |
|---|---|
| `/today` | What's due today, plus anything urgent or overdue |
| `/week` | The next 7 days |
| `/digest` | The morning list, right now |
| `/sync` | Check Canvas right now (once a minute; the bot also checks every 10 minutes) |
| `/pause 3h` | Pause reminders (`30m`, `until 18:00`, `off`) |
| `/settings` | Change time zone, morning time, quiet hours, Canvas token or Canvas address |
| `/email you@school.edu` | Also get the morning list by email, plus a heads-up 2 hours before each deadline (`/email off` stops it) |
| `/disconnect` | Delete everything the bot knows about you |

## Your data

- The bot only **reads** Canvas. It never submits, posts or changes anything.
- Your token is stored **encrypted** on the server of the friend who runs the bot.
  They could technically access it, so only join if you trust them.
- Canvas tokens are as powerful as your password and skip Duo. If you stop using the
  bot, send `/disconnect` **and** delete the token in Canvas (*Account → Settings →
  Approved Integrations*).
- If you turn on email, your address is stored encrypted too, and only after you
  confirm it with the code. `/email off` or `/disconnect` deletes it.
- If Canvas ever rejects the token (for example, it expired), the bot sends a 🔑
  message: make a new token and paste it via `/settings → 🔑 Canvas token`.
