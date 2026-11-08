/* Start-up: license check, then the app */
async function startApp() {
  try {
    S.info = await fetch('/api/version').then(r => r.json());
    const lic = await fetch('/api/license/status').then(r => r.json());
    $('#boot').classList.add('hidden');
    if (lic.state !== 'active') return showLock();
    renderShell(); $('#app').classList.remove('hidden');
    const r = (location.hash || '#/tracking').replace('#/', ''); S.route = TITLES[r] ? r : 'tracking'; renderRoute();
    pollShell(); if (!S.timer) S.timer = setInterval(pollShell, 8000);
  } catch (e) { $('#boot').textContent = 'Could not start: ' + e.message; }
}
window.addEventListener('hashchange', () => { const r = location.hash.replace('#/', ''); if (TITLES[r] && r !== S.route && !$('#app').classList.contains('hidden')) { S.route = r; renderRoute(); } });
document.addEventListener('click', e => { const a = e.target.closest('a[href^="http"]'); if (a) { e.preventDefault(); api('/api/open_url', { url: a.href }); } });
startApp();
