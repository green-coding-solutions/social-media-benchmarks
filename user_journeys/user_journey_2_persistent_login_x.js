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
  await page.goto('https://x.com/TechCrunch');
  await page.waitForTimeout(3000);

  await page.getByLabel('Post', { exact: true }).click();
  await page.getByRole('button', { name: /(Everyone can reply|Only accounts you mention)/i }).click();
  await page.getByRole('radio', { name: 'Verified accounts' }).click();
  await page.getByRole('button', { name: 'Verified accounts' }).click();
  await page.getByRole('radio', { name: 'Only accounts you mention' }).click();
  // }

  const post = "This is an automated test post that will be deleted in a few minutes: Lorem ipsum dolor sit amet, consectetur adipiscing elit, sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.";
  await page.locator('div.public-DraftEditor-content').clear();
  await page.locator('div.public-DraftEditor-content').pressSequentially(post, {delay: 100});
  await page.waitForTimeout(500);

  await page.locator('div.public-DraftEditor-content').press('Control+Enter');

  // await page.getByTestId('tweetButton').click({ force: true });
  await page.waitForTimeout(500);

  await page.goto('https://x.com/nils1985825');
  await page.waitForTimeout(500);
  await page.getByText(post).click();
  await page.waitForTimeout(3000);

  console.log('Closing browser');
  await browser.close();
  console.log('Done!');
})();
