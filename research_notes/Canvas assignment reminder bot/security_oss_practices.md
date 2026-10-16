# Security, Privacy, and Open-Source Engineering Practices for a Self-Hosted Canvas Reminder Bot

_Method note for the report writer: WebFetch failed with DNS errors for every domain tried (canvas.instructure.com, core.telegram.org, docs.ntfy.sh, docs.github.com, developerdocs.instructure.com), and the Context7 MCP server failed to connect (proxy 403). Every finding below therefore comes from WebSearch result summaries. Each one is attributed to the URL the search returned, but quotes are paraphrased by the search tool and were not checked word for word against the primary page. Sources marked "(secondary)" or "(low-quality)" are vendor blogs, community posts, or AI "skill" pages and should be treated as orientation, not authority. Today's date for this research: 2026-10-16._

## 1. Threat model: what leaked credentials allow, and how to limit the damage

### Takeaway
The Canvas personal access token (PAT) is the most valuable secret in the system by a wide margin. It lets the holder act as the student, bypasses SSO and MFA, and by default never expires. The Telegram bot token gives full control of the bot and its message history. A Gmail app password lets the holder sign in to the mailbox from a non-Google client. An ntfy topic on the public server is effectively a shared password. The design should assume each of these leaks eventually, so every one needs an expiry, a revocation runbook, and a narrow blast radius (owner-only chat_id allowlist, webhook secret check, private ntfy topic with ACLs).

### Cited Findings
**Canvas PAT capabilities and lifetime**
- A Canvas token has an optional `expires_at`. Null means the token "does not permanently expire". Regenerating an expired token requires setting a new expiration date, and a token's expiration, purpose, and scopes can be updated later. — [Instructure Access Tokens API](https://developerdocs.instructure.com/services/canvas/resources/access_tokens)
- Token `scopes`: "if empty, there are no scope limitations". — [Instructure Access Tokens API](https://developerdocs.instructure.com/services/canvas/resources/access_tokens)
- (secondary) Scopes on user tokens are reportedly ignored unless the default developer key has "enable scopes" turned on. Without that, the token inherits the user's full permissions. — [withone.ai Canvas knowledge page](https://www.withone.ai/knowledge/canvas-lms/conn_mod_def%3A%3AGM1M-sc97B4%3A%3Ad09v-RRZSlezboJOw2LHUw)
- A token created for another user stays pending until that user activates it. A token created for yourself works immediately. — [Instructure Access Tokens API](https://developerdocs.instructure.com/services/canvas/resources/access_tokens)
- Tokens bypass SSO and MFA and ignore session timeouts. — [Canvas Insider blog](https://www.canvasinsider.blog/p/two-checkboxes-im-glad-i-found-in)
- "The downstream impact of a compromised token can exceed that of a stolen password, especially since MFA provides no protection". Abusive scripts can also overload Canvas. — [University of Missouri System, Canvas user API token policy](https://tdx.umsystem.edu/TDClient/66/MOOnline/KB/Article/2193/Canvas-user-API-token-policy)
- A token holder can reach course materials, assignments, and grades much as if they had the user's login. Sharing a token with an outside party is often a policy violation, and the guidance is to revoke or regenerate it immediately. — [Cornell, Canvas API access tokens](https://learn.canvas.cornell.edu/canvas-api-access-tokens)
- Giving out a token is equivalent to sharing your login credentials. — [Emory Canvas Support](https://canvas-support.emory.edu/instructionalsupport/api-tokens.html)
- Many AI tools and browser extensions ask for tokens "to automate downloads or submissions" and often store them insecurely. Some schools bar students from generating tokens, and teacher-generated tokens there must expire within 90 days. — [St. Edward's University KB](https://support.stedwards.edu/TDClient/96/Portal/KB/Article/6479/Canvas-API-Access-Tokens)
- Canvas API tokens are access credentials and "should be considered as sensitive information". Store them securely, do not share them with third parties, and review existing tokens periodically. FERPA-protected student records are a stated concern. — [Texas A&M Canvas API Access Token Request Policy](https://lms.tamu.edu/support/canvas-api)

**Canvas platform changes in 2025 that affect students (verify against official release notes)**
- September 2025: a new admin setting, "Restrict Student Personal Access Token Creation". When it is on, users whose only role is student cannot create tokens. Users with several roles follow their highest permission. — [UC San Diego Extension, New Features and System Changes](https://extensionhelpcenter.ucsd.edu/hc/en-us/articles/360046912971-New-Features-and-System-Changes); [UC Riverside Canvas Features & Releases](https://canvas.ucr.edu/canvas-features-and-releases)
- Deploy notes dated 2025-10-08 list "Required Fields and Expiration Limit". Deploy notes dated 2025-11-05 list "Restrict Personal Access Tokens Includes Observers" and "Access Token Expiration Date Required – Student". The actual maximum lifetime value was not in the snippet. — [UC Riverside Canvas Features & Releases](https://canvas.ucr.edu/canvas-features-and-releases)
- UW–Madison stopped student self-service token generation on November 14, 2025. Students now have to request a token. — [UW–Madison IT, Change to student access tokens](https://it.wisc.edu/academic-technology/learn-uw-news/change-to-student-access-tokens-in-canvas/)

**Telegram bot token**
- The bot token grants full control of the bot, including reading messages in every chat the bot can access and sending messages as the bot. — [GitGuardian remediation: Telegram bot token](https://gitguardian.com/remediation/telegram-bot-token); [RedHunt Labs exposure docs](https://docs.redhuntlabs.com/docs/exposure-risks/credentials/telegram_bot_token)
- Revoking: send `/revoke` to BotFather and pick the bot. The old token stops working immediately, and every deployment then needs the new one. — [GitGuardian](https://gitguardian.com/remediation/telegram-bot-token)
- With the token, `getUpdates` returns recent messages sent to the bot. A leaked token compromises the bot, not the owner's personal Telegram account. — [DEV Community, Writing Telegram bots from the command line](https://dev.to/begoon/writing-telegram-bots-from-command-line-9b8)
- Webhook verification: `setWebhook` takes a `secret_token`. Telegram then sends that value in the `X-Telegram-Bot-Api-Secret-Token` header on every webhook request. The token is 1–256 characters, limited to `A-Z a-z 0-9 _ -`. — [aiogram setWebhook docs (mirrors Bot API text)](https://docs.aiogram.dev/en/latest/api/methods/set_webhook.html)
- Using a secret URL path in addition to the header check is also recommended. — [R telegram.bot setWebhook docs](https://rdrr.io/cran/telegram.bot/man/setWebhook.html)

**ntfy**
- "Because there is no sign-up, the topic is essentially a password, so pick something that's not easily guessable." — [ntfy docs, Publishing](https://docs.ntfy.sh/publish)
- Topic names on ntfy.sh are public. Without access control, the topic name works as a password. — [ntfy Terms](https://docs.ntfy.sh/terms/)
- A randomly generated topic name is "as good as a good password". Brute force is impractical because the default rate limit is 60 burst requests, then one request every 10 seconds. Topic names are limited to letters, digits, `_` and `-`, up to 64 characters. — [ntfy FAQ](https://docs.ntfy.sh/faq/)
- A self-hosted ntfy server with no configuration is open: "anyone who knows your URL can publish and subscribe to any topic". — [Railway ntfy template](https://railway.com/deploy/ntfy-push-notifications)
- `auth-default-access: deny-all` makes the server fully private. ACL entries take the form `username:topic-pattern:access`, where access is rw, ro, wo, or deny-all. The special `everyone` user grants anonymous access. — [ntfy config.md (Fossies mirror)](https://fossies.org/linux/ntfy/docs/config.md)
- For sensitive information, reserve the topic and restrict access to it. — [Home Assistant ntfy integration](https://www.home-assistant.io/integrations/ntfy/)

**SMTP / Gmail app passwords**
- Google ended password-only "less secure app" access: May 30, 2022 for consumer accounts, and in stages for Workspace with final shutoff on September 30, 2024. — [Unraid forum](https://forums.unraid.net/topic/121304-gmail-less-secure-sign-in-will-be-disabled-may-30/); [Weber State KB](https://www.weber.edu/help/kb/kb/googlesync_apps.html)
- An app password is a 16-digit code for signing in from non-Google apps. It requires 2-Step Verification and can be revoked at any time. — [Educative](https://www.educative.io/answers/how-to-create-an-app-password-in-gmail)
- Changing the main Google password silently revoked existing app passwords (single anecdotal report). — [Shallow Thoughts blog](https://shallowsky.com/blog/tags/gmail)

### Inferences
- **What an attacker can do with the Canvas PAT:** anything the student can do in the web UI or API. That includes reading grades, feedback, and submissions; submitting or replacing assignment submissions (sabotage, or an academic-integrity incident the student gets blamed for); sending inbox messages to instructors and classmates as the student; posting to discussions; downloading course files that may contain other students' data; and changing profile or notification settings. Since the API can create tokens for "yourself" that are usable immediately, an attacker may be able to mint a second token for persistence. A leak response must therefore list and delete every unknown token (Canvas Account → Settings → Approved Integrations; UI label from general knowledge, verify), not just the known one.
- **Canvas PAT mitigations for the project:**
  1. In the README, tell users to create the token with the shortest workable expiry (for example 90–120 days), name it after the bot, and set a calendar reminder to rotate it.
  2. Have the bot read `GET /api/v1/users/self` plus the token's `expires_at`, if available, at startup and warn the user (via their own channel) N days before expiry. Watch for 401 responses and alert on them.
  3. Make the bot read-only by design: only call GET endpoints, never wire up submission or messaging endpoints, and say so in SECURITY.md.
  4. Explain that many schools now block student token creation or require expiry (2025 Canvas settings), so the bot must handle "no token possible" gracefully. Offer an iCal-feed fallback; Canvas calendar feeds are a separate feature, not verified here.
- **Telegram mitigations:**
  1. Hard-code an allowlist of `chat_id`s (normally just the owner) and silently drop updates from anyone else. Bots are publicly discoverable by username, so otherwise anyone can `/start` it and query deadlines.
  2. For a self-hosted single user, prefer long polling (`getUpdates`). It needs no inbound port or TLS certificate.
  3. If webhooks are used, generate a 64+ character random `secret_token`, compare it with `hmac.compare_digest`, add a random path segment, and reject requests without the header.
  4. Document the `/revoke` runbook.
- **ntfy mitigations:** Generate the topic as `prefix-<uuid4>` (well under 64 characters). Put no grades or descriptions in push bodies, only titles, due times, and a link. For anything more sensitive, self-host with `auth-default-access: deny-all` and a write-only token for the bot, or use ntfy.sh reserved topics with access tokens.
- **Email mitigations:** Recommend a dedicated sending account or a transactional email provider with a send-only API key over the user's primary Gmail app password. A Gmail app password authenticates as the whole mailbox for SMTP/IMAP (inference, not verified against Google docs), so its blast radius covers the user's email.

### Gaps
- Instructure's official PAT documentation pages (developerdocs.instructure.com) could not be fetched directly. The claim that scopes apply only when the developer key enforces them comes from a secondary source.
- The maximum token lifetime introduced by the October/November 2025 "Expiration Limit" changes was not found.
- There was no official Google source on exactly what an app password can reach (SMTP only, or IMAP and full mail as well).
- No source was found on whether Telegram exposes audit logs of `getUpdates` calls after a leak.

## 2. Secret storage for a self-hosted app, and what changes for a multi-user hosted version

### Takeaway
For a single-user deployment: keep secrets out of the image and out of git, deliver them as files (Docker/Compose secrets mounted at `/run/secrets`, read through a `*_FILE` convention) or as a `chmod 600` `.env` file, wrap them in a `SecretStr` type, and redact them from every log line. The Telegram token sits in the API URL path, so HTTP-client request logging is the most likely leak. Encrypting secrets at rest on the same box as the key adds little. For a multi-user hosted service, switch to Canvas OAuth2: developer key, 1-hour access tokens, refresh tokens. Encrypt each user's refresh token with envelope encryption under a KMS key, bind it to the user ID as associated data, and plan for revocation and deletion.

### Cited Findings
- The OWASP Secrets Management Cheat Sheet covers the full secret lifecycle (creation, storage, rotation, revocation, auditing). It treats manual rotation as error-prone and recommends automation. — [OWASP Secrets Management Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Secrets_Management_Cheat_Sheet.html); summary at [Infisical](https://infisical.com/blog/owasp-secrets-management-cheat-sheet.md) (secondary)
- Environment variables are "visible to anyone who can docker inspect the container" and can show up in process listings and logs. — [StackHarbor, Docker secrets handling](https://stackharbor.com/en/knowledge-base/docker-secrets-handling/); [Jacar, Env vars and secrets in Docker Compose](https://jacar.es/en/docker-compose-environment-variables-and-secrets/)
- Compose `secrets:` are mounted read-only at `/run/secrets/<name>`, outside the process environment, and do not appear in `docker inspect`. The `*_FILE` convention (for example `POSTGRES_PASSWORD_FILE=/run/secrets/db_password`) is supported by official images. Compose 2.30.0 or later is recommended for full secrets support. Compose secrets do not require Swarm. — [Phase.dev, Docker Compose secrets](https://phase.dev/blog/docker-compose-secrets/); [OneUptime, Docker Compose secrets](https://oneuptime.com/blog/post/2026-01-25-docker-compose-secrets/view)
- Check `Config.Env` in `docker inspect`. If it contains anything that looks like a password rather than a secret-file path, that secret is "one docker inspect away from being leaked". — [Phase.dev](https://phase.dev/blog/docker-compose-secrets/)
- Logging: the OWASP Logging Cheat Sheet lists passwords, session identifiers, access tokens, database connection strings, and encryption keys as values that usually should not be logged directly. They should be removed, masked, hashed, or encrypted instead. — summarized by [Vincent Schmalbach](https://www.vincentschmalbach.com/how-to-redact-sensitive-data-from-application-logs/) (secondary); primary: [OWASP Logging Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Logging_Cheat_Sheet.html)
- OWASP (A)ASVS 8.7: do not log sensitive data, specifically session identifiers, passwords, hashes, or API tokens. — [OWASP AASVS 8.7](https://owasp-aasvs.readthedocs.io/en/latest/requirement-8.7.html)
- Inventory every value that can reach a log, including Authorization headers, and treat downstream masking as a backup rather than the main control. — [Vincent Schmalbach](https://www.vincentschmalbach.com/how-to-redact-sensitive-data-from-application-logs/)
- Envelope encryption: a data key encrypts the payload, and a per-tenant master key (KEK) wraps the data key. Bind associated data (tenant ID, record ID) to the ciphertext. Store only the wrapped key, KMS key ID, nonce, and ciphertext with its tag. — [DesignGurus, tenant-aware encryption](https://www.designgurus.io/answers/detail/how-would-you-implement-tenantaware-encryption-envelope-encryption-byok) (secondary)
- One KEK for all tenants simplifies key management but gives no cryptographic isolation. Rotation means re-wrapping data keys while keeping old KEK versions available for decryption. — [WorkOS, Envelope encryption explained](https://workos.com/blog/envelope-encryption-explained)
- AWS IAM Identity Center uses a customer KMS key as the wrapping key for data keys, with an encryption context. KMS encrypts at most 4 KB directly, which is why it wraps data keys. — [AWS IAM Identity Center encryption at rest](https://docs.aws.amazon.com/singlesignon/latest/userguide/encryption-at-rest.md)
- Canvas OAuth2: developer keys are OAuth2 client ID/secret pairs, and the scopes a client requests must be a subset of the key's scopes. — [Canvas Developer Keys doc (UCLA mirror)](https://bruinlearn.ucla.edu/doc/api/file.developer_keys.html)
- Developer keys issued after October 2015 produce access tokens that last 1 hour. Apps must use refresh tokens, and a refresh response does not include a new refresh token. Users can revoke an app's access from their profile settings. — [Canvas OAuth2 Endpoints (OU mirror)](https://canvas.ou.edu/doc/api/file.oauth_endpoints.html)
- If a developer key enforces scopes and the app later requests more scopes, Canvas may reject refresh tokens that were issued with the smaller set. — [Canvas Community, refresh token validity](https://community.canvaslms.com/t5/Developers-Group/How-long-is-a-refresh-token-valid/m-p/537282)
- If the developer key does not require scopes and none are requested, the token gets all scopes. — [django-canvas-oauth README](https://github.com/Harvard-University-iCommons/django-canvas-oauth)
- (unofficial) A Canvas Community moderator wrote that asking users of a multi-user app to create a PAT violates Instructure's API policy and "will almost certainly result in your app being blocked". UNH/PSU say they restrict tokens partly to comply with Instructure's API policy. — [Canvas Community, Pros and Cons of user access tokens](https://community.canvaslms.com/t5/Canvas-Question-Forum/Pros-and-Cons-of-user-access-tokens/td-p/631632); [UNH/PSU KB](https://td.usnh.edu/TDClient/60/Portal/KB/Article/5520/Canvas-User-API-Token-Access-UNH-PSU)
- Canvas API docs are moving to the Instructure Developer Documentation Portal, with redirects starting after July 1, 2026. — [Canvas OAuth2 Endpoints mirror notice](https://canvas.ou.edu/doc/api/file.oauth_endpoints.html)

### Inferences
- **Recommended single-user secret delivery, in order of preference:**
  1. Compose secrets, or systemd `LoadCredential=` on bare-metal installs, read through `CANVAS_TOKEN_FILE`, `TELEGRAM_TOKEN_FILE`, and similar variables.
  2. A `.env` file outside the repo, `chmod 600`, owned by the service user, and listed in `.gitignore`. Ship `.env.example` with placeholder values only.
  3. OS keyring through the Python `keyring` library, for desktop or CLI installs only. No source was fetched for this.
  - At startup, refuse to run if the secrets file is group- or world-readable (an `ssh`-style permission check).
- **Encrypting the token store at rest** (Fernet, age, libsodium) only helps if the key lives somewhere other than the ciphertext: a different volume, a keyring, or a passphrase entered at boot. For a single box, file permissions plus full-disk encryption give most of the value, and the README should say so honestly.
- **Redaction design:**
  - Load secrets into `pydantic.SecretStr` or an equivalent type so `repr()` and `str()` print `**********`.
  - Install a `logging.Filter` on the root handler that applies regexes for the known token shapes. Canvas tokens look like `<digits>~<64 alphanumerics>` and Telegram tokens like `<digits>:<35 chars>`; both shapes are from general knowledge, so verify them. Also redact `Authorization: Bearer …`.
  - Set `httpx`/`httpcore`/`urllib3` loggers to WARNING. The Telegram Bot API puts the token in the URL path (`https://api.telegram.org/bot<TOKEN>/sendMessage`), so any INFO or DEBUG request log or exception message containing the URL leaks it. Verify against the HTTP client's logging behavior.
  - Never include raw API responses or exception `repr`s containing request objects in user-visible error notifications.
  - Add a unit test that captures logs during a full run with sentinel secrets and asserts the sentinels never appear.
- **Multi-user hosted version:**
  - Use Canvas OAuth2 with an institution-approved developer key, not PATs. This requires each school's Canvas admin to install or approve the key, which makes a "public hosted service for any student" structurally hard.
  - Store only refresh tokens, encrypted per user with envelope encryption. Use KMS for the KEK and AES-GCM data keys with AAD = `user_id|canvas_host`.
  - Keep access tokens in memory only.
  - Rotate KEKs. On account deletion, call Canvas's token-delete (logout) endpoint (endpoint not verified here) and delete the ciphertext.

### Gaps
- The full text of the OWASP Secrets Management and Logging cheat sheets was not retrieved, so the specific recommendations on environment variables and encryption are unverified.
- No fetched source covers Python `keyring` security properties, systemd credentials, or SOPS/age for self-hosted configuration.
- The text of Instructure's official "API Policy" was not found. The PAT-prohibition claim comes from a community moderator, not Instructure.
- The Canvas token-format regexes are from general knowledge, not a fetched source.

## 3. Privacy and legal: FERPA, GDPR, Instructure terms, academic integrity

### Takeaway
FERPA binds educational institutions, not students. A student pulling their own data with their own token onto their own server is not making a FERPA disclosure. The real constraints are the school's acceptable-use and token policies, many of which forbid giving tokens to third parties. A hosted multi-user service changes this materially. It would hold many students' education-record data with no "school official" contract, would likely breach institutional policies and Instructure's API expectations if built on PATs, and would need a privacy policy, data minimization, retention limits, deletion, and (for EU users) full GDPR controller obligations. The household exemption covers only purely personal use.

### Cited Findings
- When a student turns 18 or attends a postsecondary institution at any age, they become an "eligible student" and all FERPA rights transfer from the parent to the student. — [Caltech FERPA student PDF](https://finaid.caltech.edu/documents/29302/FERPA-Student.pdf); [John Cabot University, FERPA for students](https://www.johncabot.edu/registrar/ferpa/ferpa-for-students.pdf)
- Before an educational agency or institution discloses personally identifiable information from education records, FERPA requires signed and dated written consent, unless an exception applies. — [Berklee, Student Privacy Rights under FERPA](https://www.berklee.edu/registrar/student-privacy-rights-ferpa); [SUNY Suffolk, FERPA](https://sunysuffolk.edu/explore-academics/faculty-and-staff/center-for-teaching-and-learning/online-teaching/ferpa.jsp)
- The U.S. Department of Education's guidance "Protecting Student Privacy While Using Online Educational Services: Requirements and Best Practices" identifies the FERPA exceptions, including the school official exception, that schools rely on when using online services. — [studentprivacy.ed.gov](https://studentprivacy.ed.gov/resources/protecting-student-privacy-while-using-online-educational-services-requirements-and-best)
- Under the school official exception, a vendor must perform a service the institution would otherwise perform itself and must be under the institution's direct control. The Department calls a written agreement a best practice, not a requirement. — [Security Scientist, FERPA and third-party vendors](https://answers.securityscientist.net/q/28170/how-does-ferpa-apply-to-third-party-vendors-and-cloud-services) (secondary)
- Institutional policy treats sharing a Canvas token with an outside party as a violation. — [Cornell](https://learn.canvas.cornell.edu/canvas-api-access-tokens); [Texas A&M](https://lms.tamu.edu/support/canvas-api)
- GDPR household exemption, Article 2(2)(c): it covers processing for personal, family, household, or recreational purposes. It does not apply when the data is used for professional or commercial activity or made publicly available. — [Irish Data Protection Commission FAQ](https://dataprotection.ie/en/faqs/general/what-household-exemption)
- The exemption "must be read very restrictively, as is the case for all exceptions in EU law". — [Mondaq, "One-man controller"](https://www.mondaq.com/data-protection/1773198/one-man-controller-the-responsibility-of-individuals-under-the-gdpr)
- GDPR Article 25 requires privacy by design and by default. By default, only data necessary for each purpose is processed, which covers the amount collected, the extent of processing, the storage period, and accessibility. — [sota.io, GDPR Article 25 developer guide](https://sota.io/blog/gdpr-article-25-privacy-by-design-paas-saas-developer-guide) (secondary)
- Article 5 data minimisation and storage limitation: data that was minimal when collected still breaches Article 5 if it is never deleted. — [Legiscope](https://www.legiscope.com/blog/gdpr-data-minimisation-storage-limitation-official.html) (secondary)
- Data subject requests, including Article 17 erasure, must be answered within one month under Article 12(3), with an extension possible for complex cases. — [Cadence, GDPR SaaS compliance](https://cadence.withremote.ai/blog/gdpr-saas-compliance) (secondary)

### Inferences
- **Single-user self-hosted.**
  - FERPA: the student is the data subject exercising their own access. FERPA's consent rules govern the institution's disclosures. The README should still warn that the user's school may prohibit PATs or third-party tools, and that the user is responsible for complying with their institution's policies.
  - GDPR: an EU student running the bot for themselves is very likely covered by the household exemption. If they run it for classmates, the exemption likely stops applying.
- **Multi-user hosted service, minimum needs:**
  - A privacy policy stating which Canvas data is fetched, why, where it is stored, retention, sub-processors (Telegram, email provider, ntfy, hosting), and how to delete an account.
  - Data minimization: fetch only course names, assignment names, due/lock dates, submission status, and `html_url`. Do not fetch grades, comments, rubric feedback, discussion bodies, or files.
  - Purge assignments a fixed number of days after their due date.
  - One-click deletion that also revokes the OAuth grant.
  - A breach-notification plan.
  - A DPA and records of processing if serving EU users.
  - Age gating if K-12 students might use it, since Canvas is widely used in K-12 (COPPA/state student-privacy laws; not researched here).
- **Academic integrity:** a read-only reminder tool raises no integrity concern. But the token technically allows submissions and messaging. The project should never add "auto-submit" or messaging features, and should document that it is read-only so schools can evaluate it.
- **Other students' data:** assignment descriptions and announcements can contain names or group assignments. Forwarding only the title and due date limits incidental exposure of classmates' data to Telegram, email, or ntfy third parties.

### Gaps
- No primary Department of Education text was retrieved stating explicitly that a student may share their own records with any third party without FERPA implications. That conclusion is an inference from FERPA applying to institutions. Confirm against 34 CFR Part 99 or studentprivacy.ed.gov FAQs.
- Instructure's API Policy, Acceptable Use Policy, and developer terms could not be retrieved. Whether a self-hosted personal script using a PAT complies is unconfirmed.
- State student-privacy laws (for example California SOPIPA) and COPPA applicability to a hosted service were not researched.
- GDPR Article 28 (processor) obligations and the EDPB position on self-hosted tools serving friends or family were not covered.

## 4. Input/output safety: escaping, link handling, SSRF, supply chain

### Takeaway
Treat every string from Canvas as untrusted. Assignment names are plain text that may contain Markdown or HTML metacharacters, and descriptions are HTML. Escape for the specific sink: Telegram HTML or MarkdownV2, an email HTML body, email headers. Simplest is Telegram HTML mode with `html.escape`, or sending `entities` and skipping parse modes entirely. If the Canvas base URL is user-supplied, require `https`, validate the host against an allowlist, never follow redirects or pagination `Link` URLs to another host while carrying the token, and in a hosted version block private and loopback IPs with DNS-rebinding-safe checks. Use hash-locked dependencies (`uv.lock`), `pip-audit` or OSV scanning, and SHA-pinned Actions to cover supply-chain risk.

### Cited Findings
- MarkdownV2: in regular text the characters `_ * [ ] ( ) ~ \` > # + - = | { } . !` must be backslash-escaped. Inside code spans and blocks only `` ` `` and `\` are special. Inside a link URL only `)` and `\` are special. — [utterstep/telegram-escape (GitHub)](https://github.com/utterstep/telegram-escape); [Zabbix ZBX-20150 bug](https://support.zabbix.com/browse/ZBX-20150)
- Backslash itself should also be treated as needing an escape. Sources were inconsistent on this. — [telegram-escape](https://github.com/utterstep/telegram-escape)
- Telegram HTML mode: every `<`, `>`, and `&` that is not part of a tag or entity must be replaced with its HTML entity. All numeric entities are accepted, but only `&lt; &gt; &amp; &quot;` are supported as named entities. — [Telegram Bot API mirror (tgrm)](https://tgrm.oss.hagever.com/types/Telegram.ParseMode.html); [aiogram formatting utils](https://docs.aiogram.dev/uk-ua/latest/utils/formatting.html)
- SSRF: enforce URL scheme, port, and destination with a positive allowlist. Disable HTTP redirects. Watch for DNS rebinding and TOCTOU races. Do not rely on deny lists or regular expressions. — [OWASP Top 10 A10:2021 SSRF](https://owasp.org/Top10/2021/A10_2021-Server-Side_Request_Forgery_(SSRF)/index.html)
- Disable redirect following in the web client because redirects can bypass input validation. Allowlist input validation is preferred when the expected format is known. — [OWASP SSRF Prevention Cheat Sheet](https://cheatsheetseries.owasp.org/cheatsheets/Server_Side_Request_Forgery_Prevention_Cheat_Sheet.html)
- DNS rebinding: the attacker returns a safe IP during validation, then switches DNS to an internal address before the fetch. — [Nette SSRF protection docs](https://doc.nette.org/de/http/ssrf)
- `uv.lock` records SHA-256 hashes for every distribution by default, and a mismatch fails the install. Hashes do not protect against a malicious version published through legitimate PyPI channels. `--exclude-newer` helps avoid freshly published versions. — [pydevtools, pin dependencies with hashes in uv](https://pydevtools.com/handbook/how-to/how-to-pin-dependencies-with-hashes-in-uv/)
- `pip-audit` (Trail of Bits / PyPA) checks against the Python Packaging Advisory Database, has an OSV option, and works on any project, for example `uvx pip-audit -r requirements.txt`. — [pip-audit on PyPI](https://pypi.org/project/pip-audit/2.3.2); [pydevtools, scan Python dependencies](https://pydevtools.com/handbook/how-to/how-to-scan-python-dependencies-for-vulnerabilities/)
- uv has an experimental `UV_MALWARE_CHECK` that queries OSV before downloading. — [Classmethod, uv audit and malware check](https://dev.classmethod.jp/articles/uv-audit-malware-check-supply-chain/)
- tj-actions/changed-files (CVE-2025-30066, March 2025): attackers repointed tags v1–v45.0.7 to a malicious commit that printed CI secrets into logs. The action was used in about 23,000 repositories. SHA-pinned workflows were unaffected. — [Safeguard, tj-actions explained](https://safeguard.sh/resources/blog/tj-actions-changed-files-github-actions-supply-chain-compromise)

### Inferences
- **Sink-specific encoding rules for the code:**
  - **Telegram:** pick one mode project-wide. HTML mode is easiest: `html.escape(text, quote=True)` on every interpolated field, then wrap with the bot's own tags. Better still, build messages with `entities` (aiogram's or python-telegram-bot's formatting helpers) so no parsing happens at all.
  - **Telegram length:** truncate titles before escaping, so an escape sequence is never cut in half. Telegram's 4096-character message limit is from general knowledge; verify it.
  - **Email:** render with Jinja2 `autoescape=True`, always send a `text/plain` alternative, and never put Canvas text into headers unescaped. Strip CR/LF from the Subject to prevent header injection; Python's `email.message.EmailMessage` with the default policy rejects newlines in headers (verify).
  - **Canvas HTML descriptions:** never forward them. If a snippet is needed, strip to text with a real HTML parser such as `bleach`, `nh3`, or `selectolax`.
  - **Links:** only emit `html_url` values whose host equals the configured Canvas host and whose scheme is `https`. A crafted description could otherwise produce phishing links that look like they come from the user's own bot.
- **Base URL validation (single-user):**
  - Parse with `urllib.parse`. Require scheme `https`, no userinfo, no path beyond `/`, no IP literals.
  - Optionally warn when the host is not under `*.instructure.com` (many schools use custom domains, so warn rather than block).
  - Pin the host for the whole session. The token must only ever go to that exact host.
  - Canvas pagination uses `Link` headers. Before following `rel="next"`, check that its host matches, otherwise a compromised or misconfigured proxy could exfiltrate the token.
  - Use `httpx` with `follow_redirects=False`, or re-check the host on each hop.
- **Base URL validation (hosted multi-user):** also resolve the hostname, reject private, loopback, link-local, and metadata ranges (169.254.169.254), and connect to the validated IP, or use an egress proxy that enforces this, to close the DNS-rebinding TOCTOU gap.
- **Dependencies:** use few runtime dependencies (`httpx`, a Telegram library, `pydantic`, a scheduler). Commit `uv.lock`, run `pip-audit`/OSV in CI and on a weekly schedule, and enable Dependabot security updates.

### Gaps
- The official Telegram Bot API formatting section (core.telegram.org) could not be fetched. The escape rules come from libraries and mirrors.
- No fetched source covered Python `email` header-injection behavior or which HTML sanitizer libraries are current in 2026.
- No source confirmed Canvas `Link`-header pagination host behavior; this is general knowledge.

## 5. Repository and CI security for a public GitHub project (2026)

### Takeaway
Turn on everything GitHub gives public repositories for free: secret scanning with push protection, private vulnerability reporting plus a SECURITY.md, Dependabot alerts and security updates (with version updates on a cooldown), CodeQL default setup, and a branch ruleset on `main`. Harden Actions: pin every action to a full-length SHA (GitHub can enforce this), set `permissions: {}` or read-only at the top of every workflow, avoid `pull_request_target`, and lint with zizmor. Publish releases with trusted publishing, Sigstore-backed attestations (artifact attestations reach SLSA Build L2, and L3 through a reusable workflow), and immutable releases. Track posture with OpenSSF Scorecard and the Best Practices badge. Run gitleaks, ruff, and mypy in pre-commit.

### Cited Findings
- Since March 2024, secret scanning push protection is on by default for pushes to public repositories. The developer can remove the secret or bypass the block. — [GitHub Blog, Keeping secrets out of public repositories](https://github.blog/news-insights/product-news/keeping-secrets-out-of-public-repositories/); [The Hacker News](https://thehackernews.com/2024/03/github-rolls-out-default-secret.html)
- New public repositories owned by personal accounts have secret scanning and push protection enabled by default. Existing repositories and new organization-owned repositories are not affected. — [GitHub Changelog 2024-03-11](https://github.blog/changelog/2024-03-11-secret-scanning-and-push-protection-are-enabled-by-default-on-new-public-repositories/)
- Push protection detects a limited set of token types and lacks historical scanning, so pair it with a local scanner. — [GitGuardian blog](https://blog.gitguardian.com/github-push-protection-enhancing-open-source-security-with-limitations-to-consider)
- Private vulnerability reporting is separate from SECURITY.md. Owners and admins of public repositories can enable it, and reporters then use Security → "Report a vulnerability". Without it, reporters must follow SECURITY.md or open an issue asking for a contact. — [GitHub Docs, Privately reporting a security vulnerability](https://docs.github.com/en/code-security/how-tos/report-and-fix-vulnerabilities/report-a-vulnerability/privately-reporting-a-security-vulnerability)
- GITHUB_TOKEN: new repositories and organizations default to read-only. When a `permissions` key is used, every unspecified permission is set to none except `metadata: read`. Workflows from forked PRs get write permissions downgraded to read. — [GitHub Docs, Automatic token authentication (GHES mirror)](https://docs.github.com/de/enterprise-server@3.5/actions/security-guides/automatic-token-authentication); [GitHub Blog, new tool to secure your GitHub Actions](https://github.blog/security/new-tool-to-secure-your-github-actions)
- GitHub has a setting, "Require actions to be pinned to a full-length commit SHA" (Settings → Actions → General), that covers GitHub-authored actions too. Reusable workflows can still use tags. — [Safeguard, SHA-pin tags or get burned](https://safeguard.sh/resources/blog/github-actions-pinning-sha-vs-tag); [StarSling best practice](https://starsling.dev/best-practices/github-actions/pin-action-shas)
- A SHA can point to an "impostor" commit that exists only in a fork. Verify the SHA is in the canonical repository; zizmor catches tag pins and impostor SHAs. Dependabot or Renovate can update SHA pins, and pinact can do the initial rewrite. — [Safeguard](https://safeguard.sh/resources/blog/github-actions-pinning-sha-vs-tag); [pydevtools, pin GitHub Actions by SHA for Python](https://pydevtools.com/handbook/how-to/how-to-pin-github-actions-by-sha-for-python-projects/); [Lullabot ADR 2026-05-05](https://architecture.lullabot.com/adr/20260505-pin-github-actions-to-hash/)
- Dependabot `cooldown` delays only version updates. Security updates bypass it and open immediately. `groups` can use `applies-to: security-updates`. — [GitHub Blog, Tame Dependabot](https://github.blog/security/supply-chain-security/tame-dependabot-group-your-updates-slow-the-cadence-keep-security-fast/); [StepSecurity, Dependabot cooldown](https://www.stepsecurity.io/blog/announcing-dependabot-configuration-enhancements-cooldown-and-group-support)
- (unverified) A DEV post claims GitHub made a 3-day cooldown the default for Dependabot version updates on July 14, 2026. No GitHub changelog confirmation was found. — [DEV Community, Taming Dependabot 2026](https://dev.to/instasla/taming-dependabot-a-2026-guide-to-grouping-cooldowns-and-cutting-pr-noise-246e)
- CodeQL default setup detects languages (Python included) and analyzes PRs and pushes to default and protected branches without a workflow file. The weekly schedule turns off after six months with no activity. — [GitHub Docs, Configuring default setup](https://docs.github.com/en/code-security/how-tos/scan-code-for-vulnerabilities/configure-code-scanning/configuring-default-setup-for-code-scanning); [GitHub Changelog 2023-01-08](https://github.blog/changelog/2023-01-08-code-scanning-can-be-set-up-more-easily-without-committing-a-workflow-file-to-the-repository/)
- OpenSSF Scorecard checks: Binary-Artifacts, Branch-Protection, CI-Tests, CII-Best-Practices, Code-Review, Contributors, Dangerous-Workflow, Dependency-Update-Tool, Fuzzing, License, Maintained, Packaging, Pinned-Dependencies, SAST, Security-Policy, Signed-Releases, Token-Permissions, Vulnerabilities. Branch-Protection cannot read classic branch protection rules without a fine-grained token. — [OpenSSF Scorecard v5 (pkg.go.dev)](https://beta.pkg.go.dev/github.com/ossf/scorecard/v5); [Scorecard summary (jsDelivr-hosted doc)](https://cdn.jsdelivr.net/npm/@sebastienrousseau/dotfiles@0.2.511/docs/security/SCORECARD.md) (secondary)
- OpenSSF Best Practices badge: "passing" requires meeting every MUST and every SHOULD (or documenting a reason). Required items include a published vulnerability reporting process and running at least one static analysis tool before major releases. Only about 10% of projects pursuing a badge hold "passing" at any time. — [CHAOSS, OpenSSF Best Practices Badge](https://chaoss.community/?p=3939); [bestpractices.dev](https://www.bestpractices.dev/projects/1)
- Artifact attestations alone meet SLSA v1.0 Build Level 2. Building in a shared reusable workflow can meet Build Level 3. Public repositories use the public-good Sigstore instance. The workflow needs `id-token: write` and `attestations: write`. — [GitHub Docs, Using artifact attestations](https://docs.github.com/actions/security-guides/using-artifact-attestations-to-establish-provenance-for-builds); [Ian Lewis, Understanding GitHub artifact attestations](https://www.ianlewis.org/en/understanding-github-artifact-attestations)
- PyPI supports PEP 740 digital attestations tied to Trusted Publishing OIDC identities. Since `pypa/gh-action-pypi-publish` v1.11.0, attestations are produced by default. `uv publish` does not generate them by itself. pip and uv do not yet reject unsigned packages. — [PyPI Blog 2024-11-14](https://blog.pypi.org/posts/2024-11-14-pypi-now-supports-digital-attestations/); [Trail of Bits](https://blog.trailofbits.com/2024/11/14/attestations-a-new-generation-of-signatures-on-pypi/); [pydevtools, publish with attestations](https://pydevtools.com/handbook/how-to/how-to-publish-python-packages-with-digital-attestations/)
- Immutable releases became generally available on October 28, 2025. New releases lock their assets and protect their tags, and each gets signed attestations in Sigstore bundle format. — [GitHub Changelog 2025-10-28](https://github.blog/changelog/2025-10-28-immutable-releases-are-now-generally-available/)
- Rulesets can require signed commits and restrict tag changes. These are reportedly available free on public repositories. — [tessl gh-setup repo-settings reference](https://tessl.io/registry/uinaf/gh-setup/files/references/repo-settings.md) (secondary)
- Gitleaks can run as a pre-commit hook on staged changes and supports a baseline file (`--baseline-path`) and `.gitleaks.toml`. detect-secrets keeps a reviewed `.secrets.baseline` and alerts only on new findings. — [gitleaks README](https://github.com/gitleaks/gitleaks); [OneUptime, secret detection](https://oneuptime.com/blog/post/2026-01-30-secret-detection/view)

### Inferences
**Concrete checklist for this repo:**
1. **`.gitignore`:** `.env`, `*.env`, `secrets/`, `*.sqlite*`, `cassettes/` (or a review policy for cassettes), `.venv/`. Commit `.env.example` only.
2. **Pre-commit:** `gitleaks` (staged mode; check the current subcommand name), `ruff check --fix`, `ruff format`, `mypy --strict` (or pyright), plus `check-added-large-files` and `detect-private-key` from `pre-commit-hooks`. Run the same hooks in CI, because local hooks are optional for contributors.
3. **Workflows:**
   - Put `permissions: {}` at the top of each workflow and grant per job (for example `contents: read`; `security-events: write` for SARIF upload; `id-token: write` plus `attestations: write` only in the release job).
   - Use `actions/checkout` with `persist-credentials: false`.
   - Never interpolate `${{ github.event.* }}` into `run:`; pass it through `env:`.
   - No `pull_request_target`.
   - Turn on GitHub's SHA-pinning enforcement setting.
   - Run zizmor in CI.
4. **`dependabot.yml`:** ecosystems `uv` (or `pip`), `github-actions`, and `docker`. Weekly or monthly grouped version updates with a cooldown. Security updates stay immediate.
5. **Ruleset on `main`:** require PRs, require status checks (tests, lint, CodeQL), block force-push and deletion, optionally require signed commits, and protect `v*` tags.
6. **Releases:** immutable releases, `actions/attest-build-provenance` for the container image and wheels (plus `attest-sbom` with an SPDX/CycloneDX SBOM from syft), Trusted Publishing to PyPI, and an image pushed to GHCR by digest. Document `gh attestation verify` in the README.
7. **Posture:** add the `ossf/scorecard-action` workflow and its badge, and apply for the Best Practices "passing" badge. Most passing criteria fall out of the items above.

### Gaps
- Current docs.github.com pages could not be fetched. Details such as the exact location of the SHA-pinning setting and the free availability of rulesets features on public repositories come from secondary sources.
- The official OpenSSF Scorecard check documentation and scoring weights were not retrieved; only the check list is reliable.
- No fetched source covered `zizmor` docs directly, or GitHub's "dangerous workflow" guidance on `pull_request_target` and script injection. These are general knowledge.

## 6. Testing strategy to make the scheduler "bug-free"

### Takeaway
Most real bugs in a reminder bot are time bugs: DST, time zones, all-day or 23:59 deadlines, overrides, duplicate or missed sends after restarts. Make the scheduler a pure function `(assignments, now, already_sent, user_tz, offsets) → reminders_to_send`. Test it with frozen time (time-machine is faster than freezegun and patches at the C layer), explicit DST-boundary cases, and Hypothesis properties ("never sent twice", "never after the deadline", "sent within the polling window"). Then add replayed Canvas responses (VCR.py/pytest-recording, with Authorization headers and tokens scrubbed) and fake notification adapters. Run mypy or pyright in strict mode and ruff. Mutation testing is worth running on the scheduler module only.

### Cited Findings
- freezegun replaces every imported date/time reference, so its cost scales with the number of module-level attributes. time-machine patches at the C layer, so its cost stays constant. The 2021 benchmark showed about 100x faster setup in a minimal case, and the 2026 re-benchmark confirmed freezegun is O(n) in loaded modules while time-machine is O(1). — [Adam Johnson, freezegun vs time-machine benchmark (2021)](https://adamj.eu/tech/2021/02/19/freezegun-versus-time-machine/); [Adam Johnson, time-machine O(1) vs freezegun O(n) (2026-08-03)](https://adamj.eu/tech/2026/08/03/python-time-machine-o1-freezegun-on/)
- freezegun holds time constant by default, while time-machine keeps time moving from the travelled-to point unless `tick=False`. time-machine 3.3.0 (July 2026) ships a migration CLI that adds `tick=False` to match freezegun. — [Better Stack, time-machine vs freezegun](https://betterstack.com/community/guides/testing/time-machine-vs-freezegun/); [Adam Johnson, time-machine 3.3.0](https://adamj.eu/tech/2026/07/31/python-time-machine-3.3.0/); [time-machine docs, comparison](https://time-machine.readthedocs.io/en/latest/comparison.html)
- Hypothesis datetime strategies handle ambiguous and imaginary local times through `fold`: fold=0 picks the offset before the transition and fold=1 the offset after. There is an `allow_imaginary` option. The source code warns its logic is wrong for zones with negative DST, such as Europe/Dublin. — [Hypothesis datetime strategy source](https://hypothesis.readthedocs.io/en/latest/_modules/hypothesis/strategies/_internal/datetime.html)
- A recipe pattern: generate a UTC instant, then `astimezone` into the target zone, which never produces a nonexistent or ambiguous local time. — [hypothesis-recipes README](https://ithub.global.ssl.fastly.net/python-testing-debugging/hypothesis-recipes/blob/main/README.md) (secondary)
- VCR.py: `filter_headers` and `filter_query_parameters` take names, `(name, replacement)` tuples, or callables. `before_record_request` and `before_record_response` can modify or drop interactions. With `decode_compressed_response=True`, decompression happens before custom filters run. — [VCR.py Advanced Features](https://vcrpy.readthedocs.io/en/latest/advanced.html)
- pytest-recording is configured through a `vcr_config` fixture that returns a dict. — [VCR.py/pytest-recording guide](https://qaskills.sh/blog/vcrpy-pytest-recording-http-replay-guide) (secondary)
- Mutation testing: an academic comparison of five Python tools found mutmut's results inconclusive because its runs were incomplete. Poodle had 50.9% mutant competency and Cosmic Ray 25.7%. — [Emerging Researchers, Python mutation testing tool comparison](https://emerging-researchers.org/projects/413-3/)
- mutmut 3.5.0 had its last push on April 18, 2026. Mutation testing is slow by design and best aimed at a focused module with real business rules. — [depscope mutmut](https://depscope.dev/pkg/pypi/mutmut); [QA Skills mutmut guide](https://qaskills.sh/blog/mutmut-python-mutation-testing-guide) (secondary)

### Inferences
**Architecture for testability**
- Inject a `Clock` (or `now: datetime`) into the scheduler instead of calling `datetime.now()`. Time-travel libraries are then only needed for integration tests.
- Store every instant as an aware UTC `datetime`. Convert to the user's `ZoneInfo` only for display and for "local-time" rules such as "remind me at 8 pm the day before".

**Mandatory example tests (table-driven)**
- **DST boundaries:**
  - US spring-forward 2026-03-08 and fall-back 2026-11-01 in `America/New_York`, EU 2026-03-29 and 2026-10-25. These dates follow from the standard rules (second Sunday in March, first Sunday in November, last Sundays in the EU); verify them.
  - A "remind 24 h before" on a deadline the day after spring-forward. Decide and document whether this means 24 elapsed hours or the same wall-clock time.
  - A reminder whose local time falls in the skipped hour or the repeated hour.
- **Deadline shapes:** a deadline at 23:59:59 local; assignments with `due_at = null`; `lock_at` before `due_at`; per-section overrides (different due dates for the same assignment); deadlines already past at first sync; a due date changed after a reminder was already sent.
- **Data and runtime:** a user time zone different from the course or account time zone; leap day 2028-02-29; a bot restart in the middle of a window (idempotency via a persisted `sent` set keyed by `(assignment_id, due_at, offset)`); clock skew; Canvas returning 401, 403, 429, or 5xx; pagination.

**Hypothesis properties**
- For arbitrary assignment sets, offsets, time zones (`st.timezones()`), and any increasing sequence of poll times:
  1. each `(assignment, offset)` is emitted at most once;
  2. nothing is emitted after `due_at`, or after `lock_at` if configured;
  3. if polls are at most P minutes apart, every reminder fires no later than P minutes after its target time;
  4. the scheduler's output is unchanged across a restart (state round-trip).
- Use stateful testing (`RuleBasedStateMachine`) for create, update, and delete of assignments between polls.

**Recorded contract tests**
- Record real Canvas responses once against a throwaway or sandbox account. Configure `filter_headers=[("authorization", "REDACTED")]` and `filter_query_parameters=["access_token"]`, and add a `before_record_response` that rewrites user names, emails, and IDs.
- Run CI in `--record-mode=none` so tests never reach the network.
- Add a CI test that greps cassettes for token patterns and fails if any match, and run gitleaks over `tests/cassettes/`.
- Use `respx` (for httpx) for small, hand-written edge-case responses.

**Notification adapters**
- Define a `Notifier` protocol with Telegram, SMTP, and ntfy implementations plus an in-memory `FakeNotifier`.
- Test escaping with adversarial titles: `<b>`, `&amp;`, `*_[]()`, emoji, a 5,000-character title, RTL text, a newline in the subject.
- Use `aiosmtpd` or a local SMTP sink for SMTP tests, and a local ntfy container or `respx` for ntfy.

**Quality gates**
- About 90% branch coverage on `scheduler/` and `formatting/`, with no coverage target for adapter glue.
- `mypy --strict` or `pyright --strict`.
- ruff with the `S` (flake8-bandit), `DTZ` (naive datetimes), `B`, and `UP` rule sets. `DTZ` is particularly valuable here because it flags `datetime.now()` without a tz. Rule-set names are from general knowledge of ruff; verify them.
- Mutation testing (mutmut or Cosmic Ray) on `scheduler.py` only, nightly or before releases.

### Gaps
- Current Hypothesis docs for `st.timezones()` with the stdlib `zoneinfo` backend, and `allow_imaginary` details, were not retrieved; only the source module was.
- No fetched source covered respx, pytest-recording record modes, or ruff `DTZ`/`S` rule names. These are general knowledge to verify.
- There is no empirical data on the cost-benefit of mutation testing for small projects beyond the single academic comparison.
- The format of Canvas `due_at` (ISO 8601 UTC) and override semantics were not verified against Canvas Assignments API docs in this pass.

## 7. Licensing and community health files

### Takeaway
Use Apache-2.0 (or MIT) for maximum adoption. Apache-2.0 adds an explicit patent grant and patent-retaliation clause, which suits a tool other people may build on. Choose AGPL-3.0 only to force anyone running a modified hosted version to publish their changes, at some cost to adoption. Add SECURITY.md (with private vulnerability reporting on), CONTRIBUTING.md, CODE_OF_CONDUCT.md, and issue forms that warn reporters never to paste tokens or logs containing them.

### Cited Findings
- MIT requires keeping the copyright and license notice and has no express patent grant. Apache-2.0 adds an express patent license from contributors plus a retaliation clause that ends a litigant's patent license, and requires keeping the license and any NOTICE file. — [credativ, Understanding open source licenses (Jan 2026)](https://www.credativ.de/en/blog/credativ-inside/understanding-open-source-licenses-gpl-mit-apache-compared/); [OSSAlt licensing guide 2026](https://ossalt.com/guides/oss-licensing-guide-mit-apache-agpl-2026) (secondary)
- AGPL-3.0 is network copyleft: running a modified AGPL app as a network service can require providing the source to its users. Purely internal or personal use rarely triggers the obligations. Many open-source SaaS alternatives use AGPL with dual commercial licensing. Apache-2.0 is incompatible with GPLv2. — [OSSAlt](https://ossalt.com/guides/oss-licensing-guide-mit-apache-agpl-2026); [CoderCops, open source licensing 2026](https://blog.codercops.com/blog/open-source-licensing-agencies-2026) (secondary)
- OpenSSF Scorecard includes "License" and "Security-Policy" checks. — [OpenSSF Scorecard v5](https://beta.pkg.go.dev/github.com/ossf/scorecard/v5)
- The Best Practices badge requires publishing a vulnerability reporting process. — [CHAOSS](https://chaoss.community/?p=3939)

### Inferences
- **Recommendation:** Apache-2.0. It is permissive, carries a patent grant, and is compatible with most Python dependencies (check for any GPLv2-only dependency). If the author later runs a hosted version and wants to discourage closed forks, AGPL-3.0 is the alternative, and the license must be chosen before outside contributions arrive. Relicensing later needs every contributor's consent, unless a CLA or DCO policy allows it.
- **Community files:**
  - `SECURITY.md`: supported versions, the private reporting link, a response SLA (for example acknowledgement within 7 days), scope ("the bot is read-only; token handling bugs are in scope"), and a "what to do if you leaked your token" section.
  - `CONTRIBUTING.md`: dev setup with `uv`, pre-commit, how to record cassettes safely, DCO sign-off.
  - `CODE_OF_CONDUCT.md`: Contributor Covenant.
  - `.github/ISSUE_TEMPLATE/*.yml` forms with a required checkbox: "I have removed all tokens, chat IDs, and emails from logs".
  - `PULL_REQUEST_TEMPLATE.md` and `CODEOWNERS`.

### Gaps
- No primary source (OSI, choosealicense.com, FSF) was fetched; the license summaries come from secondary blogs.
- The current Contributor Covenant version and GitHub issue-forms documentation were not retrieved.

## 8. Container hardening

### Takeaway
Ship a multi-stage image. Use either a distroless Python runtime (`:nonroot`) or `python:3.x-slim` with a fixed non-root UID, pinned by digest. Run it read-only with a tmpfs for `/tmp`, `cap_drop: [ALL]`, and `no-new-privileges`, with secrets mounted at `/run/secrets` and no inbound ports when using long polling. Scan with Trivy or Grype in CI and gate on HIGH/CRITICAL. Attach an SBOM and provenance attestation to each published image.

### Cited Findings
- A multi-stage build onto `gcr.io/distroless/python3-debian12`, using the `:nonroot` tag for distroless, and checking the runtime UID with `id`. — [CubePath, Container image hardening best practices](https://cubepath.com/docs/container-security/container-image-hardening-best-practices) (secondary)
- Run as non-root with a read-only root filesystem and dropped Linux capabilities, disallow privilege escalation, and pair distroless images with Trivy scans for HIGH/CRITICAL CVEs. — [Skillselion container-hardening](https://skillselion.com/skills/bagelhole/devops-security-agent-skills/container-hardening) (low-quality)
- Map `--cap-drop`, seccomp, and AppArmor to CIS Docker Benchmark v1.8.0. Validate with docker-bench-security, Hadolint, and Dockle. Verify that `whoami` is non-root and that filesystem writes fail. — [Agent Wiki, hardening Docker containers](https://moltchat-agent-commons.onrender.com/wiki/hardening-docker-containers-for-production_skill_(Anthropic-Cybersecurity-Skills)) (low-quality)
- Compose secrets mount at `/run/secrets/<name>` and stay out of `docker inspect`. — [Phase.dev](https://phase.dev/blog/docker-compose-secrets/)
- Artifact attestations (provenance, and SBOMs through `attest-sbom`) can be attached to container images pushed to a registry. — [GitHub Docs, artifact attestations](https://docs.github.com/actions/security-guides/using-artifact-attestations-to-establish-provenance-for-builds)

### Inferences
- **Reference Compose service:**
  - `user: "10001:10001"`
  - `read_only: true`
  - `tmpfs: ["/tmp"]`
  - `cap_drop: ["ALL"]`
  - `security_opt: ["no-new-privileges:true"]`
  - a named volume only for the state DB (`/data`, owned by 10001)
  - `secrets:` for the Canvas, Telegram, and SMTP credentials
  - no `ports:` (long polling), `restart: unless-stopped`, and memory/CPU limits
  - a healthcheck that does not print secrets
- **Distroless trade-off:** distroless Python follows Debian's Python version and has no shell, which makes debugging harder. `python:3.13-slim` with a non-root user is a pragmatic alternative. Either way, pin by `@sha256:` digest and let Dependabot's `docker` ecosystem bump it.
- **CI:** `hadolint` on the Dockerfile; build; Trivy (or Grype) scan with SARIF upload to code scanning, failing on fixable HIGH/CRITICAL; syft SBOM; `attest-build-provenance` plus `attest-sbom`; push to GHCR by digest.

### Gaps
- Official Docker, Google distroless, Aqua Trivy, and Anchore Grype documentation could not be fetched. The container findings rest on secondary or low-quality sources and should be cross-checked against the CIS Docker Benchmark and the official docs.
- No source covered rootless Docker or Podman as an alternative for home-server users.
