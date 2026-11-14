/* ================================================================ Inbox: every connected mailbox in one list, checked every 20 seconds */
const IB = { account: 0, q: '', unread: false, sel: null, data: null, rev: -1, timer: null, images: {}, open: null };
const ibTime = ts => {
  const d = new Date(ts * 1000), now = new Date();
  if (d.toDateString() === now.toDateString()) return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  const y = new Date(now); y.setDate(now.getDate() - 1);
  if (d.toDateString() === y.toDateString()) return 'Yesterday';
  if (now - d < 6 * 864e5) return d.toLocaleDateString([], { weekday: 'short' });
  return d.toLocaleDateString([], { month: 'short', day: 'numeric', ...(d.getFullYear() !== now.getFullYear() ? { year: 'numeric' } : {}) });
};
const ibAgo = ts => { if (!ts) return 'not checked yet'; const s = Math.max(0, Math.round(Date.now() / 1000 - ts)); return s < 5 ? 'just now' : s < 60 ? `${s}s ago` : `${Math.round(s / 60)}m ago`; };
const ibInitials = m => ((m.from_name || m.from_addr || '?').replace(/[^A-Za-z0-9 ]/g, '').trim().split(/\s+/).slice(0, 2).map(w => w[0]).join('') || '?').toUpperCase();

async function ibLoad() {
  const qs = new URLSearchParams({ account: IB.account || 0, q: IB.q, unread: IB.unread ? 1 : 0 });
  IB.data = await api('/api/inbox?' + qs);
  IB.rev = IB.data.rev;
  return IB.data;
}

PAGES.inbox = async function (v) {
  const T = S.tok;
  await ibLoad();
  if (T !== S.tok) return;
  const sm = IB.data.summary;
  if (!sm.accounts.length) {
    v.innerHTML = `<div class="page"><div class="ph"><div><h1>Inbox</h1><p>Read the mail from your connected inboxes without leaving the app.</p></div></div>
      <div class="card ib-empty"><div class="ib-ic">${icon('mail')}</div><h3>Link your iCloud email</h3>
      <p>Sign in with your iCloud address and an app-specific password (make one at appleid.apple.com under Sign-In and Security → App-Specific Passwords). Hide My Email addresses forward to this inbox, so they show up here too.</p>
      <button class="btn p" id="ib-link">Link iCloud email</button> <button class="btn" id="ib-other">Another provider</button></div></div>`;
    const link = async p => { S.mail = S.mail || await api('/api/mail/accounts'); accountModal(null, p); };
    $('#ib-link').onclick = () => link('icloud'); $('#ib-other').onclick = () => link('gmail');
    return;
  }
  v.innerHTML = `<div class="page ib">
    <div class="ib-top"><div><h1>Inbox</h1><div class="ib-sub" id="ib-sub"></div></div>
      <div class="ib-tools"><div class="ib-search">${icon('search', 16)}<input id="ib-q" placeholder="Search mail" value="${esc(IB.q)}"></div>
        <div class="chips"><button data-f="all" class="${IB.unread ? '' : 'on'}">All</button><button data-f="unread" class="${IB.unread ? 'on' : ''}">Unread</button></div>
        <button class="btn icon" id="ib-ref" title="Check now">${icon('refresh', 17)}</button><button class="btn" id="ib-link">Link email</button></div></div>
    <div class="ib-grid"><nav class="ib-boxes" id="ib-boxes"></nav><div class="ib-list" id="ib-list"></div><section class="ib-read" id="ib-read"></section></div></div>`;
  const drawBoxes = () => {
    const s = IB.data.summary;
    $('#ib-boxes').innerHTML = `<button data-a="0" class="${IB.account ? '' : 'on'}"><span>All inboxes</span>${s.unread ? `<em>${s.unread}</em>` : ''}</button>
      ${s.accounts.map(a => `<button data-a="${a.id}" class="${IB.account === a.id ? 'on' : ''}" title="${esc(a.error || a.email)}"><span>${esc(a.email)}</span>${a.error ? '<i class="ib-err"></i>' : a.unread ? `<em>${a.unread}</em>` : ''}</button>`).join('')}`;
    $('#ib-sub').textContent = `${IB.data.total} message${IB.data.total === 1 ? '' : 's'} · checked ${ibAgo(s.last)} · checks every ${s.interval} seconds`;
  };
  const drawList = () => {
    const L = $('#ib-list'), ms = IB.data.messages, multi = IB.data.summary.accounts.length > 1;
    if (!ms.length) {
      const loading = IB.data.summary.accounts.some(a => !a.loaded);
      L.innerHTML = `<div class="ib-none">${loading ? '<span class="spin"></span> Loading your mail…' : IB.q || IB.unread ? 'Nothing matches.' : 'No mail yet.'}</div>`; return;
    }
    L.innerHTML = ms.map(m => {
      const key = m.account_id + ':' + m.uid, alias = m.to_addr && !m.to_addr.includes(m.account) ? m.to_addr.split(',')[0] : '';
      return `<div class="ib-row ${m.seen ? '' : 'new'} ${IB.sel === key ? 'on' : ''}" data-k="${key}">
        <div class="ib-av">${esc(ibInitials(m))}</div>
        <div class="ib-mid"><div class="ib-l1"><b>${esc(m.from_name || m.from_addr)}</b><span class="ib-t">${m.flagged ? `<span class="ib-flag">${icon('flag', 13)}</span>` : ''}${m.attach ? icon('clip', 13) : ''}${ibTime(m.ts)}</span></div>
          <div class="ib-subj">${esc(m.subject || '(no subject)')}</div>
          <div class="ib-snip">${esc(m.snippet)}</div>
          ${alias || (multi && !IB.account) ? `<div class="ib-to">${esc(alias || m.account)}</div>` : ''}</div></div>`;
    }).join('');
  };
  const drawReader = async () => {
    const R = $('#ib-read');
    if (!IB.sel) { R.innerHTML = `<div class="ib-none ib-pick">${icon('mail')}<span>Select a message to read it</span></div>`; return; }
    const [aid, uid] = IB.sel.split(':').map(Number), meta = IB.data.messages.find(m => m.account_id === aid && m.uid === uid) || {};
    R.innerHTML = `<div class="ib-none"><span class="spin"></span></div>`;
    let m;
    try { m = await api(`/api/inbox/message?account=${aid}&uid=${uid}&images=${IB.images[IB.sel] ? 1 : 0}`); }
    catch (x) { if (IB.sel === aid + ':' + uid) R.innerHTML = `<div class="ib-none">${esc(x.message)}</div>`; return; }
    if (IB.sel !== aid + ':' + uid) return;
    IB.open = m;
    if (!meta.seen && meta.uid) { meta.seen = 1; const row = $(`.ib-row[data-k="${IB.sel}"]`); if (row) row.classList.remove('new'); }
    const allowImg = IB.images[IB.sel];
    const csp = `default-src 'none'; style-src 'unsafe-inline' https: http:; font-src https: http: data:; img-src data: cid:${allowImg ? ' https: http:' : ''}`;
    const doc = m.kind === 'html'
      ? `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="${csp}"><base target="_blank"><style>body{margin:0;padding:22px 26px;font-family:-apple-system,"Segoe UI",system-ui,sans-serif;font-size:14px;color:#1d1d24;background:#fff;word-wrap:break-word}img{max-width:100%;height:auto}table{max-width:100%!important}a{color:#c8213f}${allowImg ? '' : 'img[src^="http"],img[src^="//"]{visibility:hidden}'}</style></head><body>${m.body}</body></html>`
      : `<!doctype html><html><head><meta http-equiv="Content-Security-Policy" content="${csp}"><base target="_blank"><style>body{margin:0;padding:22px 26px;font:14px/1.6 -apple-system,"Segoe UI",system-ui,sans-serif;color:#d9dae3;background:#12121a;white-space:pre-wrap;word-wrap:break-word}a{color:#ff4d6a}</style></head><body>${m.body.replace(/(https?:\/\/[^\s<]+)/g, '<a href="$1">$1</a>')}</body></html>`;
    R.innerHTML = `<div class="ib-head"><h2>${esc(m.subject)}</h2>
        <div class="ib-meta"><div class="ib-from"><div class="ib-av">${esc(ibInitials(m))}</div><div><b>${esc(m.from_name || m.from_addr)}</b> <span class="muted">&lt;${esc(m.from_addr)}&gt;</span>
          <div class="muted small">to ${esc(m.to)}${m.cc ? ` · cc ${esc(m.cc)}` : ''} · ${new Date(m.date * 1000).toLocaleString([], { dateStyle: 'medium', timeStyle: 'short' })}</div></div></div>
        <div class="ib-acts"><button class="btn sm ghost" data-x="unread" title="Mark as unread (U)">${icon('dot', 15)}Unread</button><button class="btn sm ghost ${meta.flagged ? 'on' : ''}" data-x="flag" title="Flag">${icon('flag', 15)}${meta.flagged ? 'Flagged' : 'Flag'}</button><button class="btn sm ghost" data-x="del" title="Delete (Del)">${icon('trash', 15)}Delete</button></div></div></div>
      ${m.remote_images && !allowImg ? `<div class="ib-imgbar">Images from the sender are hidden to stop read-tracking. <button class="btn sm" data-x="img">Show images</button></div>` : ''}
      ${m.attachments.length ? `<div class="ib-atts">${m.attachments.map(a => `<button class="ib-att" data-att="${a.idx}" title="Save to Downloads and open">${icon('clip', 15)}<span>${esc(a.name)}</span><em>${a.size > 1048576 ? (a.size / 1048576).toFixed(1) + ' MB' : Math.max(1, Math.round(a.size / 1024)) + ' KB'}</em></button>`).join('')}</div>` : ''}
      <iframe class="ib-frame ${m.kind}" sandbox="allow-popups allow-popups-to-escape-sandbox" referrerpolicy="no-referrer"></iframe>`;
    $('.ib-frame', R).srcdoc = doc;
    R.onclick = async e => {
      const b = e.target.closest('[data-x],[data-att]'); if (!b) return;
      if (b.dataset.att) { const r = await act(() => api('/api/inbox/attachment', { account: aid, uid, idx: +b.dataset.att, open: true })); if (r) toast('Saved to ' + r.path); return; }
      const x = b.dataset.x;
      if (x === 'img') { IB.images[IB.sel] = true; drawReader(); }
      if (x === 'unread') { await act(() => api('/api/inbox/flags', { account: aid, uids: [uid], flag: 'seen', on: false })); meta.seen = 0; IB.sel = null; await refresh(); }
      if (x === 'flag') { await act(() => api('/api/inbox/flags', { account: aid, uids: [uid], flag: 'flagged', on: !meta.flagged })); meta.flagged = meta.flagged ? 0 : 1; drawList(); drawReader(); }
      if (x === 'del') del(aid, uid);
    };
  };
  const del = async (aid, uid) => {
    const i = IB.data.messages.findIndex(m => m.account_id === aid && m.uid === uid), next = IB.data.messages[i + 1] || IB.data.messages[i - 1];
    if (await act(() => api('/api/inbox/delete', { account: aid, uids: [uid] }), 'Moved to Deleted Messages')) { IB.sel = next ? next.account_id + ':' + next.uid : null; await refresh(); }
  };
  const refresh = async (quiet) => {
    const L = $('#ib-list'); if (!L) return; const top = L.scrollTop;
    await ibLoad(); if (S.route !== 'inbox' || !$('#ib-list')) return;
    drawBoxes(); drawList(); $('#ib-list').scrollTop = top;
    if (!quiet || (IB.sel && !$('#ib-read .ib-head'))) drawReader();
  };
  drawBoxes(); drawList(); drawReader();
  $('#ib-boxes').onclick = e => { const b = e.target.closest('[data-a]'); if (!b) return; IB.account = +b.dataset.a; IB.sel = null; refresh(); };
  $('#ib-list').onclick = e => { const r = e.target.closest('.ib-row'); if (!r || IB.sel === r.dataset.k) return; IB.sel = r.dataset.k; $$('.ib-row.on').forEach(x => x.classList.remove('on')); r.classList.add('on'); drawReader(); };
  $('.ib-tools .chips').onclick = e => { const b = e.target.closest('[data-f]'); if (!b) return; IB.unread = b.dataset.f === 'unread'; $$('.ib-tools .chips button').forEach(x => x.classList.toggle('on', x === b)); refresh(true); };
  let qt; $('#ib-q').oninput = e => { IB.q = e.target.value; clearTimeout(qt); qt = setTimeout(() => refresh(true), 200); };
  $('#ib-ref').onclick = async e => { const b = e.currentTarget; b.classList.add('spinning'); await api('/api/inbox/check', {}); setTimeout(() => b.classList.remove('spinning'), 1200); };
  $('#ib-link').onclick = async () => { S.mail = await api('/api/mail/accounts'); accountModal(null, 'icloud'); };
  // keyboard: J/K or arrows to move, U unread, Delete to delete
  document.onkeydown = e => {
    if (S.route !== 'inbox' || /INPUT|TEXTAREA|SELECT/.test(document.activeElement.tagName) || $('.modal')) return;
    const ms = IB.data.messages, i = ms.findIndex(m => m.account_id + ':' + m.uid === IB.sel);
    const go = j => { const m = ms[j]; if (!m) return; IB.sel = m.account_id + ':' + m.uid; drawList(); drawReader(); const r = $(`.ib-row[data-k="${IB.sel}"]`); if (r) r.scrollIntoView({ block: 'nearest' }); };
    if (e.key === 'j' || e.key === 'ArrowDown') { e.preventDefault(); go(i + 1); }
    if (e.key === 'k' || e.key === 'ArrowUp') { e.preventDefault(); go(Math.max(0, i - 1)); }
    if ((e.key === 'Delete' || e.key === 'Backspace') && IB.sel) { const [a, u] = IB.sel.split(':').map(Number); del(a, u); }
    if (e.key === 'u' && IB.sel) $('[data-x="unread"]') && $('[data-x="unread"]').click();
  };
  // live: the app checks every 20s; this just notices when something changed
  clearInterval(IB.timer);
  IB.timer = setInterval(async () => {
    if (S.route !== 'inbox' || !$('#ib-list')) { clearInterval(IB.timer); return; }
    try { const s = await api('/api/inbox/state'); if (s.rev !== IB.rev) refresh(true); else { IB.data.summary.last = s.last; drawBoxes(); } } catch (e) { }
  }, 4000);
};
