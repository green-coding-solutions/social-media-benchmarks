// Loads a page in the same browser GMT uses and reports which candidate selectors resolve.
//
// This is the cheap half of selector tuning: everything reachable without logging in. It
// cannot check anything behind auth - for that, run the matching _smoke scenario headful.
//
// Usage (see probe.sh):  node probe_selectors.js '<json>'
//   json: [{ "name": "x login", "url": "...", "selectors": {"label": "css", ...} }, ...]
const { firefox } = require("playwright");

const CONTEXT_OPTIONS = {
  viewport: { width: 1920, height: 1080 },
  locale: "en-US",
  timezoneId: "Europe/Berlin",
  ignoreHTTPSErrors: true,
};

async function main() {
  const targets = JSON.parse(process.argv[2]);
  const browser = await firefox.launch({ headless: true });

  for (const target of targets) {
    const context = await browser.newContext(CONTEXT_OPTIONS);
    // Same patch the scenarios apply, so we see what they would see.
    await context.addInitScript(() => {
      Object.defineProperty(navigator, "webdriver", { get: () => false });
    });
    const page = await context.newPage();

    console.log(`\n=== ${target.name} :: ${target.url}`);
    try {
      const res = await page.goto(target.url, { waitUntil: "domcontentloaded", timeout: 45000 });
      await page.waitForTimeout(target.settle || 8000);
      console.log(`    HTTP ${res ? res.status() : "?"}   final url: ${page.url()}`);
    } catch (e) {
      console.log(`    NAVIGATION FAILED: ${e.message.split("\n")[0]}`);
      await context.close();
      continue;
    }

    // Cookie banners overlay the page and swallow the first click on anything beneath them.
    for (const label of target.preClick || []) {
      try {
        await page.getByRole("button", { name: label }).first().click({ timeout: 8000 });
        console.log(`    clicked pre-step: ${label}`);
        await page.waitForTimeout(3000);
      } catch (e) {
        console.log(`    pre-step not found (may be fine): ${label}`);
      }
    }

    if (target.dumpTestids) {
      const ids = await page.evaluate(() => {
        const counts = {};
        for (const el of document.querySelectorAll("[data-testid]")) {
          const k = el.getAttribute("data-testid");
          counts[k] = (counts[k] || 0) + 1;
        }
        return Object.entries(counts).sort((a, b) => b[1] - a[1]).slice(0, 30);
      });
      console.log("    --- data-testid inventory (top 30) ---");
      for (const [k, n] of ids) { console.log(`        ${String(n).padStart(4)}  ${k}`); }
      if (ids.length === 0) { console.log("        (none)"); }
    }

    for (const [label, selector] of Object.entries(target.selectors)) {
      let count = 0;
      let visible = 0;
      try {
        count = await page.locator(selector).count();
        if (count > 0) {
          visible = await page.locator(selector).filter({ visible: true }).count();
        }
      } catch (e) {
        console.log(`    ERR   ${label.padEnd(22)} ${selector}  -> ${e.message.split("\n")[0]}`);
        continue;
      }
      const mark = visible > 0 ? "OK  " : (count > 0 ? "HID " : "MISS");
      console.log(`    ${mark}  ${label.padEnd(22)} ${count} matched / ${visible} visible   ${selector}`);
    }

    if (target.dumpButtons) {
      const buttons = await page.evaluate(() =>
        Array.from(document.querySelectorAll("button, [role=button], input[type=submit]"))
          .filter((el) => el.offsetParent !== null)
          .slice(0, 25)
          .map((el) => ({
            tag: el.tagName.toLowerCase(),
            type: el.getAttribute("type"),
            testid: el.getAttribute("data-testid"),
            id: el.getAttribute("id"),
            cls: (el.getAttribute("class") || "").slice(0, 60),
            text: (el.innerText || "").trim().slice(0, 40),
          }))
      );
      console.log("    --- visible buttons ---");
      for (const b of buttons) {
        console.log(`        ${b.tag} type=${b.type} testid=${b.testid} id=${b.id} text=${JSON.stringify(b.text)} class=${b.cls}`);
      }
    }

    // Dump every input on the page: the fastest way to find what a login form actually uses.
    if (target.dumpInputs) {
      const inputs = await page.evaluate(() =>
        Array.from(document.querySelectorAll("input, textarea")).map((el) => ({
          tag: el.tagName.toLowerCase(),
          type: el.getAttribute("type"),
          name: el.getAttribute("name"),
          id: el.getAttribute("id"),
          autocomplete: el.getAttribute("autocomplete"),
          testid: el.getAttribute("data-testid"),
        }))
      );
      console.log("    --- inputs on page ---");
      for (const i of inputs) {
        console.log(`        ${i.tag} type=${i.type} name=${i.name} id=${i.id} autocomplete=${i.autocomplete} testid=${i.testid}`);
      }
    }
    await context.close();
  }
  await browser.close();
}

main().catch((e) => { console.error(e); process.exit(1); });
