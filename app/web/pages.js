/* Order Tracker pages: Tracking, Needs attention, Email accounts, Discord webhooks */
const STATUS_ORDER = ['placed', 'shipped', 'out_for_delivery', 'delivered', 'cancelled', 'partially_cancelled', 'refunded'];
const pill = (st, label) => `<span class="pill ${st}"><i></i>${esc(label)}</span>`;
const pbadge = (o) => o.image ? `<div class="pb"><img src="${esc(o.image)}"></div>` : `<div class="pb" style="background:${o.color || '#8a8a99'}">${esc((o.retailer || '?')[0])}</div>`;

/* ================================================================ Tracking */
const COLS = [['product', 'Product', 1], ['order', 'Order #', 1], ['price', 'Price', 1], ['account', 'Account', 1], ['retailer', 'Retailer', 1], ['status', 'Status', 1], ['date', 'Date', 0], ['tracking', 'Tracking', 0], ['qty', 'Qty', 0]];
const TR = { q: '', retailer: '', range: 'all', status: 'all', sort: store.get('tr.sort', { col: 'date', dir: -1 }), sel: new Set(), cols: store.get('tr.cols', Object.fromEntries(COLS.map(c => [c[0], !!c[2]]))), data: null };

PAGES.tracking = async function (v) {
  const T = S.tok;
  TR.data = await api('/api/tracking');
  if (T !== S.tok) return;
  const d = TR.data, ov = d.overview;
  const max = Math.max(1, ...ov.days.map(x => x.spent));
  const sr = ov.stick_rate == null ? null : Math.round(ov.stick_rate * 100);
  v.innerHTML = `<div class="page">
   <div class="ph"><div><h1>Tracking</h1><p>Every order your inboxes have confirmed, shipped or delivered.</p></div></div>
   <div class="stats">
     <div class="stat"><div class="k"><span class="dot"></span>Orders</div><div class="v">${ov.total}</div><div class="d">${ov.last ? `Last: ${esc(ov.last.retailer)} · ${fdate(ov.last.date)}` : 'Nothing yet'}</div></div>
     <div class="stat"><div class="k"><span class="dot b"></span>Placed</div><div class="v">${ov.placed}</div><div class="d">Waiting to ship</div></div>
     <div class="stat"><div class="k"><span class="dot a"></span>In transit</div><div class="v">${ov.in_transit}</div><div class="d">Shipped or out for delivery</div></div>
     <div class="stat"><div class="k"><span class="dot g"></span>Delivered</div><div class="v">${ov.delivered}</div><div class="d">${sr == null ? 'No orders yet' : sr + '% stick rate'}</div></div>
     <div class="stat"><div class="k"><span class="dot r"></span>Cancelled</div><div class="v ${ov.cancelled ? 'red' : ''}">${ov.cancelled}</div><div class="d">${ov.cancelled ? 'Cancelled or refunded' : 'None'}</div></div>
   </div>
   <div class="two">
     <div class="card" style="margin:0"><div class="cardt"><span>14-day activity</span><span style="letter-spacing:0;font-weight:500;text-transform:none">${money(ov.spent_14d)} spent</span></div>
       <div class="bars">${ov.days.map(x => `<div class="b ${x.spent ? '' : 'z'}" style="${x.spent ? `height:${Math.max(6, x.spent / max * 100)}%` : ''}" data-tip="${fdate(x.day)} · ${x.count} order${x.count === 1 ? '' : 's'} · ${money(x.spent)}"></div>`).join('')}</div>
       <div class="axis"><span>${fdate(ov.days[0].day)}</span><span>${fdate(ov.days[7].day)}</span><span>Today</span></div></div>
     <div class="card" style="margin:0"><div class="cardt"><span>By retailer</span><span style="letter-spacing:0;font-weight:500;text-transform:none">${ov.total} total</span></div>
       ${ov.retailers.length ? ov.retailers.map(r => `<div class="rl"><span class="sq" style="background:${r.color}"></span>${esc(r.retailer)}<span class="n">${Math.round(r.ok / r.total * 100)}% · ${r.total}</span></div>`).join('') : '<div class="note">No orders yet.</div>'}</div>
   </div>
   <div class="filters" style="margin-top:20px">
     <input class="inp" id="tq" placeholder="Search order #, tracking, product, email…" style="max-width:370px" value="${esc(TR.q)}">
     <select class="sel" id="tret" style="width:190px"><option value="">All retailers</option>${d.retailers.map(r => `<option ${TR.retailer === r ? 'selected' : ''}>${esc(r)}</option>`).join('')}</select>
     <div class="chips" id="trange">${[['all', 'All'], ['7', '7 days'], ['30', '30 days'], ['90', '90 days']].map(([k, l]) => `<button data-r="${k}" class="${TR.range === k ? 'on' : ''}">${l}</button>`).join('')}</div>
   </div>
   <div class="chips" id="tstat" style="margin-bottom:18px">${[['all', 'All'], ['placed', 'Placed'], ['shipped', 'Shipped'], ['out_for_delivery', 'Out for delivery'], ['delivered', 'Delivered'], ['cancelled', 'Cancelled'], ['partially_cancelled', 'Partially cancelled'], ['refunded', 'Refunded']].map(([k, l]) => `<button data-s="${k}" class="${TR.status === k ? 'on' : ''}">${l}</button>`).join('')}</div>
   <div class="card"><div class="hd"><h3>Recent orders</h3><div class="r"><button class="btn sm" id="tcols">Columns</button><button class="btn sm" id="tadd">Add order</button></div></div>
     <div id="tbulk"></div><div class="tbl-wrap" id="ttable"></div></div></div>`;
  $('#tq').oninput = e => { TR.q = e.target.value; drawOrders(); };
  $('#tret').onchange = e => { TR.retailer = e.target.value; drawOrders(); };
  $('#trange').onclick = e => { const b = e.target.closest('[data-r]'); if (!b) return; TR.range = b.dataset.r; $$('#trange button').forEach(x => x.classList.toggle('on', x === b)); drawOrders(); };
  $('#tstat').onclick = e => { const b = e.target.closest('[data-s]'); if (!b) return; TR.status = b.dataset.s; $$('#tstat button').forEach(x => x.classList.toggle('on', x === b)); drawOrders(); };
  $('#tadd').onclick = () => orderForm();
  $('#tcols').onclick = e => menu(e, COLS.map(c => ({ label: (TR.cols[c[0]] ? '✓  ' : '      ') + c[1], fn: () => { TR.cols[c[0]] = !TR.cols[c[0]]; if (!Object.values(TR.cols).some(Boolean)) TR.cols.product = true; store.set('tr.cols', TR.cols); drawOrders(); setTimeout(() => $('#tcols') && $('#tcols').click(), 0); } })));
  drawOrders();
};

function filteredOrders() {
  let o = TR.data.orders; const q = TR.q.toLowerCase();
  if (q) o = o.filter(x => [x.order_number, x.tracking, x.product, x.account, x.retailer].join(' ').toLowerCase().includes(q) || x.items.some(i => i.name.toLowerCase().includes(q)));
  if (TR.retailer) o = o.filter(x => x.retailer === TR.retailer);
  if (TR.status !== 'all') o = o.filter(x => x.status === TR.status);
  if (TR.range !== 'all') { const cut = new Date(Date.now() - TR.range * 864e5).toISOString().slice(0, 10); o = o.filter(x => (x.order_date || '') >= cut); }
  const k = { product: x => x.product || '', order: x => x.order_number, price: x => x.total ?? -1, account: x => x.account || '', retailer: x => x.retailer, status: x => STATUS_ORDER.indexOf(x.status), date: x => x.order_date || '', tracking: x => x.tracking || '', qty: x => x.qty }[TR.sort.col];
  return [...o].sort((a, b) => (k(a) > k(b) ? 1 : k(a) < k(b) ? -1 : 0) * TR.sort.dir);
}

function drawOrders() {
  const rows = filteredOrders(); const cols = COLS.filter(c => TR.cols[c[0]]);
  const sel = TR.sel; for (const id of [...sel]) if (!TR.data.orders.some(o => o.id === id)) sel.delete(id);
  const cell = (c, o) => ({
    product: `<td class="p"><div class="pcell">${pbadge(o)}<span>${esc(o.product || '(no product)')}</span></div></td>`, order: `<td class="mono">${esc(o.order_number)}</td>`,
    price: `<td style="font-weight:600">${money(o.total)}</td>`, account: `<td class="mono">${esc(o.account || '—')}</td>`, retailer: `<td>${esc(o.retailer)}</td>`,
    status: `<td>${pill(o.status, o.status_label)}</td>`, date: `<td>${fdate(o.order_date)}</td>`, tracking: `<td class="mono">${esc(o.tracking || '—')}</td>`, qty: `<td>${o.qty}</td>`
  }[c[0]]);
  $('#ttable').innerHTML = rows.length ? `<table class="t"><thead><tr><th style="width:34px"><input type="checkbox" class="ck" id="tall" ${rows.length && rows.every(o => sel.has(o.id)) ? 'checked' : ''}></th>${cols.map(c => `<th data-c="${c[0]}">${c[1]}<span class="ar">${TR.sort.col === c[0] ? (TR.sort.dir > 0 ? '▲' : '▼') : '⇅'}</span></th>`).join('')}</tr></thead>
    <tbody>${rows.map(o => `<tr data-id="${o.id}" class="${sel.has(o.id) ? 'sel' : ''}"><td><input type="checkbox" class="ck" ${sel.has(o.id) ? 'checked' : ''}></td>${cols.map(c => cell(c, o)).join('')}</tr>`).join('')}</tbody></table>`
    : `<div class="empty" style="margin:8px 0"><b>${TR.data.orders.length ? 'No orders match these filters' : 'No orders yet'}</b>${TR.data.orders.length ? 'Try a different search or filter.' : 'Connect an email account and orders appear here on their own — or add one by hand.'}
      ${TR.data.orders.length ? '' : '<br><button class="btn p" id="egoto">Connect email</button>'}</div>`;
  const g = $('#egoto'); if (g) g.onclick = () => go('email');
  $('#tbulk').innerHTML = sel.size ? `<div class="bulk"><b>${sel.size} selected</b><button class="btn sm" id="bst">Set status…</button><button class="btn sm danger" id="bdel">Delete</button><button class="btn sm ghost" id="bclr">Clear</button></div>` : '';
  if (sel.size) {
    $('#bclr').onclick = () => { sel.clear(); drawOrders(); };
    $('#bst').onclick = e => menu(e, STATUS_ORDER.map(s => ({ label: TR.data.statuses[s], fn: async () => { await act(() => api('/api/orders/status', { ids: [...sel], status: s }), 'Updated'); sel.clear(); refreshPage(); } })));
    $('#bdel').onclick = async () => { if (await confirmBox(`Delete ${sel.size} order${sel.size > 1 ? 's' : ''}?`, 'They stay hidden even if their emails are scanned again. You can restore them in Settings → Deleted orders.', 'Delete', true)) { await act(() => api('/api/orders/delete', { ids: [...sel] })); sel.clear(); refreshPage(); } };
  }
  const t = $('#ttable'); if (!rows.length) return;
  $('#tall').onclick = e => { rows.forEach(o => e.target.checked ? sel.add(o.id) : sel.delete(o.id)); drawOrders(); };
  $$('th[data-c]', t).forEach(th => th.onclick = () => { const c = th.dataset.c; TR.sort = { col: c, dir: TR.sort.col === c ? -TR.sort.dir : 1 }; store.set('tr.sort', TR.sort); drawOrders(); });
  $$('tbody tr', t).forEach(tr => tr.onclick = e => {
    const id = +tr.dataset.id;
    if (e.target.classList.contains('ck')) { e.target.checked ? sel.add(id) : sel.delete(id); drawOrders(); return; }
    orderDrawer(id);
  });
}

function orderForm(o) {
  const d = TR.data, e = o || { retailer: '', order_number: '', status: 'placed', order_date: new Date().toISOString().slice(0, 10), qty: 1 };
  modal(`<h2>${o ? 'Edit order' : 'Add order'}</h2><p>${o ? 'Changes here are saved as made by hand.' : 'For an order that never arrived by email.'}</p>
   <div class="col2"><div class="fld"><label class="f">Retailer</label><input class="inp" id="fr" list="rl" value="${esc(e.retailer)}"><datalist id="rl">${d.retailers.map(r => `<option>${esc(r)}`).join('')}</datalist></div>
   <div class="fld"><label class="f">Order number</label><input class="inp" id="fn" value="${esc(e.order_number)}"></div></div>
   <div class="fld"><label class="f">Product</label><input class="inp" id="fp" value="${esc(e.product || '')}"></div>
   <div class="col2"><div class="fld"><label class="f">Total ($)</label><input class="inp" id="ft" value="${e.total ?? ''}"></div><div class="fld"><label class="f">Quantity</label><input class="inp" id="fq" type="number" min="1" value="${e.qty || 1}"></div></div>
   <div class="col2"><div class="fld"><label class="f">Status</label><select class="sel" id="fs">${STATUS_ORDER.map(s => `<option value="${s}" ${e.status === s ? 'selected' : ''}>${d.statuses[s]}</option>`).join('')}</select></div>
   <div class="fld"><label class="f">Order date</label><input class="inp" id="fd" type="date" value="${esc((e.order_date || '').slice(0, 10))}"></div></div>
   <div class="col2"><div class="fld"><label class="f">Account (email)</label><input class="inp" id="fa" value="${esc(e.account || '')}"></div><div class="fld"><label class="f">Tracking number</label><input class="inp" id="fk" value="${esc(e.tracking || '')}"></div></div>
   <div class="err hidden" id="ferr"></div><div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="fsave">Save</button></div>`, {
    onMount: m => $('#fsave', m).onclick = async () => {
      try { await api('/api/orders/save', { id: o && o.id, retailer: $('#fr', m).value, order_number: $('#fn', m).value, product: $('#fp', m).value, total: $('#ft', m).value, qty: $('#fq', m).value, status: $('#fs', m).value, order_date: $('#fd', m).value, account: $('#fa', m).value, tracking: $('#fk', m).value }); closeModal(); closeDrawer(); toast('Saved'); refreshPage(); }
      catch (x) { $('#ferr', m).textContent = x.message; $('#ferr', m).classList.remove('hidden'); }
    }
  });
}

async function orderDrawer(id) {
  const o = await act(() => api('/api/orders/detail?id=' + id)); if (!o) return;
  const full = TR.data.orders.find(x => x.id === id) || o;
  openDrawer(`<div class="row"><h2 style="margin:0;flex:1">Order ${esc(o.order_number)}</h2><button class="iconbtn" data-dclose>${icon('x', 18)}</button></div>
    <div class="row" style="margin:14px 0">${pbadge(full)}<div><b>${esc(o.retailer)}</b><div class="muted small">${esc(o.product || 'No product read')}</div></div><span style="margin-left:auto">${pill(o.status, TR.data.statuses[o.status])}</span></div>
    <div class="kv"><span>Total</span><span>${money(o.total)}</span><span>Ordered</span><span>${fdate(o.order_date)}</span><span>Account</span><span class="mono">${esc(o.account || '—')}</span>
      <span>Tracking</span><span class="mono">${esc(o.tracking || '—')} ${o.carrier ? `<span class="muted">· ${esc(o.carrier)}</span>` : ''}</span>${o.delivery_detail ? `<span>Carrier says</span><span>${esc(o.delivery_detail)}</span>` : ''}${o.eta ? `<span>Expected</span><span>${esc(o.eta)}</span>` : ''}
      <span>Source</span><span>${o.source === 'manual' ? 'Added by hand' : 'Email'}</span></div>
    ${o.items.length ? `<div class="cardt" style="margin-top:20px">Items</div>${o.items.map(i => `<div class="row" style="padding:7px 0;border-bottom:1px solid var(--line)"><span style="flex:1">${esc(i.name)}</span><span class="muted">×${i.qty}</span><span>${money(i.unit_price)}</span></div>`).join('')}` : ''}
    ${o.checkouts.length ? `<div class="cardt" style="margin-top:20px">Linked checkouts</div>${o.checkouts.map(c => `<div class="row small" style="padding:5px 0"><span style="flex:1">${esc(c.product)}</span><span class="muted">${esc(c.bot || c.store)}</span></div>`).join('')}` : ''}
    <div class="cardt" style="margin-top:22px">History</div><div class="tl">${o.events.map(e => `<div><b>${esc(TR.data.statuses[e.status] || e.status)}</b> <span class="muted small">${fdt(e.ts)} · ${esc(e.note)}</span></div>`).join('')}</div>
    <div class="divider"></div><div class="row wrap"><button class="btn" id="d-edit">Edit</button><button class="btn" id="d-move">Move retailer</button><button class="btn" id="d-merge">Merge into…</button><button class="btn danger" id="d-del">Delete</button></div>`, d => {
    $('#d-edit', d).onclick = () => orderForm(o);
    $('#d-del', d).onclick = async () => { if (await confirmBox('Delete this order?', 'It stays hidden even if its emails are scanned again. Restore it any time in Settings → Deleted orders.', 'Delete', true)) { await act(() => api('/api/orders/delete', { ids: [o.id] })); closeDrawer(); refreshPage(); } };
    $('#d-move', d).onclick = () => modal(`<h2>Move to another retailer</h2><p>Use this when an order was filed under the wrong store.</p><div class="fld"><input class="inp" id="mr" list="rl2" value="${esc(o.retailer)}"><datalist id="rl2">${TR.data.retailers.map(r => `<option>${esc(r)}`).join('')}</datalist></div><div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="mgo">Move</button></div>`,
      { onMount: m => $('#mgo', m).onclick = async () => { if (await act(() => api('/api/orders/move', { id: o.id, retailer: $('#mr', m).value }), 'Moved')) { closeModal(); closeDrawer(); refreshPage(); } } });
    $('#d-merge', d).onclick = () => modal(`<h2>Merge into another order</h2><p>Combines this order's items and history into the one you pick, then removes this one.</p><div class="fld"><select class="sel" id="mm">${TR.data.orders.filter(x => x.id !== o.id).map(x => `<option value="${x.id}">${esc(x.retailer)} · ${esc(x.order_number)}</option>`).join('')}</select></div><div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="mgo">Merge</button></div>`,
      { onMount: m => $('#mgo', m).onclick = async () => { if (await act(() => api('/api/orders/merge', { from_id: o.id, into_id: +$('#mm', m).value }), 'Merged')) { closeModal(); closeDrawer(); refreshPage(); } } });
  });
}

/* ================================================================ Needs attention */
PAGES.attention = async function (v) {
  const T = S.tok;
  const items = await api('/api/attention');
  if (T !== S.tok) return;
  v.innerHTML = `<div class="page"><div class="ph"><div><h1>Needs attention</h1><p>Emails that look like orders but need a quick decision before they are added.</p></div></div>
   ${items.length ? items.map(a => `<div class="card" data-id="${a.id}"><div class="row"><div style="flex:1;min-width:0"><div class="t" style="font-weight:600;font-size:16px">${esc(a.subject || '(no subject)')}</div>
     <div class="muted small" style="margin-top:3px">${esc(a.sender)} · ${fdt(a.created_at)}${a.guess ? ` · looks like ${esc(a.guess)}` : ''}</div></div><span class="pill"><i style="background:var(--amber)"></i>${esc(a.reason)}</span></div>
     <p class="small muted" style="margin:12px 0;white-space:pre-wrap;line-height:1.5">${esc((a.snippet || '').slice(0, 300))}</p>
     <div class="row wrap"><button class="btn p sm" data-add>Add as order</button><button class="btn sm" data-ign="sender">Ignore this sender</button><button class="btn sm" data-ign="domain">Ignore this website</button><button class="btn sm ghost" data-dis>Dismiss</button></div></div>`).join('')
     : '<div class="empty plain">Nothing needs your attention.</div>'}</div>`;
  $$('[data-id]', v).forEach(card => {
    const a = items.find(x => x.id == card.dataset.id), done = async (fn, m) => { if (await act(fn, m)) { pollShell(); refreshPage(); } };
    $('[data-dis]', card).onclick = () => done(() => api('/api/attention/resolve', { id: a.id }));
    $$('[data-ign]', card).forEach(b => b.onclick = () => done(() => api('/api/attention/resolve', { id: a.id, ignore: b.dataset.ign }), 'Ignored from now on'));
    $('[data-add]', card).onclick = async () => {
      TR.data = TR.data || await api('/api/tracking');
      const m = (a.snippet + ' ' + a.subject).match(/(?:order|#)\s*#?\s*([A-Z0-9][A-Z0-9-]{5,24})/i);
      orderForm({ retailer: a.guess, order_number: m ? m[1].toUpperCase() : '', status: 'placed', order_date: new Date().toISOString().slice(0, 10), qty: 1 });
      const sv = $('#fsave'); const orig = sv.onclick;
      sv.onclick = async () => { try { await api('/api/attention/add', { attention_id: a.id, retailer: $('#fr').value, order_number: $('#fn').value, product: $('#fp').value, total: $('#ft').value, qty: $('#fq').value, status: $('#fs').value, order_date: $('#fd').value, account: $('#fa').value, tracking: $('#fk').value }); closeModal(); toast('Order added'); pollShell(); refreshPage(); } catch (x) { $('#ferr').textContent = x.message; $('#ferr').classList.remove('hidden'); } };
    };
  });
};

/* ================================================================ Email accounts */
PAGES.email = async function (v) {
  const T = S.tok;
  const d = await api('/api/mail/accounts'); S.mail = d;
  if (T !== S.tok) return;
  v.innerHTML = `<div class="page"><div class="ph"><div><h1>Email accounts</h1><p>Every connected inbox is watched live. Orders are matched across inboxes, so forwarded copies don't double up.</p></div>
    <div class="acts"><button class="btn" id="m-eml">Import .eml files</button><button class="btn" id="m-sync">Sync now</button><button class="btn" id="m-back">Backfill all</button><button class="btn" id="m-out">Add Outlook</button><button class="btn p" id="m-add">Add accounts</button></div></div>
    ${d.sync.running ? `<div class="card" style="padding:14px 20px"><div class="row"><span class="spin"></span><span>Syncing… <span class="muted small">${esc(d.sync.log.slice(-1)[0] || '')}</span></span></div></div>` : ''}
    ${d.accounts.length ? d.accounts.map(a => `<div class="item big" data-id="${a.id}"><span class="dot ${!a.enabled ? '' : a.last_error ? 'r' : a.live ? 'g' : 'a'}"></span>
      <div><div class="t" style="font-size:17px">${esc(a.email)}</div><div class="s">${esc(a.description)}</div></div>
      <div class="r"><button class="btn sm" data-a="sync">Sync now</button><button class="btn sm" data-a="edit">Edit</button><button class="btn sm" data-a="back">Backfill</button>
      <label class="sw" style="margin:0 10px"><input type="checkbox" data-a="en" ${a.enabled ? 'checked' : ''}><i></i></label><button class="btn sm ghost" data-a="rm">Remove</button></div></div>`).join('') : '<div class="empty"><b>No email accounts yet</b>Add the inbox your orders arrive in. Passwords stay on this computer.<br><button class="btn p" id="m-add2">Add accounts</button></div>'}
    <div class="card" style="margin-top:6px"><h3>Your other addresses</h3><p>The addresses you send or forward store emails from. A forward from one of these is read as the original store's email. Your connected mailboxes are always included. Adding an address doesn't add an order or read any mail by itself; run Backfill afterwards to read older forwards.</p>
      ${d.connected.map(e => `<div class="item" style="padding:12px 16px"><span class="mono" style="font-size:14px">${esc(e)}</span><span class="muted small">· connected mailbox (remove the account above to stop using it)</span></div>`).join('')}
      ${d.own.map(e => `<div class="item" style="padding:12px 16px"><span class="mono" style="font-size:14px">${esc(e)}</span><div class="r"><button class="btn sm ghost" data-own="${esc(e)}">Remove</button></div></div>`).join('')}
      <label class="f" style="margin-top:14px">Add an address</label><div class="row"><input class="inp" id="own-i" placeholder="you@example.com"><button class="btn" id="own-b" style="padding:10px 22px">Add</button></div></div></div>`;
  const sync = async (full, id) => { if (await act(() => api('/api/mail/sync', { full, id }), full ? 'Backfill started' : 'Checking mail…')) { setTimeout(refreshPage, 600); const t = setInterval(async () => { const s = await api('/api/mail/sync'); if (!s.running) { clearInterval(t); pollShell(); if (S.route === 'email') refreshPage(); if (s.stats) toast(`Done — ${s.stats.orders} order email${s.stats.orders === 1 ? '' : 's'}, ${s.stats.attention} needing attention${s.stats.errors ? `, ${s.stats.errors} problem(s)` : ''}`); } }, 1200); } };
  $('#m-sync').onclick = () => sync(false);
  $('#m-back').onclick = async () => { if (await confirmBox('Backfill all inboxes?', 'Re-reads every email in every connected inbox from the beginning. Safe to repeat — nothing is duplicated and deleted orders stay hidden. It can take a while on a big mailbox.', 'Backfill')) sync(true); };
  $('#m-add').onclick = () => accountModal(); const a2 = $('#m-add2'); if (a2) a2.onclick = () => accountModal();
  $('#m-out').onclick = () => accountModal(null, 'outlook');
  $('#m-eml').onclick = async () => { const fs = await pickFiles('.eml'); if (!fs.length) return; const files = await Promise.all(fs.map(async f => ({ name: f.name, text: await readText(f) }))); const r = await act(() => api('/api/mail/import_eml', { files })); if (r) { toast(`Read ${r.files} email${r.files === 1 ? '' : 's'}: ${r.orders} order${r.orders === 1 ? '' : 's'}, ${r.attention} need attention, ${r.skipped} skipped`); pollShell(); refreshPage(); } };
  $('#own-b').onclick = async () => { if (await act(() => api('/api/mail/own/add', { address: $('#own-i').value }), 'Added')) refreshPage(); };
  $$('[data-own]', v).forEach(b => b.onclick = async () => { await act(() => api('/api/mail/own/remove', { address: b.dataset.own })); refreshPage(); });
  $$('.item[data-id]', v).forEach(row => {
    const id = +row.dataset.id, a = d.accounts.find(x => x.id === id);
    row.onclick = async e => {
      const k = e.target.closest('[data-a]'); if (!k) return; const t = k.dataset.a;
      if (t === 'sync') sync(false, id); if (t === 'back') sync(true, id); if (t === 'edit') accountModal(a);
      if (t === 'en') { await act(() => api('/api/mail/accounts/enable', { id, enabled: k.checked })); setTimeout(() => { pollShell(); refreshPage(); }, 300); }
      if (t === 'rm' && await confirmBox('Remove ' + a.email + '?', 'Orders already read from it stay. It stops being watched and its saved password is deleted.', 'Remove', true)) { await act(() => api('/api/mail/accounts/delete', { id })); pollShell(); refreshPage(); }
    };
  });
};

function accountModal(a, preset) {
  const P = S.mail.providers; let mode = 'single';
  const draw = (m) => {
    const prov = (a && a.provider) || preset || 'gmail';
    m.innerHTML = `${a ? '' : `<div class="seg"><button data-m="single" class="${mode === 'single' ? 'on' : ''}">Single account</button><button data-m="bulk" class="${mode === 'bulk' ? 'on' : ''}">Bulk add</button></div>`}
    ${mode === 'single' ? `<h2>${a ? 'Edit email account' : 'Add an email account'}</h2><p>Connects over IMAP. Nothing leaves this computer except the connection to your mail provider.</p>
      <div class="fld"><label class="f">Email address</label><input class="inp" id="ae" placeholder="you@gmail.com" value="${esc(a ? a.email : '')}"></div>
      <div class="fld"><label class="f">Mail provider</label><select class="sel" id="ap">${Object.entries(P).map(([k, p]) => `<option value="${k}" ${prov === k ? 'selected' : ''}>${esc(p.label)}</option>`).join('')}</select><div class="hint" id="aph"></div></div>
      <div class="fld hidden" id="ahw"><label class="f">IMAP server</label><div class="row"><input class="inp" id="ah" placeholder="imap.mydomain.com" value="${esc(a ? a.host : '')}"><input class="inp" id="aport" style="width:110px" value="${a ? a.port : 993}"></div></div>
      <div class="fld"><label class="f">App password</label><input class="inp" id="apw" type="password" placeholder="${a && a.has_password ? 'Saved — leave blank to keep' : ''}" autocomplete="off"><div class="hint" id="ahint"></div></div>
      <div class="fld"><label class="f">Username (if different from email)</label><input class="inp" id="au" value="${esc(a ? a.username : '')}"></div>`
      : `<h2>Bulk add accounts</h2><p>One per line as <code>email:apppassword</code>. Gmail, iCloud, Yahoo, AOL and Fastmail are recognised automatically; for anything else add the server: <code>email:apppassword:imap.host.com:993</code>.</p>
      <textarea class="ta" id="abulk" placeholder="first@gmail.com:abcd efgh ijkl mnop&#10;second@icloud.com:xxxx-xxxx-xxxx-xxxx&#10;third@mydomain.com:password:imap.mydomain.com:993"></textarea>
      <div class="hint">Each account is tested before it's added — this takes a few seconds per account.</div><div id="bres"></div>`}
    <div class="err hidden" id="aerr"></div>
    <div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="ago">${mode === 'single' ? (a ? 'Save' : 'Connect') : 'Connect 0 accounts'}</button></div>`;
    $$('[data-close]', m).forEach(b => b.onclick = closeModal);
    $$('[data-m]', m).forEach(b => b.onclick = () => { mode = b.dataset.m; draw(m); });
    if (mode === 'single') {
      const sync = () => { const k = $('#ap', m).value; $('#aph', m).textContent = P[k].host ? `${P[k].host} · port 993` : ''; $('#ahint', m).textContent = P[k].hint; $('#ahw', m).classList.toggle('hidden', k !== 'custom'); };
      $('#ap', m).onchange = sync; $('#ae', m).oninput = e => { const dom = e.target.value.split('@')[1] || ''; const map = { 'icloud.com': 'icloud', 'me.com': 'icloud', 'gmail.com': 'gmail', 'outlook.com': 'outlook', 'hotmail.com': 'outlook', 'yahoo.com': 'yahoo', 'aol.com': 'aol', 'fastmail.com': 'fastmail' }; if (map[dom] && !a) { $('#ap', m).value = map[dom]; sync(); } };
      sync();
      $('#ago', m).onclick = async e => {
        const err = $('#aerr', m); err.classList.add('hidden');
        const body = { id: a && a.id, email: $('#ae', m).value, provider: $('#ap', m).value, host: $('#ah', m).value, port: $('#aport', m).value, password: $('#apw', m).value, username: $('#au', m).value };
        try {
          await busy(e.currentTarget, async () => {
            const t = await api('/api/mail/accounts/test', body); if (!t.ok) throw new Error(t.error);
            await api('/api/mail/accounts/save', body);
          });
          closeModal(); toast('Connected'); api('/api/mail/sync', { id: null }).catch(() => { }); pollShell(); refreshPage();
        } catch (x) { err.textContent = x.message; err.classList.remove('hidden'); }
      };
    } else {
      const ta = $('#abulk', m), btn = $('#ago', m), cnt = () => ta.value.split('\n').filter(l => l.trim() && !l.trim().startsWith('#')).length;
      ta.oninput = () => { btn.textContent = `Connect ${cnt()} account${cnt() === 1 ? '' : 's'}`; btn.disabled = !cnt(); }; btn.disabled = true;
      btn.onclick = async () => {
        btn.disabled = true; btn.innerHTML = '<span class="spin"></span> Testing…';
        try {
          const r = await api('/api/mail/accounts/bulk', { text: ta.value, test: true });
          const good = r.results.filter(x => x.ok).length;
          $('#bres', m).innerHTML = r.results.map(x => `<div class="small" style="margin-top:6px;color:${x.ok ? 'var(--green)' : 'var(--red)'}">${x.ok ? '✓' : '✗'} ${esc(x.email)} ${x.ok ? '' : '— ' + esc(x.error)}</div>`).join('');
          if (good) { toast(`${good} account${good === 1 ? '' : 's'} connected`); api('/api/mail/sync', {}).catch(() => { }); pollShell(); if (good === r.results.length) { closeModal(); refreshPage(); } else { refreshPage(); } }
        } catch (x) { $('#aerr', m).textContent = x.message; $('#aerr', m).classList.remove('hidden'); }
        btn.disabled = false; btn.textContent = 'Connect ' + cnt() + ' accounts';
      };
    }
  };
  modal('', { onMount: m => draw(m) });
}

/* ================================================================ Discord webhooks */
PAGES.webhooks = async function (v) {
  const T = S.tok;
  const d = await api('/api/webhooks');
  if (T !== S.tok) return;
  v.innerHTML = `<div class="page"><div class="ph"><div><h1>Discord webhooks</h1><p>Post order progress to any channel you own. Each webhook can get a different set of events.</p></div><div class="acts"><button class="btn p" id="w-add">Add webhook</button></div></div>
   ${d.items.length ? d.items.map(w => `<div class="card" data-id="${w.id}"><div class="row"><div style="flex:1;min-width:0"><div style="font-weight:600;font-size:17px">${esc(w.name)}</div><div class="mono dim" style="margin-top:3px">${esc(w.url_masked)}</div></div>
     <button class="btn sm" data-a="test">Send test</button><button class="btn sm" data-a="edit">Edit</button><label class="sw"><input type="checkbox" data-a="en" ${w.enabled ? 'checked' : ''}><i></i></label><button class="btn sm ghost" data-a="rm">Delete</button></div>
     <div class="row wrap" style="margin-top:14px;gap:8px">${w.events.length ? w.events.map(e => `<span class="pill"><i></i>${esc((d.events.find(x => x.id === e) || {}).label || e)}</span>`).join('') : '<span class="note">No events selected — nothing will be sent.</span>'}</div>
     ${w.last_status ? `<div class="note" style="margin-top:10px">Last test: ${esc(w.last_status)}</div>` : ''}</div>`).join('')
     : '<div class="empty"><b>No webhooks yet</b>Paste a Discord webhook URL and pick which events to send.</div>'}</div>`;
  const form = w => modal(`<h2>${w ? 'Edit webhook' : 'Add webhook'}</h2><p>In Discord: channel settings → Integrations → Webhooks → New Webhook → Copy Webhook URL.</p>
    <div class="fld"><label class="f">Name</label><input class="inp" id="wn" placeholder="Orders channel" value="${esc(w ? w.name : '')}"></div>
    <div class="fld"><label class="f">Webhook URL</label><input class="inp" id="wu" placeholder="${w ? 'Saved — leave blank to keep' : 'https://discord.com/api/webhooks/…'}"></div>
    <div class="fld"><label class="f">Send these events</label><div class="col2">${d.events.map(e => `<label class="tog" style="margin:5px 0"><input type="checkbox" class="ck we" value="${e.id}" ${(w ? w.events.includes(e.id) : ['shipped', 'delivered', 'cancelled'].includes(e.id)) ? 'checked' : ''}>${esc(e.label)}</label>`).join('')}</div></div>
    <div class="err hidden" id="werr"></div><div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="wsv">Save</button></div>`, {
    onMount: m => $('#wsv', m).onclick = async () => { try { await api('/api/webhooks/save', { id: w && w.id, name: $('#wn', m).value, url: $('#wu', m).value, events: $$('.we', m).filter(x => x.checked).map(x => x.value), enabled: w ? w.enabled : true }); closeModal(); toast('Saved'); refreshPage(); } catch (x) { $('#werr', m).textContent = x.message; $('#werr', m).classList.remove('hidden'); } }
  });
  $('#w-add').onclick = () => form();
  $$('.card[data-id]', v).forEach(c => c.onclick = async e => {
    const k = e.target.closest('[data-a]'); if (!k) return; const w = d.items.find(x => x.id == c.dataset.id);
    if (k.dataset.a === 'edit') form(w);
    if (k.dataset.a === 'test') { const r = await busy(k, () => act(() => api('/api/webhooks/test', { id: w.id }))); if (r) { toast(r.result === 'ok' ? 'Test sent — check your channel' : 'Discord said: ' + r.result, r.result !== 'ok'); refreshPage(); } }
    if (k.dataset.a === 'en') { await act(() => api('/api/webhooks/save', { ...w, url: '', enabled: k.checked })); refreshPage(); }
    if (k.dataset.a === 'rm' && await confirmBox('Delete this webhook?', 'Nothing more is sent to it.', 'Delete', true)) { await act(() => api('/api/webhooks/delete', { id: w.id })); refreshPage(); }
  });
};
