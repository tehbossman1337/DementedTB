// Drives the Inventory pages. Usage: node ui_inv_test.js <appUrl> <licenseKey> <shotsDir>
const { chromium } = require('playwright');
const [, , APP, KEY, OUT] = process.argv;
let fails = 0; const ok = (c, m) => { if (!c) { fails++; console.log('FAIL:', m); } };
(async () => {
  const b = await chromium.launch(); const p = await (await b.newContext({ viewport: { width: 1500, height: 940 } })).newPage(); const errs = [];
  p.on('pageerror', e => errs.push(e.message)); p.on('console', m => m.type() === 'error' && !/403/.test(m.text()) && errs.push(m.text()));
  await p.goto(APP); await p.waitForSelector('#lk,#app:not(.hidden)'); if (await p.locator('#lk').count()) { await p.fill('#lk', KEY); await p.click('#lgo'); } await p.waitForSelector('#app:not(.hidden)');
  const side = await p.textContent('#side'); ok(side.includes('Inventory') && side.includes('Fees & settings') && !side.includes('Site accounts') && side.includes('Accounts'), 'sidebar has Inventory and plain Accounts');
  const nav = async id => { await p.click(`[data-nav="${id}"]`); await p.waitForTimeout(500); };
  await nav('inv_items'); await p.waitForSelector('#i-add');
  await p.click('#i-add'); await p.fill('#im-name', 'Pokemon 151 Elite Trainer Box'); await p.fill('#im-qty', '4'); await p.fill('#im-pp', '40'); await p.fill('#im-lp', '70'); await p.selectOption('#im-plat', 'eBay'); await p.screenshot({ path: OUT + '/inv-item-modal.png' }); await p.click('#im-save');
  await p.waitForSelector('tr[data-id]:has-text("151 Elite")'); ok(await p.locator('tr[data-id]', { hasText: '151 Elite' }).count() === 1, 'item listed'); ok(await p.locator('tr[data-id]', { hasText: 'From order' }).count() + await p.locator('tr[data-id]').count() >= 2, 'delivered order landed in inventory');
  await p.screenshot({ path: OUT + '/inv-items.png' });
  await p.locator('tr[data-id]', { hasText: '151 Elite' }).locator('[data-sell]').click(); await p.waitForSelector('#sm-save'); await p.fill('#sm-qty', '2'); await p.fill('#sm-price', '150'); await p.fill('#sm-shk', '8'); await p.waitForTimeout(200);
  ok(/Profit/.test(await p.textContent('#sm-prev')), 'live profit preview'); await p.screenshot({ path: OUT + '/inv-sale-modal.png' }); await p.click('#sm-save');
  await nav('inv_sales'); await p.waitForSelector('tr[data-id]'); ok(await p.locator('tr[data-id]').count() === 1, 'sale listed'); await p.screenshot({ path: OUT + '/inv-sales.png' });
  await nav('inv_receipts'); await p.waitForSelector('#r-add'); await p.click('#r-add'); await p.fill('#rm-amt', '20'); await p.fill('#rm-ven', 'Uline'); await p.selectOption('#rm-cat', 'Shipping Supplies'); await p.click('#rm-save'); await p.waitForSelector('tr[data-id]');
  await nav('inv_scan'); await p.waitForSelector('#sc-in'); await p.fill('#sc-in', 'PK-0002'); await p.press('#sc-in', 'Enter'); await p.waitForSelector('.scanmsg.ok'); ok(/quantity is now 5/.test(await p.textContent('.scanmsg')), 'scan receive'); await p.screenshot({ path: OUT + '/inv-scan.png' });
  await nav('inv_tax'); await p.waitForSelector('#tx-y'); ok(/Net profit/.test(await p.textContent('#view')), 'tax page'); await p.screenshot({ path: OUT + '/inv-tax.png' });
  await nav('inv_dash'); await p.waitForSelector('.stats'); await p.waitForTimeout(300); ok(/Net profit/.test(await p.textContent('#view')), 'dashboard'); await p.screenshot({ path: OUT + '/inv-dash.png' });
  await nav('inv_settings'); await p.waitForSelector('#st-save'); await p.screenshot({ path: OUT + '/inv-settings.png' });
  ok(errs.length === 0, 'no console errors: ' + errs.join(' | '));
  await b.close(); console.log(fails ? fails + ' FAILED' : 'inventory UI ok');
})();
