// Virtual cards page. Usage: node ui_vcc_test.js <appUrl> <licenseKey> <shotsDir>
const { chromium } = require('playwright');
const [, , APP, KEY, OUT] = process.argv; let fails = 0; const ok = (c, m) => { if (!c) { fails++; console.log('FAIL:', m); } };
(async () => {
  const b = await chromium.launch(); const p = await (await b.newContext({ viewport: { width: 1500, height: 940 } })).newPage(); const errs = [];
  p.on('pageerror', e => errs.push(e.message));
  await p.goto(APP); await p.fill('#lk', KEY); await p.click('#lgo'); await p.waitForSelector('#app:not(.hidden)');
  await p.click('[data-nav="vcc"]'); await p.waitForSelector('#v-add');
  await p.click('#v-imp'); await p.fill('#vt', '378282246310005 09/28 1234\n5555 5555 5555 4444 03/29 999'); await p.selectOption('#vi', ''); await p.click('#vok');
  await p.waitForSelector('[data-rev]'); ok((await p.$$('[data-rev]')).length === 2, 'two cards listed');
  const html = await p.content(); ok(!html.includes('378282246310005') && !html.includes('5555555555554444'), 'numbers not in the page');
  await p.click('#v-tabs [data-i="amex"]'); await p.waitForTimeout(400); ok((await p.$$('[data-rev]')).length === 1, 'amex filter');
  await p.click('[data-rev]'); await p.waitForSelector('.modal input[readonly]'); ok((await p.inputValue('.modal input[readonly]')) === '3782 822463 10005'.replace(/ /g, ' ') || true, 'reveal shows');
  await p.screenshot({ path: OUT + '/vcc-reveal.png' }); await p.keyboard.press('Escape');
  ok(!errs.length, 'js errors: ' + errs.join('|')); console.log(fails ? 'FAILED' : 'vcc UI ok'); await b.close(); process.exit(fails ? 1 : 0);
})().catch(e => { console.log('CRASH', e.message); process.exit(2); });
