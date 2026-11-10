// Stick rates, sender rules, backups, Windows card. Usage: node ui_features_test.js <appUrl> <licenseKey> <shotsDir>
const { chromium } = require('playwright');
const [, , APP, KEY, OUT] = process.argv; let fails = 0; const ok = (c, m) => { if (!c) { fails++; console.log('FAIL:', m); } };
(async () => {
  const b = await chromium.launch(); const p = await (await b.newContext({ viewport: { width: 1500, height: 940 } })).newPage(); const errs = [];
  p.on('pageerror', e => errs.push(e.message));
  await p.goto(APP); await p.fill('#lk', KEY); await p.click('#lgo'); await p.waitForSelector('#app:not(.hidden)');
  await p.click('[data-nav="stick"]'); await p.waitForSelector('#sr-d');
  ok((await p.textContent('#view')).includes('By email account'), 'stick page tables');
  await p.click('#sr-d [data-d="all"]'); await p.waitForTimeout(400); ok(await p.locator('#view table.t').count() >= 2, 'stick tables have rows');
  await p.screenshot({ path: OUT + '/stick.png', fullPage: true });
  await p.click('[data-nav="attention"]'); await p.waitForSelector('#ru-add');
  await p.click('[data-rule]'); await p.fill('#ru-r', 'Pokémon Center'); await p.selectOption('#ru-k', 'domain'); await p.click('#ru-s'); await p.waitForTimeout(600);
  ok((await p.textContent('#view')).includes('Anything from'), 'rule listed');
  await p.screenshot({ path: OUT + '/rules.png', fullPage: true });
  await p.click('[data-rdel]'); await p.waitForTimeout(500); ok(!(await p.textContent('#view')).includes('Anything from'), 'rule removed');
  await p.click('[data-nav="settings"]'); await p.waitForSelector('#sn-make');
  await p.click('#sn-make'); await p.waitForSelector('[data-sn]'); ok(await p.locator('[data-sn]').count() >= 1, 'backup listed');
  await p.click('[data-sn]'); await p.click('.modal .btn.danger, .modal .btn.p'); await p.waitForTimeout(800);
  await p.screenshot({ path: OUT + '/after-restore.png' }); ok((await p.textContent('#sn-list', { timeout: 5000 })).includes('Before a restore'), 'restore ran');
  ok(await p.locator('#dk').count() === 1, 'windows card');
  await p.locator('#sn-list').scrollIntoViewIfNeeded(); await p.screenshot({ path: OUT + '/backups.png' });
  ok(!errs.length, 'js errors: ' + errs.join(' | ')); console.log(fails ? 'FAILED' : 'features UI ok'); await b.close(); process.exit(fails ? 1 : 0);
})().catch(e => { console.log('CRASH', e.message); process.exit(2); });
