const assert = require('node:assert/strict');
const { spawnSync } = require('node:child_process');
const { mkdtemp, readFile, rm } = require('node:fs/promises');
const { tmpdir } = require('node:os');
const { join } = require('node:path');
const { chromium, webkit, devices } = require('playwright');

async function checkDashboard(browser, device, report) {
  const page = await browser.newPage(devices[device]);
  const errors = [];
  try {
    page.on('pageerror', error => errors.push(error.message));
    // Reproduce the live window even when CI runs after the real entry deadline.
    await page.clock.setFixedTime(new Date('2026-11-23T21:00:00Z'));
    await page.route('https://super6-test.invalid/**', async route => {
      const path = new URL(route.request().url()).pathname;
      if (path === '/report.json') return route.fulfill({ json: report });
      const file = { '/': 'index.html', '/dashboard.js': 'dashboard.js',
        '/capture.js': 'capture.js', '/style.css': 'style.css' }[path];
      if (!file) return route.abort();
      await route.fulfill({ path: join('dashboard', file) });
    });
    await page.goto('https://super6-test.invalid/');
    await page.getByText('Provisional forecast · limited pre-match evidence').waitFor();
    await page.getByText('Chance of all six exact scores').waitFor();
    await page.getByText('Form and opposition evidence').first().click();
    await page.getByText(/Recent games · 4 matches/).first().waitFor();
    await page.getByRole('button', { name: 'Load selected round' }).click();
    assert.equal(await page.getByLabel('Round label').inputValue(), '2026–27 Round 18');
    await page.getByText('Attach manual research evidence').click();
    await page.getByLabel('Evidence type').selectOption('injuries');
    await page.locator('#manual-url').fill('https://example.invalid/team-news');
    await page.locator('#manual-time').fill('2026-11-23T20:00:00Z');
    await page.locator('#manual-note').fill('Synthetic browser-test evidence only.');
    await page.getByRole('button', { name: 'Attach evidence' }).click();
    await page.getByText('Evidence attached to fixture 1.', { exact: false }).waitFor();
    await page.getByLabel(/I checked all six/).check();
    await page.getByRole('button', { name: 'Save local confirmation' }).click();
    await page.getByText('Six fixtures confirmed and saved on this device.').waitFor();
    const [download] = await Promise.all([
      page.waitForEvent('download'),
      page.getByRole('button', { name: 'Export round JSON' }).click()
    ]);
    const saved = JSON.parse(await readFile(await download.path(), 'utf-8'));
    assert.equal(saved.fixtures.length, 6);
    assert.equal(saved.fixtures[0].research.injuries.url, 'https://example.invalid/team-news');
    assert.equal(saved.official.confirmed_at, '2026-11-23T21:00:00.000Z');
    await page.reload();
    assert.equal(await page.getByLabel('Round label').inputValue(), '2026–27 Round 18');
    await page.locator('#round').selectOption({ label: '2020–21 Round 1' });
    await page.getByText('Model prediction pending complete pre-deadline evidence.').waitFor();
    await page.getByText('First goal from Sky match reports · Minute 13').waitFor();
    await page.getByLabel('Forecast').selectOption('venue_goals');
    await page.getByText('Five previous results per venue').first().click();
    await page.getByText('West Ham United at home').waitFor();
    await page.locator('#round').selectOption({ label: 'Synthetic test only' });
    await page.getByText('Forecast based on verified pre-deadline evidence').waitFor();
    await page.getByText('Chance of 13+ points').waitFor();
    await page.getByText('100,000 simulations', { exact: false }).waitFor();
    await page.getByText('Research evidence').first().click();
    const round = page.locator('#round-content');
    assert.equal(await round.locator('article').count(), 6);
    assert.equal(await round.locator('a').filter({ hasText: /^form$/ }).count(), 5);
    assert.equal(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth), true);
    assert.deepEqual(errors, []);
    console.log(device + ' dashboard and fixture capture checks passed');
  } finally {
    await page.close();
  }
}

async function testDashboard() {
  const temp = await mkdtemp(join(tmpdir(), 'super6-dashboard-'));
  try {
    const build = spawnSync('python', ['tests/browser_fixture.py', temp], {
      env: { ...process.env, PYTHONPATH: '.' }, stdio: 'inherit'
    });
    assert.equal(build.status, 0);
    const report = JSON.parse(await readFile(join(temp, 'report.json'), 'utf-8'));
    // Simulate a damaged link at the presentation boundary independently of importer rejection.
    report.rounds.find(row => row.round.id === 'Synthetic test only')
      .round.fixtures[0].research.form.url = 'https://example.invalid:bad/';
    for (const [engine, device] of [[chromium, 'Pixel 7'], [webkit, 'iPhone 13'], [webkit, 'iPad Mini']]) {
      const browser = await engine.launch();
      try {
        await checkDashboard(browser, device, report);
      } finally {
        await browser.close();
      }
    }
  } finally {
    await rm(temp, { recursive: true, force: true });
  }
}

testDashboard().catch(error => {
  console.error(error);
  process.exitCode = 1;
});
