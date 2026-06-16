const { firefox } = require('playwright');
const { DatabaseSync } = require('node:sqlite');
const fs = require('node:fs');
const util = require('node:util');
const exec = util.promisify(require("child_process").exec);

(async () => {
  console.log('Starting browser');
  const userDataDir = 'playwright-user-data';
  const browserParams = {headless: false, slowMo: 500, proxy: {server: '127.0.0.1:3128'}, firefoxUserPrefs: {'dom.webdriver.enabled': false}, ignoreHTTPSErrors: true};
  const browser = await firefox.launchPersistentContext(userDataDir, browserParams);
  const page = browser.pages()[0];

  // disable cache
  page.route('**', route => route.continue());

  let crawlId = -1;
  let visitId = -1;
  let visitUrl = "";
  let responsesToPatch = [];

  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'webdriver', {
      get: () => false
    });
  });

  // User Journeys
  await page.goto('https://mastodon.bsd.cafe/@techcrunch@threads.net');
  await page.waitForTimeout(500);


  //await page.getByRole('feed').hover();
  await page.waitForLoadState('networkidle');
  for (let i = 0; i < 299; i++) {
    await page.mouse.wheel(0, 300);
    await page.waitForTimeout(500);
  }

  await page.waitForLoadState('networkidle');

  console.log('Closing browser');
  await browser.close();
  console.log('Done!');
})();
