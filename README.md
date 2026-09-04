# social-media-benchmarks

Energy benchmarks for the major social media platforms, measured through a real browser with the
[Green Metrics Tool](https://github.com/green-coding-solutions/green-metrics-tool).

The question is whether platforms that show you broadly the same thing — a scrolling feed of short
posts — differ meaningfully in what they cost to render, and where that cost sits: in bytes, in
JavaScript, in idle polling, or in how much DOM they keep alive as you scroll.

## Status

Which scenarios are actually runnable, as of the last verification pass. "Verified" means the whole
scenario was replayed command-by-command against a live account, including publishing a post and
deleting it again, with the account confirmed back at 0 posts afterwards.

| Platform | Runnable | Scenario | Variables needed | Anchor feed |
| --- | --- | --- | --- | --- |
| X | **yes** | `usage_scenario_x.yml` | `USERNAME`, `PASSWORD` | `x.com/TechCrunch` |
| Mastodon | **yes** | `usage_scenario_mastodon.yml` | `USERNAME`, `PASSWORD`, `INSTANCE` | `@techcrunch@threads.net` (bridged from Threads) |
| Bluesky | **yes** | `usage_scenario_bluesky.yml` | `USERNAME`, `PASSWORD` | `bsky.app/profile/techcrunch.com` |
| Reddit | **yes** | `usage_scenario_reddit.yml` | `USERNAME`, `PASSWORD` | `r/technology` |
| LinkedIn | **no** | `usage_scenario_linkedin.yml` | `USERNAME`, `PASSWORD`, `SESSION` | `linkedin.com/company/techcrunch` |
| Threads | **no** | `usage_scenario_threads.yml` | `USERNAME`, `PASSWORD` | `threads.com/@techcrunch` |

Variable names are `__GMT_VAR_SECRET_<NAME>__` except `INSTANCE`, which is `__GMT_VAR_INSTANCE__`
(a public hostname, deliberately not secret so runs can be grouped by instance).

**The four that work, in detail:**

| Platform | Commands | Failures | Slowest command |
| --- | --- | --- | --- |
| X | 46 | 0 | 27.2 s |
| Mastodon | 43 | 0 | 26.3 s |
| Bluesky | 45 | 0 | 26.4 s |
| Reddit | 45 | 0 | 33.8 s (Login) |

**The two that do not:**

| Platform | Blocked by | What would unblock it |
| --- | --- | --- |
| LinkedIn | Device checkpoint — mails a code to the account on every credential login, and GMT starts a fresh browser profile every run | A `li_at` session cookie passed as `__GMT_VAR_SECRET_SESSION__` |
| Threads | Instagram rejects the password (`{"user":true,"authenticated":false}`) | Correct credentials, and a Threads profile created once interactively |

Everything past both logins is unverified — assume selectors there are wrong until proven otherwise.

**The anchor feed is the point of the comparison.** Every scenario scrolls the platform's own
personalised home feed *and* a TechCrunch feed, and TechCrunch publishes the same articles to all
of these. The home-feed numbers tell you what a real session costs; the anchor-feed numbers are the
closest thing to a controlled comparison, because the underlying content is genuinely the same.

Reddit is the weak link: TechCrunch has no Reddit presence, so it uses `r/technology`, which carries
similar content but not the same items. Treat Reddit's anchor number as indicative, not comparable.

## Running one

```bash
cd /home/didi/code/green-metrics-tool
./runner.py \
  --uri /home/didi/code/social-media-benchmarks \
  --filename usage_scenario_bluesky.yml \
  --variable '__GMT_VAR_SECRET_USERNAME__=me.bsky.social' \
  --variable '__GMT_VAR_SECRET_PASSWORD__=...'
```

`--variable` is singular and repeated once per variable. `--uri-type` is not needed for a local
path — GMT detects the folder.

Mastodon additionally needs `__GMT_VAR_INSTANCE__`, a bare hostname with no scheme:

```bash
  --variable '__GMT_VAR_INSTANCE__=mastodon.social'
```

GMT rejects a run if a supplied variable is unused *or* if a placeholder is left unreplaced, so the
list above is exactly what each scenario needs — no more, no less.

Always single-quote the values in your shell. Generated passwords routinely contain `!`, `$` and
`%`, which bash would otherwise eat before GMT ever sees them.

### Smoke runs, for tuning selectors

A full scenario is roughly 18 minutes — two 300 s scrolls, two 60 s idles, and settle time in
between. **`--dev-no-sleeps` does not shorten it**: that flag only suppresses GMT's own internal
sleeps (`_custom_sleep`), not `sleep` commands inside a flow or `sleep()` inside a Playwright
command.

So every platform has a `_smoke` variant with the same 21 phases in the same order, but 20 s
scrolls and 5 s idles — about 4 minutes end to end — and **running headful**, so you can watch what
the browser is actually doing when a selector misses.

```bash
./runner.py \
  --uri /home/didi/code/social-media-benchmarks \
  --filename usage_scenario_x_smoke.yml \
  --variable '__GMT_VAR_SECRET_USERNAME__=@handle' \
  --variable '__GMT_VAR_SECRET_PASSWORD__=...' \
  --allow-unsafe \
  --dev-no-system-checks=check_ssh_session
```

`--allow-unsafe` is required and not optional here. Headful means mounting `/tmp/.X11-unix` into
the container, and in safe mode GMT rebases absolute mount paths into the repo folder
(`lib/scenario_runner.py`), so the mount silently would not be your X socket. You also need an X
server on `DISPLAY=:0` — fine on a desktop, which is where you should be debugging anyway.

Smoke numbers are not comparable to anything. Headful rendering alone changes the energy profile;
these files exist to make the debugging loop watchable, not to measure.

### Before you run

```bash
python3 validate_scenarios.py
```

This catches the failure modes that otherwise surface ten minutes into a measurement: single quotes
in a Playwright command, anything mangled by GMT's shell round trip, JS syntax errors, credentials
that would break the YAML parse, undeclared custom metrics, and flow names GMT would reject.

## Submitting to the cluster

Cluster runs go through `submit_software.py` from the `gmt-helpers` repo, which posts to
`/v1/runs/add`. Two prerequisites that are easy to miss:

1. **The cluster clones from GitHub, not from your disk.** Commit and push before submitting, or
   the run measures whatever the remote happens to hold.
2. **This repository is private.** GMT must be able to clone it, which means an SSH key on your GMT
   user (Settings -> SSH private key). Without it the job fails at checkout.

Find the machine id first:

```bash
python3 /home/didi/code/gmt-helpers/api/submit_software.py --token "$GMT_AUTH_TOKEN" list-machines
```

Then submit one platform per call. `--variables` takes `KEY=VALUE` and may be repeated:

```bash
python3 /home/didi/code/gmt-helpers/api/submit_software.py \
  --token "$GMT_AUTH_TOKEN" submit \
  --name "Social Media - Bluesky" \
  --repo-url "https://github.com/green-coding-solutions/social-media-benchmarks" \
  --branch main \
  --filename usage_scenario_bluesky.yml \
  --machine-id <ID> \
  --schedule-mode one-off \
  --variables "__GMT_VAR_SECRET_USERNAME__=<handle>" \
  --variables "__GMT_VAR_SECRET_PASSWORD__=<password>"
```

Mastodon additionally needs `--variables "__GMT_VAR_INSTANCE__=mastodon.social"`.

Note `submit_software.py` calls `.strip()` on both key and value, so a credential with leading or
trailing whitespace would be silently altered. None of ours have any.

For repeated measurements use `--schedule-mode variance` (or `daily`) instead of `one-off`. A single
run is roughly 18 minutes per platform.

## Credentials

Credentials use GMT's secret variable mechanism (`__GMT_VAR_SECRET_*__`, added in GMT commit
`6ec96687`), so they are safe to use on the cluster:

- Secret variables are **encrypted before storage** with the key from
  `security.encryption_public_key_file`, and only the encrypted form reaches the `runs`, `jobs` and
  `watchlist` tables or the frontend (`lib/utils.py: encrypt_secret_usage_scenario_variables`).
- On a machine with **no encryption key configured** — the usual local CLI case — they are stored
  **redacted** rather than encrypted. GMT prints a warning and persists
  `*****GMT-REDACTED*****`. The plaintext is never written either way.
- The decrypted plaintext is registered with `utils.register_sensitive_values()`, so
  `filter_sensitive_data()` scrubs it from everything GMT prints or persists — including the
  container's `docker run -e` arguments and the IPC process's `Evaluating <command>` log lines.
  Values shorter than 4 characters are ignored, to avoid garbling unrelated output.

`__GMT_VAR_INSTANCE__` is deliberately *not* secret: it is a public hostname, and leaving it visible
means you can filter and group runs by instance in the GMT timeline. If you would rather have the
account handle visible for the same reason, rename `__GMT_VAR_SECRET_USERNAME__` to
`__GMT_VAR_USERNAME__` in `build_scenarios.py` and regenerate.

### Two implementation details worth knowing

**Credentials are passed as container env vars, not inlined into Playwright commands.** Log
scrubbing makes inlining safe now, but env vars remain better: env values may contain any character,
while a Playwright command may not contain a single quote at all (see below).

**The env values use literal block scalars.** GMT substitutes `__GMT_VAR_*__` into this file as raw
text *before* the YAML is parsed, so a plain mapping breaks on any credential that starts with `@`
or `%`, or contains a quote or a colon — a YAML `ScannerError`, not a login failure. Inside a block
scalar every character is literal:

```yaml
    environment:
      GMT_SM_PASSWORD: |-
        __GMT_VAR_SECRET_PASSWORD__
```

`validate_scenarios.py` substitutes deliberately hostile values and asserts they survive the parse
byte for byte, so this cannot silently regress.

## What each run measures

21 flow steps, one per action, with identical names across all six platforms so the phases line up
in GMT's comparison view.

| Phase | What it isolates |
| --- | --- |
| `Setup Browser Harness` *(hidden)* | context, stealth patches, helpers |
| `Setup Platform Bindings` *(hidden)* | the `S` selector/URL map |
| `Warm Cache` *(hidden)* | fills the squid cache, then discards the context |
| `Login` | the auth flow, typed at human speed |
| `Load Home Feed` | cold cookies, warm HTTP cache — app shell + first paint |
| `Idle On Home Feed` | 60 s of nothing. Pure background polling, timers, animation, ads |
| `Scroll Home Feed Timed` | 300 s of scrolling — infinite scroll and lazy loading |
| `Scroll Home Feed Fixed Ticks` | 400 wheel ticks on a fresh context — same distance, variable time |
| `Scroll Back To Top` | scroll restoration, re-render on the way up |
| `Load Anchor Feed` | the cross-platform load comparison |
| `Scroll Anchor Feed Timed` | the cross-platform scroll comparison |
| `Open Post And Thread` | deep comment tree rendering |
| `Open Image Lightbox` | image decode, compositing, gallery paging |
| `Search With Typing` | typeahead — most platforms fire a request per keystroke |
| `Compose And Publish Post` | draft autosave, character counting, link preview fetch |
| `Delete Published Post` | the write path, and it cleans up after itself |
| `Like And Unlike` | optimistic UI re-render |
| `Open Notifications` | |
| `Navigate Tabs` | client-side routing vs full document loads |
| `Background Tab Idle` | 60 s hidden behind a blank tab — does the app throttle its timers? |
| `Logout` | |

**Timed and fixed-tick scrolling are both there on purpose.** Timed scrolling flatters a platform
that loads slowly, because it renders fewer posts per minute. Fixed-tick scrolling flatters a
platform with tall, sparse cards. Reading them together, alongside `feed_posts_rendered`, separates
"slow to load" from "expensive to render".

### Custom metrics

Every phase emits a page-weight snapshot from inside the browser, so energy can be normalised rather
than compared raw:

| Metric | Unit | Source |
| --- | --- | --- |
| `page_load_ms` | ms | Navigation Timing |
| `page_dom_content_loaded_ms` | ms | Navigation Timing |
| `page_transfer_bytes` | Bytes | Resource Timing, cumulative — includes lazy-loaded content |
| `page_requests` | Requests | Resource Timing entry count |
| `page_dom_nodes` | Nodes | live element count |
| `feed_posts_rendered` | Posts | count of feed items in the DOM |
| `scroll_ticks` | Ticks | wheel events issued |

These reach GMT via `logNote()` in the IPC process, which emits
`<microsecond timestamp> <key>=<int>` — matching GMT's default custom-metric regex — and are
attributed to whichever phase was active when they were emitted.

`feed_posts_rendered` is what makes energy-per-post computable, and it is the number to watch: a
platform that renders half as many posts per scroll will look artificially green on a per-minute
basis.

Alongside these, the machine's own providers give you `network_io_cgroup_container` (bytes in and
out of the browser container) and, if enabled, `network_connections_proxy_container`, which logs
every domain contacted — likely a headline result on its own for the ad-heavy platforms.

## Editing

Do not hand-edit the `usage_scenario_*.yml` files. They are generated:

```bash
python3 build_scenarios.py && python3 validate_scenarios.py
```

`build_scenarios.py` holds the shared harness once, a `PLATFORMS` table for the parts that differ,
and a `PROFILES` table for the full and smoke timings. A change to scrolling or page reporting lands
in all twelve files identically instead of drifting. The generated files are still fully
self-contained — GMT needs nothing but the `.yml`.

### Two hard limits

**No single quotes in a `type: playwright` command.** GMT ships them via
`bash -ec "echo '<command>' > /tmp/playwright-ipc-commands"`, and a single quote terminates that
shell quote. Use double quotes, and backticks when a selector needs embedded double quotes:

```js
await page.locator(`[data-testid="tweet"]`).click();
```

**No playwright command may run longer than 60 seconds.** GMT hard-kills each one at 60 s
(`lib/scenario_runner.py`, a literal `timeout=60`; the old `--measurement-playwright-process-duration`
flag no longer exists). This is why `build_scenarios.py` emits a 300 s scroll as twelve 25 s
`gmtScrollChunk()` commands inside one flow step — same phase, same total duration, no command near
the ceiling. Tick counts accumulate in a global across the chunks and are reported once.

Related: `getByRole(role, {name: "X"})` matches by **substring** by default. A bare
`{name: "Continue"}` on X's login page also matches *"Continue with phone"* and silently routes into
phone signup. Every role matcher here uses an anchored, case-insensitive regex —
`{name: /^Continue$/i}` — which gives whole-string matching without betting on capitalisation.

Multi-line commands are fine — the shipped GMT templates use them. `shell: bash` is set on every
Playwright command so backslashes pass through literally (dash's builtin `echo` would interpret
them). `build_scenarios.py` asserts on single quotes; `validate_scenarios.py` re-checks by actually
running the round trip.

### State across commands

Each command is a separate `eval` in the IPC process, so declare shared state *without* `let` or
`const` to land it on the global object. `S`, `page_result`, `bgPage` and every `gmt*` helper work
this way. `page`, `context`, `browser`, `sleep` and `logNote` come from the IPC script itself and
can be reassigned — which is how `gmtNewContext()` swaps in a fresh context mid-run.

## Checking selectors without a measurement run

`tools/` holds two things that make selector work cheap. Both run in the same
`mcr.microsoft.com/playwright:v1.62.1-noble` image GMT uses, so what they see is what a run sees.

**`tools/probe_selectors.js`** loads a page and reports which candidate selectors resolve, plus an
inventory of the inputs, buttons and `data-testid`s actually present. This is how the selectors
below were established rather than guessed:

```bash
docker run -d --name probe -v "$PWD/tools:/probe:ro" -w /tmp/work \
  mcr.microsoft.com/playwright:v1.62.1-noble sh -c "mkdir -p /tmp/work && tail -f /dev/null"
docker exec probe bash -c "cd /tmp/work && npm init -y >/dev/null && npm install playwright@1.62.1 >/dev/null"
docker cp tools/probe_selectors.js probe:/tmp/work/
docker exec probe bash -c 'cd /tmp/work && node probe_selectors.js "[{\"name\":\"x\",\"url\":\"https://x.com/i/flow/login\",\"dumpInputs\":true,\"selectors\":{}}]"'
```

**`tools/gmt_schema_check.py`** runs GMT's own `SchemaChecker` over the generated files, after
reproducing the include-merge and flow-prepend handling, and asserts that credential-shaped values
survive the parse and that each profile has the right headless mode and X11 mount:

```bash
GMT_DIR=/home/didi/code/green-metrics-tool python3 tools/gmt_schema_check.py
```

**`tools/extract_commands.py` + `tools/run_locally.js`** replay a scenario's Playwright commands
against a live browser, in order, timing each one and flagging any that approach the 60 s ceiling.
It reproduces the globals the IPC provides, so it is the same code path minus the measurement:

```bash
python3 tools/extract_commands.py usage_scenario_x_smoke.yml > cmds.json
docker cp cmds.json probe:/tmp/work/ && docker cp tools/run_locally.js probe:/tmp/work/
docker exec -e GMT_SM_USERNAME=... -e GMT_SM_PASSWORD=... probe \
  bash -c "cd /tmp/work && node run_locally.js cmds.json --skip 'Compose And Publish Post'"
```

`--skip` takes flow step names, which is how you leave the publishing steps out while checking
everything else.

## Selector status

Probed live on 2026-08-20. Anything not marked verified is still a guess.

| Platform | Login | Feed / actions |
| --- | --- | --- |
| X | **verified end to end** | **verified end to end**: 46 commands, 0 failures, 0 warnings, including publishing a post and deleting it again |
| Mastodon | **verified end to end** — against mastodon.social | **verified end to end**: 42 commands, 0 failures, 0 warnings, including publishing a post and deleting it again |
| Bluesky | **verified end to end** | **verified end to end**: 44 commands, 0 failures, 0 warnings, including publishing a post and deleting it again |
| LinkedIn | **cannot be logged in unattended** — needs a `li_at` session cookie, see below | unverified (blocked behind the login) |
| Reddit | **verified end to end** — the JS challenge does not block a real browser | **verified end to end**: 43 commands, 0 failures, including publishing to r/test and deleting it again |
| Threads | login flow **verified up to submit**; credentials rejected by Instagram — see below | **not ready** (blocked behind the login) |

Three things the probing turned up that apply broadly:

- **Cookie consent walls gate several platforms.** X and Threads both block interaction until
  dismissed, and Threads renders *zero* inputs until then. Worse, Playwright's `.click()` times out
  on both because the overlay fails its actionability check — a DOM click goes straight through.
  `gmtDismissConsent()` and `gmtClick()` handle this, and `S.consent` lists the button labels to
  try, most privacy-preserving first.
- **X's logged-out pages are a different render from the logged-in app.** `x.com/TechCrunch` shows
  five `article` elements and exactly one `data-testid`. Every feed step here runs authenticated, so
  the testid selectors are right — but do not tune them against a logged-out page.
- **Desktop and mobile layouts do not share selectors.** Bluesky's `bottomBar*`, `composeFAB` and
  `searchBtn` testids simply do not exist at 1920x1080 — the desktop rail uses `aria-label`
  instead, and its composer is an unlabelled `contenteditable` inside `composePostView`. A testid
  found in a mobile screenshot or a blog post is not evidence.
- **A control that renames itself when active cannot be toggled by one selector.** Mastodon's
  favourite button becomes "Remove from favourites", so runs silently accumulated likes on the
  anchor account until `S.unlike` was added. The like step now clears leftover state first and
  leaves the account as it found it.
- **Reddit is web components with shadow DOM.** Playwright locators pierce open shadow roots;
  `page.evaluate` with `querySelectorAll` does not. Enumerating Reddit's post menu through
  `evaluate` showed only "Share" and hid the Delete entry entirely. Stay in locator land there.
- **Confirmation buttons rarely say what you expect.** Reddit's delete confirmation reads
  "Yes, Delete", so an anchored `/^Delete$/i` never matched and the post survived.
- **Some apps call `performance.clearResourceTimings()`.** On X, reading the resource timing buffer
  flatlined at 66992 bytes while the DOM grew from 3429 to 5156 nodes. `page_transfer_bytes` and
  `page_requests` are therefore counted by a `PerformanceObserver` installed before any page script
  runs, which cannot be cleared. GMT's `network_io_cgroup_container` remains the authoritative byte
  figure; treat the in-page numbers as the per-page breakdown.

**X**, **Mastodon**, **Bluesky** and **Reddit** have each been replayed in full against a live
account — every step including `Compose And Publish Post` and `Delete Published Post` — with 0
failures and 0 warnings, and every account verified back at 0 posts afterwards. All four were
re-run against the current generated files after the last harness change, so the verification
matches what is in the repo rather than an earlier revision:

| Platform | Commands | Failures | Slowest command |
| --- | --- | --- | --- |
| X | 46 | 0 | 27.2 s |
| Mastodon | 43 | 0 | 26.3 s |
| Bluesky | 45 | 0 | 26.4 s |
| Reddit | 45 | 0 | 33.8 s (Login) |

Every command sits well inside GMT's 60 s ceiling. Reddit was the tightest at 38.5 s until its
compose step was split a second time — it is the only platform that types two fields there.

**LinkedIn** and **Threads** are both blocked at the login, for different reasons — see below.
Nothing past either login is verified.

Reddit's JS challenge turned out not to be a blocker: it gates scripted HTTP clients, not a real
browser. `curl` gets a bot wall where Playwright logs in normally.

### Threads: the flow works, the credentials did not

The login sequence is verified as far as submitting, and it is more involved than it looks.
`threads.com/login` renders **zero inputs**. Only after *both* the Meta consent wall is dismissed
*and* "Use your Instagram account" is clicked do three inputs appear. The consent buttons refuse a
Playwright click, so `gmtDismissConsent` uses a DOM click; the submit control is a `div` with
`role=button`, not a real button.

The submit reached Instagram and came back:

```json
{"user":true,"authenticated":false,"status":"ok"}
```

`user: true` means the account exists and the identifier resolved; `authenticated: false` means the
password was rejected. A checkpoint would have carried a `checkpoint_url`, and an unknown account
would return `user: false` — so this is a plain credential mismatch, not bot detection.

Worth knowing: **Instagram reports this as HTTP 200 with no visible error on the page.** The form
just sits there. The scenario now throws if it is still on `/login` after submitting, so a bad
password fails the run loudly instead of quietly measuring a logged-out wall.

Everything past the login — feed, compose, delete, tabs, logout — remains unverified guesswork.
Retry sparingly: repeated failed Instagram logins invite a lockout or an IP block.

### LinkedIn needs a session cookie

LinkedIn accepts the credentials and then refuses to finish:

> Let's do a quick verification. The login attempt seems suspicious. To finish signing in please
> enter the verification code we sent to your email address.

This is not a selector problem and not a one-off — it reproduces every time. GMT starts a **fresh
browser profile on every run**, so LinkedIn sees an unrecognised device each time and always
challenges. No unattended run can read an emailed code, so credential login is simply not available
here.

The way through is to restore an existing session. Log in once in a normal browser, then copy the
`li_at` cookie (DevTools → Application → Cookies → `https://www.linkedin.com` → `li_at`) and pass it
as `__GMT_VAR_SECRET_SESSION__`:

```bash
  --variable '__GMT_VAR_SECRET_SESSION__=AQEDAT...'
```

Treat that value exactly like a password — it *is* a full session. It is a secret variable, so it is
encrypted at rest and scrubbed from logs like the others. It expires, and logging out or changing
the password invalidates it, so expect to refresh it periodically. Passing the literal `none`
attempts the credential path instead, which will fail at the checkpoint with a clear message rather
than quietly measuring a logged-out page.

One consequence for comparability: LinkedIn's `Login` phase restores a session rather than
performing a credential login, so that single phase is not comparable with the other platforms.
Every other phase is.

Two other things LinkedIn does differently, both fixed:

- **Its login page contains no `<form>` element at all**, and renders two input pairs of which the
  first is hidden. Anything scoped to a form finds nothing, and a plain `.first()` picks the hidden
  one — hence page-wide selectors with `:visible`.
- **It picks its UI language from the request IP, not `Accept-Language`.** From a German IP it
  serves German, so the submit button reads "Einloggen" and every English text matcher misses.
  `S.cookies` now pins `lang=v=2&lang=en_US`, which also keeps runs from different locations
  comparable — a different language means different text, different fonts and different bytes.

### Publish-then-fail-to-delete is the failure mode to watch

It happened on **both** Mastodon and Bluesky before being fixed: the post published, the delete step
could not find it, and a public post stayed up. Two different causes — Mastodon's status menu
entries are plain buttons rather than `role=menuitem`, and Bluesky's Following feed does not
reliably show a post you just made.

Both delete steps now work from the **profile page**, where your own posts always appear, and X was
changed to match even though its delete is still unproven. If you see
`WARNING could not find own post to delete` in a run, go check the account. The public APIs make
this cheap:

```bash
curl -s "https://public.api.bsky.app/xrpc/app.bsky.actor.getProfile?actor=HANDLE" | grep -o '"postsCount":[0-9]*'
curl -s "https://mastodon.social/api/v1/accounts/lookup?acct=HANDLE" | grep -o '"statuses_count":[0-9]*'
```

Two more things the Mastodon run cost before they were fixed:

- **A publish that succeeds followed by a delete that fails leaves a public post up.** That happened
  once here. The delete step was looking for `role=menuitem`, but Mastodon's status menu entries are
  plain buttons inside `.dropdown-menu`. If you see `WARNING could not find own post to delete` in a
  run, check the account.
- **`page.mouse.wheel` has no actionability timeout and can block indefinitely.** One tick on
  Mastodon's virtualised column hung for 845 s, which GMT would have killed at 60 s. Every tick is
  now raced against a 6 s wall clock (`gmtWheel`), and a stalled tick ends its chunk with a warning
  instead of taking the run down.

A note on the harness rather than the platforms: the container needs working DNS. One run failed
entirely with `NS_ERROR_UNKNOWN_HOST` on every navigation when the configured resolver stopped
answering, which shows up as `page_dom_nodes=13` (an error page) rather than as an obvious network
error.

Steps that cannot find their target log a `WARNING step skipped, ...` note and continue. `Login`
and the feed status check still throw, because a wrong login makes every later number meaningless.
After a run, `grep WARNING` the logs; fix anything it names in `Setup Platform Bindings`, which is
the only place selectors live.

## Detection

The scenarios run headless Firefox, which is far less detectable than headless Chromium: the user
agent is identical to headful Firefox, so it is not advertised. On top of that:

- `navigator.webdriver` is patched to `false` via `addInitScript`
- a realistic viewport, locale and timezone are set
- typing uses `pressSequentially` with a randomised 80–160 ms per-keystroke delay
- scrolling uses randomised wheel deltas and randomised pauses
- clicks are separated by randomised human-scale pauses

The user agent is deliberately *not* overridden — Playwright's real Firefox UA is more consistent
than any string we could substitute, and a UA that disagrees with the engine is itself a signal.

If X or LinkedIn still challenge the login, the next lever is headful, which the `_smoke` files
already are. To make a *measurement* run headful, switch its profile in `build_scenarios.py` to the
headful helper and regenerate — and remember that from then on the run needs `--allow-unsafe`, an X
server, and that its numbers are no longer comparable to the headless ones.

Note that squid MITMs TLS for the cache, which is itself a mild signal. Dropping to
`gmt-playwright.yml` (no cache, no proxy) is a one-line change if a platform proves sensitive to it.

## Posting

`Compose And Publish Post` publishes real content to real accounts and `Delete Published Post`
removes it again. The text is explicitly marked as an automated test post. Reddit posts to `r/test`,
which exists for this purpose. If a delete step cannot find its post it logs a warning rather than
failing, so **check the accounts after the first few runs** to be sure nothing is accumulating.

## Prior work

`user_journeys/` holds the earlier standalone Playwright scripts for X and Mastodon. They are kept
for reference — the selector knowledge in them is still good — but they are not part of the GMT
flow. The `pass`-based credential lookup in the login examples is what the `__GMT_VAR_*__` variables
replace.
