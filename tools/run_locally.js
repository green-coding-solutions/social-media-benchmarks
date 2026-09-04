// Replays a scenario's playwright commands against a live browser, reproducing the
// environment gmt-playwright-ipc.js provides (browser/context/page/sleep/logNote globals,
// each command evaluated inside its own async wrapper).
//
// This is a selector check, not a measurement. It exists so a broken selector costs
// seconds instead of a full GMT run.
//
// Usage: node run_locally.js cmds.json [--skip "Step Name" ...] [--headed]
const fs = require("fs");
const { firefox } = require("playwright");

let browser = null, context = null, page = null, page_result = null, bgPage = null;
let S = {}, GMT_POST_TEXT = "", GMT_TICKS = 0;

const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
function logNote(message) {
  const timestamp = String(BigInt(Date.now()) * 1000000n).slice(0, 16);
  console.log(`      note: ${timestamp} ${message}`);
}

(async () => {
  const cmds = JSON.parse(fs.readFileSync(process.argv[2], "utf-8"));
  const skip = [];
  for (let i = 3; i < process.argv.length; i++) {
    if (process.argv[i] === "--skip") skip.push(process.argv[++i]);
  }

  browser = await firefox.launch({ headless: !process.argv.includes("--headed") });
  context = await browser.newContext({ viewport: { width: 1920, height: 1080 } });
  page = await context.newPage();

  let lastStep = null, failures = 0, skipped = 0;
  for (const c of cmds) {
    if (skip.includes(c.step)) {
      if (c.step !== lastStep) { console.log(`\n--- ${c.step}  [SKIPPED]`); lastStep = c.step; skipped++; }
      continue;
    }
    if (c.step !== lastStep) { console.log(`\n--- ${c.step}`); lastStep = c.step; }

    if (c.sleep !== undefined) { console.log(`   sleep ${c.sleep}s`); await sleep(c.sleep * 1000); continue; }

    const t0 = Date.now();
    try {
      await eval(`(async () => { ${c.js} })()`);
      const secs = ((Date.now() - t0) / 1000).toFixed(1);
      // GMT kills any single playwright command at 60s.
      const flag = secs > 45 ? "  <-- OVER GMT BUDGET" : "";
      console.log(`   ok  #${c.idx} (${secs}s)${flag}`);
    } catch (e) {
      failures++;
      console.log(`   FAIL #${c.idx} (${((Date.now() - t0) / 1000).toFixed(1)}s): ${String(e).split("\n")[0]}`);
      console.log(`        ${c.js.split("\n")[0].slice(0, 110)}`);
    }
  }
  console.log(`\n=== ${cmds.length} commands, ${failures} failures, ${skipped} steps skipped`);
  try { await page.screenshot({ path: "/tmp/work/final.png" }); } catch (e) {}
  await browser.close();
  process.exit(failures ? 1 : 0);
})().catch((e) => { console.error("FATAL", e); process.exit(2); });
