const assert = require("assert");
const fs = require("fs");
const path = require("path");
const { pathToFileURL } = require("url");
const { chromium } = require("playwright");

const root = path.join(__dirname, "settings-redesign-demos");
const output = path.join(__dirname, "..", "build", "qa", "settings-redesign-demos");
const pages = ["index", "quiet-editorial", "command-center", "library-shelf"];
const viewports = [{ name: "375", width: 375, height: 812 }, { name: "390", width: 390, height: 844 }, { name: "1440", width: 1440, height: 1000 }];

(async () => {
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: "msedge", headless: true });
  const results = [];
  try {
    for (const pageName of pages) {
      for (const viewport of viewports) {
        const page = await browser.newPage({ viewport: { width: viewport.width, height: viewport.height } });
        const errors = [];
        page.on("pageerror", (error) => errors.push(error.message));
        await page.goto(pathToFileURL(path.join(root, `${pageName}.html`)).href, { waitUntil: "load" });
        const layout = await page.evaluate(() => {
          const viewportWidth = document.documentElement.clientWidth;
          const overflowingControls = [...document.querySelectorAll("button, input, select")]
            .filter((element) => element.getBoundingClientRect().right > viewportWidth + 1)
            .map((element) => element.id || element.textContent.trim());
          return { scrollWidth: document.documentElement.scrollWidth, viewportWidth, overflowingControls, title: document.title };
        });
        assert.equal(errors.length, 0, `${pageName}/${viewport.name}: ${errors.join("; ")}`);
        assert(layout.scrollWidth <= layout.viewportWidth + 1, `${pageName}/${viewport.name}: horizontal overflow ${layout.scrollWidth} > ${layout.viewportWidth}`);
        assert.equal(layout.overflowingControls.length, 0, `${pageName}/${viewport.name}: overflowing controls ${layout.overflowingControls.join(", ")}`);
        if (pageName !== "index") {
          const sectionIds = await page.locator(".settings-panel").evaluateAll((items) => items.map((item) => item.id));
          assert.deepEqual(sectionIds, ["voice", "daily", "library", "mobile", "system", "refresh"], `${pageName}/${viewport.name}: vertical section order changed`);
          assert((await page.locator("details").count()) >= 3, `${pageName}/${viewport.name}: progressive details missing`);
          await page.locator("details").first().click();
          assert.equal(await page.locator("details").first().evaluate((details) => details.open), true, `${pageName}/${viewport.name}: details did not open`);
          await page.click('[data-action="refresh"]');
          assert.equal(await page.locator(".toast").isVisible(), true, `${pageName}/${viewport.name}: action feedback missing`);
        }
        await page.screenshot({ path: path.join(output, `${pageName}-${viewport.name}.png`), fullPage: true });
        results.push({ page: pageName, viewport: viewport.name, width: layout.scrollWidth, title: layout.title });
        await page.close();
      }
    }
  } finally {
    await browser.close();
  }
  fs.writeFileSync(path.join(output, "results.json"), JSON.stringify(results, null, 2));
  console.log(JSON.stringify({ passed: results.length, output }, null, 2));
})().catch((error) => { console.error(error.stack || error); process.exitCode = 1; });
