const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const { mkdtemp, readFile, rm } = require('node:fs/promises');
const { tmpdir } = require('node:os');
const { join } = require('node:path');
const { chromium } = require('playwright');

async function testDashboard() {
  const temp = await mkdtemp(join(tmpdir(), 'super6-dashboard-'));
  let browser;
  try {
    const build = spawnSync('python', ['tests/browser_fixture.py', temp], {
      env: { ...process.env, PYTHONPATH: '.' }, stdio: 'inherit'
    });
    assert.equal(build.status, 0);
    browser = await chromium.launch({
      executablePath: process.env.SUPER6_TEST_CHROMIUM || undefined
    });
    const page = await browser.newPage({
      viewport: { width: 360, height: 800 }, isMobile: true, hasTouch: true
    });
    const errors = [];
    page.on('pageerror', error => errors.push(error.message));
    const report = JSON.parse(await readFile(join(temp, 'report.json'), 'utf-8'));
    // Simulate a damaged link at the presentation boundary independently of importer rejection.
    report.rounds[1].round.fixtures[0].research.form.url = 'https://example.invalid:bad/';
    await page.route('https://super6-test.invalid/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (path === '/report.json') return route.fulfill({ json: report });
      const file = { '/': 'index.html', '/dashboard.js': 'dashboard.js', '/style.css': 'style.css' }[path];
      if (!file) return route.abort();
      await route.fulfill({ path: join('dashboard', file) });
    });
    await page.goto('https://super6-test.invalid/');
    await page.getByText('Model prediction pending complete pre-deadline evidence.').waitFor();
    await page.getByText('First goal from Sky match reports · Minute 13').waitFor();
    await page.getByLabel('Forecast').selectOption('venue_goals');
    await page.getByText('Five previous results per venue').first().click();
    await page.getByText('West Ham United at home').waitFor();
    await page.locator('#round').selectOption({ label: 'Synthetic test only' });
    await page.getByText('Chance of 13+ points').waitFor();
    await page.getByText('100,000 simulations', { exact: false }).waitFor();
    await page.getByText('Research evidence').first().click();
    const round = page.locator('#round-content');
    assert.equal(await round.locator('article').count(), 6);
    assert.equal(await round.locator('a').filter({ hasText: /^form$/ }).count(), 5);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    assert.deepEqual(errors, []);
    console.log('Mobile dashboard checks passed at 360 CSS pixels');
  } finally {
    if (browser) await browser.close();
    await rm(temp, { recursive: true, force: true });
  }
}

testDashboard().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
