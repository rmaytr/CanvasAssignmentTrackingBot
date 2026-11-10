# Joining guide

> For students who got an invite link from whoever runs the bot.

**Short version to send a friend** (with your invite link):

> I set up a Telegram bot that sends you a ranked list of what's due on Canvas every
> morning, and reminds you every 2 hours before anything is due within 24 hours,
> until you submit it (you can make that more or less often). Tap this link (it works once, for 7 days): LINK
> It'll ask for your Canvas address and either a Canvas "access token" or your
> Canvas calendar feed link (it explains both, about 2 minutes). Either one is stored
> encrypted on my server, and /disconnect deletes everything.

## What you do (about 2 minutes)

1. **Tap the invite link** and press **Start** in Telegram.
2. **Send your school's Canvas address**: what you see in the browser's address bar
   on Canvas, e.g. `school.instructure.com`.
3. **Connect Canvas**, one of two ways (see *Token or calendar feed?* below):
   - **🔑 Access token (reminders stop by themselves once you submit).** In Canvas (the
     bot sends a button that opens the page): *Account → Settings → Approved Integrations
     → + New Access Token*. Purpose: `Reminder bot`; expiry: 120 days or less, so a leaked
     token can't be used for long (the bot tells you when it stops working). Copy the
     token and **paste it into the chat**.
   - **📅 Calendar feed link (no token; you mark things done yourself).** Tap
     **📅 Calendar feed link instead**, then in Canvas open **Calendar** and tap
     **Calendar Feed** at the bottom right (on a phone, use the browser, not the
     Canvas app). Copy the link, which looks like
     `https://school.instructure.com/feeds/calendars/user_….ics`, and **paste it into
     the chat**. You can also paste it straight away instead of a token.

   Either way the bot deletes your message right away and checks it with Canvas.
   *No "+ New Access Token" button?* Your school doesn't allow tokens: use the calendar
   feed link.
4. **Pick your time zone** (a button, or type your city), **the time for your morning
   list** (any time up to 8 PM), and **quiet hours** when the bot never messages you.

That's it: "✅ All set!". Reminders start at the bot's defaults; change them any time
(see *Reminders* below).

## Token or calendar feed?

| | 🔑 Access token | 📅 Calendar feed link |
|---|---|---|
| Reminders stop when you submit | ✅ by themselves | ❌ tap ✅ Done when you hand something in |
| Due dates, events, 🔗 links | ✅ | ✅ |
| Course announcements (📢) | ✅ | ❌ not in the feed |
| Ranking by share of your grade | ✅ | ❌ ranked by due date and type only |
| Works if your school blocks tokens | ❌ | ✅ |
| What the bot holds | a token as powerful as your password (the bot only uses it to read) | a link that only shows your calendar |

With the calendar feed, the bot can't tell what you've submitted, so it keeps reminding
you about anything due soon until you tap **✅ Done** (in a reminder, the morning list,
or `/today`). That's the whole trade-off. You can switch any time in `/settings`:
**🔑 Canvas token** or **📅 Calendar feed**. The bot forgets the old one once the new
one works.

## Using it

- **Morning list**: everything due in the next 14 days (or 7 or 21), ranked by urgency and how
  much of your grade it's worth. Tap ✅ to mark something done that Canvas can't
  see (paper or in-class work).
- **Reminders**: every 2 hours while something is due within 24 hours and not
  submitted. Submitting in Canvas stops them by themselves (within about 10
  minutes). Buttons: ✅ Done, 💤 2h snooze, 🔗 open in Canvas.
  To change the rhythm, send `/settings` and tap **⏰ Reminders**: repeat every 1, 2,
  3 or 4 hours or not at all, start reminding 12, 24 or 48 hours before work is due
  (the morning list's 🔴 URGENT group stays "due within 24 hours"), and have the morning list cover 7, 14 or 21 days. With **No repeats** you
  still get the morning list and one-off messages (new last-minute work, work due
  overnight, overdue work, the end of a snooze).
- **Announcements and events**: a 📢 message when a course posts an announcement,
  and a 📅 heads-up an hour before a calendar event. They also appear in the morning
  list under *Announcements & events*. They're never treated as homework, so no
  reminders or "overdue" messages.
- **Email (optional, if the person running the bot set it up)**: send
  `/email you@gmail.com`, then send back the 6-digit code from the email. You then
  also get the morning list by email, and one email 2 hours before each deadline.
  A personal address (Gmail, iCloud, Outlook.com) works best: school mail systems
  sometimes silently hold back emails from new senders, even ones you mark as safe.
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
| `/status` | Last sync, whether your token (or calendar feed) works, the next list and reminder, your reminder rhythm, email on or off |
| `/settings` | Change time zone, morning time, quiet hours, reminder rhythm, email, Canvas token, calendar feed or Canvas address |
| `/email you@gmail.com` | Also get the morning list by email, plus a heads-up 2 hours before each deadline (`/email off` stops it) |
| `/feedback your message` | Send a note to the person who runs the bot: a bug, an idea, or that you're stuck (they see your Telegram name and ID, never your Canvas data) |
| `/disconnect` | Delete everything the bot knows about you |

## Your data

- The bot only **reads** Canvas. It never submits, posts or changes anything.
- Your token (or calendar feed link) is stored **encrypted** on the server of the friend
  who runs the bot. They could technically access it, so only join if you trust them.
- The calendar feed link is private, like a password: anyone with it can see your Canvas
  calendar (not your grades or submissions). Don't post it anywhere. The bot deletes it
  from the chat wherever you paste it, and keeps it out of its logs.
- Canvas tokens are as powerful as your password and skip Duo. If you stop using the
  bot, send `/disconnect` **and** delete the token in Canvas (*Account → Settings →
  Approved Integrations*).
- If you turn on email, your address is stored encrypted too, and only after you
  confirm it with the code. `/email off` or `/disconnect` deletes it.
- If Canvas ever rejects the token (for example, it expired), the bot sends a 🔑
  message: make a new token and paste it via `/settings → 🔑 Canvas token`.
- If Canvas stops serving your calendar feed link, the bot sends a 📅 message: copy the
  link again (*Calendar → Calendar Feed*) and paste it via `/settings → 📅 Calendar feed`.
