"""Notifications: the bell in the app, Windows toasts, and Discord webhooks you own."""
import json
import os
import subprocess
import threading
import urllib.error
import urllib.request

from . import config, db
from .parsers import STATUS_LABEL

EVENTS = [("placed", "Order placed"), ("shipped", "Shipped"), ("out_for_delivery", "Out for delivery"), ("delivered", "Delivered"),
          ("cancelled", "Cancelled"), ("partially_cancelled", "Partially cancelled"), ("refunded", "Refunded"),
          ("attention", "Needs attention"), ("checkout", "New checkout")]
COLORS = {"placed": 0x4C8DF6, "shipped": 0xF5A524, "out_for_delivery": 0xF5A524, "delivered": 0x34D399, "cancelled": 0xE5304F,
          "partially_cancelled": 0xE5304F, "refunded": 0xA78BFA, "attention": 0xF5A524, "checkout": 0x34D399, "test": 0x8A8A99}


def valid_webhook(url):
    return bool(url) and url.startswith(("https://discord.com/api/webhooks/", "https://discordapp.com/api/webhooks/", "https://canary.discord.com/api/webhooks/", "https://ptb.discord.com/api/webhooks/"))


def post_webhook(url, payload, timeout=10):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method="POST",
                                 headers={"Content-Type": "application/json", "User-Agent": "DementedToolbox (local app)"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return "ok" if r.status < 300 else f"HTTP {r.status}"
    except urllib.error.HTTPError as e:
        return f"HTTP {e.code}"
    except Exception as e:
        return f"failed: {type(e).__name__}"


def list_webhooks(c):
    out = []
    for r in c.execute("SELECT * FROM webhooks ORDER BY id"):
        d = dict(r)
        d["events"] = json.loads(d["events"] or "[]")
        d["enabled"] = bool(d["enabled"])
        u = d["url"]
        d["url_masked"] = u[:36] + "…" + u[-6:] if len(u) > 50 else u
        out.append(d)
    return out


def save_webhook(c, d, wid=None):
    url = str(d.get("url") or "").strip()
    if not wid and not valid_webhook(url):
        raise ValueError("That doesn't look like a Discord webhook URL (it starts with https://discord.com/api/webhooks/)")
    if wid and url and not valid_webhook(url):
        raise ValueError("That doesn't look like a Discord webhook URL")
    ev = [e for e in (d.get("events") or []) if e in dict(EVENTS)]
    name = str(d.get("name") or "").strip()[:60] or "Webhook"
    if wid:
        old = c.execute("SELECT url FROM webhooks WHERE id=?", (wid,)).fetchone()
        if not old:
            raise ValueError("That webhook no longer exists")
        c.execute("UPDATE webhooks SET name=?, url=?, events=?, enabled=? WHERE id=?",
                  (name, url or old["url"], json.dumps(ev), 1 if d.get("enabled", True) else 0, wid))
    else:
        wid = c.execute("INSERT INTO webhooks(name,url,events,enabled) VALUES(?,?,?,?)", (name, url, json.dumps(ev), 1 if d.get("enabled", True) else 0)).lastrowid
    c.commit()
    return wid


def delete_webhook(c, wid):
    c.execute("DELETE FROM webhooks WHERE id=?", (wid,))
    c.commit()


def test_webhook(c, wid):
    w = c.execute("SELECT * FROM webhooks WHERE id=?", (wid,)).fetchone()
    if not w:
        raise ValueError("That webhook no longer exists")
    res = post_webhook(w["url"], {"username": config.APP_NAME, "embeds": [{"title": "Test notification", "description": "If you can read this, your webhook works.",
                                                                           "color": COLORS["test"], "footer": {"text": config.APP_NAME}}]})
    c.execute("UPDATE webhooks SET last_status=? WHERE id=?", (res, wid))
    c.commit()
    return res


def toast(title, body):
    if os.name != "nt" or os.environ.get("DT_NO_TOAST"):
        return
    def run():
        try:
            esc = lambda s: str(s).replace("'", "''").replace("&", "&amp;").replace("<", "&lt;")
            ps = ("[Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType = WindowsRuntime] | Out-Null;"
                  "$t=[Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02);"
                  f"$n=$t.GetElementsByTagName('text');$n.Item(0).AppendChild($t.CreateTextNode('{esc(title)}'))|Out-Null;$n.Item(1).AppendChild($t.CreateTextNode('{esc(body)}'))|Out-Null;"
                  "[Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('Demented Toolbox').Show([Windows.UI.Notifications.ToastNotification]::new($t))")
            subprocess.run(["powershell", "-NoProfile", "-WindowStyle", "Hidden", "-Command", ps], timeout=15, creationflags=0x08000000)
        except Exception:
            pass
    threading.Thread(target=run, daemon=True).start()


def notify(c, kind, title, body="", link="", dedupe=None, fields=None, push=True):
    """Record in the bell, toast it, and send it to every webhook subscribed to this kind of event."""
    if dedupe:
        if c.execute("SELECT 1 FROM notifications WHERE dedupe=?", (dedupe,)).fetchone():
            return False
    c.execute("INSERT INTO notifications(ts,kind,title,body,link,dedupe) VALUES(?,?,?,?,?,?)", (db.now(), kind, title, body, link, dedupe))
    c.commit()
    if push:
        toast(title, body)
        hooks = [w for w in list_webhooks(c) if w["enabled"] and kind in w["events"]]
        if hooks:
            emb = {"title": title[:250], "description": body[:1800], "color": COLORS.get(kind, 0x8A8A99), "footer": {"text": config.APP_NAME},
                   "fields": [{"name": k, "value": str(v)[:200], "inline": True} for k, v in (fields or {}).items() if v not in (None, "")][:8]}
            def send():
                for w in hooks:
                    post_webhook(w["url"], {"username": config.APP_NAME, "embeds": [emb]})
            threading.Thread(target=send, daemon=True).start()
    return True


def list_notifications(c, limit=60):
    return {"items": db.rows(c, "SELECT * FROM notifications ORDER BY id DESC LIMIT ?", (limit,)),
            "unread": c.execute("SELECT COUNT(*) FROM notifications WHERE read=0").fetchone()[0]}


def mark_read(c, ids=None):
    if ids:
        c.execute(f"UPDATE notifications SET read=1 WHERE id IN ({','.join('?' * len(ids))})", [int(i) for i in ids])
    else:
        c.execute("UPDATE notifications SET read=1")
    c.commit()


def clear(c):
    c.execute("DELETE FROM notifications")
    c.commit()
