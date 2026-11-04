/* Optional real-browser private-file navigation gate, synthetic bridge only.
   Headless cannot certify native app-window chrome or window-manager sizing. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright-core');
(async () => {
  const context = await chromium.launchPersistentContext(process.env.ELARIA_TEST_PROFILE, {
    executablePath:process.env.ELARIA_CHROMIUM_PATH, headless:true,
    viewport:{width:1280,height:800},
    args:['--no-sandbox','--no-zygote','--in-process-gpu','--use-gl=angle','--use-angle=swiftshader']
  });
  try {
    const page = context.pages()[0] || await context.newPage();
    // Explicit navigation: this tests the private file/redirect, NOT native --app startup.
    await page.goto(process.env.ELARIA_TEST_LINK);
    await page.waitForFunction(() => document.querySelector('iframe')?.contentWindow.ElariaShell?.state.daemon);
    console.log('Current private launch connected.');
    assert(page.url() === process.env.ELARIA_TEST_URL, 'private file must reach this exact fresh launch');
    assert(await page.locator('#wire-error').isHidden());
    const origin = new URL(page.url()).origin;
    await page.goto(origin + '/');
    await page.waitForFunction(() => document.getElementById('wire-error')?.textContent.startsWith('LOCKED'));
    assert(!await page.locator('iframe').getAttribute('src'));
    console.log('Bare root remains locked.');
    const stale = await context.newPage();
    await stale.goto(origin + '/#pair=' + 'Z'.repeat(43));
    await stale.waitForFunction(() => document.getElementById('wire-error')?.textContent.includes('expired link'));
    assert(await stale.locator('#wire-error').isVisible());
    console.log('PASS: private file reaches current authenticated shell; root and stale links do not');
  } finally { await context.close(); }
})().catch(error => { console.error(error.message); process.exit(1); });
