/* Demented Toolbox UI core: helpers, shell, lock screen, router */
const $ = (s, r = document) => r.querySelector(s);
const $$ = (s, r = document) => [...r.querySelectorAll(s)];
const esc = s => String(s ?? '').replace(/[&<>"']/g, c => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const money = n => n == null || n === '' ? '—' : '$' + Number(n).toLocaleString('en-US', { minimumFractionDigits: 2, maximumFractionDigits: 2 });
const fdate = d => { if (!d) return '—'; const t = new Date(String(d).replace(' ', 'T')); return isNaN(t) ? d : t.toLocaleDateString('en-US', { month: 'short', day: 'numeric' }); };
const fdt = d => { if (!d) return '—'; const t = new Date(String(d).replace(' ', 'T')); return isNaN(t) ? d : t.toLocaleString('en-US', { month: 'short', day: 'numeric', hour: 'numeric', minute: '2-digit' }); };
const store = { get(k, d) { try { const v = localStorage.getItem('dt.' + k); return v == null ? d : JSON.parse(v); } catch (e) { return d; } }, set(k, v) { try { localStorage.setItem('dt.' + k, JSON.stringify(v)); } catch (e) { } } };

const IC = {
  truck: '<path d="M3 7h11v9H3zM14 10h4l3 3v3h-7"/><circle cx="7" cy="17.5" r="1.7"/><circle cx="17" cy="17.5" r="1.7"/>',
  box: '<path d="M12 3l8 4.5v9L12 21l-8-4.5v-9z"/><path d="M4 7.5l8 4.5 8-4.5M12 12v9"/>',
  bell: '<path d="M6 16V11a6 6 0 0112 0v5l1.5 2h-15z"/><path d="M10 20a2 2 0 004 0"/>',
  mail: '<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="M3.5 7l8.5 6 8.5-6"/>',
  discord: '<path d="M7.5 6.5C9 5.8 10.5 5.5 12 5.5s3 .3 4.5 1c2 2.7 3 5.6 3.2 9-1.3 1-2.7 1.6-4.2 2l-.9-1.6c.5-.2 1-.4 1.4-.7-.3-.2-.6-.4-.9-.5-2.2 1-4.8 1-7 0-.3.1-.6.3-.9.5.4.3.9.5 1.4.7L7 17.5c-1.5-.4-2.9-1-4.2-2 .2-3.4 1.2-6.3 3.2-9z" stroke-linejoin="round"/><circle cx="9.3" cy="12" r="1.1" fill="currentColor"/><circle cx="14.7" cy="12" r="1.1" fill="currentColor"/>',
  target: '<circle cx="12" cy="12" r="3"/><circle cx="12" cy="12" r="7.5"/><path d="M12 2v4M12 18v4M2 12h4M18 12h4"/>',
  doc: '<path d="M7 3h8l4 4v14H7z"/><path d="M15 3v4h4M10 12h6M10 16h6"/>',
  layers: '<path d="M12 3l9 5-9 5-9-5z"/><path d="M3 13l9 5 9-5"/>',
  gear: '<circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.7 1.7 0 00.3 1.8l.1.1a2 2 0 11-2.8 2.8l-.1-.1a1.7 1.7 0 00-1.8-.3 1.7 1.7 0 00-1 1.5V21a2 2 0 11-4 0v-.1a1.7 1.7 0 00-1.1-1.5 1.7 1.7 0 00-1.8.3l-.1.1a2 2 0 11-2.8-2.8l.1-.1a1.7 1.7 0 00.3-1.8 1.7 1.7 0 00-1.5-1H3a2 2 0 110-4h.1a1.7 1.7 0 001.5-1.1 1.7 1.7 0 00-.3-1.8l-.1-.1a2 2 0 112.8-2.8l.1.1a1.7 1.7 0 001.8.3H9a1.7 1.7 0 001-1.5V3a2 2 0 114 0v.1a1.7 1.7 0 001 1.5 1.7 1.7 0 001.8-.3l.1-.1a2 2 0 112.8 2.8l-.1.1a1.7 1.7 0 00-.3 1.8V9a1.7 1.7 0 001.5 1H21a2 2 0 110 4h-.1a1.7 1.7 0 00-1.5 1z"/>',
  refresh: '<path d="M20 11a8 8 0 00-14-4L4 9M4 4v5h5M4 13a8 8 0 0014 4l2-2M20 20v-5h-5"/>',
  image: '<rect x="3" y="4" width="18" height="16" rx="2.5"/><circle cx="9" cy="10" r="1.7"/><path d="M4 18l5-5 4 4 3-3 4 4"/>',
  min: '<path d="M5 12h14"/>', max: '<rect x="6" y="6" width="12" height="12" rx="1.5"/>', x: '<path d="M6 6l12 12M18 6L6 18"/>',
  dots: '<circle cx="5" cy="12" r="1.6" fill="currentColor"/><circle cx="12" cy="12" r="1.6" fill="currentColor"/><circle cx="19" cy="12" r="1.6" fill="currentColor"/>',
  user: '<circle cx="12" cy="8" r="3.6"/><path d="M4.5 20c.6-3.8 3.7-6 7.5-6s6.9 2.200 7.500 6"/>',
  card: '<rect x="3" y="5" width="18" height="14" rx="2.5"/><path d="M3 10h18M7 15h4"/>',
  key: '<circle cx="8" cy="15" r="3.5"/><path d="M10.500 12.500L19 4M16 7l2.500 2.500M13.500 9.500L15.500 11.500"/>',
  shield: '<path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M9 12l2 2 4-4"/>',
};
const icon = (n, s = 20) => `<svg width="${s}" height="${s}" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.7" stroke-linecap="round" stroke-linejoin="round">${IC[n] || ''}</svg>`;
const LOGO = `<svg width="26" height="26" viewBox="0 0 40 40"><path d="M10 7h10.5c7 0 11.5 4.6 11.5 13S27.500 33 20.500 33H10z" fill="#0d0d13"/><path d="M16 14h4c3.300 0 5.500 2.300 5.500 6s-2.200 6-5.500 6h-4z" fill="#e5304f"/></svg>`;

/* ---------- api */
let locked = false;
async function api(path, body) {
  let r;
  try {
    r = await fetch(path, body === undefined ? {} : { method: 'POST', headers: { 'Content-Type': 'application/json' }, body: JSON.stringify(body) });
  } catch (e) { throw new Error('The app is not responding. Close and reopen it.'); }
  let j = {};
  try { j = await r.json(); } catch (e) { }
  if (r.status === 403 && j.locked) { showLock(); throw new Error(j.error); }
  if (!r.ok) throw new Error(j.error || ('Error ' + r.status));
  return j;
}
const act = async (fn, okMsg) => { try { const r = await fn(); if (okMsg) toast(okMsg); return r; } catch (e) { toast(e.message, true); return null; } };

function toast(msg, isErr) {
  const t = document.createElement('div'); t.className = 'toast' + (isErr ? ' err' : ''); t.textContent = msg;
  $('#toasts').appendChild(t); setTimeout(() => t.remove(), isErr ? 6500 : 3500);
}

/* ---------- modal / drawer / menu */
function modal(html, { wide = false, onMount, onClose } = {}) {
  const ov = $('#overlay'); ov.innerHTML = `<div class="modal ${wide ? 'wide' : ''}">${html}</div>`; ov.classList.remove('hidden');
  const close = () => { ov.classList.add('hidden'); ov.innerHTML = ''; onClose && onClose(); };
  ov.onmousedown = e => { if (e.target === ov) close(); };
  ov._close = close;
  $$('[data-close]', ov).forEach(b => b.onclick = close);
  onMount && onMount($('.modal', ov), close);
  return close;
}
const closeModal = () => { const ov = $('#overlay'); ov._close && ov._close(); };
function confirmBox(title, text, okLabel = 'Confirm', danger = false) {
  return new Promise(res => {
    modal(`<h2>${esc(title)}</h2><p>${text}</p><div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn ${danger ? 'danger' : 'p'}" id="cok">${esc(okLabel)}</button></div>`,
      { onMount: (m, close) => { $('#cok', m).onclick = () => { close(); res(true); }; $$('[data-close]', m).forEach(b => b.addEventListener('click', () => res(false))); } });
  });
}
function openDrawer(html, onMount) {
  const d = $('#drawer'); d.innerHTML = html; d.classList.remove('hidden');
  $$('[data-dclose]', d).forEach(b => b.onclick = closeDrawer); onMount && onMount(d);
}
const closeDrawer = () => { $('#drawer').classList.add('hidden'); $('#drawer').innerHTML = ''; };
function menu(ev, items) {
  ev.stopPropagation(); $$('.menu').forEach(m => m.remove());
  const m = document.createElement('div'); m.className = 'menu';
  m.innerHTML = items.map((it, i) => it === '-' ? '<hr>' : `<button class="${it.cls || ''}" data-i="${i}">${esc(it.label)}</button>`).join('');
  document.body.appendChild(m);
  const r = ev.currentTarget.getBoundingClientRect();
  m.style.left = Math.min(r.left, innerWidth - 220) + 'px'; m.style.top = Math.min(r.bottom + 4, innerHeight - m.offsetHeight - 10) + 'px';
  m.onclick = e => { const b = e.target.closest('button'); if (b) { m.remove(); items[+b.dataset.i].fn(); } };
}
document.addEventListener('click', () => { $$('.menu').forEach(m => m.remove()); const bp = $('#bellpanel'); if (!bp.classList.contains('hidden') && !event.target.closest('#bellpanel')) bp.classList.add('hidden'); });
document.addEventListener('keydown', e => { if (e.key === 'Escape') { closeModal(); closeDrawer(); } });

const busy = async (btn, fn) => { const old = btn.innerHTML; btn.disabled = true; btn.innerHTML = '<span class="spin"></span>'; try { return await fn(); } finally { btn.disabled = false; btn.innerHTML = old; } };
const pickFiles = (accept, multiple = true) => new Promise(res => { const i = document.createElement('input'); i.type = 'file'; i.accept = accept; i.multiple = multiple; i.onchange = () => res([...i.files]); i.click(); });
const readText = f => new Promise((res, rej) => { const r = new FileReader(); r.onload = () => res(r.result); r.onerror = rej; r.readAsText(f); });

/* ---------- state + shell */
const S = { route: 'tracking', info: null, page: null, shell: null, tok: 0 };
const NAV = [
  { id: 'tracker', label: 'Order Tracker', icon: 'truck', items: [['tracking', 'Tracking', 'box'], ['attention', 'Needs attention', 'bell'], ['email', 'Email accounts', 'mail'], ['webhooks', 'Discord webhooks', 'discord']] },
  { id: 'arsenal', label: 'Arsenal', icon: 'target', items: [['checkouts', 'Checkouts', 'doc'], ['servers', 'Servers & channels', 'discord'], ['bots', 'Bots & proxies', 'layers'], ['rules', 'Price rules', 'doc']] },
  { id: 'vault', label: 'Profiles & Accounts', icon: 'user', items: [['profiles', 'Profiles', 'card'], ['siteaccts', 'Site accounts', 'key']] },
];
const TITLES = { tracking: ['Order Tracker', 'Tracking'], attention: ['Order Tracker', 'Needs attention'], email: ['Order Tracker', 'Email accounts'], webhooks: ['Order Tracker', 'Discord webhooks'],
  checkouts: ['Arsenal', 'Checkouts'], servers: ['Arsenal', 'Servers & channels'], bots: ['Arsenal', 'Bots & proxies'], rules: ['Arsenal', 'Price rules'], profiles: ['Profiles & Accounts', 'Profiles'], siteaccts: ['Profiles & Accounts', 'Site accounts'], settings: ['Demented Toolbox', 'Settings'] };

function renderShell() {
  const open = store.get('groups', { tracker: true, arsenal: true, vault: true });
  $('#side').innerHTML = `
    <div class="brand"><div class="logo">${LOGO}</div><div><b>Demented Toolbox</b><span>v${esc(S.info.version)}</span></div></div>
    <div class="sec">MODULES</div>
    ${NAV.map(g => `<button class="grp ${open[g.id] ? '' : 'closed'}" data-grp="${g.id}">${icon(g.icon)}<span>${g.label}</span><span class="car">▼</span></button>
      <div class="sub ${open[g.id] ? '' : 'closed'}" id="sub-${g.id}">${g.items.map(([id, l, ic]) => `<button class="nav" data-nav="${id}">${icon(ic, 18)}<span>${l}</span><span class="side-ind" id="ind-${id}"></span></button>`).join('')}</div>`).join('')}
    <div class="sec">APP</div>
    <button class="grp" data-nav="settings" style="font-weight:500">${icon('gear')}<span>Settings</span></button>
    <div class="me">
      <div class="who"><div class="avatar" id="avatar"></div><div><b id="who-name"></b><span class="plan" id="who-plan"></span></div></div>
      <div class="live-line"><span class="dot" id="live-dot"></span><span id="live-text">…</span></div>
      <button class="upd" id="btn-upd">${icon('refresh', 18)}<span>Check for updates</span></button>
    </div>`;
  $('#side').onclick = e => {
    const g = e.target.closest('[data-grp]'); if (g) { const o = store.get('groups', { tracker: true, arsenal: true }); o[g.dataset.grp] = !o[g.dataset.grp]; store.set('groups', o); g.classList.toggle('closed'); $('#sub-' + g.dataset.grp).classList.toggle('closed'); return; }
    const n = e.target.closest('[data-nav]'); if (n) go(n.dataset.nav);
  };
  $('#btn-upd').onclick = checkUpdates;
  const hasWin = !!(window.pywebview || navigator.userAgent.includes('pywebview'));
  $('#top').innerHTML = `<div class="crumb" id="crumb"></div><div class="grow pywebview-drag-region"></div><div class="live off" id="live-pill"><span class="dot"></span>LIVE</div>
    <button class="iconbtn" id="bell" title="Notifications">${icon('bell', 20)}<span class="badge hidden" id="bell-n">0</span></button>
    <div class="winctl" id="winctl">${['min', 'max', 'x'].map(k => `<button class="${k}" data-win="${k}">${icon(k, 16)}</button>`).join('')}</div>`;
  $('#bell').onclick = e => { e.stopPropagation(); toggleBell(); };
  $('#winctl').onclick = e => { const b = e.target.closest('[data-win]'); if (!b) return; const a = window.pywebview && window.pywebview.api; if (a) a[{ min: 'minimize', max: 'maximize', x: 'close' }[b.dataset.win]](); };
  if (!hasWin) setTimeout(() => { if (!window.pywebview) $('#winctl') && $('#winctl').classList.add('hidden'); }, 1500);
}

async function go(route, force) {
  if (S.route === route && !force && S.page) { renderRoute(); return; }
  S.route = route; location.hash = '#/' + route; closeDrawer(); renderRoute();
}
function renderRoute() {
  const [a, b] = TITLES[S.route] || ['', ''];
  $('#crumb').innerHTML = `<b>${esc(a)}</b><i>/</i>${esc(b)}`;
  $$('[data-nav]').forEach(n => n.classList.toggle('on', n.dataset.nav === S.route));
  const fn = PAGES[S.route]; const v = $('#view'); v.scrollTop = 0;
  if (S.page !== S.route && typeof vstate !== 'undefined') vstate.q = '';
  S.page = S.route; S.tok++; fn(v);
}
const PAGES = {};
function refreshPage() { if (PAGES[S.route]) { const v = $('#view'); const y = v.scrollTop; S.tok++; const r = PAGES[S.route](v); Promise.resolve(r).then(() => v.scrollTop = y); } }

async function pollShell() {
  try {
    const s = await api('/api/shell'); S.shell = s;
    const lv = s.live, on = lv.total > 0 && lv.live > 0;
    $('#live-pill').classList.toggle('off', !on); $('#live-dot').className = 'dot ' + (on ? 'g' : '');
    $('#live-text').textContent = lv.total ? `${lv.live} of ${lv.total} inbox${lv.total > 1 ? 'es' : ''} live` : 'No inbox connected';
    const ind = $('#ind-email'); if (ind) ind.innerHTML = lv.total ? `<span class="dot ${on ? 'g' : 'r'}"></span>` : '';
    const ia = $('#ind-attention'); if (ia) ia.innerHTML = s.attention ? `<span class="badge">${s.attention}</span>` : '';
    const bn = $('#bell-n'); bn.textContent = s.unread; bn.classList.toggle('hidden', !s.unread);
    const L = s.license; $('#who-name').textContent = L.user || 'Member'; $('#who-plan').textContent = L.open ? 'Open build' : ({ member: 'Member', pro: 'Pro', trial: 'Trial', dev: 'Developer' }[L.plan] || L.plan) + ' license';
    $('#avatar').innerHTML = `<svg width="38" height="38" viewBox="0 0 38 38"><defs><linearGradient id="ag" x1="0" y1="0" x2="1" y2="1"><stop offset="0" stop-color="#ff4d6a"/><stop offset="1" stop-color="#7c1d33"/></linearGradient></defs><rect width="38" height="38" fill="url(#ag)"/><text x="19" y="25" text-anchor="middle" font-size="18" font-weight="700" fill="#fff" font-family="Inter,Segoe UI,sans-serif">${esc((L.user || 'M')[0].toUpperCase())}</text></svg>`;
    const sig = s.unread + ':' + s.attention + ':' + lv.live + ':' + s.sync.running + ':' + s.discord.running;
    if (L.state !== 'active') showLock(); else { if (S.sig && S.sig !== sig) softRefresh(); S.sig = sig; }
  } catch (e) { }
}
function softRefresh() { const ae = document.activeElement; if (['tracking', 'attention', 'email', 'checkouts', 'servers'].includes(S.route) && $('#overlay').classList.contains('hidden') && $('#drawer').classList.contains('hidden') && !(ae && /INPUT|TEXTAREA|SELECT/.test(ae.tagName))) refreshPage(); }

async function toggleBell() {
  const p = $('#bellpanel');
  if (!p.classList.contains('hidden')) { p.classList.add('hidden'); return; }
  const j = await api('/api/notifications');
  p.innerHTML = `<div class="row" style="padding:8px 12px"><b style="flex:1">Notifications</b><button class="btn sm ghost" id="nrd">Mark all read</button><button class="btn sm ghost" id="ncl">Clear</button></div>` +
    (j.items.length ? j.items.map(n => `<div class="nt ${n.read ? '' : 'un'}" data-link="${esc(n.link)}"><b>${esc(n.title)}</b><span>${esc(n.body || '')} · ${fdt(n.ts)}</span></div>`).join('') : '<div class="empty plain" style="margin:8px;border:0">Nothing yet. New orders and checkouts show up here.</div>');
  p.classList.remove('hidden');
  p.onclick = e => { e.stopPropagation(); const n = e.target.closest('.nt'); if (n && n.dataset.link) { p.classList.add('hidden'); go(n.dataset.link); } };
  $('#nrd', p).onclick = async () => { await api('/api/notifications/read', {}); p.classList.add('hidden'); pollShell(); };
  $('#ncl', p).onclick = async () => { await api('/api/notifications/clear', {}); p.classList.add('hidden'); pollShell(); };
  api('/api/notifications/read', {}).then(pollShell);
}

function tokenModal() {
  modal(`<h2>GitHub token</h2><p>Only needed if the release repository is private. Create a token with read-only access to the repository's contents and paste it here, then check for updates again.</p><div class="fld"><input class="inp" id="gt" type="password" placeholder="ghp_…"></div><div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="gts">Save</button></div>`,
    { onMount: m => $('#gts', m).onclick = async () => { await act(() => api('/api/update/token', { token: $('#gt', m).value }), 'Saved'); closeModal(); } });
}
async function checkUpdates() {
  const b = $('#btn-upd'); const r = await busy(b, () => act(() => api('/api/update/check')));
  if (!r) return;
  if (!r.ok) { toast(r.error, true); if (/token|private|No release/i.test(r.error)) tokenModal(); return; }
  if (!r.update) return toast(`You're up to date (build ${r.current}).`);
  modal(`<h2>Update available</h2><p>Build ${r.latest} is ready (you have ${r.current}). Your data is never touched by an update.</p>${r.notes ? `<p class="small muted">${esc(r.notes).slice(0, 400)}</p>` : ''}
    <div class="prog hidden" id="up-p"><i></i></div><div class="small muted" id="up-t"></div>
    <div class="mfoot"><button class="btn" data-close>Later</button><button class="btn p" id="up-go">Download & install</button></div>`, {
    onMount: m => {
      $('#up-go', m).onclick = async e => {
        e.target.disabled = true; await api('/api/update/download', { url: r.url, size: r.size }); $('#up-p', m).classList.remove('hidden');
        const t = setInterval(async () => {
          const s = await api('/api/update/status');
          $('#up-p i', m).style.width = (s.total ? s.done / s.total * 100 : 5) + '%'; $('#up-t', m).textContent = s.phase === 'downloading' ? `Downloading… ${Math.round(s.done / 1048576)} MB` : s.phase;
          if (s.phase === 'ready') { clearInterval(t); $('#up-t', m).textContent = 'Installing — the app will restart.'; api('/api/update/install', {}); }
          if (s.phase === 'error') { clearInterval(t); $('#up-t', m).textContent = s.error; }
        }, 600);
      };
    }
  });
}

/* ---------- lock screen */
let lockOpen = false;
async function showLock(msg) {
  if (lockOpen) return; lockOpen = true;
  $('#app').classList.add('hidden'); $('#boot').classList.add('hidden');
  const st = await fetch('/api/license/status').then(r => r.json());
  const L = $('#lock'); L.classList.remove('hidden');
  const why = msg || st.error || st.last_error || '';
  L.innerHTML = `<div class="lockwin pywebview-drag-region" style="left:0;justify-content:flex-end"><div style="flex:1;height:44px" class="pywebview-drag-region"></div>${['min', 'x'].map(k => `<button data-win="${k}">${icon(k, 16)}</button>`).join('')}</div>
  <div class="lockcard"><div class="logo">${LOGO.replace('width="26" height="26"', 'width="34" height="34"')}</div>
    <h1>Activate Demented Toolbox</h1><p class="c">Enter the license key you were given. It unlocks the app on this computer.</p>
    ${why ? `<div class="err" style="text-align:center;margin:-8px 0 14px">${esc(why)}</div>` : ''}
    <div class="fld"><input class="inp keyinp" id="lk" placeholder="DT-XXXXX-XXXXX-XXXXX-XXXXX" autocomplete="off" spellcheck="false" maxlength="29"></div>
    <div class="fld"><label class="f">This computer's name</label><input class="inp" id="ldev" value="${esc(st.device_name)}"></div>
    <div id="lerr" class="err hidden" style="text-align:center"></div>
    <button class="btn p" id="lgo" style="width:100%;justify-content:center;padding:13px;margin-top:6px">Activate</button>
    <div class="row" style="justify-content:center;margin-top:16px"><button class="btn sm ghost" id="lsrv">License server: ${esc(st.server)}</button></div></div>`;
  $$('[data-win]', L).forEach(b => b.onclick = () => { const a = window.pywebview && window.pywebview.api; if (a) a[{ min: 'minimize', x: 'close' }[b.dataset.win]](); });
  const key = $('#lk', L);
  key.oninput = () => { let v = key.value.toUpperCase().replace(/[^A-Z0-9]/g, ''); if (v.startsWith('DT')) v = v.slice(2); v = v.slice(0, 20); key.value = v ? 'DT-' + (v.match(/.{1,5}/g) || []).join('-') : ''; };
  const submit = async (force) => {
    const err = $('#lerr', L); err.classList.add('hidden');
    const r = await busy($('#lgo', L), () => api('/api/license/activate', { key: key.value, device_name: $('#ldev', L).value, force }).catch(e => ({ ok: false, error: e.message })));
    if (r.ok) { lockOpen = false; L.classList.add('hidden'); startApp(); return; }
    err.classList.remove('hidden'); err.textContent = r.error;
    if (r.code === 'in_use') { err.innerHTML = esc(r.error) + '<br><button class="btn sm" id="lforce" style="margin-top:10px">Use it on this computer</button>'; $('#lforce', L).onclick = () => submit(true); }
  };
  $('#lgo', L).onclick = () => submit(false);
  key.onkeydown = e => { if (e.key === 'Enter') submit(false); }; key.focus();
  $('#lsrv', L).onclick = () => modal(`<h2>License server</h2><p>The address of the server that checks license keys. You only change this if the seller gave you a different one.</p>
    <div class="fld"><input class="inp" id="surl" value="${esc(st.server)}"></div><div class="mfoot"><button class="btn" data-close>Cancel</button><button class="btn p" id="ssave">Save</button></div>`,
    { onMount: m => $('#ssave', m).onclick = async () => { const r = await act(() => api('/api/license/server', { url: $('#surl', m).value })); if (r) { closeModal(); lockOpen = false; L.classList.add('hidden'); showLock(); } } });
}
