"""Support log: a text file describing what the app has seen. Email subjects are never included."""
import os
import platform
import re

from . import config, db, discord, mail, notify, updater

EMAIL = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
SECRET = re.compile(r"(https://(?:\w+\.)?discord(?:app)?\.com/api/webhooks/\S+|[A-Za-z0-9_\-]{24,}\.[A-Za-z0-9_\-]{6,}\.[A-Za-z0-9_\-]{20,}|(?i:password|token|secret|passphrase)\s*[:=]\s*\S+)")


def build(c, hide_emails=True):
    L = [f"{config.APP_NAME} {config.VERSION} (build {updater.build_info.BUILD})", f"System: {platform.system()} {platform.release()} · Python {platform.python_version()}",
         f"Generated: {db.now()}", ""]
    accts = db.rows(c, "SELECT * FROM mail_accounts ORDER BY id")
    L.append(f"== Email accounts ({len(accts)}) ==")
    for a in accts:
        L.append(f"- {a['email']} · {a['provider']} · {a['host']}:{a['port']} · {'enabled' if a['enabled'] else 'paused'} · last checked {a['last_checked'] or 'never'} · "
                 f"{('error: ' + a['last_error']) if a['last_error'] else 'ok'}")
    L.append("")
    L.append("== Orders ==")
    for st, n in c.execute("SELECT status, COUNT(*) FROM orders GROUP BY status"):
        L.append(f"- {st}: {n}")
    for r, n in c.execute("SELECT retailer, COUNT(*) FROM orders GROUP BY retailer"):
        L.append(f"- retailer {r}: {n}")
    L.append("")
    L.append("== Recent emails the app looked at (newest first, no subjects) ==")
    for r in db.rows(c, "SELECT ts, retailer, outcome FROM processed ORDER BY ts DESC LIMIT 80"):
        L.append(f"- {r['ts']} · {r['retailer'] or '-'} · {r['outcome']}")
    L.append("")
    L.append("== Needs attention ==")
    for r in db.rows(c, "SELECT reason, guess, created_at FROM attention WHERE resolved=0 ORDER BY id DESC LIMIT 40"):
        L.append(f"- {r['created_at']} · {r['guess'] or '?'} · {r['reason']}")
    L.append("")
    L.append("== Exceptions ==")
    for r in db.rows(c, "SELECT kind,value FROM exceptions"):
        L.append(f"- {r['kind']}: {r['value']}")
    L.append("")
    L.append("== Webhooks ==")
    for w in notify.list_webhooks(c):
        L.append(f"- {w['name']} · {'on' if w['enabled'] else 'off'} · events: {', '.join(w['events']) or 'none'} · last: {w['last_status'] or '-'}")
    L.append("")
    L.append("== Discord / Arsenal ==")
    st = discord.status(c)
    L.append(f"- bot token: {'set' if st['bot']['has_token'] else 'not set'} · watching {st['watching']} channel(s) · last sync {st['last'] or 'never'} · error: {st['error'] or 'none'}")
    for s in db.rows(c, "SELECT name,linked FROM servers"):
        L.append(f"- server {s['name']} · {'linked' if s['linked'] else 'not linked'}")
    n = c.execute("SELECT COUNT(*) FROM checkouts WHERE deleted_at IS NULL").fetchone()[0]
    L.append(f"- checkouts: {n}")
    L.append("")
    p = os.path.join(config.DATA_DIR, "app.log")
    if os.path.exists(p):
        L.append("== app.log (last 60 lines) ==")
        try:
            L += open(p, encoding="utf-8", errors="replace").read().splitlines()[-60:]
        except OSError:
            pass
    text = "\n".join(L)
    text = SECRET.sub("[removed]", text)
    if hide_emails:
        labels = {}
        order = [a["email"].lower() for a in accts]
        for e in order:
            labels.setdefault(e, f"account{len(labels) + 1}")
        def sub(m):
            e = m.group(0).lower()
            return labels.setdefault(e, f"account{len(labels) + 1}")
        text = EMAIL.sub(sub, text)
    return text
