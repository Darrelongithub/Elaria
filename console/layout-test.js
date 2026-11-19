/* Optional actual-browser geometry gate. Existing local Chromium + playwright-core only.
   ELARIA_TEST_URL must be a synthetic test bridge, never the owner's daemon.
   No model calls; no downloads. This is containment evidence, not owner visual approval. */
'use strict';
const assert = require('node:assert/strict');
const { chromium } = require('playwright-core');
(async () => {
  const browser = await chromium.launch({
    executablePath: process.env.ELARIA_CHROMIUM_PATH,
    headless: true,
    args: ['--no-sandbox', '--no-zygote', '--in-process-gpu', '--disable-dev-shm-usage', '--use-gl=angle', '--use-angle=swiftshader', '--enable-unsafe-swiftshader']
  });
  const rows = [];
  try {
    for (const [width, height] of [[1920,1080],[1440,900],[1024,768],[800,600],[390,844],[320,480]]) {
      const page = await browser.newPage({viewport:{width,height}});
      const errors = [];
      page.on('pageerror', error => errors.push(error.message));
      await page.goto(process.env.ELARIA_TEST_URL);
      await page.waitForFunction(() => document.querySelector('iframe').contentWindow.ElariaShell);
      const frame = page.frames().find(f => new URL(f.url()).pathname === '/console');
      await frame.waitForSelector('.orb.ready', {state:'attached'});
      await page.waitForTimeout(350);
      const outer = await page.evaluate(() => ({
        w:document.documentElement.scrollWidth,h:document.documentElement.scrollHeight,
        frame:document.querySelector('iframe').getBoundingClientRect().toJSON(),
        error:!document.getElementById('wire-error').hidden
      }));
      assert.equal(outer.w,width); assert.equal(outer.h,height);
      assert.equal(outer.frame.height,height); assert(!outer.error);
      const geometry = await frame.evaluate(() => {
        const rect = s => document.querySelector(s).getBoundingClientRect().toJSON();
        const orb = document.querySelector('.orb');
        const canvas = document.querySelector('#stage canvas');
        return {
          chat:rect('.term'),orb:rect('.orb'),stage:rect('#stage'),footer:rect('.console-footer'),
          lamps:rect('.lamps'),composer:rect('.cwrap'),input:rect('textarea'),sidebar:rect('.sb'),
          overflow:[orb.scrollWidth-orb.clientWidth,orb.scrollHeight-orb.clientHeight],
          canvas:canvas ? canvas.getBoundingClientRect().toJSON() : null,
          stageClient:[document.querySelector('#stage').clientWidth,document.querySelector('#stage').clientHeight],
          pixels:canvas ? [canvas.width,canvas.height] : null
        };
      });
      assert(geometry.chat.width > width * .35, 'chat must not fall into zero-width column');
      assert(Math.abs(geometry.footer.bottom-height)<1);
      assert(geometry.lamps.left >= 0 && geometry.lamps.right <= width);
      assert(geometry.composer.bottom <= geometry.footer.top+1);
      assert(geometry.input.width > 0 && geometry.input.right <= geometry.chat.right+1);
      if (width > 1040) {
        assert(Math.abs(geometry.orb.width/width-.36)<.002);
        assert(Math.abs(geometry.stage.height/geometry.orb.height-.80)<.005);
      }
      if (width > 680) {
        assert(geometry.canvas, 'actual renderer canvas required for this gate');
        assert(geometry.canvas.width > 0 && geometry.canvas.height > 0);
        assert(Math.abs(geometry.canvas.width-geometry.stage.width)<1);
        assert(Math.abs(geometry.canvas.height-geometry.stage.height)<1);
        assert(geometry.stage.top >= geometry.orb.top && geometry.stage.bottom <= geometry.orb.bottom+1);
        assert(geometry.stage.left >= geometry.orb.left && geometry.stage.right <= geometry.orb.right+1);
        assert.deepEqual(geometry.overflow,[0,0]);
      } else assert.equal(geometry.orb.width,0, 'small-screen orb must yield, not float over chat');
      if (width <= 940) {
        assert(geometry.sidebar.right <= 0);
        assert.equal(await frame.locator('#tgSb').getAttribute('aria-expanded'),'false');
        await frame.locator('#tgSb').click();
        await page.waitForTimeout(280);
        assert.equal(await frame.locator('#tgSb').getAttribute('aria-expanded'),'true');
        await frame.locator('#closeSb').click();
        await page.waitForTimeout(280);
      }
      await frame.locator('#tgFull').click();
      await page.waitForTimeout(300);
      const bounds = await frame.locator('#full').boundingBox();
      assert(bounds.y+bounds.height <= geometry.footer.top+1, 'full pane must leave footer visible');
      await frame.locator('#fclose').click();
      await page.waitForTimeout(250);
      await frame.locator('textarea').fill('Synthetic geometry input '.repeat(80));
      const input = await frame.locator('textarea').boundingBox();
      assert(input.y+input.height <= geometry.footer.top+1);
      assert.deepEqual(errors,[]);
      rows.push({viewport:[width,height],panel:[geometry.orb.width,geometry.orb.height],
        stage:geometry.stageClient,chat:geometry.chat.width,footer:geometry.footer.height});
      await page.close();
    }
    // Real ResizeObserver/fallback behavior through successive width changes, same engine instance.
    const page = await browser.newPage({viewport:{width:1920,height:1080}});
    await page.goto(process.env.ELARIA_TEST_URL);
    await page.waitForFunction(() => document.querySelector('iframe').contentWindow.ElariaShell);
    const frame = page.frames().find(f => new URL(f.url()).pathname === '/console');
    for (const width of [800,390,1440]) {
      await page.setViewportSize({width,height:900});
      await page.waitForTimeout(400);
      const sizes = await frame.evaluate(() => {
        const s=document.querySelector('#stage'),c=s.querySelector('canvas');
        return {w:s.clientWidth,h:s.clientHeight,pw:c.width,ph:c.height,chat:document.querySelector('.term').clientWidth};
      });
      assert(sizes.chat>width*.35);
      if(width>680) {
        assert(sizes.w>0 && sizes.h>0);
        assert(Math.abs(sizes.pw/sizes.ph-sizes.w/sizes.h)<.01, 'renderer aspect must follow stage resize');
      }
    }
    console.log('PASS: browser containment, 36%/80% wide geometry, footer, narrow chat, controls and resize');
    console.log(JSON.stringify(rows));
  } finally { await browser.close(); }
})().catch(error => { console.error(error.message); process.exit(1); });
