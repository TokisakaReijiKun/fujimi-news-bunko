// Compare the actual pre-sync PC bundle with current formal assets using synthetic APIs.
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const { chromium } = require('playwright');
const root = path.resolve(__dirname, '..');
const output = path.join(root, 'build/qa/pc-settings-style');
const baseline = path.join(root, 'dist/FujimiShinbunBunko-before-sync-20261017/_internal/static');
const panels = {
  voice: ['.voice-panel', '.panel-heading', 'h3', '#active-voice-badge', '#add-voice', '#voice-list'],
  daily: ['.daily-settings-panel', '.panel-heading', 'h3', '#schedule-state', '.daily-content-settings', '#daily-target-count', '#daily-content-summary', '#source-list', '#daily-mode', '#generate-daily'],
  library: ['.library-settings-panel', '.panel-heading', 'h3', '#library-sort-setting'],
  desktop: ['#desktop-settings-panel', '.panel-heading', 'h3', '.desktop-paths', '#open-desktop-data'],
  refresh: ['.refresh-panel', '.panel-heading', 'h3', '#refresh-storage'],
};

async function capture(browser, staticRoot, name) {
  const context = await browser.newContext({ viewport: { width: 1440, height: 1000 } });
  const sources = ['NHKニュース', '朝日新聞', '読売新聞', '日本経済新聞', '産経新聞', 'Yahoo!ニュース'].map((title, i) => ({ id: i + 1, name: title, homepage: 'https://example.org/', minimum_count: 1, voice_mode: 'browser' }));
  const values = {
    'health': { status: 'ok', tts: 'browser' },
    'voice-mode': { mode: 'browser', browser_voice_name: 'ja-JP-KeitaNeural', browser_voice_label: '圭太' },
    'browser-voices': [{ id: 'ja-JP-KeitaNeural', name: '圭太', available: true }],
    'library': { sort: 'recent', lookup_chinese_translations: true },
    'daily-content': { target_count: 10, source_count: 6, required_count: 6 },
    'daily-schedule': { mode: 'manual', time: '00:00', scheduler_available: true },
    'news-sources': sources,
    'device-sync': { enabled: false, status: 'disabled', paired_devices: [] },
    'daily': { status: 'idle' },
  };
  await context.route('**/*', async route => {
    const url = new URL(route.request().url());
    if (url.pathname.startsWith('/api/')) return route.fulfill({ contentType: 'application/json', body: JSON.stringify(values[url.pathname.split('/').pop()] || []) });
    const file = path.resolve(staticRoot, url.pathname.replace(/^\/static\//, ''));
    return file.startsWith(staticRoot + path.sep) && fs.existsSync(file)
      ? route.fulfill({ path: file }) : route.fulfill({ status: 404, body: '' });
  });
  await context.addInitScript(() => {
    window.pywebview = { api: { get_desktop_settings: async () => ({ project_root: 'C:/Fujimi', data_dir: 'C:/Fujimi/data', python_executable: 'C:/Fujimi/FujimiShinbunBunko.exe' }) } };
  });
  const page = await context.newPage();
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  await page.goto('http://127.0.0.1:8439/static/index.html#settings');
  await page.waitForFunction(() => document.querySelector('#voice-list').children.length && document.querySelector('#source-list').children.length === 6 && !document.querySelector('#desktop-settings-panel').hidden);
  await page.evaluate(() => document.fonts.ready);
  const snapshot = await page.evaluate(spec => {
    const properties = ['display', 'backgroundColor', 'color', 'borderRadius', 'borderTopWidth', 'borderTopColor', 'paddingTop', 'paddingRight', 'paddingBottom', 'paddingLeft', 'fontFamily', 'fontSize', 'fontWeight', 'lineHeight', 'boxShadow', 'gap', 'gridTemplateColumns', 'flexDirection'];
    const result = {};
    for (const [name, selectors] of Object.entries(spec)) {
      const panel = document.querySelector(selectors[0]);
      const panelRect = panel.getBoundingClientRect();
      result[name] = selectors.map((selector, i) => {
        const node = i ? panel.querySelector(selector) : panel;
        if (!node) throw new Error(`Missing ${name}: ${selector}`);
        const rect = node.getBoundingClientRect(), style = getComputedStyle(node);
        return {
          selector,
          style: Object.fromEntries(properties.map(property => [property, style[property]])),
          rect: { x: rect.x - panelRect.x, y: rect.y - panelRect.y, width: rect.width, height: rect.height },
        };
      });
    }
    return { panels: result, viewport: innerWidth, width: document.documentElement.scrollWidth };
  }, panels);
  assert.deepEqual(errors, []);
  assert(snapshot.width <= snapshot.viewport + 1, `${name}: horizontal overflow`);
  await page.screenshot({ path: path.join(output, `${name}.png`), fullPage: true });
  await context.close();
  return snapshot;
}

(async () => {
  assert(fs.existsSync(path.join(baseline, 'index.html')), 'Pre-sync PC backup is required as the visual baseline');
  fs.mkdirSync(output, { recursive: true });
  const browser = await chromium.launch({ channel: 'msedge', headless: true });
  try {
    const before = await capture(browser, baseline, 'before');
    const after = await capture(browser, path.join(root, 'static'), 'after');
    const differences = [];
    for (const name of Object.keys(panels)) {
      before.panels[name].forEach((expected, i) => {
        const actual = after.panels[name][i];
        for (const [property, value] of Object.entries(expected.style)) {
          if (actual.style[property] !== value) differences.push(`${name} ${expected.selector} ${property}: ${value} -> ${actual.style[property]}`);
        }
        for (const [axis, value] of Object.entries(expected.rect)) {
          if (Math.abs(actual.rect[axis] - value) > 1) differences.push(`${name} ${expected.selector} ${axis}: ${value} -> ${actual.rect[axis]}`);
        }
      });
    }
    fs.writeFileSync(path.join(output, 'results.json'), JSON.stringify({ before, after, differences }, null, 2));
    assert.deepEqual(differences, [], 'Original PC settings styles and control positions must be preserved');
    console.log(JSON.stringify({ passed: true, panels: Object.keys(panels), output }));
  } finally { await browser.close(); }
})().catch(error => { console.error(error); process.exitCode = 1; });
