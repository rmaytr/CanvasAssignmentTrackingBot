# Notification Delivery Channels for a Personal, Self-Hosted Assignment Reminder Bot (state as of Oct 2026)

Research-process caveat for the report writer: this session's network egress blocked direct fetches of most primary vendor sites (core.telegram.org, docs.ntfy.sh, pushover.net, twilio.com, resend.com, support.google.com, grammy.dev all failed with DNS/proxy refusal), and the Context7 docs MCP failed to connect. GitHub-hosted docs/release pages were fetched directly. Everything else comes from web-search result summaries, which sometimes surface official pages (Twilio changelog/support, Pushover support/receipts pages, AWS SES FAQ, ntfy terms) and sometimes only secondary blogs. Each claim notes which kind of source it is. Re-check items marked "verify" before publishing.

Workload assumed throughout: one recipient; one 8 AM digest per day, plus a "due in <24h" reminder every 2 hours per pending assignment. That works out to roughly 30 digests and a few hundred reminders a month, under 1,000 messages/month total. Every free tier below easily covers that volume. Only SMS costs money per message.

## 1. Telegram Bot API: setup, chat_id, buttons/callbacks, polling vs webhooks, formatting, limits, cost, owner-only access, token security, libraries

### Takeaway
Telegram costs nothing and is two-way. Inline keyboard buttons send callback queries back to the bot, which covers "Done" and "Snooze 2h" directly, and long polling (getUpdates) needs no public IP, so it runs fine behind home NAT. The usual pitfalls: answer every callback, escape MarkdownV2 (or use HTML), have the user press /start once (a bot can't message first), and gate every handler on the owner's chat_id/user_id.

### Cited Findings
**Setup and chat_id**
- To prevent spam, a bot cannot start a chat. The user has to open the bot and press Start (or send any message) before the bot can reply. — [advancedweb.hu](https://advancedweb.hu/the-easiest-way-to-set-up-a-chat-with-your-telegram-bot/); [docs.quotesnap.net](https://docs.quotesnap.net/notification/how-to-get-telegram-bot-chat-id)
- The chat_id can be read by calling `getUpdates` with the bot token: it sits at `result[0].message.chat.id` in the returned JSON. If the result comes back empty, sending the bot another message usually makes updates appear. — [docs.quotesnap.net](https://docs.quotesnap.net/notification/how-to-get-telegram-bot-chat-id); [openHAB community](https://community.openhab.org/t/solved-telegram-cant-get-chat-id/43870)

**Cost**
- The Bot API has no per-message fee and no volume tiers. The only cost is the server you host the bot on (secondary source; the official FAQ couldn't be fetched). — [Unipile, "Is the Telegram API Free?"](https://www.unipile.com/is-the-telegram-api-free/)
- An optional paid-broadcast feature (Bot API 7.1) lets a bot send up to 1,000 messages/sec, paid in Telegram Stars. It's irrelevant at single-user scale. — [python-telegram-bot AIORateLimiter docs](https://docs.python-telegram-bot.org/en/v21.8/telegram.ext.aioratelimiter.html)

**Rate limits** (from the official Bot FAQ as quoted by grammY and libraries)
- Per chat: "avoid sending more than one message per second. We may allow short bursts that go over this limit, but eventually you'll begin receiving 429 errors." — [grammY "Flood Limits" (search excerpt)](https://grammy.dev/advanced/flood)
- Per group: no more than 20 messages/minute to the same group. Bulk/global: about 30 messages/second overall. — [grammY flood docs](https://grammy.dev/advanced/flood); [python-telegram-bot AIORateLimiter docs](https://docs.python-telegram-bot.org/en/v21.8/telegram.ext.aioratelimiter.html)

**Inline buttons and callback queries ("Mark done" / "Snooze 2h")**
- `callback_data` on an InlineKeyboardButton is limited to 1–64 bytes. — [grammY types (deno.land)](https://deno.land/x/grammy_types@v3.6.2/markup.ts?source=); [R telegram.bot InlineKeyboardButton docs](https://www.quantargo.com/help/r/latest/packages/telegram.bot/2.4.0/InlineKeyboardButton)
- The client shows a progress indicator on the pressed button until the bot calls `answerCallbackQuery`, so the bot should always answer, even when it has no notification to show. — [R telegram.bot docs](https://www.quantargo.com/help/r/latest/packages/telegram.bot/2.4.0/InlineKeyboardButton.html)
- The common pattern is to answer the callback, then edit the original message in place (e.g., replace the buttons with "Done"). This is a secondary glossary, not the official docs. — [telegramads.it glossary](https://telegramads.it/info/callback-query)
- Bot API 10.3 (2026) reportedly lets bots mark inline buttons as inactive, for example to show a choice already made, and allows buttons inside "Rich Messages". These are Russian-language news reports; no official date was found. — [Skillbox](https://skillbox.ru/media/code/telegram-obnovil-bot-api-do-versii-103/); [Unisender](https://www.unisender.com/ru/blog/news/telegram-vypustil-bolshoe-obnovlenie-chat-botov/)
- Bot API 10.2 was released July 14, 2026, according to a third-party migration guide. — [dev.to Bot API 10.2 guide](https://dev.to/unifyport/telegram-bot-api-102-migration-guide-rich-messages-ephemeral-edits-and-communities-gfe)

**Long polling vs webhooks**
- Webhooks: Telegram sends each update as an HTTPS POST to a registered URL. The only supported ports are 443, 80, 88 and 8443, and a `secret_token` lets the bot verify that requests really come from Telegram. — [aiogram setWebhook source (quotes Bot API docstring)](https://docs.aiogram.dev/en/latest/_modules/aiogram/methods/set_webhook.html)
- getUpdates and webhooks are mutually exclusive: while a webhook is set, getUpdates won't work. — [aiogram setWebhook source](https://docs.aiogram.dev/en/latest/_modules/aiogram/methods/set_webhook.html)
- python-telegram-bot's `run_polling` is "a convenience method for the important use case of running 'just' a single bot". `run_webhook` is the webhook counterpart. — [PTB wiki: Frequently requested design patterns](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Frequently-requested-design-patterns)

**Formatting (MarkdownV2 pitfalls)**
- In MarkdownV2, the characters `_ * [ ] ( ) ~ \` > # + - = | { } . !` must be backslash-escaped, and the backslash itself must be escaped too. Unescaped text fails with a 400 error such as "Bad Request: can't parse entities: Character '+' is reserved and must be escaped with the preceding '\\'". — [ScriptureBot PR #139 (real bug)](https://github.com/julwrites/ScriptureBot/pull/139); [utterstep/telegram-escape](https://github.com/utterstep/telegram-escape); [grammY ParseMode ref](https://grammy.dev/ref/types/parsemode)
- Inside code/pre blocks only `` ` `` and `\` are special. Inside link URLs only `)` and `\` are special. — [telega format docs](https://telega.hexdocs.pm/3.0.0/telega/format.html)

**Owner-only access**
- PTB's recommended pattern: register a `TypeHandler(Update, callback)` in group -1 so it runs before every other handler, check `update.effective_user.id` against an allowlist, and raise `ApplicationHandlerStop` to drop updates from anyone else. For per-command limits, use `filters.Chat` / `filters.User`. — [PTB wiki: Frequently requested design patterns](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Frequently-requested-design-patterns)

**Scheduling inside PTB**
- `JobQueue.run_daily(time, days=...)` and `run_repeating(interval, first, last, chat_id)` cover the 8 AM digest and the 2-hour reminders. A naive `datetime.time` is interpreted in the bot's default timezone, which is UTC unless `Defaults.tzinfo` is set. — [PTB JobQueue docs (stable)](https://docs.python-telegram-bot.org/en/stable/telegram.ext.jobqueue.html); [PTB wiki: JobQueue](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Extensions---JobQueue)
- PTB's persistence doesn't serialize jobs, though APScheduler job stores can be used. Reminders therefore have to be rebuilt from the bot's own database after a restart. — [PTB wiki: JobQueue](https://github.com/python-telegram-bot/python-telegram-bot/wiki/Extensions---JobQueue)

**Token security and revocation**
- If the token leaks, run `/revoke` in @BotFather (or `/mybots` → pick the bot → API Token → Revoke current token). A new token is issued and the old one stops working immediately. — [BotHelp guide](https://help.bothelp.io/en/change-token-telegram-bot); [GitGuardian remediation](https://gitguardian.com/remediation/telegram-bot-token)
- Leaked bot tokens are a recognized secret type that scanners (GitGuardian, DeepSource, Xygeni) detect, so keep the token out of git. — [GitGuardian](https://gitguardian.com/remediation/telegram-bot-token); [DeepSource SCT-1049](https://deepsource.com/directory/secrets/issues/SCT-1049)

**Libraries (versions and maintenance as of Oct 2026)**
- **python-telegram-bot (Python):** v22.8 released 2026-06-12, v22.7 on 2026-03-16, v22.6 on 24 Jan. The 22.8 changelog says "Full Support for Bot API 9.6", but the stable docs list a Bot API constant of 10.0 (conflict, unresolved). — [PTB GitHub releases](https://github.com/python-telegram-bot/python-telegram-bot/releases); [PTB changelog](https://docs.python-telegram-bot.org/en/stable/changelog.html)
- **aiogram (Python, asyncio):** v3.31.0 released 25 Aug (2026) with Bot API 10.3; v3.30.0 on 17 Jul with Bot API 10.2. — [aiogram GitHub releases](https://github.com/aiogram/aiogram/releases)
- **grammY (TypeScript/Deno/Node):** v1.46.0 released 26 Aug (2026) with Bot API 10.3; v1.45.0 on 16 Jul with Bot API 10.2. — [grammY GitHub releases](https://github.com/grammyjs/grammY/releases)
- **Telegraf (TypeScript):** latest release v4.16.3 on 29 Feb (2024, the only recent leap year). The v4.16.0 notes call it "the last major update for Telegraf v4", supported only until February 2025. A v5 was planned, but no newer release appears. — [Telegraf GitHub releases](https://github.com/telegraf/telegraf/releases)

### Inferences
- Long polling is the clear choice for a self-hosted bot behind NAT. getUpdates is an outbound pull, while webhooks need a publicly reachable HTTPS endpoint on 443/80/88/8443 (a tunnel or reverse proxy).
- With one user and well under 1 msg/sec, rate limits are a non-issue. Even sending reminders for several assignments at the same moment won't hit 429 if sends are spaced or batched into one message.
- `callback_data` at 64 bytes fits compact payloads such as `done:<assignment_id>` or `snz:<assignment_id>:2h`, but not full JSON. Canvas assignment IDs are numeric, so they fit easily.
- HTML parse mode is usually the safer choice for text pulled from Canvas (course names and titles full of `-`, `.`, `(`, `!`). This rests on general knowledge that HTML mode needs only `<`, `>`, `&` escaped; the HTML rules weren't verified in this session.
- Library pick: aiogram and grammY are the most current (Bot API 10.3, Aug 2026). PTB is mature with a built-in JobQueue, but its Bot API support lags slightly. Avoid Telegraf for new TypeScript projects.

### Gaps
- Couldn't fetch core.telegram.org directly to confirm the exact current FAQ wording, the 4,096-character message limit, `disable_notification` (silent messages, useful for quiet hours) and the HTML-mode escaping rules. These are widely known but unverified here.
- No official release date for Bot API 10.3.
- python-telegram-bot's exact Bot API level (9.6 vs 10.0) is unresolved.

## 2. Email: Gmail SMTP + App Password vs transactional providers; free tiers, domain verification, deliverability

### Takeaway
For a single recipient, the easiest free email path is the student's own Gmail account sending to itself over SMTP with an App Password (requires 2-Step Verification). It needs no domain and no DNS setup. Transactional providers (Resend, Brevo, SES, etc.) require a domain you control with SPF/DKIM, and SendGrid no longer has a free plan. Email is fine for the 8 AM digest but poor for 2-hourly nags: there are no native buttons, and frequent self-sent mail is easy to tune out or gets filtered.

### Cited Findings
**Gmail SMTP with an App Password**
- Regular-password SMTP no longer works. Personal Gmail needs an App Password (a 16-character code, shown once, requires 2-Step Verification) or OAuth 2.0. — [cli.nylas.com Gmail SMTP 2026](https://cli.nylas.com/guides/gmail-smtp-settings); [smtpedia Gmail settings 2026](https://smtpedia.com/gmail-email-settings-pop3-imap-smtp/); [mailmeteor 2026](https://mailmeteor.com/blog/gmail-smtp-settings)
- "Less Secure Apps" were turned off in stages starting September 30, 2024. For Google Workspace accounts, Google's help page says LSA support ended May 1, 2025, and OAuth is required there. — [WP Mail SMTP](https://wpmailsmtp.com/gmail-less-secure-apps/); [Google Workspace KB](https://knowledge.workspace.google.com/kb/how-to-set-up-gmail-with-apple-mail-000007979); [mailertogo 2026](https://resources.mailertogo.com/guide/gmail-smtp-settings-host-port-authentication)
- App Passwords still work for personal Gmail as of 2026. Google recommends OAuth 2.0 instead and calls app passwords "unnecessary in most cases". Some blogs warn of a phase-out, but no Google deprecation date was found. — [cli.nylas.com](https://cli.nylas.com/guides/gmail-smtp-settings); [Mailbird blog](https://www.getmailbird.com/gmail-oauth-changes-app-password-phase-out/); [warmysender](https://warmysender.com/blog/guides/google-app-passwords-deprecated-what-to-use-instead)
- Settings are smtp.gmail.com on port 587 (STARTTLS) or 465 (SSL/TLS). Free accounts are capped at about 500 messages/day and Workspace at 2,000/day. — [cli.nylas.com](https://cli.nylas.com/guides/gmail-smtp-settings); [tomba.io](https://tomba.io/blog/gmail-smtp-setup)

**Transactional providers: free tiers (2025–2026)**
- **Resend:** free plan of 3,000 emails/month capped at 100/day, 1 verified domain. When the cap is hit, sending pauses with no surprise charges. Pro is $20/month for 50,000 emails. Log retention is quoted as 1 day in a 2025 source and 30 days in 2026 sources (verify). — [Resend blog "New free tier"](https://resend.com/blog/new-free-tier); [WP Mail SMTP Resend review 2026](https://wpmailsmtp.com/resend-review/); [userjot 2025](https://userjot.com/blog/resend-pricing-in-2025)
- **SendGrid:** Twilio ended the free Email API plan on May 27, 2025. New accounts get a 60-day trial at 100 emails/day, after which sending halts until you pay. — [SendGrid (Wikipedia)](https://en.wikipedia.org/wiki/SendGrid); [dreamlit.ai](https://dreamlit.ai/blog/best-sendgrid-alternatives)
- **Brevo:** free plan of 300 emails/day, described as permanent. — [Mailjet comparison](https://www.mailjet.com/comparisons/sendgrid-alternatives/); [mailercloud](https://www.mailercloud.com/blog/sendgrid-alternatives)
- **Postmark:** free allowance of 100 emails/month (not per day). — [agentdeals.dev](https://agentdeals.dev/email-service-alternatives)
- **Mailgun:** contested. One source lists a free 100/day plan; another lists the free tier as trial only (verify). — [agentdeals.dev](https://agentdeals.dev/email-service-alternatives); [Omnivery](https://omnivery.com/alternatives/sendgrid-alternative)
- **Mailjet:** 6,000/month with a 200/day cap. **MailerSend** cut its free plan from 3,000 to 500 emails/month in October 2025. — [agentdeals.dev](https://agentdeals.dev/email-service-alternatives); [Mailjet comparison](https://www.mailjet.com/comparisons/sendgrid-alternatives/)
- **Amazon SES:** 3,000 free message charges/month for the first 12 months. Since July 15, 2025, new AWS customers also get up to $200 in Free Tier credits (6-month free plan). New accounts start in a sandbox that can only send to verified identities, which is fine when the only recipient is yourself. The sandbox caps of 200/day and 1/sec come from third-party sources. — [AWS SES FAQ](https://aws.amazon.com/ses/faqs/); [oneuptime SES verify guide 2026](https://oneuptime.com/blog/post/2026-02-12-verify-email-addresses-amazon-ses/markdown)

**Deliverability rules**
- Gmail sender guidelines: all senders need at least SPF or DKIM, valid reverse DNS, TLS, and low complaint rates. Senders of 5,000+ messages/day to Gmail must also have SPF + DKIM + DMARC and one-click unsubscribe. Since around November 2025 Gmail rejects non-compliant mail with 550 errors instead of deferring it (secondary sources). — [mailreach 2026](https://www.mailreach.co/blog/gmail-sender-guidelines); [egressif](https://egressif.io/resources/sender-requirements/gmail); [Oxford IT blog](https://blogs.it.ox.ac.uk/nexus/640); [BleepingComputer](https://www.bleepingcomputer.com/news/google/google-now-blocks-spoofed-emails-for-better-phishing-protection/)

### Inferences
- Gmail self-send through smtp.gmail.com is authenticated by Google itself (SPF/DKIM for gmail.com), so the student needs no domain and spam-folder risk is minimal. The 500/day cap is far above the needs here (around 15/day max).
- Resend/Brevo/SES all need the student to own a domain and add SPF/DKIM (plus DMARC as good practice) DNS records. That's an extra cost (a domain is around $10/year; not researched here) and setup a student probably doesn't need when Gmail SMTP works.
- Resend's 100/day cap isn't a constraint (well under 20/day here). SendGrid should be excluded.
- Every-2-hours email to the same inbox works technically, but threads pile up and phone mail apps often batch or silence notifications. Email suits the daily digest and a fallback copy, not the primary nag channel.
- Email can only be "interactive" through links (e.g., `https://bot.example/done?id=…&sig=…`), which need a publicly reachable endpoint. That breaks the "behind NAT, no public server" simplicity Telegram long polling offers.

### Gaps
- No primary Google page was fetched to confirm the current App Password requirements text or the 500/day limit (support.google.com was blocked).
- No official current pricing pages were fetched for Brevo, Postmark, Mailgun or Mailjet; figures come from comparison blogs.
- No data was found on how Gmail treats frequent self-addressed automated mail (e.g., whether it auto-categorizes or suppresses notifications).

## 3. SMS/text: how bots send SMS, number costs, US A2P 10DLC and toll-free verification (2024–2026), carrier email-to-SMS gateways, international differences

### Takeaway
To send SMS, a bot rents a phone number from a CPaaS provider (Twilio, Telnyx, Plivo, Vonage) and calls its API. Since February 2025, US carriers block unregistered 10DLC traffic, so even a hobbyist must register a Sole Proprietor brand and campaign or verify a toll-free number. That means fees, a privacy policy and terms URLs, and 1–3 weeks of lead time. The free carrier email-to-SMS gateways are effectively dead (T-Mobile late 2024, AT&T June 17 2025, Verizon announced for March 31 2027 and already unreliable). For a no-budget student, SMS isn't worth it compared with free push apps.

### Cited Findings
**How it works and what it costs (US, Twilio)**
- Twilio US outbound SMS costs about $0.0079–$0.0083 per segment (sources disagree; one checked $0.0083 on Sep 4, 2026). A local number is about $1.15/month and a toll-free number about $2.00/month. — [textbee.dev Twilio cost breakdown](https://textbee.dev/blog/twilio-pricing-real-cost-breakdown); [automationatlas 2026](https://automationatlas.io/answers/twilio-pricing-explained-2026/); [zavu.dev](https://www.zavu.dev/en/blog/twilio-sms-pricing)
- Carriers add pass-through fees per outbound 10DLC message: about $0.0035 AT&T and $0.0045 T-Mobile/Verizon. The all-in cost is roughly $0.011–$0.013 per message. — [textbee.dev](https://textbee.dev/blog/twilio-pricing-real-cost-breakdown); [sociocs 10DLC explainer](https://www.sociocs.com/post/twilio-10dlc-explained/)
- **Telnyx** charges about $0.004/message part plus carrier fees, with numbers from $1.00/month. **Plivo** quotes vary ($0.005–$0.0077/message), numbers around $0.50/month, and 10DLC brand $4.50 plus a campaign fee of $10/month billed quarterly. — [Knock benchmark Plivo vs Telnyx](https://knock.app/sms-api-benchmarks/compare/plivo-vs-telnyx); [CloudTalk Telnyx pricing](https://www.cloudtalk.io/blog/telnyx-pricing/); [prospeo Plivo review 2026](https://prospeo.io/s/plivo-pricing-reviews-pros-and-cons)

**A2P 10DLC registration (US long codes)**
- Carriers began blocking all unregistered 10DLC traffic in early February 2025 (Feb 1 per most sources, Feb 3 per Telnyx), and a 2026 guide says the block still applies. — [FreePBX community](https://community.freepbx.org/t/reminder-unregistered-10dlc-to-be-blocked-as-of-feb-1st-2025/103057); [Telnyx 10DLC FAQ](https://support.telnyx.com/en/articles/3679260-frequently-asked-questions-about-10dlc); [dev.to 2026 guide](https://dev.to/alfredo_romero_fc4afdcb68/a2p-10dlc-survival-guide-for-voice-agencies-2026-carrier-filtering-is-now-real-time-29mp)
- **Sole Proprietor brand** (for individuals or businesses without a tax ID/EIN): one-time brand fee of $4.50 per Twilio support ($4 per another Twilio page), $15 one-time campaign vetting, and about $2/month per campaign ($1.50–$10 depending on use case). Limits: 1 campaign, 1 phone number, 1,000 messages/day. A business that has an EIN must register as Low-Volume or Standard instead. — [Twilio support article](https://support.twilio.com/hc/en-us/articles/1260803965530); [Twilio 10DLC overview](https://pages.twilio.com/10DLC-HelpArticles-WW); [Twilio A2P 10DLC brand docs](https://www.twilio.com/docs/trust-hub/registrations/a2p-10dlc-brand)
- 10DLC registration adds roughly 1–3 weeks before a new US sender number works, and failed registrations still cost money. — [textbee.dev](https://textbee.dev/blog/twilio-pricing-real-cost-breakdown)

**Toll-free verification**
- Twilio toll-free numbers can't send SMS to the US/Canada until toll-free verification is complete. Verification requires a paid (non-trial) account and a Compliance Profile. — [Twilio TF console onboarding](https://www.twilio.com/docs/messaging/compliance/toll-free/console-onboarding); [Twilio TF API onboarding](https://www.twilio.com/docs/messaging/compliance/toll-free/api-onboarding); [Twilio TF Onboarding Guide](https://support.twilio.com/hc/en-us/articles/13264118705051-Toll-Free-Verification-Onboarding-Guide)
- Since February 17, 2026, a Business Registration Number (e.g., a 9-digit EIN) is required on all new toll-free submissions except sole proprietorships. Since September 15, 2026, privacy-policy and terms-and-conditions URLs are required on all new submissions. — [Twilio changelog: BRN required](https://www.twilio.com/en-us/changelog/business-registration-numbers-required-for-toll-free-messaging-p); [Twilio changelog: privacy policy/T&C](https://www.twilio.com/en-us/changelog/toll-free-verification-now-requires-privacy-policy-and-terms-and)
- Sources conflict on unverified traffic: Twilio's docs say unverified toll-free numbers can't send, while a June 2026 consultancy says pending numbers can send but face aggressive filtering. — [Twilio TF console onboarding](https://www.twilio.com/docs/messaging/compliance/toll-free/console-onboarding); [Telphi Consulting](https://www.telphiconsulting.com/blog/twilio-toll-free-verification-cost)

**Carrier email-to-SMS gateways**
- **AT&T** (`@txt.att.net`, also Cricket) shut down on June 17, 2025, in both directions. — [Princeton SCAD IT notice](https://scad.princeton.edu/news/att-discontinues-email-text-and-text-email-service); [SignalWire](https://signalwire.com/blog/att-ending-email-to-text); [Suped](https://www.suped.com/knowledge/email-deliverability/troubleshooting/what-to-do-when-experiencing-issues-sending-email-to-sms-texts-via-att)
- **T-Mobile** (`@tmomail.net`) reportedly stopped in Nov–Dec 2024 with no formal announcement. — [sigspan gateway status 2026](https://sigspan.com/carrier-gateway-shutdown); [TextBolt Verizon migration table](https://textbolt.com/migration/verizon/)
- **Verizon** (`@vtext.com`, `@vzwpix.com`) has a formal notice of permanent shutdown on March 31, 2027, but the gateway is already unreliable: messages are blocked, filtered or silently dropped. One outlier source claims a June 2025 retirement, which looks like an error. — [sigspan Verizon](https://sigspan.com/verizon-email-to-text-gateway); [ourcodeworld](https://ourcodeworld.com/articles/read/3339/verizon-vtext-shutdown-what-it-teams-are-using-now); conflicting: [emailontext.com](https://emailontext.com/guides/carrier-email-to-text-shutdown)
- Bell (Canada) has also shut down its email-to-SMS gateway. — [TextBolt Bell](https://textbolt.com/blog/bell-email-to-sms-alternative)

**International differences**
- **India:** DLT registration with TRAI (sender ID plus pre-approved templates, tax IDs such as GSTIN/PAN) is required. — [AWS End User Messaging India sender ID](https://docs.aws.amazon.com/sms-voice/latest/userguide/registrations-sms-senderid-india.md); [Plivo compliance FAQ](https://plivo.com/docs/faq/messaging/messaging-compliance)
- **US/Canada:** alphanumeric sender IDs aren't supported, so you need a 10DLC, toll-free or short-code number. — [Telnyx international SMS compliance](https://developers.telnyx.com/docs/messaging/messages/international-sms-compliance); [Plivo compliance FAQ](https://plivo.com/docs/faq/messaging/messaging-compliance)
- **UK:** alphanumeric sender IDs are generally usable. Sources disagree on whether pre-registration is recommended or required (1–2 weeks). — [Telnyx](https://developers.telnyx.com/docs/messaging/messages/international-sms-compliance); [EnableX SMS regulations](https://developer.enablex.io/messaging/sms-regulatory.html)

### Inferences
- Rough US cost for this bot on Twilio with Sole Proprietor 10DLC: about 300–400 messages/month × ~$0.012 ≈ $4–5, plus a $1.15 number and about $2 campaign fee, so roughly $7–8/month, plus about $19.50 one-time (brand + vetting). That's small but not zero, and it adds registration paperwork (privacy policy/terms pages, sample messages, opt-in description) and weeks of lead time, for a channel with no free interactive buttons (replies would have to be parsed as "DONE 3" keywords).
- A sole proprietor can still register in 2026, but registration is built for businesses. A one-user personal reminder campaign may face vetting friction (inference; no source documents rejections of personal-use campaigns).
- Email-to-SMS gateways shouldn't be used: only Verizon's partly works, and it ends in March 2027.
- SMS's one real advantage is that it works without any app or data connection. For a student with a smartphone, a free push channel beats it on cost, setup and interactivity.

### Gaps
- No official Twilio pricing page was fetched (blocked), so the base rate is $0.0079 vs $0.0083 (unresolved) and the exact current Sole Proprietor fee is $4 vs $4.50 (unresolved).
- Twilio trial-account limits (e.g., sending only to verified numbers, "Sent from a Twilio trial account" prefix) weren't verified this session.
- No source found on whether TCR/Twilio approves single-recipient personal-use Sole Proprietor campaigns.
- Vonage pricing wasn't researched.
- textbee.dev markets using your own Android phone as an SMS gateway with "no 10DLC registration" ([textbee.dev US](https://textbee.dev/sms-pricing/twilio/us)), but its terms and reliability weren't evaluated.

## 4. Push-notification services and chat platforms: ntfy, Pushover, Gotify, Discord, Slack, WhatsApp Cloud API, Signal

### Takeaway
ntfy (free, open source, self-hostable, Android/iOS/web, priorities, up to 3 action buttons) and Pushover ($4.99 one-time per platform, 10,000 free messages/month, emergency priority with acknowledgment receipts) are the strongest dedicated push options. Discord works but needs a bot (not a webhook) for DMs and interactive buttons. WhatsApp Cloud API and Signal (signal-cli) are poor fits for a hobbyist because of business onboarding and unofficial-client fragility, respectively. Gotify has no first-party iOS app.

### Cited Findings
**ntfy**
- Publishing is a plain HTTP PUT/POST to a topic URL. Priorities run 1–5: 5 = "really long vibration bursts, default notification sound with a pop-over notification", 4 = long vibration + pop-over, 3 = default, 2 = no sound/vibration (visible only when the drawer is pulled down), 1 = no sound, under "Other notifications". — [ntfy docs: publish.md (GitHub)](https://github.com/binwiederhier/ntfy/blob/main/docs/publish.md)
- Up to three action buttons per notification:
  - `view` (open a URL/app; Android, Apple, Firefox)
  - `http` (send an HTTP request, POST by default, with custom method/headers/body; Android, Apple, Firefox; `clear=true` dismisses the notification only if the request succeeds)
  - `broadcast` (Android intent, Android only)
  - `copy` (Android/Firefox)

  — [ntfy docs: publish.md](https://github.com/binwiederhier/ntfy/blob/main/docs/publish.md)
- Markdown formatting (`X-Markdown: true`) is supported on Android and Firefox. — [ntfy docs: publish.md](https://github.com/binwiederhier/ntfy/blob/main/docs/publish.md)
- Scheduled/delayed delivery uses `X-In` (relative) and `X-At` (absolute) headers, accepting a minimum of 10 seconds and a maximum of 3 days (per a third-party skill doc; verify on docs.ntfy.sh). v2.29.0 (7 Oct 2026) added timezone support (`X-Timezone`) and RFC 3339 timestamps for delayed notifications. — [secluded.site ntfy skill doc](https://git.secluded.site/agent-skills/blob/main/skills/notifying-through-ntfy/SKILL.md?raw=1); [ntfy GitHub releases](https://github.com/binwiederhier/ntfy/releases)
- Active maintenance: v2.31.0 (15 Oct 2026, fixes messages lost on client reconnect), v2.30.0 (12 Oct 2026), v2.29.0 (7 Oct 2026). — [ntfy GitHub releases](https://github.com/binwiederhier/ntfy/releases)
- **Topic security on ntfy.sh:** without access controls, "your topic name functions as a password" (official terms). Reserved topics and access control on ntfy.sh are paid features. — [ntfy Terms](https://docs.ntfy.sh/terms/); [toolradar ntfy pricing](https://toolradar.com/tools/ntfy/pricing)
- **ntfy.sh tiers** (third-party; verify): Free with rate limits, about 250 messages/day per one plugin's docs. Supporter around $5–6/month. Pro $12/month (or $10/month billed annually) with 20,000 messages/day, 10 reserved topics, 20 phone calls, 250 emails/day and 250 MB attachments. — [toolradar ntfy pricing](https://toolradar.com/tools/ntfy/pricing); [Checkmk ntfy plugin](https://exchange.checkmk.com/p/ntfy-plugin)
- **Self-hosted access control:**
  - `auth-file` (SQLite), with `auth-default-access` set to `deny-all` for a private server.
  - `ntfy user add`, plus `ntfy access USER TOPIC rw|ro|wo|deny` ACLs with `*` wildcards.
  - Access tokens via `ntfy token add` (prefix `tk_`, up to 60 per user). Tokens currently grant full account access rather than per-topic access.
  - Publishers can authenticate with HTTP Basic auth or a Bearer token.

  — [ntfy docs: config.md (GitHub)](https://github.com/binwiederhier/ntfy/blob/main/docs/config.md); [secluded.site skill doc (Bearer)](https://git.secluded.site/agent-skills/blob/main/skills/notifying-through-ntfy/SKILL.md?raw=1)
- **iOS caveat when self-hosting:** because of iOS background limits, a self-hosted server must set `upstream-base-url: "https://ntfy.sh"`. It then forwards only a message ID and a topic-URL hash to ntfy.sh/APNs, and the app fetches the content from your server. Without this, iOS delivery "can take hours". — [ntfy docs: config.md](https://github.com/binwiederhier/ntfy/blob/main/docs/config.md)
- Default self-hosted rate limits: a burst of 60 requests per visitor, replenishing 1 every 5 s; 30 subscriptions; email burst of 16, replenishing 1 per hour. — [ntfy docs: config.md](https://github.com/binwiederhier/ntfy/blob/main/docs/config.md)

**Pushover**
- Individual pricing is a $4.99 one-time purchase per platform (iOS/iPadOS, Android, Desktop), with no subscription and a free 30-day trial per platform. Teams cost $5/user/month. — [Pushover pricing](https://pushover.net/pricing); [Pushover support: cost](https://support.pushover.net/i8-cost); [Pushover blog: 30-day trial](https://blog.pushover.net/posts/2021/2/free-trial-now-30-days-instead-of-7)
- Sending allowance: 10,000 free messages/month (25,000 for Team apps), resetting at midnight US Central on the 1st. Extra capacity starts at 10,000 messages for $50, and an exhausted quota returns errors (HTTP 429 per a third-party client). A blog quoting a Pushover post says the limits become per-account instead of per-application from May 1, 2026, and Pushover support pages show both wordings (verify). — [Pushover support: limits](https://support.pushover.net/i12-message-size-and-frequency-limitations); [Pushover support: extra capacity](https://support.pushover.net/i13); [deuts.org](https://deuts.org/p/pushover-api-limit/); [Pushover.NET README](https://github.com/msawyer91/Pushover.NET)
- **Emergency priority (2):**
  - Repeats the alert every `retry` seconds (minimum 30) until acknowledged or until `expire` passes. The maximum `expire` is 10,800 s (3 h) per newer docs; older wrappers say 86,400 s (conflict).
  - The API returns a `receipt` you can poll for acknowledged/expired status.
  - An optional `callback` URL receives a POST when the user acknowledges, retried after 1 minute on a non-2xx response.
  - A cancel endpoint stops the retries.

  — [Pushover Receipts & Callbacks API](https://pushover.net/api/receipts); [Pipedream Pushover emergency action](https://pipedream.com/apps/pushover/actions/emergency-push-notification); [pushoverr R docs](https://cran.r-project.org/web/packages/pushoverr/refman/pushoverr.html); [PushoverForPS](https://www.powershellgallery.com/packages/PushoverForPS/1.2/Content/PushoverForPS.psm1)

**Gotify**
- Self-hosted only. The official Android app is solid, but there's no first-party iOS app; iOS users rely on the third-party iGotify app, which needs a separate assistant/plugin. — [jacar.es](https://jacar.es/?p=4229); [selfhostyourself](https://www.selfhostyourself.com/services/gotify); [iGotify App Store](https://apps.apple.com/app/igotify/id6473452512)

**Discord**
- Webhooks are rate-limited at about 5 requests per 2 seconds per webhook (another source says 5 per 5 s). Webhooks can't DM users; DMs need a bot token. — [Hookdeck Discord webhooks guide](https://hookdeck.com/webhooks/platforms/guide-to-discord-webhooks-features-and-best-practices.md); [cybrancee](https://cybrancee.com/blog/discord-webhooks-explained-what-they-can-and-cant-do/)
- Buttons in webhook messages are non-interactive unless the webhook is application-owned and `with_components=true` is set. Click events go to the application, not the webhook. — [cybrancee](https://cybrancee.com/blog/discord-webhooks-explained-what-they-can-and-cant-do/); [Hookdeck](https://hookdeck.com/webhooks/platforms/guide-to-discord-webhooks-features-and-best-practices.md)

**WhatsApp Cloud API**
- On July 1, 2025, Meta switched from per-conversation billing to per-delivered-template billing. Messages inside the 24-hour customer-service window (including utility templates) are free; outside it, utility templates are billed by country, about $0.004 per message in the US. One source says free-form replies will be metered from Oct 1, 2026 (unverified). — [YCloud](https://www.ycloud.com/blog/whatsapp-api-pricing-update); [Authgear 2026](https://www.authgear.com/post/whatsapp-api-pricing/); [Spur 2026](https://www.spurnow.com/en/blogs/whatsapp-business-api-pricing-explained)

**Signal (signal-cli, unofficial)**
- signal-cli registration and sending can hit 429 rate limits and "proof required" CAPTCHA challenges (one user reported a 24-hour wait), which have to be solved by hand at signalcaptchas.org and submitted with `submitRateLimitChallenge`. Signal Support won't help with signal-cli. — [Healthchecks.io blog](https://blog.healthchecks.io/hp-rewrite/4729aced94ebc929baf36eba9b9eca5c); [Zabbix forum](https://www.zabbix.com/forum/zabbix-help/478771-zabbix-and-signal-cli-for-media-notification); [gist](https://gist.github.com/szepeviktor/2c6a19cb91c4bb561369707f22bcf413)

### Inferences
- ntfy is the best free dedicated push app: you can stay on ntfy.sh free with an unguessable topic name, or self-host with `deny-all` plus tokens. Its "Done"/"Snooze" `http` actions are sent from the phone, so the target URL must be reachable from the phone's network. A bot behind home NAT would need a tunnel or reverse proxy, unlike Telegram callbacks, which come back through Telegram's servers to a polling bot. One workaround is to point the `http` action at another ntfy topic that the bot subscribes to over an outbound connection. That pattern is inferred from ntfy's design and not tested or documented in the sources.
- Pushover's emergency priority is built for "nag until acknowledged", but the 3-hour expire cap and 30-second minimum retry mean it repeats within minutes rather than every 2 hours across a day. Use it for the final "due in <3h" escalation, and let the bot's own scheduler handle 2-hourly reminders. It costs $4.99 once per platform after the trial, which a $0 budget may rule out.
- Discord is viable only if the student already lives in Discord. It needs a full bot application (gateway connection, intents) for DMs and buttons, which is more work than Telegram for the same result.
- WhatsApp requires Meta Business onboarding and template approval (business-verification specifics weren't verified this session). That's overkill for one user.
- Signal via signal-cli needs a dedicated phone number for the bot plus unpredictable CAPTCHA interventions. It's not reliable enough to depend on for deadlines.

### Gaps
- **Slack:** incoming webhooks and free-plan limits weren't researched this session.
- **WhatsApp:** the exact business-verification, test-number and display-name requirements for a personal developer weren't confirmed from Meta docs.
- **ntfy:** official ntfy.sh free-tier daily limits and the exact delay limits couldn't be confirmed from docs.ntfy.sh, and iOS support for `http` actions from the lock screen wasn't verified in detail.
- **Pushover:** whether emergency-priority messages count differently against quota, and the per-account change, are unconfirmed.

## 5. Abstraction libraries for multi-channel sending (Apprise, Novu, ntfy as hub)

### Takeaway
Apprise (Python, BSD-2-Clause, actively maintained: v2.0.1 in Oct 2026) sends to 100+ services through one URL syntax (`tgram://`, `ntfys://`, `pover://`, `mailto://`, Twilio, Signal, Discord…). It's one-way only, so it suits fan-out (e.g., also email the digest) but can't handle Telegram button callbacks. Novu wasn't researched.

### Cited Findings
- Apprise is "Push Notifications that work with just about every platform!": a Python library plus CLI that uses a single URL format. Its tables list well over 100 services, including Telegram, Discord, Slack, Amazon SNS, Gotify, Signal, ntfy, Pushover, email and Twilio SMS. — [caronc/apprise GitHub](https://github.com/caronc/apprise)
- URL examples are `tgram://bottoken/ChatID`, `ntfy://topic/` (`ntfys://` for HTTPS), `pover://user@token` and `mailto://userid:pass@domain.com`. CLI usage looks like `apprise -t "title" -b "body" "tgram://…"`. A separate `apprise-api` project provides a web/API server. The license is BSD-2-Clause. — [caronc/apprise GitHub](https://github.com/caronc/apprise)
- Releases: v2.0.1 (3 Oct), v2.0.0 (26 Sep), v1.13.1 (31 Aug). The year isn't shown, but the sequence is consistent with 2026. — [Apprise releases](https://github.com/caronc/apprise/releases)
- The README describes outbound notifications only, with no buttons or replies. — [caronc/apprise GitHub](https://github.com/caronc/apprise)

### Inferences
- A sensible architecture: use a native Telegram library (aiogram/PTB) for the interactive primary channel, and optionally Apprise for one-way fallbacks (email digest, ntfy), so users can add channels by pasting an Apprise URL into config.
- ntfy can also act as a hub, since it can forward to email (`X-Email`, and v2.30.0 added SMTP LOGIN auth). Apprise is the more general fan-out tool.
- The year on the Apprise release dates (v2.0.x Sept/Oct) is inferred to be 2026 from ordering. Verify on PyPI.

### Gaps
- Novu (open-source notification infrastructure) wasn't researched. Its current self-hosting footprint and free cloud tier are unknown here.
- Apprise's exact service count and Python version support weren't extracted.

## 6. Native "repeat until acknowledged" and interactive acknowledgement support

### Takeaway
Only Pushover offers server-side "repeat until acknowledged" (emergency priority, with receipts and an ack callback), and it's capped at a 3-hour window. Telegram (inline keyboard → callback query) and ntfy (`http` action buttons) both support one-tap acknowledgement, but the bot has to implement the repeat-every-2-hours loop itself. Email and SMS have no native ack beyond links or reply keywords.

### Cited Findings
- **Pushover:** emergency priority repeats every `retry` seconds (minimum 30) until acknowledged or until `expire` passes (maximum 10,800 s per newer docs). The receipt API reports acknowledged/expired status, the callback URL receives a POST on acknowledgment, and a cancel endpoint stops the retries. — [Pushover Receipts & Callbacks](https://pushover.net/api/receipts); [Pipedream](https://pipedream.com/apps/pushover/actions/emergency-push-notification)
- **Telegram:** inline button presses arrive as callback queries carrying up to 64 bytes of `callback_data`. The bot must call `answerCallbackQuery` and can edit the message afterward. — [R telegram.bot docs](https://www.quantargo.com/help/r/latest/packages/telegram.bot/2.4.0/InlineKeyboardButton.html); [grammY types](https://deno.land/x/grammy_types@v3.6.2/markup.ts?source=)
- Bot API 10.3 reportedly adds the ability to mark inline buttons inactive, for example to show "Done" was already pressed. — [Skillbox](https://skillbox.ru/media/code/telegram-obnovil-bot-api-do-versii-103/)
- **ntfy:** `http` action buttons send a configurable request on tap, and `clear=true` removes the notification only if the request succeeds. Up to 3 actions are allowed per notification. — [ntfy docs: publish.md](https://github.com/binwiederhier/ntfy/blob/main/docs/publish.md)
- **SMS/email:** no native button mechanism was documented in the sources reviewed.

### Inferences
- **Telegram bot design:**
  - Every reminder carries `[✅ Done] [⏰ Snooze 2h] [Open in Canvas]` (the last as a URL button).
  - "Done" records completion and stops future reminders for that assignment.
  - "Snooze 2h" shifts the next send.
  - Editing the original message (or sending a fresh one each cycle and deleting or editing the old one) keeps the chat clean.
- For the hardest deadlines, an optional Pushover emergency alert or an ntfy priority 5 notification in the last 2–3 hours adds a stronger interrupt. This is an optional escalation tier.
- Completion state should also be cross-checked against Canvas submission status so the user doesn't have to tap "Done" for submitted work. This depends on the Canvas API research handled elsewhere.

### Gaps
- Whether iOS ntfy supports `http` actions from the lock screen without opening the app wasn't verified.
- Telegram's exact editMessageReplyMarkup and deleteMessage constraints (e.g., the 48-hour delete window) weren't verified this session.

## 7. Quiet hours, do-not-disturb, and notification-fatigue evidence

### Takeaway
Research on mHealth and medication reminders consistently finds habituation and fatigue when similar notifications repeat. Higher frequency often doesn't improve adherence, and patients rate high message frequency poorly. For a 2-hourly "due soon" nag, the bot should enforce quiet hours, consolidate multiple assignments into one message, escalate only near the deadline, and stop immediately on "Done" or on detected submission.

### Cited Findings
- mHealth notifications "are often ignored by users, either due to appearing at inopportune moments or leading to habituation (i.e., decreased response to repeated stimulation) over time". Responsiveness and interest drop as more notifications arrive, "especially if the content was similar". — [CHI 2024, Investigating Contextual Notifications… (ACM)](https://dl.acm.org/doi/full/10.1145/3613904.3641993); [PDF](https://www.ruizlab.org/wp-content/uploads/2024/10/3613904.3641993.pdf)
- A systematic review of SMS medication-adherence interventions found reminders sent once or more per day had a smaller effect than less frequent ones, and most patients preferred two messages per week. The review attributes this to habituation, response fatigue and the intrusiveness of multiple daily messages. In one study, message frequency got the lowest satisfaction score ("too high"). — [PMC4939231](https://pmc.ncbi.nlm.nih.gov/articles/PMC4939231/)
- A randomized field experiment found more frequent daily messages didn't improve adherence, citing possible habituation or intrusion. — [arXiv 2102.05506](https://arxiv.org/pdf/2102.05506)
- The evidence is mixed and mostly comes from small, short studies. In 3 of 6 asthma interventions, daily SMS reminders didn't improve adherence over no reminders. — [PMC4939231](https://pmc.ncbi.nlm.nih.gov/articles/PMC4939231/); [PMC5862021](https://pmc.ncbi.nlm.nih.gov/articles/PMC5862021/)
- ntfy priorities 1–2 deliver silently (no sound or vibration), so a bot can downgrade overnight or low-urgency sends rather than drop them. — [ntfy docs: publish.md](https://github.com/binwiederhier/ntfy/blob/main/docs/publish.md)

### Inferences
These are design suggestions derived from the evidence above, not directly tested in the cited studies:
- Default quiet hours (e.g., 22:00–08:00 local time, user-configurable): suppress or silently deliver reminders during them, and fold anything due overnight into the 8 AM digest.
- Combine all "due in <24h" items into one message per 2-hour cycle instead of one message per assignment, which avoids the "similar content" habituation effect.
- Escalate by urgency: normal priority until about 6 hours before the deadline, high priority in the last few hours. Vary the wording (time remaining, points at stake) so messages aren't identical.
- Make snooze and mute one tap away, and stop reminders immediately once Canvas shows a submission.
- On Telegram, silent messages (`disable_notification`) could carry non-urgent cycles. That parameter is unverified here; see Gaps.

### Gaps
- No study was found that tests the optimal reminder interval for deadline (vs medication) reminders, or specifically every-2-hours cadences.
- Telegram's `disable_notification` and Pushover's low/quiet priorities (−1/−2) and quiet-hours features weren't verified from official docs this session.

## 8. Recommendation: primary and fallback channel for a no-budget student

### Takeaway
**Primary: a Telegram bot.** It's free, takes about 5 minutes via @BotFather, has two-way "Done/Snooze" buttons, uses long polling so it works behind NAT, and has mature, maintained libraries. **Fallback: email via the student's own Gmail with an App Password** (free, no domain needed), used for the 8 AM digest and as a backup if Telegram sends fail. **Optional: ntfy** (free; ntfy.sh or self-hosted) as a no-account push alternative for users who don't want Telegram, or **Pushover** ($4.99 one-time) for nag-until-acknowledged escalation. **Skip SMS:** it costs money, US carriers require 10DLC/toll-free registration, and the free carrier gateways are shut down.

### Cited Findings
Each row summarizes findings cited in sections 1–7; see those sections for the URLs.

| Channel | Cost for this use | Setup effort | Limits relevant here | Interact back? | Works behind NAT w/o public URL? | Main risks |
|---|---|---|---|---|---|---|
| **Telegram bot** | Free ([Unipile](https://www.unipile.com/is-the-telegram-api-free/)) | @BotFather token; user presses /start; read chat_id via getUpdates | ~1 msg/s per chat ([grammY](https://grammy.dev/advanced/flood)) | Yes: inline buttons → callback queries | Yes (long polling) | MarkdownV2 escaping; token leaks (revoke via /revoke); student must install Telegram |
| **Gmail SMTP (App Password)** | Free | Enable 2SV, create App Password | ~500/day ([nylas](https://cli.nylas.com/guides/gmail-smtp-settings)) | Links only | Send yes; links need a public endpoint | App Passwords discouraged by Google (no deprecation date found); email notification fatigue |
| **Resend / Brevo / SES** | Free tiers (3,000/mo, 100/day; 300/day; 3,000/mo for 12 mo) | Own domain + SPF/DKIM | Daily caps fine | Links only | Send yes | Needs a domain; SendGrid free tier gone |
| **ntfy** | Free (ntfy.sh) or self-host | Install app, pick a secret topic or self-host with ACLs | Free-tier rate limits (~250/day, unverified) | Yes: up to 3 `http`/`view` actions | Send yes; `http` callbacks need a reachable URL | Public topics unless reserved/self-hosted; iOS self-host needs upstream ntfy.sh |
| **Pushover** | $4.99 one-time per platform after 30-day trial | Account + app token | 10,000 msgs/mo free | Ack for emergency priority (receipt + callback) | Polling receipts works; callback needs a public URL | Cost; 3-hour expire cap |
| **Discord bot** | Free | Bot app + DM permission | 5 req/2 s per webhook | Yes (bot components) | Yes (gateway is outbound) | More setup than Telegram; webhooks can't DM |
| **SMS (Twilio 10DLC SP)** | ≈$7–8/mo + ≈$19.50 one-time (inferred) | Brand/campaign registration, privacy/T&C URLs, 1–3 weeks | 1,000/day SP cap | Reply keywords only | Send yes; inbound needs a webhook | Paperwork, vetting, cost |
| **Email-to-SMS gateway** | Free | None | n/a | No | n/a | AT&T/T-Mobile dead; Verizon ends 3/31/2027 |
| **WhatsApp Cloud API** | Template fees outside 24 h window (~$0.004 US utility) | Meta Business onboarding, templates | n/a | Yes | Webhook needed for inbound | Business onboarding overkill |
| **Signal (signal-cli)** | Free + a spare number | Register a number via an unofficial client | Rate-limit CAPTCHAs | Yes (replies) | Yes | Unofficial; CAPTCHA lockouts |

### Inferences
- **Why Telegram is primary:**
  - It's the only option that is simultaneously $0, interactive (Done/Snooze) without exposing a server, and well supported by maintained libraries in both Python (aiogram 3.31 / PTB 22.8) and TypeScript (grammY 1.46).
  - The user already plans to create a Telegram bot.
  - Long polling plus a scheduler (PTB JobQueue or APScheduler) runs on a laptop, Raspberry Pi or free-tier VM with no inbound ports.
- **Why email is the fallback:**
  - The student already has it. Gmail SMTP with an App Password needs no domain, DNS or third-party account.
  - It's a durable copy of the daily digest, and a recovery path if the Telegram token is revoked or the chat is blocked.
  - Limit email to the digest (and maybe a final "due in <2h" alert) to avoid inbox fatigue.
  - If Google ever removes App Passwords, move to Gmail OAuth or Resend/Brevo with a cheap domain.
- **When to choose ntfy over Telegram:** if the student doesn't want a Telegram account, or wants a no-account, open-source push channel. ntfy.sh free with a long random topic is fine for low-sensitivity data (course names, due dates). Self-host with `deny-all` ACLs for privacy, remembering the iOS upstream requirement.
- **When Pushover is worth $4.99:** if the student has repeatedly ignored reminders and wants a "keep alarming until I acknowledge" mode for the final hours.
- **Implementation tips for the bot:**
  - Store TELEGRAM_BOT_TOKEN, OWNER_CHAT_ID and GMAIL_APP_PASSWORD in env/secrets, never in git.
  - Reject every update whose chat or user ID isn't OWNER_CHAT_ID (PTB TypeHandler group -1 pattern).
  - Use HTML parse mode or a vetted MarkdownV2 escaper for Canvas-sourced text.
  - Keep `callback_data` compact (≤64 bytes).
  - Always call answerCallbackQuery.
  - Rebuild scheduled reminders from the database on restart.
  - Set an explicit timezone for 8 AM.
  - Retry on 429 using `retry_after`.

### Gaps
- Reliability/uptime SLAs for Telegram, ntfy.sh and Pushover weren't found. All are free or consumer services with no published SLA found this session.
- No data was found on Telegram or ntfy delivery latency under iOS Focus/DND modes.
- The domain cost for the transactional-email path wasn't researched.
