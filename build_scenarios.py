#!/usr/bin/env python3
"""Generates one self-contained GMT usage scenario per platform.

Every scenario gets the *same* flow step names so phases line up when you compare
runs across platforms in the Green Metrics Tool. The measurement harness (browser
context, stealth patches, scroll helpers, page-weight reporting) is defined once
here and emitted verbatim into each file, so it cannot drift between platforms.

Only the PLATFORMS table below is platform specific.

Run:  python3 build_scenarios.py && python3 validate_scenarios.py
"""
import textwrap
from pathlib import Path

ROOT = Path(__file__).parent

# --dev-no-sleeps only suppresses GMT's own internal sleeps, not the sleeps inside a
# flow, so a full scenario is ~18 minutes even in dev mode. The smoke profile exists to
# make the selector-tuning loop bearable: same 21 phases, same order, ~4 minutes.
# GMT hard-kills any single `type: playwright` command after 60 seconds
# (lib/scenario_runner.py, `timeout=60`), and there is no longer a flag to raise it.
# Long scrolls are therefore emitted as several short commands inside one flow step:
# same phase, same total duration, no command anywhere near the ceiling.
CHUNK_SECONDS = 25
CHUNK_TICKS = 60


def scroll_seconds_blocks(total, selector):
    """A timed scroll as chunked commands, all landing in the caller's flow step."""
    blocks = [js_block('gmtScrollReset();')]
    remaining = total
    while remaining > 0:
        step_len = min(CHUNK_SECONDS, remaining)
        blocks.append(js_block(f'await gmtScrollChunk({step_len});'))
        remaining -= step_len
    blocks.append(js_block(f'await gmtScrollReport({selector});'))
    return blocks


def scroll_ticks_blocks(total, selector):
    blocks = [js_block('gmtScrollReset();')]
    remaining = total
    while remaining > 0:
        step_len = min(CHUNK_TICKS, remaining)
        blocks.append(js_block(f'await gmtTickChunk({step_len});'))
        remaining -= step_len
    blocks.append(js_block(f'await gmtScrollReport({selector});'))
    return blocks


PROFILES = {
    '': dict(scroll_seconds=300, scroll_ticks=400, idle_seconds=60, sub_ticks=60,
             helper='gmt-playwright-with-cache.yml', headless='true', label=''),
    # Headful, because the whole point of a smoke run is watching what the browser actually does.
    # The headful partial mounts /tmp/.X11-unix and sets DISPLAY, which means these files need
    # --allow-unsafe (GMT rebases absolute mount paths into the repo folder in safe mode).
    '_smoke': dict(scroll_seconds=20, scroll_ticks=25, idle_seconds=5, sub_ticks=10,
                   helper='gmt-playwright-headful-with-cache.yml', headless='false',
                   label=' (smoke, headful)'),
}

# ---------------------------------------------------------------------------
# Harness. Emitted identically into every scenario.
#
# Hard constraint on every `type: playwright` command: no single quotes. GMT ships
# them via `bash -ec "echo '<command>' > <fifo>"` and a single quote breaks that
# shell quoting. Use backticks when a selector needs embedded double quotes.
# ---------------------------------------------------------------------------
HARNESS_CONTEXT = """
gmtCtxOpts = {viewport: {width: 1920, height: 1080}, locale: "en-US", timezoneId: "Europe/Berlin", ignoreHTTPSErrors: true};
gmtInit = () => {
  Object.defineProperty(navigator, "webdriver", {get: () => false});
  // Counting via an observer rather than reading the resource timing buffer: several of
  // these apps call performance.clearResourceTimings(), which silently zeroes the buffer
  // mid-session. Verified on X, where buffer reads flatlined while the DOM kept growing.
  window.__gmtBytes = 0;
  window.__gmtRequests = 0;
  try {
    performance.setResourceTimingBufferSize(20000);
    const observer = new PerformanceObserver((list) => {
      for (const entry of list.getEntries()) {
        window.__gmtBytes = window.__gmtBytes + (entry.transferSize || 0);
        window.__gmtRequests = window.__gmtRequests + 1;
      }
    });
    observer.observe({type: "resource", buffered: true});
  } catch (e) { }
};
gmtNewContext = async () => {
  if (context) { await context.close(); }
  context = await browser.newContext(gmtCtxOpts);
  // Deliberately below the hard 60s cap GMT puts on a playwright command, so a stuck locator
  // surfaces as a readable Playwright error rather than a bare docker exec timeout.
  context.setDefaultTimeout(20000);
  context.setDefaultNavigationTimeout(30000);
  await context.addInitScript(gmtInit);
  // Some platforms pick their UI language from the request IP rather than Accept-Language.
  // LinkedIn served German to a machine in Germany, which breaks every text matcher and
  // makes runs from different locations incomparable. S.cookies pins it.
  if (typeof S !== "undefined" && S.cookies) { await context.addCookies(S.cookies); }
  page = await context.newPage();
};
gmtRnd = (min, max) => min + Math.floor(Math.random() * (max - min));
gmtHuman = async () => { await sleep(gmtRnd(400, 1400)); };
gmtVisible = async (loc) => { try { return await loc.first().isVisible({timeout: 5000}); } catch (e) { return false; } };
// Waits for something a step needs. Returns null and warns instead of throwing, so one
// stale selector costs that step rather than the whole run. Steps where a failure would
// invalidate everything downstream (Login, the feed status check) still throw.
gmtNeed = async (loc, label) => {
  try { await loc.first().waitFor({state: "visible", timeout: 20000}); return loc.first(); }
  catch (e) { logNote(`WARNING step skipped, ${label} not found`); return null; }
};
"""


HARNESS_CLICK = """
// Consent sheets and sign-up banners overlay the page, so Playwright refuses to click
// what is underneath even though it is visible. Verified on X and Threads: .click()
// times out where a DOM click goes straight through. Try the honest click first, since
// it is the one that dispatches realistic events, then fall back.
gmtClick = async (loc, label) => {
  const l = loc.first();
  try { await l.click({timeout: 15000}); return true; }
  catch (e) {
    try { await l.evaluate((el) => el.click()); return true; }
    catch (e2) { logNote(`WARNING click failed, ${label}`); return false; }
  }
};
gmtType = async (loc, text) => {
  const l = loc.first();
  try { await l.click({timeout: 10000}); } catch (e) { await l.focus(); }
  await gmtHuman();
  // A 200 character post at a full human cadence is ~24s of typing, which overruns both
  // the 20s action timeout and a meaningful slice of the 60s command budget. Keep the
  // per-key delay human for short fields and scale it down for post-length text.
  const delay = text.length > 60 ? gmtRnd(25, 55) : gmtRnd(80, 160);
  await l.pressSequentially(text, {delay: delay, timeout: 45000});
};
// S.consent lists the button labels to try, most privacy preserving first. Matching on
// exact innerText because none of these platforms give the buttons a stable attribute.
gmtDismissConsent = async () => {
  if (!S.consent || S.consent.length === 0) { return null; }
  const hit = await page.evaluate((wanted) => {
    const nodes = Array.from(document.querySelectorAll("button,[role=button],div[role=button],a"));
    for (const w of wanted) {
      const el = nodes.find((n) => (n.innerText || "").trim() === w && n.offsetParent !== null);
      if (el) { el.click(); return w; }
    }
    return null;
  }, S.consent);
  if (hit) { logNote(`consent dismissed via ${hit}`); await sleep(5000); }
  else { logNote("no consent dialog found"); }
  return hit;
};
"""


HARNESS_REPORT = """
gmtNote = (k, v) => { logNote(`${k}=${Math.max(0, Math.round(v || 0))}`); };
gmtCount = async (sel) => { try { return await page.locator(sel).count(); } catch (e) { return 0; } };
gmtReportPage = async () => {
  const m = await page.evaluate(() => {
    const nav = performance.getEntriesByType("navigation")[0];
    const observed = window.__gmtBytes || 0;
    const requests = window.__gmtRequests || performance.getEntriesByType("resource").length;
    return {load: nav ? nav.duration : 0, dcl: nav ? nav.domContentLoadedEventEnd : 0, bytes: observed + (nav ? (nav.transferSize || 0) : 0), req: requests, nodes: document.getElementsByTagName("*").length};
  });
  gmtNote("page_load_ms", m.load);
  gmtNote("page_dom_content_loaded_ms", m.dcl);
  gmtNote("page_transfer_bytes", m.bytes);
  gmtNote("page_requests", m.req);
  gmtNote("page_dom_nodes", m.nodes);
};
"""

# Some platforms scroll an inner column rather than the document, so the wheel only
# works with the pointer over that column. S.feedHover / S.scrollRoot handle that.
HARNESS_SCROLL = """
gmtFocus = async () => { if (S.feedHover) { try { await page.locator(S.feedHover).first().hover({timeout: 5000}); } catch (e) { } } else { try { await page.mouse.move(960, 540); } catch (e) { } } };
// page.mouse.wheel has no actionability timeout and can block indefinitely on a busy
// virtualised feed - observed once on Mastodon at 845s for a single tick, which GMT
// would have killed at 60s. Race every tick against a wall clock.
gmtWithTimeout = async (promise, ms, label) => {
  let timer = null;
  const guard = new Promise((resolve, reject) => { timer = setTimeout(() => reject(new Error(`gmt timeout after ${ms}ms: ${label}`)), ms); });
  try { return await Promise.race([promise, guard]); }
  finally { clearTimeout(timer); }
};
gmtWheel = async () => {
  try { await gmtWithTimeout(page.mouse.wheel(0, gmtRnd(200, 460)), 6000, "mouse.wheel"); return true; }
  catch (e) { logNote("WARNING scroll tick stalled, ending this chunk early"); return false; }
};
// GMT kills any single playwright command at 60s (lib/scenario_runner.py), so a long
// scroll is emitted as several short chunks inside one flow step. Ticks accumulate in a
// global across the chunks and are reported once, so the phase still gets one figure.
GMT_TICKS = 0;
gmtScrollReset = () => { GMT_TICKS = 0; };
gmtScrollChunk = async (seconds) => {
  await gmtFocus();
  const deadline = Date.now() + (seconds * 1000);
  while (Date.now() < deadline) {
    if (!await gmtWheel()) { break; }
    GMT_TICKS = GMT_TICKS + 1;
    await sleep(gmtRnd(150, 450));
  }
};
gmtTickChunk = async (n) => {
  await gmtFocus();
  const deadline = Date.now() + 40000;
  for (let i = 0; i < n; i++) {
    if (!await gmtWheel()) { break; }
    GMT_TICKS = GMT_TICKS + 1;
    await sleep(gmtRnd(150, 450));
    if (Date.now() > deadline) { logNote("WARNING tick chunk hit its time guard"); break; }
  }
};
gmtScrollReport = async (sel) => {
  gmtNote("scroll_ticks", GMT_TICKS);
  gmtNote("feed_posts_rendered", await gmtCount(sel));
  await gmtReportPage();
};
gmtSettle = async (sel) => {
  gmtNote("feed_posts_rendered", await gmtCount(sel));
  await gmtReportPage();
};
gmtTop = async () => {
  await gmtFocus();
  if (S.scrollRoot) { await page.evaluate((sel) => { const el = document.querySelector(sel); if (el) { el.scrollTo({top: 0, behavior: "smooth"}); } }, S.scrollRoot); }
  else { await page.evaluate(() => window.scrollTo({top: 0, behavior: "smooth"})); }
  await sleep(4000);
};
gmtOpenFeed = async (url) => {
  page_result = await page.goto(url, {waitUntil: "domcontentloaded"});
  await sleep(3000);
  await gmtDismissConsent();
  try { await page.locator(S.post).first().waitFor({state: "visible", timeout: 20000}); } catch (e) { logNote(`WARNING no feed item matched ${S.post} on ${url}`); }
  await sleep(4000);
  await gmtSettle(S.post);
};
"""

POST_TEXT = ("This is an automated measurement post that will be deleted in a few minutes: "
             "Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor "
             "incididunt ut labore et dolore magna aliqua.")

CUSTOM_METRICS = [
    ('page_load_ms', 'ms'),
    ('page_dom_content_loaded_ms', 'ms'),
    ('page_transfer_bytes', 'Bytes'),
    ('page_requests', 'Requests'),
    ('page_dom_nodes', 'Nodes'),
    ('feed_posts_rendered', 'Posts'),
    ('scroll_ticks', 'Ticks'),
]


# ---------------------------------------------------------------------------
# Platform table.
#
# `bindings` defines S, the selector/URL map every generic step reads. Keys:
#   root, login, home, anchor, notifications, post, feedHover, scrollRoot, ...
# The action snippets below may use anything in S plus the harness helpers.
#
# Selectors for X, LinkedIn, Threads and Reddit are best-effort: those UIs are
# obfuscated and change often. See README.md -> "First run: tuning selectors".
# ---------------------------------------------------------------------------
PLATFORMS = {}

PLATFORMS['x'] = dict(
    title='X',
    blurb='X (Twitter), logged in, home timeline plus the shared anchor profile',
    env={'GMT_SM_USERNAME': '__GMT_VAR_SECRET_USERNAME__', 'GMT_SM_PASSWORD': '__GMT_VAR_SECRET_PASSWORD__'},
    bindings="""
S = {
  root: "https://x.com/",
  login: "https://x.com/i/flow/login",
  home: "https://x.com/home",
  anchor: "https://x.com/TechCrunch",
  notifications: "https://x.com/notifications",
  explore: "https://x.com/explore",
  consent: ["Refuse non-essential cookies", "Accept all cookies"],
  userInput: `input[name="username_or_email"]`,
  passInput: `input[name="password"]`,
  // Verified live while logged in 2026-08-20. Note the logged-out profile page is a
  // different, testid-free render - but every feed step here runs authenticated.
  post: `article[data-testid="tweet"]`,
  photo: `[data-testid="tweetPhoto"], article img[src*="media"]`,
  search: `[data-testid="SearchBox_Search_Input"]`,
  composer: `[data-testid="tweetTextarea_0"]`,
  publish: `[data-testid="tweetButtonInline"]`,
  like: `[data-testid="like"]`,
  unlike: `[data-testid="unlike"]`,
  caret: `[data-testid="caret"]`,
  confirm: `[data-testid="confirmationSheetConfirm"]`,
  accountMenu: `[data-testid="SideNav_AccountSwitcher_Button"]`,
  logout: `[data-testid="AccountSwitcher_Logout_Button"]`,
  tabs: [`[data-testid=AppTabBar_Explore_Link]`, `[data-testid=AppTabBar_Notifications_Link]`, `[data-testid=AppTabBar_Home_Link]`, `[data-testid=AppTabBar_Profile_Link]`, `[data-testid=AppTabBar_Home_Link]`]
};
""",
    login=["""
await page.goto(S.login, {waitUntil: "domcontentloaded"});
await sleep(9000);
await gmtDismissConsent();
""", """
// Two responsive copies of the form render at once; the first is the desktop one.
const form = page.locator("form").first();
const user = await gmtNeed(form.locator(S.userInput), "username field");
if (!user) { throw "X login: username field not found"; }
await gmtType(user, process.env.GMT_SM_USERNAME);
await gmtHuman();
// Anchored regex, not the bare string: getByRole name matching is substring based by
// default, and a plain "Continue" also matches "Continue with phone", which silently
// routes into the phone signup flow instead of logging in.
await gmtClick(page.getByRole("button", {name: /^Continue$/i}), "continue button");
await sleep(8000);
""", """
// The password input exists from the start but only becomes editable after Continue.
const pw = page.locator("form").first().locator(S.passInput).first();
await pw.waitFor({state: "visible", timeout: 20000});
await gmtType(pw, process.env.GMT_SM_PASSWORD);
await gmtHuman();
if (!await gmtClick(page.getByRole("button", {name: /^(Log in|Continue|Sign in)$/i}), "submit")) {
  await pw.press("Enter");
}
""", """
await page.waitForURL("**/home", {timeout: 45000});
await sleep(4000);
await gmtReportPage();
"""],
    compose=["""
await page.goto(S.home, {waitUntil: "domcontentloaded"});
await sleep(5000);
gmtBox = await gmtNeed(page.locator(S.composer), "composer");
""", """
if (!gmtBox) { return; }
await gmtType(gmtBox, GMT_POST_TEXT);
await sleep(3000);
await gmtClick(page.locator(S.publish), "publish");
await sleep(8000);
await gmtReportPage();
"""],
    delete="""
await page.goto(`https://x.com/${process.env.GMT_SM_USERNAME.replace("@", "")}`, {waitUntil: "domcontentloaded"});
await sleep(8000);
const own = page.locator(S.post).filter({hasText: "automated measurement post"}).first();
if (await gmtVisible(own)) {
  await gmtClick(own.locator(S.caret), "post caret");
  await sleep(2000);
  await sleep(2000);
  await gmtClick(page.getByRole("menuitem", {name: /^Delete$/i}), "delete menu item");
  await sleep(2000);
  await gmtClick(page.locator(S.confirm), "confirm delete");
  await sleep(4000);
} else { logNote("WARNING could not find own post to delete"); }
""",
    logout="""
const menu = await gmtNeed(page.locator(S.accountMenu), "account menu");
if (!menu) { return; }
await menu.click();
await sleep(3000);
await page.locator(S.logout).click();
await sleep(2000);
await page.locator(S.confirm).click();
await sleep(6000);
await gmtReportPage();
""",
)

PLATFORMS['mastodon'] = dict(
    title='Mastodon',
    blurb='Mastodon web client on a configurable instance, home timeline plus the shared anchor profile',
    env={'GMT_SM_USERNAME': '__GMT_VAR_SECRET_USERNAME__', 'GMT_SM_PASSWORD': '__GMT_VAR_SECRET_PASSWORD__'},
    bindings="""
S = {
  root: "https://__GMT_VAR_INSTANCE__/",
  login: "https://__GMT_VAR_INSTANCE__/auth/sign_in",
  home: "https://__GMT_VAR_INSTANCE__/home",
  anchor: "https://__GMT_VAR_INSTANCE__/@techcrunch@threads.net",
  notifications: "https://__GMT_VAR_INSTANCE__/notifications",
  explore: "https://__GMT_VAR_INSTANCE__/explore",
  consent: [],
  post: "article",
  photo: ".media-gallery__item img, .media-gallery img, .status__media img",
  search: "input.search__input",
  composer: "form.compose-form textarea",
  publish: "form.compose-form button.button--block",
  feedHover: ".scrollable",
  scrollRoot: ".scrollable",
  tabs: [`a[href$="/explore"]`, `a[href$="/notifications"]`, `a[href$="/favourites"]`, `a[href$="/lists"]`, `a[href$="/home"]`]
};
""",
    login=["""
await page.goto(S.login, {waitUntil: "domcontentloaded"});
await sleep(3000);
await gmtDismissConsent();
// Probed 2026-08-20: confirmed live against mastodon.social.
await gmtType(page.locator("#user_email"), process.env.GMT_SM_USERNAME);
await gmtHuman();
await gmtType(page.locator("#user_password"), process.env.GMT_SM_PASSWORD);
await gmtHuman();
await page.locator(`form button[type="submit"]`).first().click();
await sleep(10000);
await gmtReportPage();
"""],
    compose=["""
await page.goto(S.home, {waitUntil: "domcontentloaded"});
await sleep(6000);
gmtBox = await gmtNeed(page.locator(S.composer), "composer");
""", """
if (!gmtBox) { return; }
await gmtType(gmtBox, GMT_POST_TEXT);
await sleep(3000);
await gmtClick(page.getByRole("button", {name: /^Post$/i}), "publish");
await sleep(8000);
await gmtReportPage();
"""],
    delete="""
await page.goto(S.home, {waitUntil: "domcontentloaded"});
await sleep(8000);
const own = page.locator(S.post).filter({hasText: "automated measurement post"}).first();
if (!await gmtVisible(own)) { logNote("WARNING could not find own post to delete"); return; }
if (!await gmtClick(own.locator(`button[title="More"], button[aria-label="More"]`), "status more menu")) { return; }
await sleep(2500);
// Verified live 2026-08-20: these entries are plain buttons in .dropdown-menu with no
// role=menuitem, and the anchored regex keeps Delete from matching Delete & re-draft.
await gmtClick(page.locator(".dropdown-menu").getByText(/^Delete$/), "delete menu item");
await sleep(2500);
const confirm = page.getByRole("button", {name: /^Delete$/i});
if (await gmtVisible(confirm)) { await gmtClick(confirm, "confirm delete"); }
await sleep(5000);
""",
    logout="""
const more = await gmtNeed(page.locator(".navigation-panel").getByRole("button", {name: /^More$/i}), "navigation More menu");
if (!more) { return; }
await more.click();
await sleep(2000);
await page.getByRole("button", {name: /^Logout$/i}).first().click();
await sleep(3000);
const confirm = page.getByRole("button", {name: /^Logout$/i});
if (await gmtVisible(confirm)) { await confirm.first().click(); }
await sleep(6000);
await gmtReportPage();
""",
)

PLATFORMS['bluesky'] = dict(
    title='Bluesky',
    blurb='Bluesky web app, Following timeline plus the shared anchor profile',
    env={'GMT_SM_USERNAME': '__GMT_VAR_SECRET_USERNAME__', 'GMT_SM_PASSWORD': '__GMT_VAR_SECRET_PASSWORD__'},
    # All selectors below probed against a live logged-in desktop session 2026-08-20.
    # Note the bottomBar*/composeFAB/searchBtn testids are the MOBILE layout and do not
    # exist at 1920x1080 - the desktop rail uses aria-labels instead.
    bindings="""
S = {
  root: "https://bsky.app/",
  login: "https://bsky.app/",
  home: "https://bsky.app/",
  anchor: "https://bsky.app/profile/techcrunch.com",
  notifications: "https://bsky.app/notifications",
  explore: "https://bsky.app/search",
  consent: [],
  post: `[data-testid^="feedItem-"]`,
  photo: `[data-testid^="feedItem-"] img[src*="feed_thumbnail"], [data-testid^="feedItem-"] img[src*="feed_fullsize"]`,
  search: `[data-testid="searchScreenInput"], input[aria-label="Search"]`,
  userInput: `[data-testid="loginUsernameInput"]`,
  passInput: `[data-testid="loginPasswordInput"]`,
  loginButton: `[data-testid="loginNextButton"]`,
  // Probed live: composerTextInput does not exist. The editor is an unlabelled
  // contenteditable div inside composePostView; composerPublishBtn is real.
  composer: `[data-testid="composePostView"] [contenteditable="true"]`,
  publish: `[data-testid="composerPublishBtn"]`,
  // Two of these render (home screen and nav rail); every use goes through .first().
  composeButton: `[aria-label="Compose new post"]`,
  accountMenu: `[aria-label="Switch accounts"]`,
  like: `[data-testid="likeBtn"]`,
  dropdown: `[data-testid="postDropdownBtn"]`,
  tabs: [`a[aria-label="Explore"]`, `a[aria-label="Notifications"]`, `a[aria-label="Feeds"]`, `a[aria-label="Profile"]`, `a[aria-label="Home"]`]
};
""",
    login=["""
await page.goto(S.login, {waitUntil: "domcontentloaded"});
await sleep(9000);
// Bluesky greets a logged-out visitor with a modal splash that renders ON TOP of the
// login form. Its own "Sign in" link is the way through - the page carries other
// elements reading exactly "Sign in", and clicking those just reopens the splash, which
// then swallows every click and keystroke aimed at the form behind it.
const splash = page.locator(`[role=dialog][aria-modal="true"]`).getByText(/^Sign in$/);
if (await gmtVisible(splash)) { await gmtClick(splash, "sign in inside splash"); await sleep(6000); }
""", """
const user = await gmtNeed(page.locator(S.userInput), "username field");
if (!user) { throw "Bluesky login: username field not found"; }
await gmtType(user, process.env.GMT_SM_USERNAME);
await gmtHuman();
await gmtType(page.locator(S.passInput), process.env.GMT_SM_PASSWORD);
await gmtHuman();
await gmtClick(page.locator(S.loginButton), "submit");
""", """
await sleep(15000);
if (await page.locator(`[data-testid="noSessionView"]`).count() > 0) { throw "Bluesky login did not take - still on the logged out view"; }
await gmtReportPage();
"""],
    compose=["""
await page.goto(S.home, {waitUntil: "domcontentloaded"});
await sleep(7000);
const fab = await gmtNeed(page.locator(S.composeButton), "compose button");
if (!fab) { return; }
await gmtClick(fab, "compose button");
await sleep(4000);
gmtBox = await gmtNeed(page.locator(S.composer), "composer");
""", """
if (!gmtBox) { return; }
await gmtType(gmtBox, GMT_POST_TEXT);
await sleep(3000);
await gmtClick(page.locator(S.publish), "publish");
await sleep(9000);
await gmtReportPage();
"""],
    delete="""
// Deleting from the profile, not the home feed: a fresh post does not reliably appear
// in Following, and a delete that cannot find its post leaves a public post up.
await page.goto(`https://bsky.app/profile/${process.env.GMT_SM_USERNAME}`, {waitUntil: "domcontentloaded"});
await sleep(9000);
const own = page.locator(S.post).filter({hasText: "automated measurement post"}).first();
if (!await gmtVisible(own)) { logNote("WARNING could not find own post to delete"); return; }
if (!await gmtClick(own.locator(S.dropdown), "post dropdown")) { return; }
await sleep(2500);
await gmtClick(page.getByText(/^Delete post$/), "delete menu item");
await sleep(2500);
const confirm = page.getByRole("button", {name: /^Delete$/i});
if (await gmtVisible(confirm)) { await gmtClick(confirm, "confirm delete"); }
await sleep(5000);
""",
    logout="""
const acct = await gmtNeed(page.locator(S.accountMenu), "account menu");
if (!acct) { return; }
await gmtClick(acct, "account menu");
await sleep(3500);
await gmtClick(page.getByText(/^Sign out$/), "sign out");
await sleep(8000);
await gmtReportPage();
""",
)

PLATFORMS['linkedin'] = dict(
    title='LinkedIn',
    blurb='LinkedIn web feed plus the shared anchor company page',
    env={'GMT_SM_USERNAME': '__GMT_VAR_SECRET_USERNAME__',
         'GMT_SM_PASSWORD': '__GMT_VAR_SECRET_PASSWORD__',
         'GMT_SM_SESSION': '__GMT_VAR_SECRET_SESSION__'},
    bindings="""
S = {
  root: "https://www.linkedin.com/",
  login: "https://www.linkedin.com/login",
  home: "https://www.linkedin.com/feed/",
  anchor: "https://www.linkedin.com/company/techcrunch/posts/",
  notifications: "https://www.linkedin.com/notifications/",
  explore: "https://www.linkedin.com/feed/",
  consent: ["Reject", "Reject all", "Accept", "Accept all"],
  // Probed live: #username / #password are gone (React ids now), the page contains NO
  // form element at all, and two input pairs render of which the first is hidden - hence
  // page-wide selectors with :visible rather than anything scoped to a form.
  cookies: [{name: "lang", value: "v=2&lang=en_US", domain: ".linkedin.com", path: "/"}],
  userInput: `input[autocomplete~="username"]:visible`,
  passInput: `input[type="password"]:visible`,
  post: `div.feed-shared-update-v2, [data-id^="urn:li:activity"]`,
  photo: "div.update-components-image img",
  search: "input.search-global-typeahead__input",
  composer: "div.ql-editor",
  composeButton: "button.share-box-feed-entry__trigger",
  publish: "button.share-actions__primary-action",
  like: "button.react-button__trigger",
  tabs: [`a[href*="/mynetwork"]`, `a[href*="/jobs"]`, `a[href*="/messaging"]`, `a[href*="/notifications"]`, `a[href*="/feed"]`]
};
""",
    login=["""
await page.goto(S.login, {waitUntil: "domcontentloaded"});
await sleep(6000);
await gmtDismissConsent();
// Verified live: a credential login from a fresh browser profile is met with
// "The login attempt seems suspicious" and a code mailed to the account address. GMT
// starts a fresh profile on every run, so LinkedIn sees a new device every time and no
// unattended run can ever answer it. Restoring a li_at session cookie is the only way
// to measure LinkedIn logged in. Pass the value as __GMT_VAR_SECRET_SESSION__, or the
// literal "none" to attempt the credential path anyway.
if (process.env.GMT_SM_SESSION && process.env.GMT_SM_SESSION !== "none") {
  await context.addCookies([
    {name: "li_at", value: process.env.GMT_SM_SESSION, domain: ".linkedin.com", path: "/"},
    {name: "li_at", value: process.env.GMT_SM_SESSION, domain: ".www.linkedin.com", path: "/"}
  ]);
  logNote("restored LinkedIn session from li_at cookie");
} else {
  const user = await gmtNeed(page.locator(S.userInput), "username field");
  if (!user) { throw "LinkedIn login: username field not found"; }
  await gmtType(user, process.env.GMT_SM_USERNAME);
  await gmtHuman();
  await gmtType(page.locator(S.passInput), process.env.GMT_SM_PASSWORD);
  await gmtHuman();
  // Enter as the fallback because it does not depend on the button label, which follows
  // whatever language LinkedIn decides to serve.
  if (!await gmtClick(page.getByRole("button", {name: /^(Sign in|Log in|Einloggen)$/i}), "submit")) {
    await page.locator(S.passInput).first().press("Enter");
  }
  await sleep(14000);
}
""", """
page_result = await page.goto(S.home, {waitUntil: "domcontentloaded"});
await sleep(9000);
const here = page.url();
if (here.includes("/checkpoint/") || here.includes("/login") || here.includes("/authwall")) {
  throw `LinkedIn is not logged in (landed on ${here}). Supply a fresh li_at cookie via __GMT_VAR_SECRET_SESSION__.`;
}
await gmtReportPage();
"""],
    compose=["""
await page.goto(S.home, {waitUntil: "domcontentloaded"});
await sleep(8000);
const trig = await gmtNeed(page.locator(S.composeButton), "compose button");
if (!trig) { return; }
await trig.click();
await sleep(5000);
gmtBox = await gmtNeed(page.locator(S.composer), "composer");
""", """
if (!gmtBox) { return; }
await gmtType(gmtBox, GMT_POST_TEXT);
await sleep(3000);
await gmtClick(page.locator(S.publish), "publish");
await sleep(10000);
await gmtReportPage();
"""],
    delete="""
await page.goto(S.home, {waitUntil: "domcontentloaded"});
await sleep(8000);
const own = page.locator(S.post).filter({hasText: "automated measurement post"}).first();
if (await gmtVisible(own)) {
  await own.locator("button.feed-shared-control-menu__trigger").first().click();
  await sleep(2000);
  await page.getByRole("button", {name: /^Delete post$/i}).first().click();
  await sleep(2000);
  const confirm = page.getByRole("button", {name: /^Delete$/i});
  if (await gmtVisible(confirm)) { await confirm.first().click(); }
  await sleep(5000);
} else { logNote("WARNING could not find own post to delete"); }
""",
    logout="""
const me = await gmtNeed(page.locator("button.global-nav__primary-link-me-menu-trigger, .global-nav__me"), "me menu");
if (!me) { return; }
await me.click();
await sleep(3000);
await page.getByRole("link", {name: /^Sign Out$/i}).first().click();
await sleep(8000);
await gmtReportPage();
""",
)

PLATFORMS['reddit'] = dict(
    title='Reddit',
    blurb='Reddit web app, personalised home feed plus the shared anchor subreddit',
    env={'GMT_SM_USERNAME': '__GMT_VAR_SECRET_USERNAME__', 'GMT_SM_PASSWORD': '__GMT_VAR_SECRET_PASSWORD__'},
    bindings="""
S = {
  root: "https://www.reddit.com/",
  login: "https://www.reddit.com/login/",
  home: "https://www.reddit.com/",
  anchor: "https://www.reddit.com/r/technology/",
  notifications: "https://www.reddit.com/notifications/",
  explore: "https://www.reddit.com/",
  submit: "https://www.reddit.com/r/test/submit/",
  consent: ["Reject Optional Cookies", "Accept All"],
  userInput: `input[name="username"]`,
  passInput: `input[name="password"]`,
  post: "shreddit-post",
  photo: "shreddit-post img",
  search: "#search-input",
  composer: "shreddit-composer div[contenteditable]",
  title: `textarea[name="title"], faceplate-textarea-input textarea`,
  publish: `button[type="submit"]`,
  overflow: "shreddit-post-overflow-menu button",
  tabs: [`a[href*="/r/popular"]`, `a[href*="/news/"]`, `a[href*="/explore/"]`, `a[href$="/notifications"]`, `a[href*="feed=home"]`]
};
""",
    login=["""
await page.goto(S.login, {waitUntil: "domcontentloaded"});
await sleep(8000);
await gmtDismissConsent();
// Probed 2026-08-20: Reddit serves a JS challenge and a reCAPTCHA on this page. The
// fields resolve, but an automated login may still be refused - see README.
const user = page.locator(S.userInput);
await user.waitFor({state: "visible", timeout: 20000});
await gmtType(user, process.env.GMT_SM_USERNAME);
await gmtHuman();
await gmtType(page.locator(S.passInput), process.env.GMT_SM_PASSWORD);
await gmtHuman();
await page.getByRole("button", {name: /^Log In$/i}).first().click();
await sleep(12000);
await gmtReportPage();
"""],
    # r/test exists precisely so automated posts have somewhere harmless to go.
    compose=["""
await page.goto(S.submit, {waitUntil: "domcontentloaded"});
await sleep(8000);
gmtBox = await gmtNeed(page.locator(S.title), "post title field");
""", """
if (!gmtBox) { return; }
await gmtType(gmtBox, "Automated measurement post");
await sleep(2000);
""", """
// Reddit is the only platform that types two fields here, which put this step closest to
// the 60s ceiling of anything in the suite. Kept as its own command for headroom.
if (!gmtBox) { return; }
const body = page.locator(S.composer).first();
if (await gmtVisible(body)) { await gmtType(body, GMT_POST_TEXT); }
await sleep(3000);
""", """
if (!gmtBox) { return; }
const post = page.getByRole("button", {name: /^Post$/i});
if (await gmtVisible(post)) { await gmtClick(post, "publish"); }
await sleep(10000);
await gmtReportPage();
"""],
    delete="""
await page.goto(`https://www.reddit.com/user/${process.env.GMT_SM_USERNAME}/submitted/`, {waitUntil: "domcontentloaded"});
await sleep(9000);
const own = page.locator(S.post).filter({hasText: "Automated measurement post"}).first();
if (!await gmtVisible(own)) { logNote("WARNING could not find own post to delete"); return; }
// Reddit is web components with shadow DOM. Playwright locators pierce open shadow
// roots, but page.evaluate/querySelectorAll does not - so everything here stays in
// locator land. Probed live: the overflow control is inside shreddit-post-overflow-menu.
if (!await gmtClick(own.locator(S.overflow), "post overflow menu")) { return; }
await sleep(3000);
await gmtClick(page.getByRole("menuitem", {name: /^Delete$/i}), "delete menu item");
await sleep(3000);
// The confirmation reads "Yes, Delete", not "Delete".
const confirm = page.getByRole("button", {name: /delete/i});
if (await gmtVisible(confirm)) { await gmtClick(confirm.last(), "confirm delete"); }
else { logNote("WARNING delete confirmation not found - the post may still be up"); }
await sleep(6000);
""",
    logout="""
const drawer = await gmtNeed(page.locator("#expand-user-drawer-button"), "user drawer");
if (!drawer) { return; }
await drawer.click();
await sleep(3000);
const out = page.getByRole("menuitem", {name: /^Log Out$/i});
if (await gmtVisible(out)) { await out.first().click(); }
await sleep(8000);
await gmtReportPage();
""",
)

PLATFORMS['threads'] = dict(
    title='Threads',
    blurb='Meta Threads web app, For you feed plus the shared anchor profile',
    env={'GMT_SM_USERNAME': '__GMT_VAR_SECRET_USERNAME__', 'GMT_SM_PASSWORD': '__GMT_VAR_SECRET_PASSWORD__'},
    bindings="""
S = {
  root: "https://www.threads.com/",
  login: "https://www.threads.com/login/",
  home: "https://www.threads.com/",
  anchor: "https://www.threads.com/@techcrunch",
  notifications: "https://www.threads.com/activity",
  explore: "https://www.threads.com/search",
  // Probed 2026-08-20: threads.com/login renders zero inputs until the Meta consent wall
  // is dismissed, and then needs the Instagram entry point clicked before a form appears.
  consent: ["Decline optional cookies", "Allow all cookies"],
  loginEntry: "Use your Instagram account",
  // Verified live: placeholders "Username, phone or email" and "Password".
  userInput: `input[autocomplete~="username"]`,
  passInput: `input[autocomplete~="current-password"], input[type="password"]`,
  post: `[data-pressable-container="true"]`,
  photo: `div[role="button"] picture img`,
  search: `input[placeholder="Search"]`,
  composer: `div[contenteditable="true"]`,
  publish: `div[role="button"]:has-text("Post")`,
  tabs: [`a[href="/search"]`, `a[href="/activity"]`, `a[href="/"]`, `a[href*="/@"]`, `a[href="/"]`]
};
""",
    login=["""
await page.goto(S.login, {waitUntil: "domcontentloaded"});
await sleep(12000);
// Verified live: the page carries NO input at all until both the Meta consent wall is
// dismissed and the Instagram entry point is clicked. Only then do three inputs appear.
// The consent buttons refuse a Playwright click, so gmtDismissConsent uses a DOM click.
await gmtDismissConsent();
await sleep(6000);
if (await gmtVisible(page.getByText(S.loginEntry))) {
  await gmtClick(page.getByText(S.loginEntry), "instagram login entry");
  await sleep(8000);
}
""", """
const user = await gmtNeed(page.locator(S.userInput), "username field");
if (!user) { throw "Threads login: username field not found"; }
await gmtType(user, process.env.GMT_SM_USERNAME);
await gmtHuman();
await gmtType(page.locator(S.passInput).first(), process.env.GMT_SM_PASSWORD);
await gmtHuman();
// The submit control is a div with role=button, not a real button element.
if (!await gmtClick(page.getByRole("button", {name: /^Log in$/i}), "submit")) {
  await page.locator(S.passInput).first().press("Enter");
}
await sleep(20000);
""", """
// Instagram answers a rejected password with HTTP 200 and {"authenticated":false},
// leaving the page on /login/ with no visible error at all. Without this check the run
// would carry on and quietly measure a logged-out wall.
if (page.url().includes("/login")) {
  throw `Threads is not logged in (still on ${page.url()}). Instagram rejected the credentials, or the account needs a checkpoint cleared interactively.`;
}
await gmtReportPage();
"""],
    compose=["""
await page.goto(S.home, {waitUntil: "domcontentloaded"});
await sleep(8000);
const trigger = page.getByText("What is new?").first();
if (await gmtVisible(trigger)) { await trigger.click(); await sleep(4000); }
gmtBox = await gmtNeed(page.locator(S.composer), "composer");
""", """
if (!gmtBox) { return; }
await gmtType(gmtBox, GMT_POST_TEXT);
await sleep(3000);
await gmtClick(page.locator(S.publish).last(), "publish");
await sleep(10000);
await gmtReportPage();
"""],
    delete="""
await page.goto(`https://www.threads.com/@${process.env.GMT_SM_USERNAME}`, {waitUntil: "domcontentloaded"});
await sleep(8000);
const own = page.locator(S.post).filter({hasText: "automated measurement post"}).first();
if (await gmtVisible(own)) {
  await own.getByRole("button", {name: /^More$/i}).first().click();
  await sleep(2000);
  await page.getByText("Delete").first().click();
  await sleep(2000);
  const confirm = page.getByRole("button", {name: /^Delete$/i});
  if (await gmtVisible(confirm)) { await confirm.first().click(); }
  await sleep(5000);
} else { logNote("WARNING could not find own post to delete"); }
""",
    logout="""
await page.goto("https://www.threads.com/settings/account", {waitUntil: "domcontentloaded"});
await sleep(8000);
const out = page.getByText("Log out").first();
if (await gmtVisible(out)) { await out.click(); await sleep(3000); }
const confirm = page.getByRole("button", {name: /^Log out$/i});
if (await gmtVisible(confirm)) { await confirm.first().click(); }
await sleep(8000);
await gmtReportPage();
""",
)

# Like / favourite controls, filled in for the platforms whose binding blocks above
# did not already carry one.
PLATFORMS['mastodon']['bindings'] = PLATFORMS['mastodon']['bindings'].replace(
    '  photo: ".media-gallery__item img, .media-gallery img, .status__media img",',
    '  photo: ".media-gallery__item img, .media-gallery img, .status__media img",\n'
    '  like: `button[title="Favourite"]`,\n'
    '  unlike: `button[title="Remove from favourites"]`,')
PLATFORMS['reddit']['bindings'] = PLATFORMS['reddit']['bindings'].replace(
    '  photo: "shreddit-post img",',
    '  photo: "shreddit-post img",\n  like: "shreddit-post button[upvote]",')
PLATFORMS['threads']['bindings'] = PLATFORMS['threads']['bindings'].replace(
    '  photo: `div[role="button"] picture img`,',
    '  photo: `div[role="button"] picture img`,\n'
    '  like: `div[role="button"][aria-label="Like"], svg[aria-label="Like"]`,\n'
    '  unlike: `div[role="button"][aria-label="Unlike"], svg[aria-label="Unlike"]`,')


# ---------------------------------------------------------------------------
# Generic action bodies. Every platform gets these unchanged; they read S.
# ---------------------------------------------------------------------------
GENERIC = {}

GENERIC['thread'] = """
await gmtTop();
const first = await gmtNeed(page.locator(S.post), "a feed post");
if (!first) { return; }
await first.click();
await sleep(6000);
gmtScrollReset();
await gmtTickChunk(__SUB_TICKS__);
await gmtScrollReport(S.post);
"""

GENERIC['lightbox'] = """
await page.goto(S.anchor, {waitUntil: "domcontentloaded"});
await sleep(6000);
let photo = page.locator(S.photo);
if (!await gmtVisible(photo)) {
  await page.goto(S.explore, {waitUntil: "domcontentloaded"});
  await sleep(6000);
  photo = page.locator(S.photo);
}
if (await gmtVisible(photo)) {
  await photo.first().click();
  await sleep(5000);
  await page.keyboard.press("ArrowRight");
  await sleep(3000);
  await page.keyboard.press("Escape");
  await sleep(2000);
} else { logNote("WARNING no image matched the lightbox selector"); }
await gmtReportPage();
"""

# Typed with a per-keystroke delay on purpose: most platforms fire a typeahead
# request per keystroke, which is a real and rarely measured cost.
GENERIC['search'] = """
await page.goto(S.explore, {waitUntil: "domcontentloaded"});
await sleep(6000);
const box = await gmtNeed(page.locator(S.search), "search box");
if (!box) { return; }
await gmtType(box, "green software engineering");
await sleep(4000);
await box.press("Enter");
await sleep(8000);
gmtScrollReset();
await gmtTickChunk(__SUB_TICKS__);
await gmtScrollReport(S.post);
"""

GENERIC['like'] = """
await gmtOpenFeed(S.anchor);
// A like left behind by an earlier run would make this one a no-op, and on platforms
// where the control renames itself when active (Mastodon: Favourite -> Remove from
// favourites) it would never be found again. Clear it first, then measure the real toggle.
if (S.unlike && await gmtVisible(page.locator(S.unlike))) {
  await gmtClick(page.locator(S.unlike), "clearing a like left by an earlier run");
  await sleep(3000);
}
const like = page.locator(S.like).first();
if (!await gmtVisible(like)) { logNote("WARNING no like control matched"); return; }
await gmtClick(like, "like");
await sleep(4000);
const undo = page.locator(S.unlike ? S.unlike : S.like).first();
if (await gmtVisible(undo)) { await gmtClick(undo, "unlike"); await sleep(4000); }
else { logNote("WARNING could not undo the like - it is still set on the anchor account"); }
await gmtReportPage();
"""

GENERIC['notifications'] = """
await page.goto(S.notifications, {waitUntil: "domcontentloaded"});
await sleep(8000);
gmtScrollReset();
await gmtTickChunk(__SUB_TICKS__);
await gmtScrollReport(S.post);
"""

# Client-side route changes rather than full document loads. Platforms differ
# enormously in what they re-fetch and re-render when you move between their own tabs.
GENERIC['tabs_open'] = """
await page.goto(S.home, {waitUntil: "domcontentloaded"});
await sleep(6000);
"""

# One command per tab: as a single loop this measured 37s against X, which is under the
# 60s ceiling but not by enough to trust on a busy machine.
GENERIC['tabs_step'] = """
const l = page.locator(S.tabs[__TAB__]).first();
if (await gmtVisible(l)) { await gmtClick(l, "nav tab __TAB__"); await sleep(6000); }
else { logNote("WARNING nav tab __TAB__ not found"); }
"""

GENERIC['tabs_report'] = """
await gmtReportPage();
"""

# The feed tab is hidden behind a blank tab. A well behaved app throttles its timers here.
GENERIC['background_open'] = """
await page.goto(S.home, {waitUntil: "domcontentloaded"});
await sleep(6000);
bgPage = await context.newPage();
await bgPage.goto("about:blank");
await bgPage.bringToFront();
"""

GENERIC['background_close'] = """
await page.bringToFront();
await sleep(3000);
await bgPage.close();
await gmtReportPage();
"""


# ---------------------------------------------------------------------------
# Emitter
# ---------------------------------------------------------------------------
HEADER = """---
name: "Social Media - {title} - Firefox{suffix_label}"
author: Didi Hoffmann <didi@green-coding.io>
description: "{blurb}. One flow step per action so every action lands in its own GMT phase."

compose-file: !include-gmt-helper {helper}

# Emitted from inside the browser via logNote() as "<microsecond timestamp> <key>=<int>"
# and scraped from the detached IPC process stdout. Values are attributed to whichever
# phase was active when they were emitted, so every phase carries its own page weight.
custom_metrics:
{metrics}
services:
  gmt-playwright-nodejs:
    read-notes-stdout: true
    # Credentials travel as container env vars rather than being string-replaced into the
    # Playwright commands. Two reasons: the IPC process echoes every command it evaluates
    # to stdout (which lands in the run log), and env var values may contain any character
    # while commands sent over the IPC FIFO may not contain a single quote.
    #
    # The literal block scalars are load bearing. GMT substitutes __GMT_VAR_*__ into this
    # file as raw text *before* the YAML is parsed, so a credential starting with @ or %,
    # or containing a quote or a colon, would otherwise be a YAML syntax error rather than
    # a password. Inside a block scalar every character is literal, so nothing needs escaping.
    environment:
{env}
# Replaces the helper partial's own flow-prepend so the browser launch is visible and
# tunable here, and so the IPC process stdout is read for notes and custom metrics.
# See README.md for switching a full run to headful.
flow-prepend:
  - name: Starting browser IPC
    container: gmt-playwright-nodejs
    hidden: true
    commands:
      - type: console
        command: node /tmp/gmt-utils/gmt-playwright-ipc.js --headless {headless} --browser firefox --proxy http://squid:3128
        note: Starting browser in background process with IPC
        detach: true
        read-notes-stdout: true
      - type: console
        command: timeout 10 bash -c 'until [ -p "/tmp/playwright-ipc-ready" ]; do sleep 1; done && echo "Browser ready!"'
        shell: bash
        note: Waiting for website stepper loop to start by monitoring rendezvous file endpoint

flow:
"""


def js_block(body):
    body = textwrap.dedent(body).strip()
    assert "'" not in body, f"single quote in playwright command:\n{body}"
    return ('      - type: playwright\n'
            '        shell: bash\n'
            '        command: |\n'
            + textwrap.indent(body, ' ' * 10) + '\n')


def console_block(command, note=None):
    out = '      - type: console\n' + f'        command: {command}\n'
    if note:
        out += f'        note: {note}\n'
    return out


def step(name, blocks, hidden=False, comment=None):
    out = ''
    if comment:
        out += textwrap.indent(textwrap.dedent(comment).strip(), '  # ') + '\n'
    out += f'  - name: {name}\n    container: gmt-playwright-nodejs\n'
    if hidden:
        out += '    hidden: true\n'
    out += '    commands:\n'
    return out + ''.join(blocks)


def build(key, cfg, profile):
    metrics = ''.join(f'  {n}:\n    unit: {u}\n' for n, u in CUSTOM_METRICS)
    env = ''.join(f'      {k}: |-\n        {v}\n' for k, v in cfg['env'].items())
    out = HEADER.format(title=cfg['title'], blurb=cfg['blurb'], metrics=metrics, env=env,
                        suffix_label=profile['label'], helper=profile['helper'],
                        headless=profile['headless'])

    out += step('Setup Browser Harness',
                [js_block(HARNESS_CONTEXT), js_block(HARNESS_CLICK), js_block(HARNESS_REPORT), js_block(HARNESS_SCROLL)],
                hidden=True,
                comment="""
                Shared harness, generated identically into every scenario by build_scenarios.py.
                No single quotes anywhere below: GMT ships each command through
                `bash -ec "echo <command> > <fifo>"`, which a single quote would break.
                Use backticks for selectors that need embedded double quotes.
                """)

    out += step('Setup Platform Bindings',
                [js_block(cfg['bindings'] + f'\nGMT_POST_TEXT = "{POST_TEXT}";')],
                hidden=True,
                comment='S is the only platform specific part. Everything else reads from it.')

    out += step('Warm Cache',
                [js_block('await gmtNewContext();\nawait page.goto(S.root, {waitUntil: "load"});\nawait sleep(8000);'),
                 js_block('await gmtNewContext();')],
                hidden=True,
                comment="""
                Fills the squid cache with the static app shell, then throws the context away
                so the measured login below starts with cold cookies but a warm HTTP cache.
                """)

    out += step('Login', [js_block(b) for b in cfg['login']])
    out += step('Load Home Feed',
                [js_block('await gmtOpenFeed(S.home);'),
                 js_block('if (page_result && !page_result.ok()) throw `Home feed was not accessible. HTTP return code ${page_result.status()}`')])
    out += step('Idle On Home Feed',
                [console_block(f"sleep {profile['idle_seconds']}"), js_block('await gmtReportPage();')],
                comment="""
                Nothing is driven here. Whatever is measured is the platform polling,
                animating, prefetching or running timers entirely on its own.
                """)
    out += step('Scroll Home Feed Timed', scroll_seconds_blocks(profile['scroll_seconds'], 'S.post'))
    out += step('Scroll Home Feed Fixed Ticks',
                [js_block('await gmtOpenFeed(S.home);\nawait gmtTop();'),
                 *scroll_ticks_blocks(profile['scroll_ticks'], 'S.post')],
                comment="""
                Same feed, fixed distance instead of fixed time. Compared against the timed
                step above this separates "slow to load" from "expensive to render".
                """)
    out += step('Scroll Back To Top', [js_block('await gmtTop();\nawait gmtReportPage();')])
    out += step('Load Anchor Feed', [js_block('await gmtOpenFeed(S.anchor);')],
                comment='The cross-platform anchor: the same publisher, read on every platform.')
    out += step('Scroll Anchor Feed Timed', scroll_seconds_blocks(profile['scroll_seconds'], 'S.post'))
    out += step('Open Post And Thread', [js_block(GENERIC['thread'])])
    out += step('Open Image Lightbox', [js_block(GENERIC['lightbox'])])
    out += step('Search With Typing', [js_block(GENERIC['search'])])
    compose = cfg['compose'] if isinstance(cfg['compose'], list) else [cfg['compose']]
    out += step('Compose And Publish Post', [js_block(bl) for bl in compose])
    out += step('Delete Published Post', [js_block(cfg['delete'])])
    out += step('Like And Unlike', [js_block(GENERIC['like'])])
    out += step('Open Notifications', [js_block(GENERIC['notifications'])])
    tab_blocks = [js_block(GENERIC['tabs_open'])]
    tab_blocks += [js_block(GENERIC['tabs_step'].replace('__TAB__', str(i))) for i in range(5)]
    tab_blocks.append(js_block(GENERIC['tabs_report']))
    out += step('Navigate Tabs', tab_blocks)
    out += step('Background Tab Idle',
                [js_block(GENERIC['background_open']),
                 console_block(f"sleep {profile['idle_seconds']}"),
                 js_block(GENERIC['background_close'])])
    out += step('Logout', [js_block(cfg['logout'])])
    return out.replace('__SUB_TICKS__', str(profile['sub_ticks']))


def main():
    for key, cfg in PLATFORMS.items():
        for suffix, profile in PROFILES.items():
            path = ROOT / f'usage_scenario_{key}{suffix}.yml'
            path.write_text(build(key, cfg, profile))
            print(f'wrote {path.name}')


if __name__ == '__main__':
    main()
