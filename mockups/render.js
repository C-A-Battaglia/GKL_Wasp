// Renders the HTML mockups in mockups/src to JPEGs in mockups/.
// Usage: NODE_PATH=$(npm root -g) node mockups/render.js
const { chromium } = require('playwright');
const path = require('path');
const fs = require('fs');

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage({ deviceScaleFactor: 2, viewport: { width: 2600, height: 600 } });
  const srcDir = path.join(__dirname, 'src');
  for (const f of fs.readdirSync(srcDir).filter(f => f.endsWith('.html'))) {
    await page.goto('file://' + path.join(srcDir, f));
    await page.evaluate(() => document.fonts.ready);
    const w = await page.evaluate(() => document.body.scrollWidth);
    await page.setViewportSize({ width: w, height: 600 });
    const out = path.join(__dirname, f.replace('.html', '.jpg'));
    await page.screenshot({ path: out, type: 'jpeg', quality: 90, fullPage: true });
    console.log('wrote', out);
  }
  await browser.close();
})();
