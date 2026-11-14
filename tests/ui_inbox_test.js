// Inbox page against the fake IMAP server. Usage: node ui_inbox_test.js <appUrl> <licenseKey> <shotsDir>   (dev_stack with INBOX_LIVE=1)
const { chromium } = require('playwright');
const [, , APP, KEY, OUT] = process.argv; let fails = 0; const ok = (c, m) => { if (!c) { fails++; console.log('FAIL:', m); } };
(async () => {
  const b = await chromium.launch(); const p = await (await b.newContext({ viewport: { width: 1500, height: 940 } })).newPage(); const errs = [];
  p.on('pageerror', e => errs.push(e.message)); p.on('dialog', d => { errs.push('dialog: ' + d.message()); d.dismiss(); });
  await p.goto(APP); await p.fill('#lk', KEY); await p.click('#lgo'); await p.waitForSelector('#app:not(.hidden)');
  await p.click('[data-nav="inbox"]'); await p.waitForSelector('.ib-row');
  ok(await p.locator('.ib-row').count() === 4, 'four messages listed, got ' + await p.locator('.ib-row').count());
  ok(await p.locator('.ib-row.new').count() === 1, 'one unread');
  ok((await p.textContent('.ib-list')).includes('honker.wintry-0n@icloud.com'), 'hide-my-email alias shown');
  await p.screenshot({ path: OUT + '/inbox-list.png' });
  await p.click('.ib-row.new'); await p.waitForSelector('.ib-head');
  ok(await p.locator('.ib-imgbar').count() === 1, 'remote images blocked');
  ok(await p.locator('.ib-row.new').count() === 0, 'opened message marked read');
  const fr = p.frameLocator('.ib-frame'); ok((await fr.locator('body').textContent()).includes('P0041360611'), 'html body shown');
  ok(!(await p.locator('.ib-frame').evaluate(f => f.srcdoc)).includes('<script'), 'script stripped');
  await p.waitForTimeout(400); await p.screenshot({ path: OUT + '/inbox-open.png' });
  await p.click('[data-x="img"]'); await p.waitForSelector('.ib-head'); ok(await p.locator('.ib-imgbar').count() === 0, 'images shown on request');
  await p.click('.ib-row >> text=Your receipt from Apple'); await p.waitForSelector('.ib-att'); ok((await p.textContent('.ib-att')).includes('Receipt.pdf'), 'attachment listed');
  await p.click('[data-x="flag"]'); await p.waitForTimeout(500); ok(await p.locator('.ib-row.on .ib-flag').count() === 1, 'flag shows');
  await p.fill('#ib-q', 'walmart'); await p.waitForTimeout(600); ok(await p.locator('.ib-row').count() === 1, 'search');
  await p.fill('#ib-q', ''); await p.waitForTimeout(600);
  await p.click('.ib-tools [data-f="unread"]'); await p.waitForTimeout(500); ok(await p.locator('.ib-row').count() === 0, 'unread filter empty');
  await p.click('.ib-tools [data-f="all"]'); await p.waitForTimeout(500);
  await p.click('.ib-row >> text=Delivered: Charizard'); await p.waitForSelector('[data-x="del"]'); await p.click('[data-x="del"]'); await p.waitForTimeout(800);
  ok(await p.locator('.ib-row >> text=Delivered: Charizard').count() === 0, 'deleted');
  // new mail arrives on its own (dev stack adds one ~10s after start; the app checks every few seconds in this test)
  await p.waitForSelector('.ib-row >> text=Your Best Buy order', { timeout: 25000 }).catch(() => ok(false, 'new mail did not appear by itself'));
  ok(await p.locator('.ib-row.new').count() === 1, 'new mail is unread');
  await p.screenshot({ path: OUT + '/inbox-new.png' });
  ok(!errs.length, 'js errors: ' + errs.join(' | ')); console.log(fails ? 'FAILED' : 'inbox UI ok'); await b.close(); process.exit(fails ? 1 : 0);
})().catch(e => { console.log('CRASH', e.message); process.exit(2); });
