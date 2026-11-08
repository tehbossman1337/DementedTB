/* Arsenal pages + Settings */
const CO = { q: '', retailer: '', bot: '', proxy: '', range: 'all', from: '', to: '', match: 'all', data: null };

PAGES.checkouts = async function (v) {
  const T = S.tok;
  v.innerHTML = `<div class="page"><div class="ph"><div><h1>Checkouts</h1><p>Every success webhook scraped from your watched channels, joined to the Order Tracker where the retailer's own email confirms what actually happened.</p></div>
    <div class="acts"><button class="btn" id="c-pic">${icon('image', 18)} Success pic</button><button class="btn" id="c-exp">Export CSV</button><button class="btn p" id="c-add">Add checkout</button></div></div>
    <div id="c-stats"></div>
    <div class="filters"><input class="inp" id="cq" placeholder="Search order #, product, bot, profile…" style="max-width:380px" value="${esc(CO.q)}">
      <select class="sel" id="cret" style="width:170px"></select><select class="sel" id="cbot" style="width:150px"></select><select class="sel" id="cpx" style="width:180px"></select></div>
    <div class="row wrap" style="margin-bottom:18px;gap:16px"><div class="chips" id="crange">${[['all', 'All'], ['24h', '24h'], ['7d', '7d'], ['30d', '30d'], ['90d', '90d'], ['custom', 'Custom']].map(([k, l]) => `<button data-r="${k}" class="${CO.range === k ? 'on' : ''}">${l}</button>`).join('')}</div>
      <span id="ccust" class="row ${CO.range === 'custom' ? '' : 'hidden'}"><input type="date" class="inp" id="cfrom" style="width:150px" value="${CO.from}"><span class="muted">to</span><input type="date" class="inp" id="cto" style="width:150px" value="${CO.to}"></span>
      <div class="chips" id="cmatch">${[['all', 'All'], ['unmatched', 'Unmatched'], ['matched', 'Matched'], ['suggested', 'Suggested'], ['rejected', 'Rejected']].map(([k, l]) => `<button data-m="${k}" class="${CO.match === k ? 'on' : ''}">${l}</button>`).join('')}</div></div>
    <div id="c-list"></div></div>`;
  let t; const redraw = () => { clearTimeout(t); t = setTimeout(loadCheckouts, 120); };
  $('#cq').oninput = e => { CO.q = e.target.value; redraw(); };
  for (const [id, k] of [['cret', 'retailer'], ['cbot', 'bot'], ['cpx', 'proxy']]) $('#' + id).onchange = e => { CO[k] = e.target.value; loadCheckouts(); };
  $('#crange').onclick = e => { const b = e.target.closest('[data-r]'); if (!b) return; CO.range = b.dataset.r; $$('#crange button').forEach(x => x.classList.toggle('on', x === b)); $('#ccust').classList.toggle('hidden', CO.range !== 'custom'); loadCheckouts(); };
  $('#cfrom').onchange = e => { CO.from = e.target.value; loadCheckouts(); }; $('#cto').onchange = e => { CO.to = e.target.value; loadCheckouts(); };
  $('#cmatch').onclick = e => { const b = e.target.closest('[data-m]'); if (!b) return; CO.match = b.dataset.m; $$('#cmatch button').forEach(x => x.classList.toggle('on', x === b)); loadCheckouts(); };
  $('#c-add').onclick = () => checkoutForm();
  $('#c-pic').onclick = () => successPic();
  $('#c-exp').onclick = async () => { const r = await act(() => api('/api/arsenal/export', {})); if (r) toast('Saved to ' + r.path); };
  await loadCheckouts();
};

async function loadCheckouts() {
  const qs = new URLSearchParams({ q: CO.q, retailer: CO.retailer, bot: CO.bot, proxy: CO.proxy, range: CO.range, from: CO.from, to: CO.to, match: CO.match });
  const d = await api('/api/arsenal/checkouts?' + qs); if (S.route !== 'checkouts' || !$('#c-list')) return; CO.data = d; const st = d.stats;
  const fill = (id, label, list, cur) => { const s = $('#' + id); if (!s) return; s.innerHTML = `<option value="">${label}</option>` + list.map(x => `<option ${cur === x ? 'selected' : ''}>${esc(x)}</option>`).join(''); };
  fill('cret', 'All retailers', d.retailers, CO.retailer); fill('cbot', 'All bots', d.bots, CO.bot); fill('cpx', 'All proxy lists', d.proxies, CO.proxy);
  $('#c-stats').innerHTML = `<div class="stats">
    <div class="stat"><div class="k">Checkouts</div><div class="v">${st.count}</div><div class="d">${st.units} unit${st.units === 1 ? '' : 's'}</div></div>
    <div class="stat"><div class="k">Spend</div><div class="v">${money(st.spend)}</div><div class="d">Linked Order Tracker total where linked${st.unpriced ? ` · ${st.unpriced} unpriced` : ''}</div></div>
    <div class="stat"><div class="k">Stick rate</div>${st.stick_rate == null ? '<div class="dash"></div>' : `<div class="v green">${Math.round(st.stick_rate * 100)}%</div>`}<div class="d">${st.stick_rate == null ? 'No rated checkouts yet' : `${st.rated} confirmed by the tracker`}</div></div>
    <div class="stat"><div class="k">Tracker-confirmed</div><div class="v">${st.confirmed}</div><div class="d">Linked to one of your orders</div></div>
    <div class="stat"><div class="k">Bot-reported</div><div class="v red">${st.bot_reported}</div><div class="d">No linked order · rated from bot report</div></div></div>`;
  const L = $('#c-list');
  if (!d.items.length) {
    const none = st.count === 0 && !CO.q && !CO.retailer && !CO.bot && !CO.proxy && CO.match === 'all' && CO.range === 'all';
    L.innerHTML = `<div class="empty" style="padding:70px 24px"><b>${none ? 'No checkouts yet' : 'No checkouts match these filters'}</b>${none ? 'Link a server and watch a channel to start scraping success webhooks, or add one by hand.' : 'Try a different filter.'}${none ? '<br><button class="btn p" id="c-hand">Add a checkout by hand</button>' : ''}</div>`;
    const h = $('#c-hand'); if (h) h.onclick = () => checkoutForm(); return;
  }
  L.innerHTML = `<div class="card" style="padding:8px 24px 14px"><div class="tbl-wrap"><table class="t" id="co-t"><thead><tr><th>Product</th><th>Store</th><th>Bot</th><th>Proxy list</th><th>Price</th><th>Qty</th><th>Date</th><th>Match</th><th></th></tr></thead><tbody>
    ${d.items.map(r => `<tr data-id="${r.id}"><td class="p"><div class="pcell">${r.image ? `<div class="pb"><img src="${esc(r.image)}" onerror="this.parentNode.innerHTML='${esc((r.store || '?')[0])}'"></div>` : `<div class="pb" style="background:#2a2a38;color:#cfd0dc">${esc((r.store || r.product || '?')[0].toUpperCase())}</div>`}<div><div>${esc(r.product)}</div>${r.size ? `<div class="muted small">Size ${esc(r.size)}</div>` : ''}</div></div></td>
    <td>${esc(r.store || '—')}</td><td>${esc(r.bot || '—')}</td><td>${esc(r.proxy_list || '—')}</td>
    <td style="font-weight:600">${r.price == null ? '<span class="muted">Unpriced</span>' : money(r.price)}${r.price_source === 'rule' ? '<span class="tag">From your price rule</span>' : ''}</td><td>${r.qty}</td><td>${fdt(r.ts)}</td>
    <td>${pill(r.match_status, r.match_status[0].toUpperCase() + r.match_status.slice(1))}${r.order ? `<div class="mono dim" style="margin-top:3px">${esc(r.order.order_number)}</div>` : ''}</td>
    <td><button class="iconbtn" data-menu>${icon('dots', 18)}</button></td></tr>`).join('')}</tbody></table></div></div>`;
  $$('#co-t tbody tr').forEach(tr => {
    const r = d.items.find(x => x.id == tr.dataset.id);
    tr.onclick = e => { if (!e.target.closest('[data-menu]')) checkoutForm(r); };
    $('[data-menu]', tr).onclick = e => menu(e, [
      { label: 'Edit…', fn: () => checkoutForm(r) },
      ...(r.match_status === 'suggested' ? [{ label: 'Confirm suggested order', fn: () => matchAct(r, 'confirm') }, { label: 'Not this order', fn: () => matchAct(r, 'reject') }] : []),
      { label: 'Link to an order…', fn: () => linkPicker(r) },
      ...(r.link_order_id ? [{ label: 'Unlink order', fn: () => matchAct(r, 'unlink') }] : []),
      { label: 'Set picture…', fn: () => setPicture(r) }, { label: 'Price rule…', fn: () => ruleModal({ match: r.product, store: r.store, bot: r.bot, price: r.price == null ? '' : r.price }) }, '-',
      { label: 'Delete', cls: 'd', fn: async () => { await act(() => api('/api/arsenal/checkouts/delete', { ids: [r.id] })); loadCheckouts(); } }]);
  });
}
const matchAct = async (r, action, order_id) => { if (await act(() => api('/api/arsenal/checkouts/match', { id: r.id, action, order_id }))) loadCheckouts(); };
function linkPicker(r) {
  modal(`<h2>Link to an order</h2><p>Pick the Order Tracker order this checkout turned into.</p><div class="fld"><select class="sel" id="lo">${CO.data.orders.map(o => `<option value="${o.id}" ${r.link_order_id === o.id ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}</select></div><div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="lgo2">Link</button></div>`,
    { onMount: m => $('#lgo2', m).onclick = async () => { await matchAct(r, 'link', +$('#lo', m).value); closeModal(); } });
}
function setPicture(r) {
  pickFiles('image/*', false).then(fs => {
    if (!fs[0]) return; const img = new Image(), u = URL.createObjectURL(fs[0]);
    img.onload = async () => { const k = 160 / Math.max(img.width, img.height, 160), c = document.createElement('canvas'); c.width = Math.round(img.width * k); c.height = Math.round(img.height * k); c.getContext('2d').drawImage(img, 0, 0, c.width, c.height); await act(() => api('/api/arsenal/checkouts/image', { id: r.id, data: c.toDataURL('image/jpeg', .85) }), 'Picture set'); loadCheckouts(); };
    img.src = u;
  });
}
function checkoutForm(r) {
  const d = CO.data || {}, e = r || {};
  modal(`<h2>${r ? 'Edit checkout' : 'Add checkout'}</h2><p>${r ? 'Correcting the bot or proxy list here stops name mappings from changing this row.' : 'Log a checkout by hand.'}</p>
   <div class="fld"><label class="f">Product</label><input class="inp" id="cp" value="${esc(e.product || '')}"></div>
   <div class="col2"><div class="fld"><label class="f">Store</label><input class="inp" id="cs" list="cl-s" value="${esc(e.store || '')}"><datalist id="cl-s">${(d.retailers || []).map(x => `<option>${esc(x)}`).join('')}</datalist></div><div class="fld"><label class="f">Price each ($) — blank = unpriced</label><input class="inp" id="cpr" value="${e.price ?? ''}"></div></div>
   <div class="col2"><div class="fld"><label class="f">Quantity</label><input class="inp" id="cq2" type="number" min="1" value="${e.qty || 1}"></div><div class="fld"><label class="f">Size</label><input class="inp" id="csz" value="${esc(e.size || '')}"></div></div>
   <div class="col2"><div class="fld"><label class="f">Bot</label><input class="inp" id="cb" list="cl-b" value="${esc(e.bot || '')}"><datalist id="cl-b">${(d.bots || []).map(x => `<option>${esc(x)}`).join('')}</datalist></div><div class="fld"><label class="f">Proxy list</label><input class="inp" id="cx" list="cl-x" value="${esc(e.proxy_list || '')}"><datalist id="cl-x">${(d.proxies || []).map(x => `<option>${esc(x)}`).join('')}</datalist></div></div>
   <div class="col2"><div class="fld"><label class="f">Profile</label><input class="inp" id="cpf" value="${esc(e.profile || '')}"></div><div class="fld"><label class="f">Order number</label><input class="inp" id="con" value="${esc(e.order_number || '')}"></div></div>
   <div class="col2"><div class="fld"><label class="f">Account email</label><input class="inp" id="cem" value="${esc(e.email || '')}"></div><div class="fld"><label class="f">Date / time</label><input class="inp" id="cts" placeholder="2026-11-07 14:30" value="${esc((e.ts || '').slice(0, 16))}"></div></div>
   <div class="err hidden" id="cerr"></div><div class="mfoot">${r ? '<button class="btn danger" id="cdel" style="margin-right:auto">Delete</button>' : ''}<button class="btn" data-close>Cancel</button><button class="btn p" id="csv">Save</button></div>`, {
    onMount: m => {
      $('#csv', m).onclick = async () => { try { await api('/api/arsenal/checkouts/save', { id: r && r.id, product: $('#cp', m).value, store: $('#cs', m).value, price: $('#cpr', m).value, qty: $('#cq2', m).value, size: $('#csz', m).value, bot: $('#cb', m).value, proxy_list: $('#cx', m).value, profile: $('#cpf', m).value, order_number: $('#con', m).value, email: $('#cem', m).value, ts: $('#cts', m).value }); closeModal(); toast('Saved'); loadCheckouts(); } catch (x) { $('#cerr', m).textContent = x.message; $('#cerr', m).classList.remove('hidden'); } };
      if (r) $('#cdel', m).onclick = async () => { await act(() => api('/api/arsenal/checkouts/delete', { ids: [r.id] })); closeModal(); loadCheckouts(); };
    }
  });
}

/* ---------- success pic: a shareable image of your checkouts */
async function successPic() {
  const rows = (CO.data ? CO.data.items : []).filter(r => r.status === 'success').slice(0, 12);
  if (!rows.length) return toast('No checkouts to show yet.', true);
  const spend = CO.data.stats.spend;
  const imgs = await Promise.all(rows.map(r => new Promise(res => { if (!r.image) return res(null); const i = new Image(); i.crossOrigin = 'anonymous'; i.onload = () => res(i); i.onerror = () => res(null); i.src = r.image; })));
  const cols = Math.min(4, rows.length), cw = 260, ch = 250, pad = 28, W = pad + cols * (cw + pad), H = 150 + Math.ceil(rows.length / cols) * (ch + pad);
  const c = document.createElement('canvas'); c.width = W; c.height = H; const g = c.getContext('2d');
  g.fillStyle = '#0a0a0f'; g.fillRect(0, 0, W, H);
  const grad = g.createRadialGradient(W / 2, 0, 10, W / 2, 0, W * .6); grad.addColorStop(0, 'rgba(229,48,79,.25)'); grad.addColorStop(1, 'rgba(229,48,79,0)'); g.fillStyle = grad; g.fillRect(0, 0, W, 300);
  g.fillStyle = '#fff'; g.font = '700 34px Segoe UI, Inter, sans-serif'; g.fillText('Success', pad, 62);
  g.fillStyle = '#8c8d9f'; g.font = '16px Segoe UI, Inter, sans-serif'; g.fillText(`${rows.length} checkout${rows.length === 1 ? '' : 's'} · ${money(spend)} · Demented Toolbox`, pad, 92);
  const rr = (x, y, w, h, r) => { g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r); g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); };
  rows.forEach((r, i) => {
    const x = pad + (i % cols) * (cw + pad), y = 130 + Math.floor(i / cols) * (ch + pad);
    g.fillStyle = '#14141d'; rr(x, y, cw, ch, 16); g.fill(); g.strokeStyle = '#242433'; g.stroke();
    g.save(); rr(x + 12, y + 12, cw - 24, 140, 12); g.clip();
    if (imgs[i]) { const k = Math.max((cw - 24) / imgs[i].width, 140 / imgs[i].height); g.drawImage(imgs[i], x + 12 + (cw - 24 - imgs[i].width * k) / 2, y + 12 + (140 - imgs[i].height * k) / 2, imgs[i].width * k, imgs[i].height * k); }
    else { g.fillStyle = '#20202d'; g.fillRect(x, y, cw, 160); g.fillStyle = '#e5304f'; g.font = '700 54px Segoe UI, sans-serif'; g.textAlign = 'center'; g.fillText((r.store || r.product)[0].toUpperCase(), x + cw / 2, y + 100); g.textAlign = 'left'; }
    g.restore();
    g.fillStyle = '#ecedf3'; g.font = '600 14px Segoe UI, Inter, sans-serif'; const t = r.product.length > 30 ? r.product.slice(0, 29) + '…' : r.product; g.fillText(t, x + 14, y + 180);
    g.fillStyle = '#8c8d9f'; g.font = '13px Segoe UI, Inter, sans-serif'; g.fillText(`${r.store || ''}${r.bot ? ' · ' + r.bot : ''}`.slice(0, 34), x + 14, y + 202);
    g.fillStyle = '#34d399'; g.font = '700 16px Segoe UI, Inter, sans-serif'; g.fillText(r.price == null ? 'Unpriced' : money(r.price), x + 14, y + 230);
  });
  let url; try { url = c.toDataURL('image/png'); } catch (e) { toast('A picture from Discord blocked the image export. Remove it with “Set picture…” and try again.', true); return; }
  modal(`<h2>Success pic</h2><p>The ${rows.length} newest checkouts in your current view.</p><img src="${url}" style="width:100%;border-radius:12px;border:1px solid var(--line)"><div class="mfoot"><button class="btn" data-close>Close</button><button class="btn" id="spc">Copy image</button><button class="btn p" id="spd">Download PNG</button></div>`, {
    wide: true, onMount: m => {
      $('#spd', m).onclick = () => { const a = document.createElement('a'); a.href = url; a.download = 'demented-success.png'; a.click(); };
      $('#spc', m).onclick = () => c.toBlob(async b => { try { await navigator.clipboard.write([new ClipboardItem({ 'image/png': b })]); toast('Copied'); } catch (e) { toast('Copy isn\'t available here — use Download.', true); } });
    }
  });
}

/* ---------- price rules */
function ruleModal(pre = {}) {
  let preview = null;
  modal(`<h2>Price rule</h2><p>Give unpriced items a price of your choosing. Rules apply to future checkouts by default. A price from a rule is labelled “From your price rule” and never rewrites a checkout that has its own price.</p>
   <div class="fld"><label class="f">When the product name contains</label><input class="inp" id="rm" value="${esc(pre.match || '')}"></div>
   <div class="col2"><div class="fld"><label class="f">Store (optional)</label><input class="inp" id="rs" value="${esc(pre.store || '')}"></div><div class="fld"><label class="f">Bot (optional)</label><input class="inp" id="rb" value="${esc(pre.bot || '')}"></div></div>
   <div class="fld"><label class="f">Price each ($)</label><input class="inp" id="rp" value="${esc(pre.price ?? '')}"></div><div id="rprev"></div><div class="err hidden" id="rerr"></div>
   <div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn" id="rprevb">Preview changes</button><button class="btn p" id="rsave" disabled>Save rule</button></div>`, {
    onMount: m => {
      const body = () => ({ match: $('#rm', m).value, store: $('#rs', m).value, bot: $('#rb', m).value, price: $('#rp', m).value });
      const err = x => { $('#rerr', m).textContent = x.message; $('#rerr', m).classList.remove('hidden'); };
      ['rm', 'rs', 'rb', 'rp'].forEach(i => $('#' + i, m).oninput = () => { preview = null; $('#rsave', m).disabled = true; $('#rprev', m).innerHTML = ''; });
      $('#rprevb', m).onclick = async () => {
        $('#rerr', m).classList.add('hidden');
        try { preview = await api('/api/arsenal/rules/preview', body()); } catch (x) { return err(x); }
        $('#rprev', m).innerHTML = preview.hits.length ? `<div class="cardt" style="margin-top:6px">This will price ${preview.hits.length} existing checkout${preview.hits.length === 1 ? '' : 's'}</div><div style="max-height:200px;overflow:auto">${preview.hits.map(h => `<label class="row small" style="padding:6px 0;border-bottom:1px solid var(--line)"><input type="checkbox" class="ck rh" value="${h.id}" checked><span style="flex:1">${esc(h.product)}</span><span class="muted">${h.old == null ? 'Unpriced' : money(h.old)}</span><span>→ <b>${money(h.new)}</b></span></label>`).join('')}</div>` : '<div class="note" style="margin-top:6px">No existing checkouts match — the rule will apply to future ones.</div>';
        $('#rsave', m).disabled = false;
      };
      $('#rsave', m).onclick = async () => { try { const r = await api('/api/arsenal/rules/save', { ...body(), apply_ids: $$('.rh', m).filter(x => x.checked).map(x => +x.value) }); closeModal(); toast(`Rule saved${r.applied ? ` — priced ${r.applied} checkout${r.applied === 1 ? '' : 's'}` : ''}`); refreshPage(); } catch (x) { err(x); } };
    }
  });
}
PAGES.rules = async function (v) {
  const T = S.tok;
  const d = await api('/api/arsenal/lists');
  if (T !== S.tok) return;
  v.innerHTML = `<div class="page"><div class="ph"><div><h1>Price rules</h1><p>Give unpriced items a price of your choosing. Rules apply to future checkouts by default. A price from a rule is labelled "From your price rule" and never rewrites a checkout.</p></div><div class="acts"><button class="btn p" id="r-add">Add rule</button></div></div>
   ${d.rules.length ? d.rules.map(r => `<div class="item big"><div><div class="t">${esc(r.match)}</div><div class="s">${r.store ? 'Store: ' + esc(r.store) + ' · ' : ''}${r.bot ? 'Bot: ' + esc(r.bot) + ' · ' : ''}Added ${fdate(r.created_at)}</div></div><div class="r"><b style="font-size:17px">${money(r.price)}</b><button class="btn sm ghost" data-rm="${r.id}">Delete</button></div></div>`).join('')
     : `<div class="empty"><b>No price rules yet</b>Some bots (Shikari, SWFT) report no price at all, so their checkouts count as unpriced. Open a checkout, choose <b style="display:inline;font-size:inherit;color:var(--text)">Price rule…</b><br>on an item, set a price, and review exactly what it will change before confirming.</div>`}</div>`;
  $('#r-add').onclick = () => ruleModal();
  $$('[data-rm]', v).forEach(b => b.onclick = async () => { if (await confirmBox('Delete this rule?', 'Checkouts already priced by it keep their price.', 'Delete', true)) { await act(() => api('/api/arsenal/remove', { kind: 'rule', id: +b.dataset.rm })); refreshPage(); } });
};

/* ---------- servers & channels */
PAGES.servers = async function (v) {
  const T = S.tok;
  const d = await api('/api/discord/status'); const linked = d.servers.filter(s => s.linked), avail = d.servers.filter(s => !s.linked);
  if (T !== S.tok) return;
  const srvIcon = s => s.icon ? `<img src="${esc(s.icon)}" style="width:50px;height:50px;border-radius:12px">` : `<div class="avatar" style="border-radius:12px;width:50px;height:50px;background:#1d1d2a;color:#fff;font-weight:700">${esc((s.name || '?')[0])}</div>`;
  v.innerHTML = `<div class="page"><div class="ph"><div><h1>Servers & channels</h1><p>Link the Discord servers your bots post into, then pick the success channels to watch. Only channels your own bot can read can be watched.</p></div>
    <div class="acts"><button class="btn" id="s-ref" ${d.bot.has_token ? '' : 'disabled'}>Refresh</button><button class="btn p" id="s-add">Add a server</button></div></div>
    <div class="item big"><span class="dot ${d.error ? 'r' : d.running ? 'a' : 'g'}"></span><div><div class="t" style="font-size:17px">${d.error ? 'Problem' : d.running ? 'Syncing…' : 'Up to date'}</div><div class="s">${d.error ? esc(d.error) : d.watching ? `Watching ${d.watching} channel${d.watching === 1 ? '' : 's'}${d.last ? ' · last synced ' + fdt(d.last) : ''}` : 'Watch a channel to start syncing'}</div></div>
      <div class="r"><button class="btn sm" id="s-sync" ${d.watching ? '' : 'disabled'}>Sync now</button><button class="btn sm" id="s-back" ${d.watching ? '' : 'disabled'}>Backfill all…</button><button class="btn sm" id="s-resc" ${d.watching ? '' : 'disabled'}>Rescan all</button></div></div>
    ${!d.bot.has_token ? `<div class="empty" style="margin-top:10px"><b>Connect your Discord bot</b>Create a bot in the Discord developer portal, invite it to your server, and paste its token. It only needs to read channels.<br><button class="btn p" id="s-add2">Add a server</button></div>` : ''}
    ${linked.length ? `<div class="muted" style="margin:22px 0 10px">Linked</div>${linked.map(s => `<div class="item big" data-g="${s.guild_id}" style="cursor:pointer;flex-wrap:wrap"><span class="dot g"></span><div><div class="t" style="font-size:17px">${esc(s.name)}</div><div class="s">${s.watched} channel${s.watched === 1 ? '' : 's'} watched</div></div><div class="r"><button class="btn sm ghost" data-unlink>Unlink</button><span class="muted car" style="font-size:12px">▸</span></div><div class="chlist" style="width:100%"></div></div>`).join('')}` : ''}
    ${avail.length ? `<div class="muted" style="margin:22px 0 10px">Available to link</div>${avail.map(s => `<div class="item big" data-link="${s.guild_id}">${srvIcon(s)}<div class="t" style="font-size:17px">${esc(s.name)}</div><div class="r"><button class="btn p sm" style="padding:10px 16px">Link this server</button></div></div>`).join('')}` : ''}</div>`;
  const doSync = async (o, m) => { if (await act(() => api('/api/discord/sync', o), m)) { const t = setInterval(async () => { const s = await api('/api/discord/status'); if (!s.running) { clearInterval(t); toast(s.error ? s.error : `Done — ${s.added} new checkout${s.added === 1 ? '' : 's'}`, !!s.error); refreshPage(); } }, 1000); } };
  $('#s-sync').onclick = () => doSync({}, 'Syncing…');
  $('#s-back').onclick = async () => { if (await confirmBox('Backfill all watched channels?', 'Reads each channel\'s older success posts (up to the last 3,000 messages per channel). Checkouts you deleted stay deleted.', 'Backfill')) doSync({ backfill: true }, 'Backfilling…'); };
  $('#s-resc').onclick = async () => { if (await confirmBox('Rescan all watched channels?', 'Forgets where each channel was last read and reads it again. Nothing is duplicated.', 'Rescan')) doSync({ rescan: true }, 'Rescanning…'); };
  $('#s-ref').onclick = async e => { const r = await busy(e.currentTarget, () => api('/api/discord/refresh', {})); if (!r.ok) toast(r.error, true); refreshPage(); };
  const add = () => serverModal(d); $('#s-add').onclick = add; const a2 = $('#s-add2'); if (a2) a2.onclick = add;
  $$('[data-link]', v).forEach(r => $('button', r).onclick = async () => { await act(() => api('/api/discord/link', { guild_id: r.dataset.link, linked: true })); refreshPage(); });
  $$('[data-g]', v).forEach(card => {
    const gid = card.dataset.g, box = $('.chlist', card); let open = false;
    $('[data-unlink]', card).onclick = async e => { e.stopPropagation(); await act(() => api('/api/discord/link', { guild_id: gid, linked: false })); refreshPage(); };
    card.onclick = async e => {
      if (e.target.closest('.chlist') || e.target.closest('button')) return;
      open = !open; if (!open) { box.innerHTML = ''; return; }
      box.innerHTML = '<div class="note" style="padding:14px 0 4px">Loading channels…</div>';
      const r = await api('/api/discord/channels?guild_id=' + gid);
      box.innerHTML = `<div style="border-top:1px solid var(--line);margin-top:14px;padding-top:8px">${r.ok ? '' : `<div class="err">${esc(r.error)}</div>`}${r.channels.length ? r.channels.map(c => `<div class="row" style="padding:9px 4px"><span class="muted">#</span><span style="flex:1">${esc(c.name)}${c.error ? `<span class="err" style="margin-left:10px">${esc(c.error)}</span>` : ''}</span><label class="sw"><input type="checkbox" data-ch="${c.channel_id}" ${c.watched ? 'checked' : ''}><i></i></label></div>`).join('') : '<div class="note" style="padding:10px 4px">No text channels visible to the bot. Check its permissions.</div>'}</div>`;
      $$('[data-ch]', box).forEach(i => i.onchange = async () => { await act(() => api('/api/discord/watch', { channel_id: i.dataset.ch, watched: i.checked })); if (i.checked) doSync({}, 'Reading the channel…'); });
    };
  });
};
function serverModal(d) {
  modal(`<h2>${d.bot.has_token ? 'Add another server' : 'Add a server'}</h2>
   ${d.bot.has_token ? `<p>Your bot <b>${esc(d.bot.name)}</b> is connected. Invite it to another server, then press Refresh.</p><div class="row"><button class="btn" id="inv">Open invite link</button><button class="btn danger" id="forget">Disconnect bot</button></div><div class="divider"></div><p class="small">Replace the bot token:</p>`
   : `<p>Arsenal reads success posts with a Discord bot that <b>you</b> own. Nothing is ever posted.</p>
   <ol class="small muted" style="line-height:1.8;padding-left:20px;margin:0 0 16px"><li>Open <a href="#" data-url="https://discord.com/developers/applications">discord.com/developers/applications</a> → New Application.</li><li>Bot tab → Reset Token → copy it (paste below).</li><li>OAuth2 → invite the bot to your server with <b>View Channels</b> + <b>Read Message History</b>.</li></ol>`}
   <div class="fld"><label class="f">Bot token</label><input class="inp" id="tk" type="password" placeholder="Paste the bot token" autocomplete="off"></div><div class="err hidden" id="terr"></div>
   <div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="tgo">Save token</button></div>`, {
    onMount: m => {
      $$('[data-url]', m).forEach(a => a.onclick = e => { e.preventDefault(); api('/api/open_url', { url: a.dataset.url }); });
      if (d.bot.has_token) { $('#inv', m).onclick = () => api('/api/open_url', { url: d.invite_url }); $('#forget', m).onclick = async () => { if (await confirmBox('Disconnect the bot?', 'Removes the token, linked servers and watched channels. Checkouts you already have stay.', 'Disconnect', true)) { await api('/api/discord/forget', {}); closeModal(); refreshPage(); } }; }
      $('#tgo', m).onclick = async e => { const r = await busy(e.currentTarget, () => api('/api/discord/token', { token: $('#tk', m).value })); if (!r.ok) { $('#terr', m).textContent = r.error; $('#terr', m).classList.remove('hidden'); return; } closeModal(); toast('Bot connected'); refreshPage(); };
    }
  });
}

/* ---------- bots & proxies */
PAGES.bots = async function (v) {
  const T = S.tok;
  const sa = store.get('showarch', { bots: false, proxies: false });
  const d = await api('/api/arsenal/lists?archived=1');
  if (T !== S.tok) return;
  const bots = d.bots.filter(b => sa.bots || !b.archived), pls = d.proxy_lists.filter(p => sa.proxies || !p.archived);
  const row = (kind, r, sub) => `<div class="item" data-k="${kind}" data-id="${r.id}"><span class="dot ${r.archived ? '' : 'g'}"></span><div><div class="t">${esc(r.name)}${r.archived ? ' <span class="tag" style="background:#23232f;color:var(--muted)">Archived</span>' : ''}</div><div class="s">${sub}</div></div><div class="r"><button class="btn sm" data-e>Edit</button><button class="btn sm ghost" data-d>Delete</button></div></div>`;
  v.innerHTML = `<div class="page"><div class="ph"><div><h1>Bots & proxies</h1><p>Correct how a checkout gets attributed, and teach the app to recognise a webhook name automatically next time.</p></div></div>
   <div class="card"><div class="hd"><h3>Bots</h3><div class="r"><label class="tog"><span class="sw"><input type="checkbox" id="sab" ${sa.bots ? 'checked' : ''}><i></i></span>Show archived</label><button class="btn p sm" id="b-add">Add bot</button></div></div>
     ${bots.length ? bots.map(b => row('bot', b, `${money(b.monthly_cost)} /month${b.active_from ? ' · active from ' + b.active_from : ''}`)).join('') : '<div class="note">No bots yet — one is created automatically the first time a webhook reports it.</div>'}</div>
   <div class="card"><div class="hd"><h3>Proxy lists</h3><div class="r"><label class="tog"><span class="sw"><input type="checkbox" id="sap" ${sa.proxies ? 'checked' : ''}><i></i></span>Show archived</label><button class="btn p sm" id="p-add">Add proxy list</button></div></div>
     <p class="small" style="margin-bottom:12px">A list name gets reused — give a repurchase a new row (with its own active-from date) rather than editing this one, or the stats will read as a trend when it's really a swap.</p>
     ${pls.length ? pls.map(p => row('proxy', p, `${money(p.cost)}${p.active_from ? ' · active from ' + p.active_from : ''}`)).join('') : '<div class="note">No proxy lists yet — one is created automatically the first time a bot reports one.</div>'}</div>
   <div class="card"><div class="hd"><h3>Name mappings</h3><div class="r"><button class="btn p sm" id="n-add">Add mapping</button></div></div>
     <p class="small">Correcting a bot or proxy list on any checkout is a one-off fix. A mapping makes it stick: every future post from that webhook name is attributed automatically. Saving one re-attributes matching rows immediately, except ones you've corrected by hand.</p>
     ${d.name_maps.length ? d.name_maps.map(n => row('name', { ...n, name: n.webhook_name }, `→ ${[n.bot && 'bot ' + esc(n.bot), n.proxy_list && 'proxy list ' + esc(n.proxy_list)].filter(Boolean).join(' · ')}`)).join('') : '<div class="note">No mappings yet.</div>'}</div></div>`;
  $('#sab').onchange = e => { sa.bots = e.target.checked; store.set('showarch', sa); refreshPage(); }; $('#sap').onchange = e => { sa.proxies = e.target.checked; store.set('showarch', sa); refreshPage(); };
  const bform = b => modal(`<h2>${b ? 'Edit bot' : 'Add bot'}</h2><div class="fld"><label class="f">Name</label><input class="inp" id="bn" value="${esc(b ? b.name : '')}"></div><div class="col2"><div class="fld"><label class="f">Monthly cost ($)</label><input class="inp" id="bc" value="${b ? b.monthly_cost : ''}"></div><div class="fld"><label class="f">Active from</label><input type="date" class="inp" id="ba" value="${esc(b ? b.active_from : '')}"></div></div>
     <label class="tog"><span class="sw"><input type="checkbox" id="bar" ${b && b.archived ? 'checked' : ''}><i></i></span>Archived (hide from lists, keep the history)</label><div class="err hidden" id="berr"></div><div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="bsv">Save</button></div>`,
     { onMount: m => $('#bsv', m).onclick = async () => { try { await api('/api/arsenal/bots/save', { id: b && b.id, name: $('#bn', m).value, monthly_cost: $('#bc', m).value, active_from: $('#ba', m).value, archived: $('#bar', m).checked }); closeModal(); refreshPage(); } catch (x) { $('#berr', m).textContent = x.message; $('#berr', m).classList.remove('hidden'); } } });
  const pform = p => modal(`<h2>${p ? 'Edit proxy list' : 'Add proxy list'}</h2><div class="fld"><label class="f">Name</label><input class="inp" id="pn" value="${esc(p ? p.name : '')}"></div><div class="col2"><div class="fld"><label class="f">Cost ($)</label><input class="inp" id="pc" value="${p ? p.cost : ''}"></div><div class="fld"><label class="f">Active from</label><input type="date" class="inp" id="pa" value="${esc(p ? p.active_from : '')}"></div></div>
     <label class="tog"><span class="sw"><input type="checkbox" id="par" ${p && p.archived ? 'checked' : ''}><i></i></span>Archived</label><div class="err hidden" id="perr"></div><div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="psv">Save</button></div>`,
     { onMount: m => $('#psv', m).onclick = async () => { try { await api('/api/arsenal/proxies/save', { id: p && p.id, name: $('#pn', m).value, cost: $('#pc', m).value, active_from: $('#pa', m).value, archived: $('#par', m).checked }); closeModal(); refreshPage(); } catch (x) { $('#perr', m).textContent = x.message; $('#perr', m).classList.remove('hidden'); } } });
  const nform = n => modal(`<h2>${n ? 'Edit mapping' : 'Add mapping'}</h2><p>Posts from this webhook name will be attributed to the bot and/or proxy list below.</p><div class="fld"><label class="f">Webhook name</label><input class="inp" id="nw" value="${esc(n ? n.webhook_name : '')}"></div><div class="col2"><div class="fld"><label class="f">Bot</label><input class="inp" id="nb" list="nbl" value="${esc(n ? n.bot : '')}"><datalist id="nbl">${d.bots.map(b => `<option>${esc(b.name)}`).join('')}</datalist></div><div class="fld"><label class="f">Proxy list</label><input class="inp" id="np" list="npl" value="${esc(n ? n.proxy_list : '')}"><datalist id="npl">${d.proxy_lists.map(b => `<option>${esc(b.name)}`).join('')}</datalist></div></div>
     <div class="err hidden" id="nerr"></div><div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="nsv">Save</button></div>`,
     { onMount: m => $('#nsv', m).onclick = async () => { try { const r = await api('/api/arsenal/names/save', { id: n && n.id, webhook_name: $('#nw', m).value, bot: $('#nb', m).value, proxy_list: $('#np', m).value }); closeModal(); toast(r.reattributed ? `Saved — re-attributed ${r.reattributed} checkout${r.reattributed === 1 ? '' : 's'}` : 'Saved'); refreshPage(); } catch (x) { $('#nerr', m).textContent = x.message; $('#nerr', m).classList.remove('hidden'); } } });
  $('#b-add').onclick = () => bform(); $('#p-add').onclick = () => pform(); $('#n-add').onclick = () => nform();
  $$('.item[data-k]', v).forEach(r => {
    const k = r.dataset.k, id = +r.dataset.id, rec = (k === 'bot' ? d.bots : k === 'proxy' ? d.proxy_lists : d.name_maps).find(x => x.id === id);
    $('[data-e]', r).onclick = () => (k === 'bot' ? bform : k === 'proxy' ? pform : nform)(rec);
    $('[data-d]', r).onclick = async () => { if (await confirmBox('Delete ' + (rec.name || rec.webhook_name) + '?', k === 'name' ? 'New posts will no longer be re-attributed.' : 'Checkouts keep the name they already have. To keep history but hide it, archive it instead.', 'Delete', true)) { await act(() => api('/api/arsenal/remove', { kind: k, id })); refreshPage(); } };
  });
};

/* ================================================================ Settings */
PAGES.settings = async function (v) {
  const T = S.tok;
  const s = await api('/api/settings'), L = s.license;
  if (T !== S.tok) return;
  const kinds = s.exception_kinds;
  const exp = L.expires ? new Date(L.expires * 1000).toLocaleDateString() : 'never';
  v.innerHTML = `<div class="page" style="max-width:1100px"><div class="ph"><div><h1>Settings</h1><p>Demented Toolbox ${esc(s.version)} · build ${s.build}</p></div></div>
   <div class="card"><h3>Updates</h3><p>Updates are checked and installed from within the app. Your tracking data is never touched by an update.</p><div class="row"><button class="btn" id="s-upd">Check for updates</button><button class="btn ghost sm" id="s-tok">${s.has_github_token ? 'Change' : 'Add'} GitHub token</button></div>${s.update_repo ? '' : '<div class="note" style="margin-top:10px">This copy isn\'t linked to a release feed yet.</div>'}</div>
   <div class="card"><h3>Discord status</h3><p>Shows <b>Playing Demented Toolbox</b> on your Discord profile while the app is open, with how long it's been running. Needs the Discord desktop app on the same machine — the browser version can't be reached.</p>
     <label class="tog" style="margin-bottom:12px"><span class="sw"><input type="checkbox" id="pr-en" ${s.presence.enabled ? 'checked' : ''}><i></i></span>Show Demented Toolbox on my Discord profile</label>
     <label class="tog" style="margin-bottom:14px"><span class="sw"><input type="checkbox" id="pr-ct" ${s.presence.counts ? 'checked' : ''}><i></i></span>Include my order counts</label>
     <div class="fld" style="max-width:420px"><label class="f">Discord application ID</label><input class="inp" id="pr-id" placeholder="From discord.com/developers → your app → General Information" value="${esc(s.presence.client_id || '')}"></div>
     <div class="note">${esc(s.presence.note)}</div></div>
   <div class="card"><h3>Send logs for support</h3><p>Saves a text file describing what the app has seen — useful when an order isn't picked up. Email subjects are never included. Hiding email addresses additionally replaces them with labels like <code>account1</code> and strips webhook URLs and password-style values, so the file stays readable without exposing your inboxes.</p>
     <div class="row"><label class="tog"><span class="sw"><input type="checkbox" id="lg-h" checked><i></i></span>Hide email addresses</label><button class="btn p" id="lg-go">Export logs…</button></div></div>
   <div class="card"><h3>Backup and move to another computer</h3><p>Export everything to a single file, then import it on the new machine. Email passwords, your Discord bot token and webhook URLs are only included if you set a passphrase.</p>
     <div class="row wrap"><label class="tog"><span class="sw"><input type="checkbox" id="bk-pw"><i></i></span>Include email passwords</label><input class="inp hidden" id="bk-ph" type="password" placeholder="Passphrase (6+ characters)" style="width:260px"><button class="btn p" id="bk-ex">Export backup</button><button class="btn" id="bk-im">Import backup…</button></div></div>
   <div class="card"><h3>This device</h3><p>Shown to you if you sign in somewhere else. Your license can be active on one computer at a time.</p>
     <label class="f">Device name</label><div class="row"><input class="inp" id="dv-n" value="${esc(s.device_name)}"><button class="btn" id="dv-s">Save</button><button class="btn ghost" id="dv-o">Sign out</button></div>
     <div class="note" style="margin-top:10px">Signed in as ${esc(L.user)} · ${esc(L.plan)} license${L.hint ? ' …' + esc(L.hint) : ''} · expires ${exp}. Signing out keeps your tracking data on this computer.</div></div>
   <div class="card"><h3>Delivery updates</h3><p>When a retailer doesn't email a shipping update, Demented Toolbox can check the carrier instead. To do that it sends only the parcel's tracking number to 17TRACK, a tracking provider, using your own free API key. Nothing else about your orders is sent.</p>
     <div class="row wrap"><label class="tog"><span class="sw"><input type="checkbox" id="dl-en" ${s.delivery.enabled ? 'checked' : ''}><i></i></span>Check carriers for delivery updates</label><input class="inp" id="dl-k" type="password" style="width:280px" placeholder="${s.delivery.has_key ? '17TRACK key saved — type to replace' : '17TRACK API key'}"><button class="btn" id="dl-s">Save</button><button class="btn" id="dl-r" ${s.delivery.has_key ? '' : 'disabled'}>Check now</button></div>
     ${s.delivery.last || s.delivery.error ? `<div class="note" style="margin-top:10px">${s.delivery.error ? esc(s.delivery.error) : 'Last checked ' + fdt(s.delivery.last)}</div>` : ''}</div>
   <div class="card"><h3>Deleted orders</h3><p>Orders you delete stay hidden, even if their emails are scanned again. Restore one to let it come back on the next backfill.</p>
     ${s.deleted_orders.length ? s.deleted_orders.map(o => `<div class="item"><div><div class="t">${esc(o.retailer)} · <span class="mono">${esc(o.order_number)}</span></div><div class="s">${esc(o.product || '')} ${o.total ? money(o.total) : ''} · deleted ${fdate(o.deleted_at)}</div></div><div class="r"><button class="btn sm" data-rest="${o.id}">Restore</button></div></div>`).join('') + '<button class="btn sm ghost" id="dd-purge">Forget all</button>' : '<div class="note">Nothing hidden.</div>'}</div>
   <div class="card"><h3>Exceptions</h3><p>Emails you tell the app to ignore. They are no longer picked up as orders. Removing one only affects emails from now on; it never brings back an order you deleted.</p>
     ${s.exceptions.length ? s.exceptions.map(e => `<div class="item"><div><div class="t">${esc(e.value)}</div><div class="s">${esc(kinds[e.kind] || e.kind)}</div></div><div class="r"><button class="btn sm ghost" data-xr="${e.id}">Remove</button></div></div>`).join('') : '<div class="note mark" style="margin-bottom:14px">No exceptions.</div>'}
     <div class="row wrap" style="align-items:flex-end;margin-top:6px"><div style="flex:1;min-width:220px"><label class="f">Ignore</label><select class="sel" id="ex-k">${Object.entries(kinds).map(([k, l]) => `<option value="${k}">${esc(l)}</option>`).join('')}</select></div><div style="flex:2;min-width:260px"><label class="f">Email address or website</label><input class="inp" id="ex-v"></div><button class="btn" id="ex-a" style="padding:10px 22px">Add</button></div></div>
   <div class="card red"><h3>Reset tracker data</h3><p>Deletes every tracked order, its history, and activity, then starts fresh. Email accounts, passwords, webhooks, and your deleted-orders list are kept. Use Backfill all afterwards to pull orders in again — useful after a parser update.</p>
     <label class="f">Type <b style="color:var(--text)">reset</b> to confirm</label><div class="row"><input class="inp" id="rt-c" style="max-width:400px"><button class="btn danger" id="rt-go" disabled>Delete all tracked orders</button></div></div>
   <div class="card"><h3>Arsenal: deleted checkouts</h3><p>Checkouts you delete stay hidden, even if their channel is re-scanned. Restoring lets every one of them come back on the next backfill or rescan.</p>
     ${s.deleted_checkouts.length ? `<div class="note" style="margin-bottom:12px">${s.deleted_checkouts.length} hidden checkout${s.deleted_checkouts.length === 1 ? '' : 's'}.</div><div class="row"><button class="btn" id="dc-r">Restore all</button><button class="btn ghost" id="dc-p">Forget all</button></div>` : '<div class="note">Nothing hidden.</div>'}</div>
   <div class="card red"><h3>Reset Arsenal data</h3><p>Deletes every checkout, bot, proxy list, name mapping, linked server and channel, then starts fresh. Order Tracker data is never touched. Re-link your servers and channels afterwards to start scraping again.</p>
     <label class="f">Type <b style="color:var(--text)">reset</b> to confirm</label><div class="row"><input class="inp" id="ra-c" style="max-width:400px"><button class="btn danger" id="ra-go" disabled>Delete all Arsenal data</button></div></div>
   <div class="card red"><h3>Fresh start</h3><p>Erases everything in the app — orders, email accounts, webhooks, checkouts, settings — and leaves it like a new install. Your license stays signed in.</p>
     <label class="f">Type <b style="color:var(--text)">FRESH START</b> to confirm</label><div class="row"><input class="inp" id="fs-c" style="max-width:400px"><button class="btn danger" id="fs-go" disabled>Erase everything</button></div></div></div>`;
  const post = (p, b, m) => act(() => api(p, b), m);
  $('#s-upd').onclick = checkUpdates;
  $('#s-tok').onclick = () => modal(`<h2>GitHub token</h2><p>Only needed if the release repository is private. It needs read access to the repository's contents.</p><div class="fld"><input class="inp" id="gt" type="password" placeholder="ghp_…"></div><div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="gts">Save</button></div>`, { onMount: m => $('#gts', m).onclick = async () => { await post('/api/update/token', { token: $('#gt', m).value }, 'Saved'); closeModal(); refreshPage(); } });
  const pres = () => post('/api/settings/presence', { enabled: $('#pr-en').checked, counts: $('#pr-ct').checked, client_id: $('#pr-id').value });
  $('#pr-en').onchange = pres; $('#pr-ct').onchange = pres; $('#pr-id').onchange = pres;
  $('#lg-go').onclick = async e => { const r = await busy(e.currentTarget, () => post('/api/logs/export', { hide_emails: $('#lg-h').checked })); if (r) { toast('Saved to ' + r.path); api('/api/open_folder', {}); } };
  $('#bk-pw').onchange = e => $('#bk-ph').classList.toggle('hidden', !e.target.checked);
  $('#bk-ex').onclick = async e => { const r = await busy(e.currentTarget, () => post('/api/backup/export', { include_passwords: $('#bk-pw').checked, passphrase: $('#bk-ph').value })); if (r) { toast('Backup saved to ' + r.path + (r.encrypted ? ' (encrypted)' : '')); api('/api/open_folder', {}); } };
  $('#bk-im').onclick = async () => {
    const f = (await pickFiles('.json', false))[0]; if (!f) return; const text = await readText(f); let pw = '';
    let info; try { info = await api('/api/backup/inspect', { text }); } catch (e) { return toast(e.message, true); }
    const run = async () => { const r = await act(() => api('/api/backup/import', { text, passphrase: pw })); if (r) { closeModal(); toast(`Restored ${r.rows} records`); pollShell(); go('tracking', true); } };
    modal(`<h2>Import backup?</h2><p>This <b>replaces</b> the orders, accounts, webhooks and checkouts on this computer with the ones in the file. Your license and device name are kept.</p>${info.encrypted ? '<div class="fld"><label class="f">Passphrase</label><input class="inp" id="ip" type="password"></div>' : ''}<div class="err hidden" id="ierr"></div><div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="igo">Replace and import</button></div>`,
      { onMount: m => $('#igo', m).onclick = async () => { pw = info.encrypted ? $('#ip', m).value : ''; try { const r = await api('/api/backup/import', { text, passphrase: pw }); closeModal(); toast(`Restored ${r.rows} records`); pollShell(); go('tracking', true); } catch (x) { $('#ierr', m).textContent = x.message; $('#ierr', m).classList.remove('hidden'); } } });
  };
  $('#dv-s').onclick = () => post('/api/license/device', { name: $('#dv-n').value }, 'Saved');
  $('#dv-o').onclick = async () => { if (await confirmBox('Sign out?', 'The license is released so you can use it on another computer. Your tracking data stays here.', 'Sign out')) { await api('/api/license/signout', {}); location.reload(); } };
  $('#dl-s').onclick = async () => { if (await post('/api/settings/delivery', { enabled: $('#dl-en').checked, key: $('#dl-k').value }, 'Saved')) refreshPage(); };
  $('#dl-r').onclick = async () => { await post('/api/delivery/refresh', {}, 'Checking carriers…'); setTimeout(refreshPage, 4000); };
  $$('[data-rest]', v).forEach(b => b.onclick = async () => { await post('/api/deleted_orders/restore', { id: +b.dataset.rest }, 'Restored — run Backfill to bring it back'); refreshPage(); });
  const dp = $('#dd-purge'); if (dp) dp.onclick = async () => { await post('/api/deleted_orders/purge', {}); refreshPage(); };
  $$('[data-xr]', v).forEach(b => b.onclick = async () => { await post('/api/exceptions/remove', { id: +b.dataset.xr }); refreshPage(); });
  $('#ex-a').onclick = async () => { if (await post('/api/exceptions/add', { kind: $('#ex-k').value, value: $('#ex-v').value }, 'Added')) refreshPage(); };
  const arm = (inp, btn, word, fn) => { const i = $(inp), b = $(btn); i.oninput = () => b.disabled = i.value.trim().toLowerCase() !== word.toLowerCase(); b.onclick = fn; };
  arm('#rt-c', '#rt-go', 'reset', async () => { const r = await post('/api/reset/tracker', { confirm: $('#rt-c').value }); if (r) { toast(`Removed ${r.removed} records. Use Backfill all to pull orders in again.`); pollShell(); refreshPage(); } });
  arm('#ra-c', '#ra-go', 'reset', async () => { const r = await post('/api/reset/arsenal', { confirm: $('#ra-c').value }); if (r) { toast(`Removed ${r.removed} records.`); refreshPage(); } });
  arm('#fs-c', '#fs-go', 'fresh start', async () => { const r = await post('/api/fresh_start', { confirm: $('#fs-c').value }); if (r) { toast(`Erased ${r.removed} records.`); pollShell(); refreshPage(); } });
  const r1 = $('#dc-r'); if (r1) r1.onclick = async () => { await post('/api/arsenal/checkouts/restore', {}, 'Restored'); refreshPage(); };
  const p1 = $('#dc-p'); if (p1) p1.onclick = async () => { await post('/api/arsenal/checkouts/purge', {}); refreshPage(); };
};
