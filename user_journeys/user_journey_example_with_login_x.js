const { firefox } = require('playwright');
const { DatabaseSync } = require('node:sqlite');
const fs = require('node:fs');
const util = require('node:util');
const exec = util.promisify(require("child_process").exec);

(async () => {
  console.log('Starting browser');
  const browserParams = {headless: false, slowMo: 500, firefoxUserPrefs: {'dom.webdriver.enabled': false}, proxy: {server: '127.0.0.1:3128'}};
  const browser = await firefox.launch(browserParams);
  const page = await browser.newPage({ignoreHTTPSErrors: true});

  await page.addInitScript(() => {
    Object.defineProperty(navigator, 'webdriver', {
      get: () => false
    });
  });

  // Get Password
  let {stdout, stderr} = await exec("pass twitter | head -1");
  if (stderr) {
    console.log(`stderr getting password: ${stderr}`);
  }
  const password = stdout;

  // Get email
  ({stdout, stderr} = await exec("pass twitter | grep 'email:' | cut -d' ' -f 2"));
  if (stderr) {
    console.log(`stderr getting email: ${stderr}`);
  }
  const email = stdout;

  // Get username just in case
  ({stdout, stderr} = await exec("pass twitter | grep 'username:' | cut -d' ' -f 2"));
  if (stderr) {
    console.log(`stderr getting username: ${stderr}`);
  }
  const username = stdout;


  // User Journey
  await page.goto('https://x.com');
  await page.waitForTimeout(500);
  await patchResponses();

  await page.getByRole('link', { name: 'Sign in' }).click();
  await page.waitForTimeout(500);
  await patchResponses();

  await page.getByLabel('email').fill(email);
  await page.waitForTimeout(500);
  await page.getByRole('button', { name: 'Next' }).click();
  await page.waitForTimeout(500);

  try {
    const additionalCheck = await page.getByLabel('Phone or username').isVisible();
    if (additionalCheck) {
      await page.getByLabel('Phone or username').fill(username);
      await page.waitForTimeout(500);
      await page.getByRole('button', { name: 'Next' }).click();
      await page.waitForTimeout(500);
    }
  } catch (e) {
    console.log('No additional step for login.');
  }

  await page.locator('input[type="password"]').fill(password);
  await page.waitForTimeout(500);
  await page.getByRole('button', { name: 'Log in' }).click();
  await page.waitForTimeout(1000);
  await patchResponses();

  //await page.getByRole('feed').hover();
  //await page.waitForLoadState('networkidle');
  for (let i = 0; i < 119; i++) {
    await page.mouse.wheel(0, 200);
    await page.waitForTimeout(500);
  }

  await page.getByRole('button', { name: 'Account menu' }).click();
  console.log();
  console.log('test1');
  console.log();
  await page.getByRole('menuitem', { name: 'Log out' }).click();
  console.log();
  console.log('test2');
  console.log();
  await page.waitForTimeout(500);
  await patchResponses();
  console.log();
  console.log('test3');
  console.log();
  await page.getByRole('button').and(page.getByText('Log out')).click();
  await page.waitForTimeout(500);
  await patchResponses();

  await page.waitForLoadState('networkidle');

  console.log('Closing browser');
  await browser.close();
  console.log('Done!');
})();
