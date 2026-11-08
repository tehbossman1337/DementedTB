/* Profiles & site accounts (own design; Valor-compatible import/export) */
const vstate = { blur: store.get('blur', false), view: store.get('pview', 'cards'), gp: store.get('gp', ''), ga: store.get('ga', ''), sel: new Set(), q: '' };
const fi = (id, label, val = '', type = 'text', ph = '') => `<div class="fld"><label class="f">${label}</label><input class="inp" id="${id}" type="${type}" value="${esc(val)}" placeholder="${esc(ph)}" autocomplete="off"></div>`;
const maskCard = n => { n = String(n || '').replace(/\D/g, ''); return n ? '•••• •••• •••• ' + n.slice(-4) : 'No card saved'; };
const addrLines = a => [[a.firstName, a.lastName].filter(Boolean).join(' '), a.addressLine1, a.addressLine2, [a.city, a.state, a.zipCode].filter(Boolean).join(', '), a.countryName].filter(Boolean).map(esc).join('<br>') || '<span class="muted">—</span>';
const pickFile = (accept = '.json,application/json') => new Promise(res => { const i = document.createElement('input'); i.type = 'file'; i.accept = accept; i.onchange = () => { const f = i.files[0]; if (!f) return res(null); const r = new FileReader(); r.onload = () => res({ name: f.name, text: r.result }); r.readAsText(f); }; i.click(); });
const flip = (v, key) => { vstate.sel.clear(); vstate[key] = v; };

function groupBar(kind, groups, counts, cur, rerender) {
  const chips = groups.map(g => `<button class="gchip ${g === cur ? 'on' : ''}" data-g="${esc(g)}">${esc(g)} <em>${counts[g] || 0}</em></button>`).join('');
  return `<div class="gbar">${chips || '<span class="note">No groups yet — a group is a website, for example “Pokemon Center”.</span>'}<button class="btn sm" id="g-add">+ New group</button>${cur ? '<button class="btn sm ghost" id="g-more">Rename / delete</button>' : ''}</div>`;
}
function groupHandlers(v, kind, cur, setCur, rerender) {
  $$('[data-g]', v).forEach(b => b.onclick = () => { setCur(b.dataset.g); vstate.sel.clear(); rerender(); });
  $('#g-add', v).onclick = () => modal(`<h2>New group</h2><p>A group is a website. Profiles or accounts live inside one.</p>${fi('gn', 'Group name', '', 'text', 'e.g. Pokemon Center')}<div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="gok">Create</button></div>`,
    { onMount: m => { $('#gn', m).focus(); $('#gok', m).onclick = async () => { const r = await act(() => api('/api/vault/group', { kind, op: 'add', name: $('#gn', m).value })); if (r) { closeModal(); setCur(r.name); rerender(); } }; } });
  const mo = $('#g-more', v);
  if (mo) mo.onclick = e => menu(e, [
    { label: 'Rename group', fn: () => modal(`<h2>Rename group</h2>${fi('gn', 'New name', cur)}<div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="gok">Rename</button></div>`,
      { onMount: m => $('#gok', m).onclick = async () => { const r = await act(() => api('/api/vault/group', { kind, op: 'rename', old: cur, name: $('#gn', m).value })); if (r) { closeModal(); setCur(r.name); rerender(); } } }) },
    { label: 'Delete group and everything in it', cls: 'danger', fn: async () => { if (await confirmBox('Delete “' + cur + '”?', 'This removes the group and every ' + (kind === 'prof' ? 'profile' : 'account') + ' inside it. Export first if you might want them back.', 'Delete', true)) { const r = await act(() => api('/api/vault/group', { kind, op: 'delete', name: cur })); if (r) { setCur(''); vstate.sel.clear(); rerender(); } } } }]);
}
const sensClick = v => $$('.sens', v).forEach(e => e.onclick = ev => { if (vstate.blur && !e.classList.contains('rev')) { e.classList.add('rev'); ev.stopPropagation(); } });
const exportDone = r => { toast(`Saved ${r.count} to ${r.path}`); api('/api/open_folder', {}); };

/* ============================ PROFILES ============================ */
PAGES.profiles = async function (v) {
  const T = S.tok;
  const d = await api('/api/vault');
  if (T !== S.tok) return;
  const groups = d.groups.prof;
  if (!groups.includes(vstate.gp)) vstate.gp = groups[0] || '';
  const counts = {}; d.profiles.forEach(p => counts[p.site] = (counts[p.site] || 0) + 1);
  const all = d.profiles.filter(p => p.site === vstate.gp);
  const roots = all.filter(p => !p.parent_id);
  const q = vstate.q.toLowerCase();
  const rows = all.filter(p => !q || JSON.stringify([p.rec.name, p.rec.email, p.rec.shipping.addressLine1, p.rec.shipping.city, p.rec.card.holder]).toLowerCase().includes(q));
  const byId = Object.fromEntries(d.profiles.map(p => [p.id, p]));
  vstate.sel = new Set([...vstate.sel].filter(i => byId[i]));
  v.innerHTML = `<div class="page vwrap ${vstate.blur ? 'blurred' : ''}"><div class="ph"><div><h1>Profiles</h1><p>Checkout identities — contact, card and addresses — kept per website. Import your existing file, edit anything, make address variants, and export it back. Everything stays on this computer.</p></div>
    <div class="acts"><button class="btn" id="p-blur">${vstate.blur ? 'Blur: on' : 'Blur: off'}</button><button class="btn" id="p-imp">Import file</button><button class="btn" id="p-exp" ${all.length ? '' : 'disabled'}>Export</button><button class="btn p" id="p-add" ${vstate.gp ? '' : 'disabled'}>Add profile</button></div></div>
    ${groupBar('prof', groups, counts, vstate.gp)}
    ${vstate.gp ? `<div class="filters"><input class="inp" id="p-q" style="max-width:320px" placeholder="Search name, email, address…" value="${esc(vstate.q)}"><div class="seg" style="margin:0"><button data-view="cards" class="${vstate.view === 'cards' ? 'on' : ''}">Cards</button><button data-view="table" class="${vstate.view === 'table' ? 'on' : ''}">Table</button></div>
      <span class="note">${roots.length} profile${roots.length === 1 ? '' : 's'}${all.length > roots.length ? ` + ${all.length - roots.length} address variants` : ''}</span><span class="grow"></span><button class="btn sm" id="p-selall">${rows.length && rows.every(p => vstate.sel.has(p.id)) ? 'Clear selection' : 'Select all shown'}</button></div>
    <div id="p-bulk"></div><div id="p-list"></div>` : ''}</div>`;
  const rerender = () => { if (T === S.tok) refreshPage(); };
  groupHandlers(v, 'prof', vstate.gp, g => { vstate.gp = g; store.set('gp', g); }, rerender);
  $('#p-blur').onclick = () => { vstate.blur = !vstate.blur; store.set('blur', vstate.blur); refreshPage(); };
  $('#p-imp').onclick = () => importProfiles(groups, vstate.gp, rerender);
  $('#p-exp').onclick = () => menu({ currentTarget: $('#p-exp'), stopPropagation() { } }, [
    { label: `Everything in “${vstate.gp}”`, fn: async () => { const r = await act(() => api('/api/profiles/export', { site: vstate.gp })); r && exportDone(r); } },
    { label: vstate.sel.size ? `Only the ${vstate.sel.size} selected` : 'Only selected (select some first)', fn: async () => { if (!vstate.sel.size) return toast('Tick some profiles first', true); const r = await act(() => api('/api/profiles/export', { ids: [...vstate.sel] })); r && exportDone(r); } },
    { label: 'Every group', fn: async () => { const r = await act(() => api('/api/profiles/export', {})); r && exportDone(r); } }]);
  $('#p-add').onclick = () => profileModal(null, groups, vstate.gp, rerender);
  if (!vstate.gp) return;
  $('#p-q').oninput = e => { vstate.q = e.target.value; drawList(); const el = $('#p-q'); el.focus(); el.setSelectionRange(el.value.length, el.value.length); };
  $$('[data-view]', v).forEach(b => b.onclick = () => { vstate.view = b.dataset.view; store.set('pview', vstate.view); refreshPage(); });
  $('#p-selall').onclick = () => { const every = rows.length && rows.every(p => vstate.sel.has(p.id)); rows.forEach(p => every ? vstate.sel.delete(p.id) : vstate.sel.add(p.id)); drawList(); };
  function bulk() {
    const n = vstate.sel.size; const box = $('#p-bulk');
    box.innerHTML = n ? `<div class="bulk"><b>${n} selected</b><button class="btn sm" data-b="addr">Change address…</button><button class="btn sm" data-b="flags">Set options…</button><button class="btn sm" data-b="move">Move to group…</button><button class="btn sm" data-b="exp">Export selected</button><button class="btn sm danger" data-b="del">Delete</button><button class="btn sm ghost" data-b="clr">Clear</button></div>` : '';
    $$('[data-b]', box).forEach(b => b.onclick = async () => {
      const ids = [...vstate.sel], k = b.dataset.b;
      if (k === 'clr') { vstate.sel.clear(); drawList(); }
      if (k === 'exp') { const r = await act(() => api('/api/profiles/export', { ids })); r && exportDone(r); }
      if (k === 'del') { if (await confirmBox(`Delete ${ids.length} profile${ids.length === 1 ? '' : 's'}?`, 'Their address variants go with them.', 'Delete', true)) { await act(() => api('/api/profiles/delete', { ids }), 'Deleted'); vstate.sel.clear(); rerender(); } }
      if (k === 'addr') addressModal(ids, rerender);
      if (k === 'move') modal(`<h2>Move ${ids.length} to…</h2><div class="fld"><select class="sel" id="mv">${groups.map(g => `<option ${g === vstate.gp ? 'selected' : ''}>${esc(g)}</option>`).join('')}</select></div><div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="mvg">Move</button></div>`, { onMount: m => $('#mvg', m).onclick = async () => { await act(() => api('/api/profiles/move', { ids, site: $('#mv', m).value }), 'Moved'); closeModal(); vstate.sel.clear(); rerender(); } });
      if (k === 'flags') modal(`<h2>Options for ${ids.length} profile${ids.length === 1 ? '' : 's'}</h2><p>Only the ones you choose change.</p>
        <div class="fld"><label class="f">One checkout</label><select class="sel" id="f1"><option value="">Leave as is</option><option value="1">On</option><option value="0">Off</option></select></div>
        <div class="fld"><label class="f">Quick task</label><select class="sel" id="f2"><option value="">Leave as is</option><option value="1">On</option><option value="0">Off</option></select></div>
        <div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="fok">Apply</button></div>`, { onMount: m => $('#fok', m).onclick = async () => { const ch = {}; if ($('#f1', m).value) ch.oneCheckout = $('#f1', m).value === '1'; if ($('#f2', m).value) ch.quickTask = $('#f2', m).value === '1'; if (!Object.keys(ch).length) return closeModal(); await act(() => api('/api/profiles/patch', { ids, changes: ch }), 'Updated'); closeModal(); rerender(); } });
    });
  }
  function cardHtml(p) {
    const r = p.rec, c = r.card || {}, same = r.billingSameAsShipping;
    return `<div class="pcard ${vstate.sel.has(p.id) ? 'sel' : ''}" data-id="${p.id}"><div class="top"><input type="checkbox" class="ck" ${vstate.sel.has(p.id) ? 'checked' : ''}><div style="min-width:0"><div class="nm">${esc(r.name || 'Unnamed')}${p.parent_id ? '<span class="tag">variant</span>' : ''}</div><div class="em sens">${esc(r.email) || '—'}${r.phoneNumber ? ' · ' + esc(r.phoneNumber) : ''}</div></div>
      <div class="acts"><button class="btn sm" data-a="edit">Edit</button>${p.parent_id ? '' : '<button class="btn sm" data-a="jig">Rejig</button>'}<button class="iconbtn" data-a="more" style="width:30px;height:30px">${icon('dots', 18)}</button></div></div>
      <div class="ccard"><span class="ty">${esc(c.type || 'card')}</span><div class="num sens">${esc(maskCard(c.number))}</div><div class="meta"><span class="sens">${esc(c.holder) || '—'}</span><span class="sens">${esc(c.expiration) || '--/--'}</span></div></div>
      <div class="addrs"><div><div class="cardt">Ship to</div><div class="addr sens">${addrLines(r.shipping)}</div></div><div><div class="cardt">Bill to</div><div class="addr sens">${same ? '<span class="muted">Same as shipping</span>' : addrLines(r.billing)}</div></div></div>
      ${r.oneCheckout || r.quickTask || r.totalSpent ? `<div class="flags">${r.oneCheckout ? '<span>One checkout</span>' : ''}${r.quickTask ? '<span>Quick task</span>' : ''}${r.totalSpent ? `<span>Spent ${money(r.totalSpent)}</span>` : ''}</div>` : ''}</div>`;
  }
  function rowHtml(p) {
    const r = p.rec, c = r.card || {};
    return `<tr data-id="${p.id}" class="${vstate.sel.has(p.id) ? 'sel' : ''}"><td><input type="checkbox" class="ck" ${vstate.sel.has(p.id) ? 'checked' : ''}></td><td><b>${esc(r.name)}</b>${p.parent_id ? '<span class="tag">variant</span>' : ''}</td><td class="sens">${esc(r.email)}</td><td class="sens">${esc(r.shipping.addressLine1)} ${esc(r.shipping.addressLine2)}</td><td>${esc(r.shipping.city)}, ${esc(r.shipping.state)} ${esc(r.shipping.zipCode)}</td><td class="sens">${esc(c.type)} ${c.number ? '•••• ' + esc(String(c.number).slice(-4)) : ''}</td><td>${r.oneCheckout ? 'One checkout ' : ''}${r.quickTask ? 'Quick task' : ''}</td></tr>`;
  }
  function drawList() {
    const L = $('#p-list');
    if (!rows.length) { L.innerHTML = `<div class="empty"><b>${all.length ? 'Nothing matches that search' : 'No profiles in ' + esc(vstate.gp) + ' yet'}</b>${all.length ? '' : 'Import your file or add one by hand.'}${all.length ? '' : '<br><button class="btn p" id="p-e1">Import file</button>'}</div>`; const e = $('#p-e1'); if (e) e.onclick = () => importProfiles(groups, vstate.gp, rerender); bulk(); return; }
    L.innerHTML = vstate.view === 'cards' ? `<div class="pgrid">${rows.map(cardHtml).join('')}</div>` : `<div class="tbl-wrap"><table class="t"><thead><tr><th style="width:34px"></th><th>Name</th><th>Email</th><th>Street</th><th>City</th><th>Card</th><th>Options</th></tr></thead><tbody>${rows.map(rowHtml).join('')}</tbody></table></div>`;
    $$('[data-id]', L).forEach(el => {
      const p = byId[el.dataset.id];
      $('.ck', el).onclick = e => { e.stopPropagation(); e.target.checked ? vstate.sel.add(p.id) : vstate.sel.delete(p.id); el.classList.toggle('sel', e.target.checked); bulk(); };
      if (el.tagName === 'TR') el.onclick = () => profileModal(p, groups, vstate.gp, rerender);
      $$('[data-a]', el).forEach(b => b.onclick = ev => {
        ev.stopPropagation(); const a = b.dataset.a;
        if (a === 'edit') profileModal(p, groups, vstate.gp, rerender);
        if (a === 'jig') rejigModal(p, rerender);
        if (a === 'more') menu(ev, [
          { label: 'Duplicate', fn: async () => { const rec = JSON.parse(JSON.stringify(p.rec)); rec.id = ''; rec.name += ' copy'; await act(() => api('/api/profiles/save', { site: p.site, rec }), 'Duplicated'); rerender(); } },
          { label: 'Delete', cls: 'danger', fn: async () => { if (await confirmBox('Delete “' + p.rec.name + '”?', p.parent_id ? '' : 'Its address variants go too.', 'Delete', true)) { await act(() => api('/api/profiles/delete', { ids: [p.id] }), 'Deleted'); rerender(); } } }]);
      });
    });
    sensClick(L); bulk();
  }
  drawList();
};

async function importProfiles(groups, cur, done) {
  modal(`<h2>Import profiles</h2><p>Choose a profiles file (JSON). Every field in it is kept, including ones this app doesn't show, so you can export it back unchanged.</p>
    <div class="fld"><label class="f">Import into group</label><select class="sel" id="ig">${groups.map(g => `<option ${g === cur ? 'selected' : ''}>${esc(g)}</option>`).join('')}<option value="__new">New group…</option></select></div>
    <div class="fld hidden" id="ign">${fi('ignv', 'New group name')}</div>
    <label class="tog" style="margin-bottom:6px"><span class="sw"><input type="checkbox" id="irep"><i></i></span>Replace what's already in the group</label>
    <div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="ipick">Choose file…</button></div>`, {
    onMount: m => {
      $('#ig', m).onchange = e => $('#ign', m).classList.toggle('hidden', e.target.value !== '__new');
      $('#ipick', m).onclick = async () => {
        let site = $('#ig', m).value;
        if (site === '__new') { const g = await act(() => api('/api/vault/group', { kind: 'prof', op: 'add', name: $('#ignv', m).value })); if (!g) return; site = g.name; }
        const f = await pickFile(); if (!f) return;
        const r = await act(() => api('/api/profiles/import', { site, text: f.text, replace: $('#irep', m).checked }));
        if (r) { closeModal(); vstate.gp = site; store.set('gp', site); toast(`Imported ${r.total}: ${r.added} new, ${r.updated} updated`); done(); }
      };
    }
  });
}

function profileModal(p, groups, cur, done) {
  const r = p ? JSON.parse(JSON.stringify(p.rec)) : { name: '', email: '', phoneNumber: '', billingSameAsShipping: true, oneCheckout: false, quickTask: false, card: {}, shipping: { countryCode: 'US', countryName: 'United States' }, billing: { countryCode: 'US', countryName: 'United States' } };
  const A = (pre, a) => `<div class="col2">${fi(pre + 'fn', 'First name', a.firstName)}${fi(pre + 'ln', 'Last name', a.lastName)}</div>${fi(pre + 'a1', 'Address line 1', a.addressLine1)}${fi(pre + 'a2', 'Address line 2', a.addressLine2)}<div class="col3">${fi(pre + 'ci', 'City', a.city)}${fi(pre + 'st', 'State', a.state)}${fi(pre + 'zp', 'ZIP / postcode', a.zipCode)}</div>${fi(pre + 'co', 'Country code', a.countryCode || 'US')}`;
  const read = (pre, base) => ({ ...base, firstName: $('#' + pre + 'fn').value, lastName: $('#' + pre + 'ln').value, addressLine1: $('#' + pre + 'a1').value, addressLine2: $('#' + pre + 'a2').value, city: $('#' + pre + 'ci').value, state: $('#' + pre + 'st').value, zipCode: $('#' + pre + 'zp').value, countryCode: $('#' + pre + 'co').value.toUpperCase(), countryName: base.countryName });
  modal(`<h2>${p ? 'Edit profile' : 'Add profile'}</h2>
    <div class="fsec">Profile</div><div class="col2">${fi('pn', 'Profile name', r.name)}<div class="fld"><label class="f">Group</label><select class="sel" id="pg">${groups.map(g => `<option ${g === (p ? p.site : cur) ? 'selected' : ''}>${esc(g)}</option>`).join('')}</select></div></div>
    <div class="col2">${fi('pe', 'Email', r.email, 'email')}${fi('pp', 'Phone', r.phoneNumber)}</div>
    <div class="fsec">Card</div><div class="col2">${fi('ch', 'Name on card', r.card.holder)}${fi('cn', 'Card number', r.card.number, 'text', '•••• •••• •••• ••••')}</div><div class="col2">${fi('ce', 'Expiry (MM/YY)', r.card.expiration)}${fi('cv', 'CVV', r.card.cvv)}</div>
    <div class="fsec">Shipping address</div>${A('s', r.shipping)}
    <label class="tog" style="margin:4px 0 12px"><span class="sw"><input type="checkbox" id="bs" ${r.billingSameAsShipping ? 'checked' : ''}><i></i></span>Billing is the same as shipping</label>
    <div id="bill" class="${r.billingSameAsShipping ? 'hidden' : ''}"><div class="fsec">Billing address</div>${A('b', r.billing)}</div>
    <div class="fsec">Options</div><div class="row wrap" style="gap:22px;margin-bottom:6px"><label class="tog"><span class="sw"><input type="checkbox" id="oc" ${r.oneCheckout ? 'checked' : ''}><i></i></span>One checkout</label><label class="tog"><span class="sw"><input type="checkbox" id="qt" ${r.quickTask ? 'checked' : ''}><i></i></span>Quick task</label></div>
    <div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="psv">Save</button></div>`, {
    wide: true, onMount: m => {
      $('#bs', m).onchange = e => $('#bill', m).classList.toggle('hidden', e.target.checked);
      $('#psv', m).onclick = async () => {
        const rec = { ...r, name: $('#pn', m).value.trim(), email: $('#pe', m).value.trim(), phoneNumber: $('#pp', m).value.trim(), billingSameAsShipping: $('#bs', m).checked, oneCheckout: $('#oc', m).checked, quickTask: $('#qt', m).checked,
          card: { ...r.card, holder: $('#ch', m).value, number: $('#cn', m).value.replace(/[^\d]/g, '') || $('#cn', m).value, expiration: $('#ce', m).value, cvv: $('#cv', m).value, type: '' },
          shipping: read('s', r.shipping), billing: $('#bs', m).checked ? r.billing : read('b', r.billing) };
        if (rec.card.number === (r.card.number || '')) rec.card.type = r.card.type || '';
        const res = await act(() => api('/api/profiles/save', { site: $('#pg', m).value, rec, id: p ? p.id : undefined }), 'Saved');
        if (res) { closeModal(); vstate.gp = $('#pg', m).value; done(); }
      };
    }
  });
}

function rejigModal(p, done) {
  const n = (p.rec.name || '').trim();
  modal(`<h2>Rejig “${esc(n)}”</h2><p>Makes alternate spellings of the shipping address — street suffix, directions, punctuation and optional unit lines. Street number, street, city, state and ZIP never change, so they still deliver to the same place.</p>
    <div class="col2">${fi('jc', 'How many', '10', 'number')}${fi('js', 'Seed (optional — repeat the same set)')}</div>
    <label class="tog" style="margin-bottom:10px"><span class="sw"><input type="checkbox" id="ju" checked><i></i></span>Add unit lines (Apt, Unit, #…)</label>
    <label class="tog" style="margin-bottom:10px"><span class="sw"><input type="checkbox" id="jr" checked><i></i></span>Replace the variants made earlier for this profile</label>
    <div id="jprev"></div><div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn" id="jp">Preview</button><button class="btn p" id="jsv" disabled>Save as profiles</button></div>`, {
    onMount: m => {
      const body = save => ({ id: p.id, count: +$('#jc', m).value || 10, seed: $('#js', m).value, use_units: $('#ju', m).checked, replace: $('#jr', m).checked, save });
      $('#jp', m).onclick = async () => { const r = await act(() => api('/api/profiles/rejig', body(false))); if (!r) return; $('#jprev', m).innerHTML = `<div class="vlist">${r.variants.map((x, i) => `<div><span class="muted">${i + 1}.</span> ${esc(x.addressLine1)}${x.addressLine2 ? ', ' + esc(x.addressLine2) : ''}</div>`).join('') || '<div class="muted">No other spellings exist for this address.</div>'}</div>`; $('#jsv', m).disabled = !r.variants.length; };
      $('#jsv', m).onclick = async () => { const r = await act(() => api('/api/profiles/rejig', body(true))); if (r) { closeModal(); toast(`Saved ${r.variants.length} variants as ${n}-J1…`); done(); } };
    }
  });
}

function addressModal(ids, done) {
  modal(`<h2>Change address for ${ids.length} profile${ids.length === 1 ? '' : 's'}</h2><p>Moves them all to one address. Names and cards are untouched.</p>
    ${fi('aa1', 'Address line 1')}${fi('aa2', 'Address line 2 (optional)')}<div class="col3">${fi('aci', 'City')}${fi('ast', 'State')}${fi('azp', 'ZIP / postcode')}</div>${fi('aco', 'Country code', 'US')}
    <div class="fld"><label class="f">Apply to</label><select class="sel" id="atg"><option value="both">Shipping and billing</option><option value="shipping">Shipping only</option><option value="billing">Billing only</option></select></div>
    <label class="tog" style="margin-bottom:10px"><span class="sw"><input type="checkbox" id="auq"><i></i></span>Spell it differently on each profile</label>
    <div class="fld"><label class="f">Real unit numbers (optional, one per line — handed out in turn)</label><textarea class="ta" id="aun" rows="3" placeholder="101&#10;102&#10;103"></textarea></div><div class="err hidden" id="aer"></div>
    <div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="aok">Apply</button></div>`, {
    onMount: m => $('#aok', m).onclick = async () => {
      const r = await act(() => api('/api/profiles/address', { ids, target: $('#atg', m).value, unique: $('#auq', m).checked, units: $('#aun', m).value,
        addr: { addressLine1: $('#aa1', m).value, addressLine2: $('#aa2', m).value, city: $('#aci', m).value, state: $('#ast', m).value, zipCode: $('#azp', m).value, countryCode: $('#aco', m).value } }));
      if (r) { closeModal(); toast(`Updated ${r.updated}` + (r.note ? '. ' + r.note : '')); done(); }
    }
  });
}

/* ============================ SITE ACCOUNTS ============================ */
PAGES.siteaccts = async function (v) {
  const T = S.tok;
  const d = await api('/api/vault');
  if (T !== S.tok) return;
  const groups = d.groups.acc;
  if (!groups.includes(vstate.ga)) vstate.ga = groups[0] || '';
  const counts = {}; d.accounts.forEach(a => counts[a.site] = (counts[a.site] || 0) + 1);
  const all = d.accounts.filter(a => a.site === vstate.ga);
  const q = vstate.q.toLowerCase();
  const rows = all.filter(a => !q || (a.rec.email + ' ' + a.rec.proxy).toLowerCase().includes(q));
  const byId = Object.fromEntries(all.map(a => [a.id, a]));
  vstate.sel = new Set([...vstate.sel].filter(i => byId[i]));
  v.innerHTML = `<div class="page vwrap ${vstate.blur ? 'blurred' : ''}"><div class="ph"><div><h1>Accounts</h1><p>Store logins and proxies per website. Paste a list, import your file, edit in bulk, and export. Everything stays on this computer.</p></div>
    <div class="acts"><button class="btn" id="a-blur">${vstate.blur ? 'Blur: on' : 'Blur: off'}</button><button class="btn" id="a-imp">Import file</button><button class="btn" id="a-exp" ${all.length ? '' : 'disabled'}>Export</button><button class="btn" id="a-paste" ${vstate.ga ? '' : 'disabled'}>Paste a list</button><button class="btn p" id="a-add" ${vstate.ga ? '' : 'disabled'}>Add account</button></div></div>
    ${groupBar('acc', groups, counts, vstate.ga)}
    ${vstate.ga ? `<div class="filters"><input class="inp" id="a-q" style="max-width:320px" placeholder="Search email or proxy…" value="${esc(vstate.q)}"><span class="note">${all.length} account${all.length === 1 ? '' : 's'}</span><span class="grow"></span></div><div id="a-bulk"></div><div id="a-list"></div>` : ''}</div>`;
  const rerender = () => { if (T === S.tok) refreshPage(); };
  groupHandlers(v, 'acc', vstate.ga, g => { vstate.ga = g; store.set('ga', g); }, rerender);
  $('#a-blur').onclick = () => { vstate.blur = !vstate.blur; store.set('blur', vstate.blur); refreshPage(); };
  $('#a-imp').onclick = () => modal(`<h2>Import accounts</h2><p>Choose an accounts file (JSON with an “accounts” section). It goes into the group named in the file, or the one you choose here.</p>
    <div class="fld"><label class="f">Group</label><select class="sel" id="ig"><option value="">Use the file's site name</option>${groups.map(g => `<option ${g === vstate.ga ? 'selected' : ''}>${esc(g)}</option>`).join('')}</select></div>
    <label class="tog"><span class="sw"><input type="checkbox" id="irep"><i></i></span>Replace what's already in the group</label><div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="ipick">Choose file…</button></div>`, {
    onMount: m => $('#ipick', m).onclick = async () => { const f = await pickFile(); if (!f) return; const r = await act(() => api('/api/siteaccounts/import', { text: f.text, site: $('#ig', m).value, replace: $('#irep', m).checked })); if (r) { closeModal(); vstate.ga = r.site; store.set('ga', r.site); toast(`Imported: ${r.added} new, ${r.updated} updated`); rerender(); } }
  });
  $('#a-exp').onclick = () => menu({ currentTarget: $('#a-exp'), stopPropagation() { } }, [
    { label: `Everything in “${vstate.ga}”`, fn: async () => { const r = await act(() => api('/api/siteaccounts/export', { site: vstate.ga })); r && exportDone(r); } },
    { label: vstate.sel.size ? `Only the ${vstate.sel.size} selected` : 'Only selected (select some first)', fn: async () => { if (!vstate.sel.size) return toast('Tick some accounts first', true); const r = await act(() => api('/api/siteaccounts/export', { site: vstate.ga, ids: [...vstate.sel] })); r && exportDone(r); } }]);
  $('#a-paste').onclick = () => modal(`<h2>Paste accounts</h2><p>One per line: <span class="mono">email:password</span> or <span class="mono">email:password:proxy</span>. Existing emails are skipped.</p><textarea class="ta" id="pl" rows="9" placeholder="name@example.com:password&#10;other@example.com:password:host:port:user:pass"></textarea><div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="pok">Add</button></div>`,
    { onMount: m => $('#pok', m).onclick = async () => { const r = await act(() => api('/api/siteaccounts/add', { site: vstate.ga, text: $('#pl', m).value })); if (r) { closeModal(); toast(`Added ${r.added}${r.skipped ? `, skipped ${r.skipped}` : ''}`); rerender(); } } });
  $('#a-add').onclick = () => acctModal(null, groups, vstate.ga, rerender);
  if (!vstate.ga) return;
  $('#a-q').oninput = e => { vstate.q = e.target.value; draw(); const el = $('#a-q'); el.focus(); el.setSelectionRange(el.value.length, el.value.length); };
  function bulk() {
    const n = vstate.sel.size, box = $('#a-bulk');
    box.innerHTML = n ? `<div class="bulk"><b>${n} selected</b><button class="btn sm" data-b="proxy">Set proxy…</button><button class="btn sm" data-b="exp">Export selected</button><button class="btn sm danger" data-b="del">Delete</button><button class="btn sm ghost" data-b="clr">Clear</button></div>` : '';
    $$('[data-b]', box).forEach(b => b.onclick = async () => {
      const ids = [...vstate.sel], k = b.dataset.b;
      if (k === 'clr') { vstate.sel.clear(); draw(); }
      if (k === 'exp') { const r = await act(() => api('/api/siteaccounts/export', { site: vstate.ga, ids })); r && exportDone(r); }
      if (k === 'del') { if (await confirmBox(`Delete ${ids.length} account${ids.length === 1 ? '' : 's'}?`, '', 'Delete', true)) { await act(() => api('/api/siteaccounts/delete', { site: vstate.ga, ids }), 'Deleted'); vstate.sel.clear(); rerender(); } }
      if (k === 'proxy') modal(`<h2>Set proxy for ${ids.length}</h2><p>Leave empty to clear it.</p>${fi('px', 'Proxy', '', 'text', 'host:port:user:pass')}<div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="pxs">Apply</button></div>`, { onMount: m => $('#pxs', m).onclick = async () => { await act(() => api('/api/siteaccounts/patch', { site: vstate.ga, ids, changes: { proxy: $('#px', m).value.trim() } }), 'Updated'); closeModal(); rerender(); } });
    });
  }
  function draw() {
    const L = $('#a-list');
    if (!rows.length) { L.innerHTML = `<div class="empty"><b>${all.length ? 'Nothing matches that search' : 'No accounts in ' + esc(vstate.ga) + ' yet'}</b>${all.length ? '' : 'Paste a list or import your file.'}</div>`; bulk(); return; }
    L.innerHTML = `<div class="tbl-wrap"><table class="t"><thead><tr><th style="width:34px"><input type="checkbox" class="ck" id="a-all" ${rows.every(a => vstate.sel.has(a.id)) ? 'checked' : ''}></th><th>Email / username</th><th>Password</th><th>Proxy</th><th>Session</th><th></th></tr></thead><tbody>${rows.map(a => `<tr data-id="${esc(a.id)}" class="${vstate.sel.has(a.id) ? 'sel' : ''}"><td><input type="checkbox" class="ck" ${vstate.sel.has(a.id) ? 'checked' : ''}></td><td class="sens">${esc(a.rec.email)}</td><td class="sens mono">${esc(a.rec.password) || '—'}</td><td class="sens mono">${esc(a.rec.proxy) || '—'}</td><td>${a.rec.session ? 'Saved' : '—'}</td><td style="text-align:right"><button class="btn sm" data-a="edit">Edit</button></td></tr>`).join('')}</tbody></table></div>`;
    $('#a-all', L).onclick = e => { rows.forEach(a => e.target.checked ? vstate.sel.add(a.id) : vstate.sel.delete(a.id)); draw(); };
    $$('tr[data-id]', L).forEach(tr => {
      const a = byId[tr.dataset.id];
      $('.ck', tr).onclick = e => { e.stopPropagation(); e.target.checked ? vstate.sel.add(a.id) : vstate.sel.delete(a.id); tr.classList.toggle('sel', e.target.checked); bulk(); };
      tr.onclick = () => acctModal(a, groups, vstate.ga, rerender);
      $('[data-a]', tr).onclick = e => { e.stopPropagation(); acctModal(a, groups, vstate.ga, rerender); };
    });
    sensClick(L); bulk();
  }
  draw();
};

function acctModal(a, groups, cur, done) {
  const r = a ? a.rec : { email: '', password: '', proxy: '' };
  modal(`<h2>${a ? 'Edit account' : 'Add account'}</h2><div class="fld"><label class="f">Group</label><select class="sel" id="ag" ${a ? 'disabled' : ''}>${groups.map(g => `<option ${g === (a ? a.site : cur) ? 'selected' : ''}>${esc(g)}</option>`).join('')}</select></div>
    ${fi('ae', 'Email / username', r.email)}${fi('ap', 'Password', r.password)}${fi('ax', 'Proxy (optional)', r.proxy, 'text', 'host:port:user:pass')}
    <div class="mfoot">${a ? '<button class="btn danger" id="adel" style="margin-right:auto">Delete</button>' : ''}<button class="btn" data-close>Cancel</button><button class="btn p" id="asv">Save</button></div>`, {
    onMount: m => {
      $('#asv', m).onclick = async () => { const res = await act(() => api('/api/siteaccounts/save', { site: $('#ag', m).value, old_id: a ? a.id : undefined, rec: { ...r, email: $('#ae', m).value, password: $('#ap', m).value, proxy: $('#ax', m).value.trim() } }), 'Saved'); if (res) { closeModal(); done(); } };
      if (a) $('#adel', m).onclick = async () => { await act(() => api('/api/siteaccounts/delete', { site: a.site, ids: [a.id] }), 'Deleted'); closeModal(); done(); };
    }
  });
}
