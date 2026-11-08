/* Inventory: dashboard, items, sales, receipts, scan station, tax summary, fees & settings */
const istate = { q: '', cat: '', status: '', sel: new Set(), selS: new Set(), selR: new Set(), mode: 'receive', by: '', year: 0 };
const num = v => { const n = parseFloat(String(v ?? '').replace(/[$,]/g, '')); return isNaN(n) ? 0 : n; };
const pct = v => v == null ? '—' : (v * 100).toFixed(1) + '%';
const profCls = v => v == null ? '' : v >= 0 ? 'pos' : 'neg';
const sel2 = (id, label, opts, val = '', blank = '') => `<div class="fld"><label class="f">${label}</label><select class="sel" id="${id}">${blank !== null ? `<option value="">${esc(blank)}</option>` : ''}${opts.map(o => `<option ${o === val ? 'selected' : ''}>${esc(o)}</option>`).join('')}</select></div>`;
const dl = (id, opts) => `<datalist id="${id}">${opts.map(o => `<option value="${esc(o)}">`).join('')}</datalist>`;
const csvBar = (name, done) => `<button class="btn" data-csv-ex="${name}">Export CSV</button><button class="btn" data-csv-im="${name}">Import CSV</button>`;
function csvHandlers(v, done) {
  $$('[data-csv-ex]', v).forEach(b => b.onclick = async () => { const r = await act(() => api('/api/inv/csv/export', { name: b.dataset.csvEx })); if (r) { toast('Saved to ' + r.path); api('/api/open_folder', {}); } });
  $$('[data-csv-im]', v).forEach(b => b.onclick = async () => {
    const f = await pickFile('.csv,text/csv'); if (!f) return;
    const r = await act(() => api('/api/inv/csv/import', { name: b.dataset.csvIm, text: f.text })); if (!r) return;
    if (r.error_count) modal(`<h2>Imported ${r.added} row${r.added === 1 ? '' : 's'}</h2><p>${r.error_count} row${r.error_count === 1 ? '' : 's'} were skipped:</p><div class="vlist">${r.errors.map(e => `<div>${esc(e)}</div>`).join('')}</div><div class="mfoot"><button class="btn p" data-close>OK</button></div>`);
    else toast(`Imported ${r.added} row${r.added === 1 ? '' : 's'}`);
    done();
  });
}

/* ============================ DASHBOARD ============================ */
PAGES.inv_dash = async function (v) {
  const T = S.tok; const d = await api('/api/inv/dashboard'); if (T !== S.tok) return;
  const mx = Math.max(1, ...d.months.map(m => Math.max(m.revenue, Math.abs(m.profit))));
  const st = (k, val, sub, cls = '') => `<div class="stat"><div class="k">${k}</div><div class="v ${cls}">${val}</div><div class="d">${sub}</div></div>`;
  v.innerHTML = `<div class="page"><div class="ph"><div><h1>Inventory dashboard</h1><p>What you hold, what it cost, and what it earned. Delivered orders from the tracker are added to Items automatically.</p></div>
    <div class="acts"><button class="btn" data-go="inv_scan">Scan station</button><button class="btn p" data-go="inv_items">Add item</button></div></div>
    <div class="stats">${st('In stock', d.in_stock, d.items + ' item' + (d.items === 1 ? '' : 's'))}${st('Cost on hand', money(d.cost_on_hand), 'Market value ' + money(d.market_value))}${st('Revenue', money(d.revenue), d.sold + ' unit' + (d.sold === 1 ? '' : 's') + ' sold')}${st('Net profit', money(d.net_profit), 'After ' + money(d.expenses) + ' expenses', d.net_profit >= 0 ? 'green' : 'red')}${st('ROI', pct(d.roi), 'Fees paid ' + money(d.fees))}</div>
    <div class="card"><div class="cardt"><span>Last 6 months</span></div><div class="bars2">${d.months.map(m => `<div class="m"><div class="b rv" style="height:${Math.max(2, m.revenue / mx * 100)}%" data-tip="${m.label} revenue ${money(m.revenue)}"></div><div class="b pf ${m.profit < 0 ? 'neg' : ''}" style="height:${Math.max(2, Math.abs(m.profit) / mx * 100)}%" data-tip="${m.label} profit ${money(m.profit)}"></div></div>`).join('')}</div>
      <div class="axis">${d.months.map(m => `<span>${m.label}</span>`).join('')}</div><div class="legend"><span><i style="background:#5b5b78"></i>Revenue</span><span><i style="background:#ee3556"></i>Profit</span></div></div>
    <div class="g2">
     <div class="card"><div class="cardt"><span>Monthly target</span></div>${d.target.target ? `<div class="mini"><span>Target</span><b>${money(d.target.target)}</b></div><div class="mini"><span>So far this month</span><b class="${profCls(d.target.so_far)}">${money(d.target.so_far)}</b></div><div class="mini"><span>Remaining</span><b>${money(d.target.remaining)}</b></div><div class="mini"><span>Sales still needed (at ${money(d.target.avg_profit)} each)</span><b>${d.target.more_sales ?? '—'}</b></div>` : '<div class="note">Set a monthly profit target under Fees & settings.</div>'}</div>
     <div class="card"><div class="cardt"><span>By category</span></div>${d.by_category.map(c => `<div class="mini"><span>${esc(c.category)} · ${c.units} sold</span><b>${money(c.revenue)} <span class="muted" style="font-weight:400">(${money(c.profit)})</span></b></div>`).join('')}</div>
     <div class="card"><div class="cardt"><span>By team member</span></div>${d.by_member.map(m => `<div class="mini"><span>${esc(m.name)} · ${m.sales} sale${m.sales === 1 ? '' : 's'}</span><b>${money(m.revenue)} <span class="muted" style="font-weight:400">(${money(m.profit)})</span></b></div>`).join('')}</div>
     <div class="card"><div class="cardt"><span>Reorder hints</span></div>${d.reorder.map(r => `<div class="mini"><span>${esc(r.category)} · ${r.sold_30d} sold in 30 days · ${r.in_stock} left</span><b>${esc(r.suggestion)}</b></div>`).join('')}</div>
     <div class="card"><div class="cardt"><span>Sitting too long</span><span>${d.aging_count} over ${d.aging_days} days</span></div>${d.price_drops.length ? d.price_drops.map(p => `<div class="mini"><span>${esc(p.item)} · ${p.days} days</span><b>${p.suggested ? 'Try ' + money(p.suggested) + ' (now ' + money(p.listed) + ')' : 'Not listed'}</b></div>`).join('') : '<div class="note">Nothing in stock yet.</div>'}</div>
     <div class="card"><div class="cardt"><span>Best sales</span></div>${d.top_sales.length ? d.top_sales.map(t => `<div class="mini"><span>${esc(t.item)} · ${esc(t.sku)}</span><b class="${profCls(t.profit)}">${money(t.profit)} · ${pct(t.roi)}</b></div>`).join('') : '<div class="note">No sales with a known cost yet.</div>'}</div>
     <div class="card"><div class="cardt"><span>Recent sales</span><span>Repeat buyers: ${d.repeat_buyers.count}</span></div>${d.recent_sales.length ? d.recent_sales.map(t => `<div class="mini"><span>${esc(t.item)} · ${fdate(t.date)}</span><b>${money(t.price)} <span class="${profCls(t.profit)}" style="font-weight:400">(${t.profit == null ? 'no cost' : money(t.profit)})</span></b></div>`).join('') : '<div class="note">No sales yet.</div>'}</div></div></div>`;
  $$('[data-go]', v).forEach(b => b.onclick = () => go(b.dataset.go));
};

/* ============================ ITEMS ============================ */
PAGES.inv_items = async function (v) {
  const T = S.tok; const d = await api('/api/inv/items'); if (T !== S.tok) return;
  const L = d.lists; const q = istate.q.toLowerCase();
  const all = d.items; istate.sel = new Set([...istate.sel].filter(i => all.some(x => x.id === i)));
  const rows = all.filter(x => (!istate.cat || x.category === istate.cat) && (!istate.status || x.status === istate.status) && (!q || [x.sku, x.name, x.pokemon_set, x.card_no, x.location, x.barcode].join(' ').toLowerCase().includes(q)));
  const byId = Object.fromEntries(all.map(x => [x.id, x]));
  v.innerHTML = `<div class="page"><div class="ph"><div><h1>Items</h1><p>Everything you hold. Quantity, cost and listing price live here; sales subtract from stock.</p></div><div class="acts">${csvBar('inventory')}<button class="btn p" id="i-add">Add item</button></div></div>
    <div class="filters"><input class="inp" id="i-q" style="max-width:300px" placeholder="Search SKU, name, set, barcode…" value="${esc(istate.q)}">
     <select class="sel" id="i-cat" style="width:auto"><option value="">All categories</option>${L.categories.map(c => `<option ${c === istate.cat ? 'selected' : ''}>${c}</option>`).join('')}</select>
     <select class="sel" id="i-st" style="width:auto"><option value="">All statuses</option>${['In stock', 'Listed', 'Partly sold', 'Sold'].map(c => `<option ${c === istate.status ? 'selected' : ''}>${c}</option>`).join('')}</select><span class="note">${rows.length} of ${all.length}</span></div>
    <div id="i-bulk"></div><div id="i-list"></div></div>`;
  csvHandlers(v, refreshPage);
  $('#i-q').oninput = e => { istate.q = e.target.value; refreshPage(); setTimeout(() => { const el = $('#i-q'); el.focus(); el.setSelectionRange(el.value.length, el.value.length); }, 0); };
  $('#i-cat').onchange = e => { istate.cat = e.target.value; refreshPage(); }; $('#i-st').onchange = e => { istate.status = e.target.value; refreshPage(); };
  $('#i-add').onclick = () => itemModal(null, L, refreshPage);
  const bulk = () => { const n = istate.sel.size; $('#i-bulk').innerHTML = n ? `<div class="bulk"><b>${n} selected</b><button class="btn sm danger" id="ib-del">Delete</button><button class="btn sm ghost" id="ib-clr">Clear</button></div>` : '';
    if (n) { $('#ib-clr').onclick = () => { istate.sel.clear(); draw(); }; $('#ib-del').onclick = async () => { if (await confirmBox(`Delete ${n} item${n === 1 ? '' : 's'}?`, 'Items that already have sales are kept.', 'Delete', true)) { const r = await act(() => api('/api/inv/items/delete', { ids: [...istate.sel] })); if (r) { toast(`Deleted ${r.deleted}` + (r.blocked.length ? `. Kept (has sales): ${r.blocked.join(', ')}` : '')); istate.sel.clear(); refreshPage(); } } }; } };
  function draw() {
    const Lb = $('#i-list');
    if (!rows.length) { Lb.innerHTML = `<div class="empty"><b>${all.length ? 'Nothing matches' : 'No items yet'}</b>${all.length ? '' : 'Add one, scan it in, import a CSV — or let delivered orders from the tracker fill this in.'}</div>`; bulk(); return; }
    Lb.innerHTML = `<div class="tbl-wrap"><table class="t"><thead><tr><th style="width:34px"><input type="checkbox" class="ck" id="i-all" ${rows.every(x => istate.sel.has(x.id)) ? 'checked' : ''}></th><th>SKU</th><th>Item</th><th>Status</th><th>Left / total</th><th>Cost each</th><th>Listed</th><th>Market</th><th>Profit</th><th>Days held</th><th></th></tr></thead><tbody>
      ${rows.map(x => `<tr data-id="${x.id}" class="${istate.sel.has(x.id) ? 'sel' : ''}"><td><input type="checkbox" class="ck" ${istate.sel.has(x.id) ? 'checked' : ''}></td><td class="mono">${esc(x.sku)}</td><td class="p"><b>${esc(x.name)}</b><div class="note">${esc([x.pokemon_set, x.card_no, x.condition, x.grading].filter(Boolean).join(' · ') || x.category)}</div></td><td>${x.status}</td><td>${x.qty_remaining} / ${x.qty}</td><td>${x.purchase_price ? money(x.purchase_price) + (x.currency !== 'USD' ? ' ' + x.currency : '') : '—'}</td><td>${x.listed_price ? money(x.listed_price) : '—'}</td><td>${x.market_price ? money(x.market_price) : '—'}</td><td class="${profCls(x.profit)}">${x.profit == null ? '—' : money(x.profit)}</td><td>${x.days_held ?? '—'}</td><td style="text-align:right">${x.qty_remaining ? '<button class="btn sm" data-sell>Sell</button>' : ''}</td></tr>`).join('')}</tbody></table></div>`;
    $('#i-all', Lb).onclick = e => { rows.forEach(x => e.target.checked ? istate.sel.add(x.id) : istate.sel.delete(x.id)); draw(); };
    $$('tr[data-id]', Lb).forEach(tr => { const x = byId[tr.dataset.id];
      $('.ck', tr).onclick = e => { e.stopPropagation(); e.target.checked ? istate.sel.add(x.id) : istate.sel.delete(x.id); tr.classList.toggle('sel', e.target.checked); bulk(); };
      tr.onclick = () => itemModal(x, L, refreshPage); const sb = $('[data-sell]', tr); if (sb) sb.onclick = e => { e.stopPropagation(); saleModal({ sku: x.sku }, refreshPage); }; });
    bulk();
  }
  draw();
};
function itemModal(x, L, done) {
  const r = x || { category: 'Pokemon Card', qty: 1, currency: 'USD', purchase_date: new Date().toISOString().slice(0, 10) };
  modal(`<h2>${x ? 'Edit ' + esc(x.sku) : 'Add item'}</h2>${dl('dl-sets', L.pokemon_sets)}
    <div class="col3">${sel2('im-cat', 'Category', L.categories, r.category, null)}${fi('im-sku', 'SKU (blank = automatic)', x ? x.sku : '')}${fi('im-bc', 'Barcode (optional)', r.barcode)}</div>
    ${fi('im-name', 'Name', r.name)}<div class="col3"><div class="fld"><label class="f">Set</label><input class="inp" id="im-set" list="dl-sets" value="${esc(r.pokemon_set)}"></div>${fi('im-no', 'Card number', r.card_no)}${sel2('im-cond', 'Condition', L.conditions, r.condition, '—')}</div>
    <div class="col3">${sel2('im-gr', 'Grading', L.grading, r.grading, '—')}${fi('im-qty', 'Quantity', r.qty, 'number')}${sel2('im-by', 'Added by', L.team, r.added_by, '—')}</div>
    <div class="fsec">Cost</div><div class="col3">${fi('im-pd', 'Purchase date', r.purchase_date, 'date')}${fi('im-pp', 'Cost each', r.purchase_price || '', 'number')}${sel2('im-cur', 'Currency', L.currencies, r.currency, null)}</div>
    <div class="col2">${sel2('im-src', 'Bought from', L.purchase_sources, r.purchase_source, '—')}${fi('im-loc', 'Location', r.location)}</div>
    <div class="fsec">Selling</div><div class="col3">${sel2('im-plat', 'Listed on', L.platforms, r.listing_platform, '—')}${fi('im-lp', 'Listed price', r.listed_price || '', 'number')}${fi('im-mp', 'Market price', r.market_price || '', 'number')}</div>
    <div class="fld"><label class="f">Notes</label><textarea class="ta" id="im-notes" rows="2">${esc(r.notes)}</textarea></div>
    <div class="mfoot">${x ? '<button class="btn danger" id="im-del" style="margin-right:auto">Delete</button>' : ''}<button class="btn" data-close>Cancel</button><button class="btn p" id="im-save">Save</button></div>`, {
    wide: true, onMount: m => {
      $('#im-save', m).onclick = async () => { const g = i => $('#' + i, m).value; const item = { category: g('im-cat'), sku: g('im-sku'), barcode: g('im-bc'), name: g('im-name'), pokemon_set: g('im-set'), card_no: g('im-no'), condition: g('im-cond'), grading: g('im-gr'), qty: g('im-qty'), added_by: g('im-by'),
        purchase_date: g('im-pd'), purchase_price: g('im-pp'), currency: g('im-cur'), purchase_source: g('im-src'), location: g('im-loc'), listing_platform: g('im-plat'), listed_price: g('im-lp'), market_price: g('im-mp'), notes: g('im-notes') };
        if (await act(() => api('/api/inv/items/save', { id: x ? x.id : undefined, item }), 'Saved')) { closeModal(); done(); } };
      if (x) $('#im-del', m).onclick = async () => { const r2 = await act(() => api('/api/inv/items/delete', { ids: [x.id] })); if (r2) { if (r2.blocked.length) toast(`${x.sku} has sales, so it was kept. Delete those sales first.`, true); else { toast('Deleted'); closeModal(); done(); } } };
    }
  });
}

/* ============================ SALES ============================ */
PAGES.inv_sales = async function (v) {
  const T = S.tok; const d = await api('/api/inv/sales'); if (T !== S.tok) return;
  istate.selS = new Set([...istate.selS].filter(i => d.sales.some(x => x.id === i)));
  const q = istate.q.toLowerCase(); const rows = d.sales.filter(x => !q || [x.sale_id, x.sku, x.item_name, x.buyer, x.platform].join(' ').toLowerCase().includes(q));
  const tot = rows.reduce((a, x) => ({ rev: a.rev + x.sale_price, net: a.net + (x.net || 0), pr: a.pr + (x.profit || 0) }), { rev: 0, net: 0, pr: 0 });
  v.innerHTML = `<div class="page"><div class="ph"><div><h1>Sales</h1><p>Every sale with platform fees, shipping, profit and ROI worked out from the item's cost.</p></div><div class="acts">${csvBar('sales')}<button class="btn p" id="s-add">Log a sale</button></div></div>
    <div class="filters"><input class="inp" id="s-q" style="max-width:300px" placeholder="Search sale, item, buyer, platform…" value="${esc(istate.q)}"><span class="note">${rows.length} sale${rows.length === 1 ? '' : 's'} · revenue ${money(tot.rev)} · net ${money(tot.net)} · profit ${money(tot.pr)}</span></div><div id="s-bulk"></div>
    ${rows.length ? `<div class="tbl-wrap"><table class="t"><thead><tr><th style="width:34px"></th><th>Sale</th><th>Date</th><th>Item</th><th>Platform</th><th>Buyer</th><th>Qty</th><th>Price</th><th>Fees</th><th>Net</th><th>Profit</th><th>ROI</th></tr></thead><tbody>
      ${rows.map(x => `<tr data-id="${x.id}" class="${istate.selS.has(x.id) ? 'sel' : ''}"><td><input type="checkbox" class="ck" ${istate.selS.has(x.id) ? 'checked' : ''}></td><td class="mono">${x.sale_id}</td><td>${fdate(x.sale_date)}</td><td class="p"><b>${esc(x.item_name)}</b><div class="note mono">${esc(x.sku)}</div></td><td>${esc(x.platform) || '—'}</td><td>${esc(x.buyer) || '—'}${x.buyer_count > 1 ? `<span class="tag">repeat ×${x.buyer_count}</span>` : ''}</td><td>${x.qty}</td><td>${money(x.sale_price)}</td><td>${money(x.total_fees)}</td><td>${money(x.net)}</td><td class="${profCls(x.profit)}">${x.profit == null ? '—' : money(x.profit)}</td><td>${pct(x.roi)}</td></tr>`).join('')}</tbody></table></div>` : `<div class="empty"><b>No sales yet</b>Log one here, or use the Sell button on an item or the Scan station.</div>`}</div>`;
  csvHandlers(v, refreshPage);
  $('#s-q').oninput = e => { istate.q = e.target.value; refreshPage(); setTimeout(() => { const el = $('#s-q'); el.focus(); el.setSelectionRange(el.value.length, el.value.length); }, 0); };
  $('#s-add').onclick = () => saleModal({}, refreshPage);
  const byId = Object.fromEntries(d.sales.map(x => [x.id, x]));
  const bulk = () => { const n = istate.selS.size; $('#s-bulk').innerHTML = n ? `<div class="bulk"><b>${n} selected</b><button class="btn sm danger" id="sb-del">Delete</button><button class="btn sm ghost" id="sb-clr">Clear</button></div>` : '';
    if (n) { $('#sb-clr').onclick = () => { istate.selS.clear(); refreshPage(); }; $('#sb-del').onclick = async () => { if (await confirmBox(`Delete ${n} sale${n === 1 ? '' : 's'}?`, 'The items go back into stock.', 'Delete', true)) { await act(() => api('/api/inv/sales/delete', { ids: [...istate.selS] }), 'Deleted'); istate.selS.clear(); refreshPage(); } }; } };
  $$('tr[data-id]', v).forEach(tr => { const x = byId[tr.dataset.id];
    $('.ck', tr).onclick = e => { e.stopPropagation(); e.target.checked ? istate.selS.add(x.id) : istate.selS.delete(x.id); tr.classList.toggle('sel', e.target.checked); bulk(); };
    tr.onclick = () => saleModal(x, refreshPage, d); }); bulk();
  v._d = d;
};
async function saleModal(x, done, dd) {
  const d = dd || await api('/api/inv/sales'); const L = d.lists; const edit = x && x.id;
  const r = { sale_date: new Date().toISOString().slice(0, 10), qty: 1, ...x };
  modal(`<h2>${edit ? 'Edit ' + x.sale_id : 'Log a sale'}</h2>
    <div class="fld"><label class="f">Item (SKU)</label><select class="sel" id="sm-sku"><option value="">Choose…</option>${d.items.map(i => `<option value="${esc(i.sku)}" ${i.sku === r.sku ? 'selected' : ''}>${esc(i.sku)} — ${esc(i.name)} (${i.left} left)</option>`).join('')}</select></div>
    <div class="col3">${fi('sm-date', 'Sale date', r.sale_date, 'date')}${fi('sm-qty', 'Quantity', r.qty, 'number')}${sel2('sm-by', 'Sold by', L.team, r.sold_by, '—')}</div>
    <div class="col2">${sel2('sm-plat', 'Platform', L.platforms, r.platform, '—')}${fi('sm-buyer', 'Buyer (optional)', r.buyer)}</div>
    <div class="col3">${fi('sm-price', 'Sale price (total)', r.sale_price ?? '', 'number')}${fi('sm-shc', 'Shipping charged', r.ship_charged || '', 'number')}${fi('sm-shk', 'Shipping cost', r.ship_cost || '', 'number')}</div>
    ${fi('sm-oth', 'Other fees', r.other_fees || '', 'number')}<div class="card" style="padding:14px 18px;margin:0 0 14px" id="sm-prev"></div>
    <div class="fld"><label class="f">Notes</label><textarea class="ta" id="sm-notes" rows="2">${esc(r.notes)}</textarea></div>
    <div class="mfoot">${edit ? '<button class="btn danger" id="sm-del" style="margin-right:auto">Delete</button>' : ''}<button class="btn" data-close>Cancel</button><button class="btn p" id="sm-save">Save</button></div>`, {
    onMount: m => {
      const g = i => $('#' + i, m).value;
      const prev = () => { const it = d.items.find(i => i.sku === g('sm-sku')); const f = d.fees[g('sm-plat')]; const p = num(g('sm-price')), sc = num(g('sm-shc')), sk = num(g('sm-shk')), o = num(g('sm-oth')), q = Math.max(1, num(g('sm-qty')));
        const fee = (p + sc) * (f ? f.fee_pct : 0) + (f ? f.fixed : 0) + o, net = p + sc - fee - sk, basis = it && it.unit_cost ? it.unit_cost * q : null;
        $('#sm-prev', m).innerHTML = `<div class="mini"><span>Fees</span><b>${money(fee)}</b></div><div class="mini"><span>You keep</span><b>${money(net)}</b></div><div class="mini"><span>Profit${basis == null ? ' (no cost on this item)' : ''}</span><b class="${profCls(basis == null ? null : net - basis)}">${basis == null ? '—' : money(net - basis) + ' · ' + pct(basis ? (net - basis) / basis : null)}</b></div>`; };
      ['sm-sku', 'sm-plat', 'sm-price', 'sm-shc', 'sm-shk', 'sm-oth', 'sm-qty'].forEach(i => $('#' + i, m).oninput = prev);
      $('#sm-sku', m).onchange = () => { const it = d.items.find(i => i.sku === g('sm-sku')); if (it && !edit) { if (!g('sm-price') && it.listed) $('#sm-price', m).value = it.listed; if (!g('sm-plat') && it.platform) $('#sm-plat', m).value = it.platform; } prev(); };
      prev();
      $('#sm-save', m).onclick = async () => { const sale = { sku: g('sm-sku'), sale_date: g('sm-date'), qty: g('sm-qty'), sold_by: g('sm-by'), platform: g('sm-plat'), buyer: g('sm-buyer'), sale_price: g('sm-price'), ship_charged: g('sm-shc'), ship_cost: g('sm-shk'), other_fees: g('sm-oth'), notes: g('sm-notes') };
        const res = await act(() => api('/api/inv/sales/save', { id: edit ? x.id : undefined, sale }), 'Saved'); if (res) { closeModal(); if (res.alert) toast(res.alert); done(); } };
      if (edit) $('#sm-del', m).onclick = async () => { await act(() => api('/api/inv/sales/delete', { ids: [x.id] }), 'Deleted'); closeModal(); done(); };
    }
  });
}

/* ============================ RECEIPTS ============================ */
PAGES.inv_receipts = async function (v) {
  const T = S.tok; const d = await api('/api/inv/receipts'); if (T !== S.tok) return;
  istate.selR = new Set([...istate.selR].filter(i => d.receipts.some(x => x.id === i)));
  const q = istate.q.toLowerCase(); const rows = d.receipts.filter(x => !q || [x.vendor, x.category, x.description, x.sku, x.ref].join(' ').toLowerCase().includes(q));
  const total = rows.reduce((a, x) => a + x.amount, 0); const byId = Object.fromEntries(d.receipts.map(x => [x.id, x]));
  v.innerHTML = `<div class="page"><div class="ph"><div><h1>Receipts</h1><p>Business expenses — supplies, postage, fees, subscriptions. They come off your profit and feed the tax summary.</p></div><div class="acts">${csvBar('receipts')}<button class="btn p" id="r-add">Add receipt</button></div></div>
    <div class="filters"><input class="inp" id="r-q" style="max-width:300px" placeholder="Search vendor, category, notes…" value="${esc(istate.q)}"><span class="note">${rows.length} receipt${rows.length === 1 ? '' : 's'} · ${money(total)}</span></div><div id="r-bulk"></div>
    ${rows.length ? `<div class="tbl-wrap"><table class="t"><thead><tr><th style="width:34px"></th><th>Date</th><th>Vendor</th><th>Category</th><th>Description</th><th>SKU</th><th>Paid with</th><th style="text-align:right">Amount</th></tr></thead><tbody>${rows.map(x => `<tr data-id="${x.id}" class="${istate.selR.has(x.id) ? 'sel' : ''}"><td><input type="checkbox" class="ck" ${istate.selR.has(x.id) ? 'checked' : ''}></td><td>${fdate(x.date)}</td><td><b>${esc(x.vendor) || '—'}</b></td><td>${esc(x.category) || '—'}</td><td class="p">${esc(x.description)}</td><td class="mono">${esc(x.sku)}</td><td>${esc(x.method)}</td><td style="text-align:right">${money(x.amount)}</td></tr>`).join('')}</tbody></table></div>` : `<div class="empty"><b>No receipts yet</b>Add what you spend on the business so profit and tax numbers are honest.</div>`}</div>`;
  csvHandlers(v, refreshPage);
  $('#r-q').oninput = e => { istate.q = e.target.value; refreshPage(); setTimeout(() => { const el = $('#r-q'); el.focus(); el.setSelectionRange(el.value.length, el.value.length); }, 0); };
  $('#r-add').onclick = () => receiptModal(null, d.lists, refreshPage);
  const bulk = () => { const n = istate.selR.size; $('#r-bulk').innerHTML = n ? `<div class="bulk"><b>${n} selected</b><button class="btn sm danger" id="rb-del">Delete</button><button class="btn sm ghost" id="rb-clr">Clear</button></div>` : '';
    if (n) { $('#rb-clr').onclick = () => { istate.selR.clear(); refreshPage(); }; $('#rb-del').onclick = async () => { if (await confirmBox(`Delete ${n} receipt${n === 1 ? '' : 's'}?`, '', 'Delete', true)) { await act(() => api('/api/inv/receipts/delete', { ids: [...istate.selR] }), 'Deleted'); istate.selR.clear(); refreshPage(); } }; } };
  $$('tr[data-id]', v).forEach(tr => { const x = byId[tr.dataset.id];
    $('.ck', tr).onclick = e => { e.stopPropagation(); e.target.checked ? istate.selR.add(x.id) : istate.selR.delete(x.id); tr.classList.toggle('sel', e.target.checked); bulk(); };
    tr.onclick = () => receiptModal(x, d.lists, refreshPage); }); bulk();
};
function receiptModal(x, L, done) {
  const r = { date: new Date().toISOString().slice(0, 10), ...x };
  modal(`<h2>${x ? 'Edit receipt' : 'Add receipt'}</h2><div class="col2">${fi('rm-date', 'Date', r.date, 'date')}${fi('rm-amt', 'Amount ($)', r.amount ?? '', 'number')}</div>
    <div class="col2">${fi('rm-ven', 'Vendor', r.vendor)}${sel2('rm-cat', 'Category', L.receipt_categories, r.category, '—')}</div>${fi('rm-desc', 'Description', r.description)}
    <div class="col3">${sel2('rm-meth', 'Paid with', L.payment_methods, r.method, '—')}${fi('rm-ref', 'Reference / order #', r.ref)}${fi('rm-sku', 'For item SKU (optional)', r.sku)}</div>
    <div class="fld"><label class="f">Notes</label><textarea class="ta" id="rm-notes" rows="2">${esc(r.notes)}</textarea></div>
    <div class="mfoot">${x ? '<button class="btn danger" id="rm-del" style="margin-right:auto">Delete</button>' : ''}<button class="btn" data-close>Cancel</button><button class="btn p" id="rm-save">Save</button></div>`, {
    onMount: m => { const g = i => $('#' + i, m).value;
      $('#rm-save', m).onclick = async () => { const receipt = { date: g('rm-date'), amount: g('rm-amt'), vendor: g('rm-ven'), category: g('rm-cat'), description: g('rm-desc'), method: g('rm-meth'), ref: g('rm-ref'), sku: g('rm-sku'), notes: g('rm-notes') }; if (await act(() => api('/api/inv/receipts/save', { id: x ? x.id : undefined, receipt }), 'Saved')) { closeModal(); done(); } };
      if (x) $('#rm-del', m).onclick = async () => { await act(() => api('/api/inv/receipts/delete', { ids: [x.id] }), 'Deleted'); closeModal(); done(); }; }
  });
}

/* ============================ SCAN STATION ============================ */
PAGES.inv_scan = async function (v) {
  const T = S.tok; const d = await api('/api/inv/scans'); if (T !== S.tok) return;
  if (!istate.by || !d.team.includes(istate.by)) istate.by = d.team[0];
  v.innerHTML = `<div class="page" style="max-width:900px"><div class="ph"><div><h1>Scan station</h1><p>Scan a SKU label or a product's barcode with a USB or Bluetooth scanner (or type it and press Enter). Receive adds stock; Sell logs a sale at the listed price.</p></div></div>
    <div class="card"><div class="row wrap" style="margin-bottom:14px"><div class="seg" style="margin:0"><button data-m="receive" class="${istate.mode === 'receive' ? 'on' : ''}">Receive</button><button data-m="sell" class="${istate.mode === 'sell' ? 'on' : ''}">Sell</button></div>
     <div style="${istate.mode === 'sell' ? '' : 'display:none'}"><select class="sel" id="sc-by" style="width:auto">${d.team.map(t => `<option ${t === istate.by ? 'selected' : ''}>${esc(t)}</option>`).join('')}</select></div></div>
     <input class="inp scanbox" id="sc-in" placeholder="Scan or type a SKU / barcode…" autocomplete="off"><div id="sc-msg"></div></div>
    <div class="card"><div class="cardt"><span>Recent scans</span></div><div id="sc-log">${d.scans.length ? d.scans.map(s => `<div class="mini"><span>${fdt(s.ts)} · ${esc(s.action)} · <span class="mono">${esc(s.sku)}</span></span><b style="font-weight:500;${/^ERROR/.test(s.result) ? 'color:var(--red)' : ''}">${esc(s.result)}</b></div>`).join('') : '<div class="note">Nothing scanned yet.</div>'}</div></div></div>`;
  const inp = $('#sc-in'); inp.focus();
  $$('[data-m]', v).forEach(b => b.onclick = () => { istate.mode = b.dataset.m; refreshPage(); });
  $('#sc-by').onchange = e => istate.by = e.target.value;
  inp.onkeydown = async e => { if (e.key !== 'Enter') return; const code = inp.value.trim(); if (!code) return; inp.value = '';
    let r, err; try { r = await api('/api/inv/scan', { mode: istate.mode, code, sold_by: istate.by }); } catch (x) { err = x.message; }
    $('#sc-msg').innerHTML = `<div class="scanmsg ${err ? 'bad' : 'ok'}">${esc(err || r.message)}</div>`;
    const j = await api('/api/inv/scans'); $('#sc-log').innerHTML = j.scans.map(s => `<div class="mini"><span>${fdt(s.ts)} · ${esc(s.action)} · <span class="mono">${esc(s.sku)}</span></span><b style="font-weight:500;${/^ERROR/.test(s.result) ? 'color:var(--red)' : ''}">${esc(s.result)}</b></div>`).join(''); inp.focus(); };
};

/* ============================ TAX SUMMARY ============================ */
PAGES.inv_tax = async function (v) {
  const T = S.tok; const d = await api('/api/inv/tax' + (istate.year ? '?year=' + istate.year : '')); if (T !== S.tok) return;
  istate.year = d.year;
  const row = (k, val, neg) => `<div class="mini"><span>${k}</span><b class="${neg ? 'neg' : ''}">${neg ? '− ' : ''}${money(val)}</b></div>`;
  v.innerHTML = `<div class="page" style="max-width:900px"><div class="ph"><div><h1>Tax summary</h1><p>A year at a glance from your sales and receipts. It's a helper for your accountant, not tax advice.</p></div><div class="acts"><select class="sel" id="tx-y" style="width:auto">${d.years.map(y => `<option ${y === d.year ? 'selected' : ''}>${y}</option>`).join('')}</select></div></div>
    ${d.missing_basis ? `<div class="card" style="border-color:rgba(240,170,60,.45)"><b>${d.missing_basis} sale${d.missing_basis === 1 ? ' has' : 's have'} no cost on the item</b><div class="note" style="margin-top:6px">Add the cost each under Items, or cost of goods and net will be understated.</div></div>` : ''}
    <div class="card"><div class="cardt"><span>${d.year} · ${d.sales} sale${d.sales === 1 ? '' : 's'}</span></div>${row('Gross sales', d.gross)}${row('Cost of goods sold', d.cogs, true)}${row('Platform and other fees', d.fees, true)}${row('Shipping paid', d.shipping, true)}${row('Other expenses (receipts)', d.expenses, true)}
      <div class="mini" style="font-size:17px"><span style="color:var(--text)"><b>Net profit</b></span><b class="${profCls(d.net)}">${money(d.net)}</b></div></div>
    <div class="card"><div class="cardt"><span>Expenses by category</span></div>${Object.keys(d.expense_by_category).length ? Object.entries(d.expense_by_category).map(([k, a]) => `<div class="mini"><span>${esc(k)}</span><b>${money(a)}</b></div>`).join('') : '<div class="note">No receipts for this year.</div>'}</div></div>`;
  $('#tx-y').onchange = e => { istate.year = +e.target.value; refreshPage(); };
};

/* ============================ FEES & SETTINGS ============================ */
PAGES.inv_settings = async function (v) {
  const T = S.tok; const d = await api('/api/inv/settings'); if (T !== S.tok) return; const s = d.settings;
  v.innerHTML = `<div class="page" style="max-width:1100px"><div class="ph"><div><h1>Fees & settings</h1><p>Platform fees drive every profit number. Currencies convert costs bought abroad. Alerts and targets shape the dashboard.</p></div></div>
    <div class="card"><h3>Business</h3><div class="col3">${fi('st-p1', 'Your name', s.partner1)}${fi('st-p2', 'Partner (optional)', s.partner2)}${fi('st-ag', 'Flag stock older than (days)', s.aging_days, 'number')}</div>
      <div class="col3">${fi('st-dp', 'Suggested price drop (%)', Math.round(s.drop_pct * 100), 'number')}${fi('st-mt', 'Monthly profit target ($)', s.monthly_target || '', 'number')}${fi('st-bs', 'Alert on sales of ($) or more', s.big_sale || '', 'number')}</div>
      <label class="tog" style="margin:4px 0 14px"><span class="sw"><input type="checkbox" id="st-auto" ${s.auto_from_orders ? 'checked' : ''}><i></i></span>Add delivered orders from the tracker to Items automatically (weighted-average cost)</label><button class="btn p" id="st-save">Save</button></div>
    <div class="card"><div class="row" style="margin-bottom:12px"><h3 style="margin:0;flex:1">Platform fees</h3><button class="btn p sm" id="fe-add">Add platform</button></div><div class="note" style="margin-bottom:10px">Fee % is taken on the sale price plus shipping charged; the fixed amount is added per sale.</div>
      ${d.fees.map(f => `<div class="item"><div><div class="t">${esc(f.platform)}</div><div class="s">${(f.fee_pct * 100).toFixed(2)}% + ${money(f.fixed)}${f.notes ? ' · ' + esc(f.notes) : ''}</div></div><div class="r"><button class="btn sm" data-fe="${esc(f.platform)}">Edit</button><button class="btn sm ghost" data-fd="${esc(f.platform)}">Remove</button></div></div>`).join('')}</div>
    <div class="card"><div class="row" style="margin-bottom:12px"><h3 style="margin:0;flex:1">Currencies</h3><button class="btn p sm" id="cu-add">Add currency</button></div><div class="note" style="margin-bottom:10px">Rate = what 1 unit is worth in USD. Costs are converted when working out profit.</div>
      ${d.currencies.map(f => `<div class="item"><div><div class="t">${esc(f.code)} <span class="muted" style="font-weight:400">${esc(f.name)}</span></div><div class="s">1 ${esc(f.code)} = $${f.rate}</div></div><div class="r"><button class="btn sm" data-ce="${esc(f.code)}">Edit</button>${f.code === 'USD' ? '' : `<button class="btn sm ghost" data-cd="${esc(f.code)}">Remove</button>`}</div></div>`).join('')}</div>
    <div class="card"><h3>Data</h3><p>Export or import your items, sales and receipts as CSV. Imports use the same columns as the export; items with an existing SKU are updated.</p><div class="row wrap"><span class="muted" style="width:70px">Items</span>${csvBar('inventory')}</div><div class="row wrap" style="margin-top:10px"><span class="muted" style="width:70px">Sales</span>${csvBar('sales')}</div><div class="row wrap" style="margin-top:10px"><span class="muted" style="width:70px">Receipts</span>${csvBar('receipts')}</div></div>
    <div class="card"><h3>Reset inventory</h3><p>Removes every item, sale, receipt and scan. Fees, currencies and the order tracker are untouched.</p><button class="btn danger" id="inv-reset">Reset inventory…</button></div></div>`;
  csvHandlers(v, () => { });
  $('#st-save').onclick = () => act(() => api('/api/inv/settings/save', { settings: { partner1: $('#st-p1').value, partner2: $('#st-p2').value, aging_days: $('#st-ag').value, drop_pct: num($('#st-dp').value) / 100, monthly_target: $('#st-mt').value, big_sale: $('#st-bs').value, auto_from_orders: $('#st-auto').checked ? 1 : 0 } }), 'Saved');
  const feeModal = f => modal(`<h2>${f ? 'Edit ' + esc(f.platform) : 'Add platform'}</h2>${fi('fm-n', 'Platform', f ? f.platform : '')}<div class="col2">${fi('fm-p', 'Fee (% of sale + shipping)', f ? +(f.fee_pct * 100).toFixed(3) : '', 'number')}${fi('fm-f', 'Fixed fee per sale ($)', f ? f.fixed : '', 'number')}</div>${fi('fm-no', 'Notes', f ? f.notes : '')}<div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="fm-s">Save</button></div>`,
    { onMount: m => $('#fm-s', m).onclick = async () => { if (await act(() => api('/api/inv/fee/save', { old: f ? f.platform : '', fee: { platform: $('#fm-n', m).value, fee_pct: $('#fm-p', m).value, fixed: $('#fm-f', m).value, notes: $('#fm-no', m).value, processing: f ? f.processing : '' } }), 'Saved')) { closeModal(); refreshPage(); } } });
  $('#fe-add').onclick = () => feeModal(null);
  $$('[data-fe]', v).forEach(b => b.onclick = () => feeModal(d.fees.find(f => f.platform === b.dataset.fe)));
  $$('[data-fd]', v).forEach(b => b.onclick = async () => { if (await confirmBox('Remove ' + b.dataset.fd + '?', 'Past sales on it will show no fees.', 'Remove', true)) { await act(() => api('/api/inv/fee/delete', { platform: b.dataset.fd })); refreshPage(); } });
  const curModal = f => modal(`<h2>${f ? 'Edit ' + esc(f.code) : 'Add currency'}</h2><div class="col3">${f ? `<div class="fld"><label class="f">Code</label><input class="inp" id="cm-c" value="${esc(f.code)}" disabled></div>` : fi('cm-c', 'Code (3 letters)', '')}${fi('cm-n', 'Name', f ? f.name : '')}${fi('cm-r', 'Value in USD', f ? f.rate : '', 'number')}</div><div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="cm-s">Save</button></div>`,
    { onMount: m => $('#cm-s', m).onclick = async () => { if (await act(() => api('/api/inv/currency/save', { currency: { code: $('#cm-c', m).value, name: $('#cm-n', m).value, rate: $('#cm-r', m).value } }), 'Saved')) { closeModal(); refreshPage(); } } });
  $('#cu-add').onclick = () => curModal(null);
  $$('[data-ce]', v).forEach(b => b.onclick = () => curModal(d.currencies.find(f => f.code === b.dataset.ce)));
  $$('[data-cd]', v).forEach(b => b.onclick = async () => { if (await act(() => api('/api/inv/currency/delete', { code: b.dataset.cd }))) refreshPage(); });
  $('#inv-reset').onclick = () => modal(`<h2>Reset inventory?</h2><p>This deletes every item, sale, receipt and scan. Type <b>reset</b> to confirm.</p>${fi('rs-w', '', '')}<div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn danger" id="rs-go">Reset</button></div>`,
    { onMount: m => $('#rs-go', m).onclick = async () => { const r = await act(() => api('/api/inv/reset', { confirm: $('#rs-w', m).value })); if (r) { closeModal(); toast(`Removed ${r.removed} rows`); } } });
};
