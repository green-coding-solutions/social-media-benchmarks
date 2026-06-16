const { firefox } = require('playwright');
const { DatabaseSync } = require('node:sqlite');
const fs = require('node:fs');
const util = require('node:util');
const exec = util.promisify(require("child_process").exec);

(async () => {
  console.log('Starting browser');
  const browserParams = {headless: false, slowMo: 500, proxy: {server: '127.0.0.1:3128'}};
  const browser = await firefox.launch(browserParams);
  const page = await browser.newPage({ignoreHTTPSErrors: true});

  // Get Password
  let {stdout, stderr} = await exec("pass mastodon | head -1");
  if (stderr) {
    console.log(`stderr getting password: ${stderr}`);
  }
  const password = stdout;

  // Get email
  ({stdout, stderr} = await exec("pass mastodon | grep 'email:' | cut -d' ' -f 2"));
  if (stderr) {
    console.log(`stderr getting email: ${stderr}`);
  }
  const email = stdout;

  // User Journeys
  await page.goto('https://mastodon.bsd.cafe');
  await page.waitForTimeout(500);
  await patchResponses();

  await page.getByRole('link', { name: 'Login' }).click();
  await page.waitForTimeout(500);
  await patchResponses();

  await page.getByLabel('E-mail address').fill(email);
  await page.getByLabel('Password').fill(password);
  await page.getByRole('button', { name: 'Log in' }).click();
  await patchResponses();

  //await page.getByRole('feed').hover();
  await page.waitForLoadState('networkidle');
  for (let i = 0; i < 119; i++) {
    await page.mouse.wheel(0, 200);
    await page.waitForTimeout(500);
  }

  await page.locator('.navigation-panel').getByRole('button', { name: 'More' }).click();
  await page.getByRole('button', { name: 'Logout' }).click();
  await patchResponses();
  await page.waitForTimeout(500);

  await page.waitForLoadState('networkidle');

  console.log('Closing browser');
  await browser.close();
  console.log('Done!');
})();
