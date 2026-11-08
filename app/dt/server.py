"""Local HTTP server: the UI at /, the JSON API at /api/*. Everything except the license endpoints needs an active license."""
import gzip
import json
import mimetypes
import os
import subprocess
import sys
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import (arsenal, backup, build_info, config, db, delivery, discord, license as lic, inventory, logs, mail, notify, orders, parsers, presence, profiles, updater)

GET, POST = {}, {}
OPEN = {"/api/version", "/api/license/status", "/api/license/activate", "/api/license/server", "/api/clientlog"}


def get(path):
    def d(fn):
        GET[path] = fn
        return fn
    return d


def post(path):
    def d(fn):
        POST[path] = fn
        return fn
    return d


def need_text(b, key, msg):
    v = str(b.get(key) or "").strip()
    if not v:
        raise ValueError(msg)
    return v


def confirm_word(b, word="reset"):
    if str(b.get("confirm") or "").strip().lower() != word:
        raise ValueError(f"Type {word} to confirm")


# ---------------------------------------------------------------- license
@get("/api/version")
def _(c, q):
    return {"name": config.APP_NAME, "version": config.VERSION, "build": build_info.BUILD}


@get("/api/license/status")
def _(c, q):
    return {**lic.status(c), "last_error": lic.last_error()}


@post("/api/license/activate")
def _(c, b):
    try:
        return {"ok": True, **lic.activate(c, b.get("key"), b.get("device_name"), bool(b.get("force")))}
    except lic.LicenseError as e:
        return {"ok": False, "error": str(e), "code": e.code}


@post("/api/license/server")
def _(c, b):
    u = str(b.get("url") or "").strip().rstrip("/")
    if u and not u.startswith(("http://", "https://")):
        raise ValueError("The server address must start with https://")
    db.put(c, "license_url", u)
    db.put(c, "license_pub", "")
    return {"ok": True, "server": lic.server_url(c)}


@post("/api/license/device")
def _(c, b):
    db.put(c, "device_name", need_text(b, "name", "Enter a device name")[:80])
    return {"ok": True}


@post("/api/license/signout")
def _(c, b):
    lic.sign_out(c)
    return {"ok": True}


# ---------------------------------------------------------------- shell
@get("/api/shell")
def _(c, q):
    n = notify.list_notifications(c, 1)["unread"]
    return {"live": mail.live_summary(c), "unread": n, "attention": c.execute("SELECT COUNT(*) FROM attention WHERE resolved=0").fetchone()[0],
            "license": lic.status(c), "discord": {"running": discord.STATE["running"], "error": discord.STATE["error"]},
            "sync": {"running": mail.SYNC["running"]}, "update": updater.STATE["phase"]}


# ---------------------------------------------------------------- tracking
@get("/api/tracking")
def _(c, q):
    o = orders.list_orders(c)
    return {"orders": o, "overview": orders.overview(c, o), "statuses": parsers.STATUS_LABEL, "colors": parsers.RETAILER_COLORS,
            "retailers": sorted(set(parsers.RETAILERS) | {x["retailer"] for x in o})}


@get("/api/orders/detail")
def _(c, q):
    return orders.order_detail(c, int(q["id"][0]))


@post("/api/orders/save")
def _(c, b):
    return {"ok": True, "id": orders.save_manual(c, b, int(b["id"]) if b.get("id") else None)}


@post("/api/orders/status")
def _(c, b):
    orders.set_status(c, [int(i) for i in b["ids"]], b["status"])
    return {"ok": True}


@post("/api/orders/delete")
def _(c, b):
    orders.delete_orders(c, [int(i) for i in b["ids"]])
    return {"ok": True}


@post("/api/orders/move")
def _(c, b):
    orders.move_retailer(c, int(b["id"]), b.get("retailer"))
    return {"ok": True}


@post("/api/orders/merge")
def _(c, b):
    orders.merge(c, int(b["from_id"]), int(b["into_id"]))
    return {"ok": True}


@get("/api/attention")
def _(c, q):
    return mail.list_attention(c)


@post("/api/attention/resolve")
def _(c, b):
    mail.resolve_attention(c, int(b["id"]), b.get("ignore"))
    return {"ok": True}


@post("/api/attention/add")
def _(c, b):
    oid = orders.save_manual(c, b)
    mail.resolve_attention(c, int(b["attention_id"]))
    return {"ok": True, "id": oid}


# ---------------------------------------------------------------- email
@get("/api/mail/accounts")
def _(c, q):
    accts = mail.list_accounts(c)
    for a in accts:
        a["description"] = mail.describe(a)
    return {"accounts": accts, "own": [r["address"] for r in c.execute("SELECT address FROM own_addresses ORDER BY address")], "connected": [a["email"] for a in accts],
            "providers": {k: {"label": v["label"], "hint": v["hint"], "host": v["host"]} for k, v in mail.PROVIDERS.items()}, "sync": {"running": mail.SYNC["running"], "log": mail.SYNC["log"][-8:]}}


@post("/api/mail/accounts/save")
def _(c, b):
    return {"ok": True, "id": mail.save_account(c, b, int(b["id"]) if b.get("id") else None)}


@post("/api/mail/accounts/test")
def _(c, b):
    acct = mail.get_account(c, int(b["id"])) if b.get("id") else dict(b)
    if b.get("id"):
        acct.update({k: b[k] for k in ("host", "port", "username") if b.get(k)})
        if b.get("password"):
            acct["password"] = b["password"]
    else:
        em, prov, host, port = mail._clean(b)
        acct.update(email=em, provider=prov, host=host, port=port, password=str(b.get("password") or "").strip())
    try:
        return {"ok": True, **mail.test_account(acct)}
    except mail.MailError as e:
        return {"ok": False, "error": str(e)}


@post("/api/mail/accounts/bulk")
def _(c, b):
    return {"ok": True, "results": mail.bulk_add(c, b.get("text"), bool(b.get("test", True)))}


@post("/api/mail/accounts/delete")
def _(c, b):
    mail.delete_account(c, int(b["id"]))
    return {"ok": True}


@post("/api/mail/accounts/enable")
def _(c, b):
    mail.set_enabled(c, int(b["id"]), bool(b.get("enabled")))
    return {"ok": True}


@post("/api/mail/sync")
def _(c, b):
    if mail.SYNC["running"]:
        return {"ok": False, "error": "A sync is already running"}
    threading.Thread(target=mail.sync_all, kwargs={"full": bool(b.get("full")), "account_id": int(b["id"]) if b.get("id") else None}, daemon=True).start()
    return {"ok": True}


@get("/api/mail/sync")
def _(c, q):
    return mail.SYNC


@post("/api/mail/import_eml")
def _(c, b):
    return {"ok": True, **mail.import_eml(c, b.get("files") or [])}


@post("/api/mail/own/add")
def _(c, b):
    mail.add_own(c, b.get("address"))
    return {"ok": True}


@post("/api/mail/own/remove")
def _(c, b):
    mail.remove_own(c, b.get("address"))
    return {"ok": True}


# ---------------------------------------------------------------- webhooks / notifications
@get("/api/webhooks")
def _(c, q):
    return {"items": notify.list_webhooks(c), "events": [{"id": k, "label": v} for k, v in notify.EVENTS]}


@post("/api/webhooks/save")
def _(c, b):
    return {"ok": True, "id": notify.save_webhook(c, b, int(b["id"]) if b.get("id") else None)}


@post("/api/webhooks/delete")
def _(c, b):
    notify.delete_webhook(c, int(b["id"]))
    return {"ok": True}


@post("/api/webhooks/test")
def _(c, b):
    return {"ok": True, "result": notify.test_webhook(c, int(b["id"]))}


@get("/api/notifications")
def _(c, q):
    return notify.list_notifications(c)


@post("/api/notifications/read")
def _(c, b):
    notify.mark_read(c, b.get("ids"))
    return {"ok": True}


@post("/api/notifications/clear")
def _(c, b):
    notify.clear(c)
    return {"ok": True}


# ---------------------------------------------------------------- arsenal
@get("/api/arsenal/checkouts")
def _(c, q):
    f = {k: v[0] for k, v in q.items()}
    allrows = arsenal.list_checkouts(c)
    rows = arsenal.filtered(c, f)
    ls = arsenal.lists(c, archived=True)
    return {"items": rows, "stats": arsenal.stats(rows), "retailers": sorted({r["retailer"] for r in allrows if r["retailer"]}),
            "bots": sorted({r["bot"] for r in allrows if r["bot"]} | {b["name"] for b in ls["bots"]}),
            "proxies": sorted({r["proxy_list"] for r in allrows if r["proxy_list"]} | {p["name"] for p in ls["proxy_lists"]}),
            "orders": [{"id": o["id"], "label": f"{o['retailer']} · {o['order_number']}", "retailer": o["retailer"]} for o in db.rows(c, "SELECT id,retailer,order_number FROM orders ORDER BY id DESC LIMIT 300")],
            "has_discord": bool(db.get(c, "discord_bot_token")), "watching": c.execute("SELECT COUNT(*) FROM channels WHERE watched=1").fetchone()[0]}


@post("/api/arsenal/checkouts/save")
def _(c, b):
    return {"ok": True, "id": arsenal.save(c, b, int(b["id"]) if b.get("id") else None)}


@post("/api/arsenal/checkouts/delete")
def _(c, b):
    arsenal.delete(c, [int(i) for i in b["ids"]])
    return {"ok": True}


@post("/api/arsenal/checkouts/restore")
def _(c, b):
    arsenal.restore(c, int(b["id"]) if b.get("id") else None)
    return {"ok": True}


@post("/api/arsenal/checkouts/purge")
def _(c, b):
    arsenal.purge(c)
    return {"ok": True}


@post("/api/arsenal/checkouts/match")
def _(c, b):
    arsenal.match_action(c, int(b["id"]), b.get("action"), int(b["order_id"]) if b.get("order_id") else None)
    return {"ok": True}


@post("/api/arsenal/checkouts/image")
def _(c, b):
    arsenal.set_image(c, int(b["id"]), b.get("data") or "")
    return {"ok": True}


@get("/api/arsenal/deleted")
def _(c, q):
    return arsenal.list_checkouts(c, True)


@post("/api/arsenal/export")
def _(c, b):
    text = arsenal.export_csv(c)
    path = os.path.join(config.exports_dir(), f"checkouts_{time.strftime('%Y-%m-%d')}.csv")
    open(path, "w", encoding="utf-8", newline="").write(text)
    return {"ok": True, "path": path}


@get("/api/arsenal/lists")
def _(c, q):
    return arsenal.lists(c, archived=q.get("archived", ["0"])[0] == "1")


@post("/api/arsenal/bots/save")
def _(c, b):
    return {"ok": True, "id": arsenal.save_bot(c, b, int(b["id"]) if b.get("id") else None)}


@post("/api/arsenal/proxies/save")
def _(c, b):
    return {"ok": True, "id": arsenal.save_proxy_list(c, b, int(b["id"]) if b.get("id") else None)}


@post("/api/arsenal/names/save")
def _(c, b):
    mid, n = arsenal.save_name_map(c, b, int(b["id"]) if b.get("id") else None)
    return {"ok": True, "id": mid, "reattributed": n}


@post("/api/arsenal/remove")
def _(c, b):
    arsenal.remove(c, {"bot": "bots", "proxy": "proxy_lists", "name": "name_maps", "rule": "price_rules"}[b["kind"]], int(b["id"]))
    return {"ok": True}


@post("/api/arsenal/rules/preview")
def _(c, b):
    return {"ok": True, **arsenal.rule_preview(c, b)}


@post("/api/arsenal/rules/save")
def _(c, b):
    rid, n = arsenal.save_rule(c, b, b.get("apply_ids"))
    return {"ok": True, "id": rid, "applied": n}


# ---------------------------------------------------------------- discord
@get("/api/discord/status")
def _(c, q):
    return {**discord.status(c), "servers": discord.list_servers(c)}


@post("/api/discord/token")
def _(c, b):
    try:
        return {"ok": True, "servers": discord.set_token(c, b.get("token"))}
    except discord.DiscordError as e:
        return {"ok": False, "error": str(e)}


@post("/api/discord/refresh")
def _(c, b):
    try:
        return {"ok": True, "servers": discord.refresh_servers(c)}
    except discord.DiscordError as e:
        return {"ok": False, "error": str(e)}


@post("/api/discord/link")
def _(c, b):
    discord.link(c, b["guild_id"], bool(b.get("linked", True)))
    return {"ok": True}


@get("/api/discord/channels")
def _(c, q):
    try:
        return {"ok": True, "channels": discord.list_channels(c, q["guild_id"][0], q.get("refresh", ["1"])[0] == "1")}
    except discord.DiscordError as e:
        return {"ok": False, "error": str(e), "channels": discord.list_channels(c, q["guild_id"][0], False)}


@post("/api/discord/watch")
def _(c, b):
    discord.watch(c, b["channel_id"], bool(b.get("watched")))
    return {"ok": True}


@post("/api/discord/sync")
def _(c, b):
    if discord.STATE["running"]:
        return {"ok": False, "error": "A sync is already running"}
    threading.Thread(target=discord.sync, kwargs={"backfill": bool(b.get("backfill")), "rescan": bool(b.get("rescan"))}, daemon=True).start()
    return {"ok": True}


@post("/api/discord/forget")
def _(c, b):
    for k in ("discord_bot_token", "discord_bot_name", "discord_bot_id"):
        db.put(c, k, "")
    c.execute("DELETE FROM servers")
    c.execute("DELETE FROM channels")
    c.commit()
    return {"ok": True}


# ---------------------------------------------------------------- settings
@get("/api/settings")
def _(c, q):
    return {"version": config.VERSION, "build": build_info.BUILD, "device_name": lic.device_name(c), "license": lic.status(c),
            "presence": {**presence.settings(c), **presence.STATE}, "delivery": {**delivery.settings(c), **{k: delivery.STATE[k] for k in ("last", "error")}},
            "deleted_orders": db.rows(c, "SELECT * FROM deleted_orders ORDER BY id DESC"), "exceptions": db.rows(c, "SELECT * FROM exceptions ORDER BY id DESC"),
            "exception_kinds": orders.KINDS, "deleted_checkouts": arsenal.list_checkouts(c, True), "has_github_token": bool(db.get(c, "github_token")),
            "update_repo": updater.repo(), "exports": config.exports_dir()}


@post("/api/settings/presence")
def _(c, b):
    return {"ok": True, **presence.save(c, b)}


@post("/api/settings/delivery")
def _(c, b):
    return {"ok": True, **delivery.save_settings(c, b)}


@post("/api/delivery/refresh")
def _(c, b):
    threading.Thread(target=delivery.refresh, daemon=True).start()
    return {"ok": True}


@post("/api/exceptions/add")
def _(c, b):
    orders.add_exception(c, b.get("kind"), b.get("value"))
    return {"ok": True}


@post("/api/exceptions/remove")
def _(c, b):
    orders.remove_exception(c, int(b["id"]))
    return {"ok": True}


@post("/api/deleted_orders/restore")
def _(c, b):
    orders.restore_deleted(c, int(b["id"]))
    return {"ok": True}


@post("/api/deleted_orders/purge")
def _(c, b):
    orders.purge_deleted(c)
    return {"ok": True}


@post("/api/logs/export")
def _(c, b):
    text = logs.build(c, bool(b.get("hide_emails", True)))
    path = os.path.join(config.exports_dir(), f"demented-toolbox-logs_{time.strftime('%Y-%m-%d_%H%M%S')}.txt")
    open(path, "w", encoding="utf-8").write(text)
    return {"ok": True, "path": path}


@post("/api/backup/export")
def _(c, b):
    pw = str(b.get("passphrase") or "")
    if b.get("include_passwords") and len(pw) < 6:
        raise ValueError("Set a passphrase of at least 6 characters to include email passwords.")
    text = backup.export(c, pw if b.get("include_passwords") else "")
    path = os.path.join(config.exports_dir(), f"demented-toolbox-backup_{time.strftime('%Y-%m-%d_%H%M%S')}.json")
    open(path, "w", encoding="utf-8").write(text)
    return {"ok": True, "path": path, "encrypted": bool(b.get("include_passwords"))}


@post("/api/backup/inspect")
def _(c, b):
    return {"ok": True, "encrypted": backup.is_encrypted(b.get("text") or "")}


@post("/api/backup/import")
def _(c, b):
    return {"ok": True, "rows": backup.import_(c, b.get("text") or "", str(b.get("passphrase") or ""))}


@post("/api/reset/tracker")
def _(c, b):
    confirm_word(b)
    keep = {"deleted_orders"}
    n = db.wipe_tables(c, db.TRACKER_TABLES)
    c.execute("DELETE FROM settings WHERE key LIKE 'wm:%'")
    c.execute("UPDATE checkouts SET link_order_id=NULL, match_status='unmatched'")
    c.commit()
    return {"ok": True, "removed": n}


@post("/api/reset/arsenal")
def _(c, b):
    confirm_word(b)
    n = db.wipe_tables(c, db.ARSENAL_TABLES)
    return {"ok": True, "removed": n}


@post("/api/fresh_start")
def _(c, b):
    if str(b.get("confirm") or "").strip().upper() != "FRESH START":
        raise ValueError("Type FRESH START to confirm")
    keep = {k: db.get(c, k) for k in ("license_token", "license_pub", "license_url", "device_name", "github_token")}
    tables = [r[0] for r in c.execute("SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")]
    n = db.wipe_tables(c, tables)
    for k, v in keep.items():
        if v:
            db.put(c, k, v)
    return {"ok": True, "removed": n}



# ---------------------------------------------------------------- profiles & site accounts
def _export_file(name, obj):
    path = os.path.join(config.exports_dir(), f"{name}_{time.strftime('%Y-%m-%d_%H%M%S')}.json")
    open(path, "w", encoding="utf-8").write(json.dumps(obj, indent=2))
    return {"ok": True, "path": path, "count": len(obj.get("accounts", obj)) if isinstance(obj, dict) else 0}


def _ids(b):
    return [str(i) for i in (b.get("ids") or [])]


@get("/api/vault")
def _(c, q):
    return {"profiles": profiles.list_profiles(c), "accounts": profiles.list_accounts(c), "groups": profiles.groups(c)}


@post("/api/profiles/save")
def _(c, b):
    return {"ok": True, "id": profiles.save_profile(c, str(b.get("site") or ""), b.get("rec") or {}, b.get("id"))}


@post("/api/profiles/import")
def _(c, b):
    return {"ok": True, **profiles.import_profiles(c, need_text(b, "site", "Pick a group first"), b.get("text") or "", bool(b.get("replace")))}


@post("/api/profiles/export")
def _(c, b):
    return _export_file("profiles", profiles.export_profiles(c, b.get("site") or None, _ids(b) or None))


@post("/api/profiles/delete")
def _(c, b):
    return {"ok": True, "removed": profiles.delete_profiles(c, _ids(b))}


@post("/api/profiles/patch")
def _(c, b):
    return {"ok": True, "updated": profiles.patch_profiles(c, _ids(b), b.get("changes") or {})}


@post("/api/profiles/move")
def _(c, b):
    profiles.move_profiles(c, _ids(b), str(b.get("site") or ""))
    return {"ok": True}


@post("/api/profiles/rejig")
def _(c, b):
    v = profiles.rejig(c, str(b.get("id") or ""), b.get("count") or 10, bool(b.get("use_units", True)), b.get("seed") or None, bool(b.get("save")), bool(b.get("replace", True)))
    return {"ok": True, "variants": v}


@post("/api/profiles/address")
def _(c, b):
    units = [u.strip() for u in str(b.get("units") or "").replace(",", "\n").splitlines() if u.strip()]
    return {"ok": True, **profiles.bulk_address(c, _ids(b), b.get("addr") or {}, bool(b.get("unique")), b.get("seed") or None, bool(b.get("use_units", True)), b.get("target") or "both", units or None)}


@post("/api/siteaccounts/save")
def _(c, b):
    return {"ok": True, "id": profiles.save_account(c, str(b.get("site") or ""), b.get("rec") or {}, b.get("old_id"))}


@post("/api/siteaccounts/add")
def _(c, b):
    return {"ok": True, **profiles.add_accounts_text(c, need_text(b, "site", "Pick a group first"), b.get("text"))}


@post("/api/siteaccounts/import")
def _(c, b):
    return {"ok": True, **profiles.import_accounts(c, b.get("text") or "", b.get("site") or None, bool(b.get("replace")))}


@post("/api/siteaccounts/export")
def _(c, b):
    return _export_file("accounts", profiles.export_accounts(c, need_text(b, "site", "Pick a group first"), _ids(b) or None))


@post("/api/siteaccounts/delete")
def _(c, b):
    return {"ok": True, "removed": profiles.delete_accounts(c, str(b.get("site") or ""), _ids(b))}


@post("/api/siteaccounts/patch")
def _(c, b):
    return {"ok": True, "updated": profiles.patch_accounts(c, str(b.get("site") or ""), _ids(b), b.get("changes") or {})}


@post("/api/vault/group")
def _(c, b):
    kind, op = str(b.get("kind") or ""), str(b.get("op") or "")
    if kind not in ("acc", "prof"):
        raise ValueError("Unknown group type")
    if op == "add":
        return {"ok": True, "name": profiles.add_group(c, kind, b.get("name"))}
    if op == "rename":
        return {"ok": True, "name": profiles.rename_group(c, kind, str(b.get("old") or ""), b.get("name"))}
    if op == "delete":
        return {"ok": True, "removed": profiles.delete_group(c, kind, str(b.get("name") or ""))}
    raise ValueError("Unknown action")

@post("/api/clientlog")
def _(c, b):
    try:
        open(os.path.join(config.DATA_DIR, "app.log"), "a", encoding="utf-8").write(time.strftime("%Y-%m-%d %H:%M:%S ") + "[ui] " + str(b.get("msg") or "")[:3000] + "\n")
    except Exception:
        pass
    return {"ok": True}



# ---------------------------------------------------------------- inventory
@get("/api/inv/dashboard")
def _(c, q):
    return inventory.dashboard(c)


@get("/api/inv/items")
def _(c, q):
    return {"items": inventory.list_items(c), "lists": inventory.lists(c), "settings": inventory.settings(c)}


@get("/api/inv/sales")
def _(c, q):
    fx = {r["code"]: r["rate"] for r in inventory.list_currencies(c)}
    items = [{"sku": i["sku"], "name": i["name"], "unit_cost": i["purchase_price"] * fx.get(i["currency"], 1.0), "left": i["qty_remaining"], "listed": i["listed_price"], "platform": i["listing_platform"]} for i in inventory.list_items(c)]
    return {"sales": inventory.list_sales(c), "lists": inventory.lists(c), "fees": {f["platform"]: f for f in inventory.list_fees(c)}, "items": items}


@get("/api/inv/receipts")
def _(c, q):
    return {"receipts": inventory.list_receipts(c), "lists": inventory.lists(c)}


@get("/api/inv/tax")
def _(c, q):
    y = int((q.get("year") or [0])[0] or 0) or inventory.settings(c)["tax_year"] or __import__("datetime").date.today().year
    return inventory.tax_summary(c, y)


@get("/api/inv/settings")
def _(c, q):
    return {"settings": inventory.settings(c), "fees": inventory.list_fees(c), "currencies": inventory.list_currencies(c)}


@get("/api/inv/scans")
def _(c, q):
    return {"scans": inventory.list_scans(c), "team": inventory.team(c)}


@post("/api/inv/items/save")
def _(c, b):
    return {"ok": True, "id": inventory.save_item(c, b.get("item") or {}, int(b["id"]) if b.get("id") else None)}


@post("/api/inv/items/delete")
def _(c, b):
    return {"ok": True, **inventory.delete_items(c, [int(i) for i in b.get("ids") or []])}


@post("/api/inv/sales/save")
def _(c, b):
    return {"ok": True, **inventory.save_sale(c, b.get("sale") or {}, int(b["id"]) if b.get("id") else None)}


@post("/api/inv/sales/delete")
def _(c, b):
    inventory.delete_sales(c, [int(i) for i in b.get("ids") or []])
    return {"ok": True}


@post("/api/inv/receipts/save")
def _(c, b):
    inventory.save_receipt(c, b.get("receipt") or {}, int(b["id"]) if b.get("id") else None)
    return {"ok": True}


@post("/api/inv/receipts/delete")
def _(c, b):
    inventory.delete_receipts(c, [int(i) for i in b.get("ids") or []])
    return {"ok": True}


@post("/api/inv/scan")
def _(c, b):
    return {"ok": True, **inventory.scan(c, str(b.get("mode") or ""), b.get("code") or "", str(b.get("sold_by") or ""))}


@post("/api/inv/settings/save")
def _(c, b):
    return {"ok": True, "settings": inventory.save_settings(c, b.get("settings") or {})}


@post("/api/inv/fee/save")
def _(c, b):
    inventory.save_fee(c, b.get("fee") or {}, b.get("old") or None)
    return {"ok": True}


@post("/api/inv/fee/delete")
def _(c, b):
    inventory.delete_fee(c, str(b.get("platform") or ""))
    return {"ok": True}


@post("/api/inv/currency/save")
def _(c, b):
    inventory.save_currency(c, b.get("currency") or {})
    return {"ok": True}


@post("/api/inv/currency/delete")
def _(c, b):
    inventory.delete_currency(c, str(b.get("code") or ""))
    return {"ok": True}


@post("/api/inv/csv/export")
def _(c, b):
    name = str(b.get("name") or "")
    text = inventory.export_csv(c, name)
    path = os.path.join(config.exports_dir(), f"inventory-{name}_{time.strftime('%Y-%m-%d_%H%M%S')}.csv")
    open(path, "w", encoding="utf-8", newline="").write(text)
    return {"ok": True, "path": path}


@post("/api/inv/csv/import")
def _(c, b):
    return {"ok": True, **inventory.import_csv(c, str(b.get("name") or ""), b.get("text") or "")}


@post("/api/inv/reset")
def _(c, b):
    confirm_word(b)
    n = db.wipe_tables(c, ["inv_items", "inv_sales", "inv_receipts", "inv_scans", "inv_order_links"])
    return {"ok": True, "removed": n}

# ---------------------------------------------------------------- updates / misc
@get("/api/update/check")
def _(c, q):
    return updater.check(db.get(c, "github_token"))


@get("/api/update/status")
def _(c, q):
    return {**updater.STATE, "build": build_info.BUILD}


@post("/api/update/download")
def _(c, b):
    return updater.start_download(b.get("url", ""), db.get(c, "github_token"), int(b.get("size") or 0))


@post("/api/update/install")
def _(c, b):
    return updater.install()


@post("/api/update/token")
def _(c, b):
    db.put(c, "github_token", str(b.get("token") or "").strip())
    return {"ok": True}


@post("/api/open_url")
def _(c, b):
    url = str(b.get("url", ""))
    if not url.startswith(("https://", "http://")):
        raise ValueError("Only web links can be opened")
    import webbrowser
    webbrowser.open(url)
    return {"ok": True}


@post("/api/open_folder")
def _(c, b):
    d = config.exports_dir()
    try:
        if os.name == "nt":
            os.startfile(d)  # noqa
        elif sys.platform == "darwin":
            subprocess.Popen(["open", d])
    except Exception:
        pass
    return {"ok": True, "path": d}


# ---------------------------------------------------------------- HTTP plumbing
UI = {"ok": 0.0}  # when the window last got a complete answer from /api/shell (the watchdog in main.py uses it)


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"
    timeout = 60

    def log_message(self, *a):
        pass

    def _write(self, data, ctype, code=200, cache="no-cache"):
        gz = len(data) > 1500 and "gzip" in (self.headers.get("Accept-Encoding") or "")
        body = gzip.compress(data, 1) if gz else data
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(body)))
        if gz:
            self.send_header("Content-Encoding", "gzip")
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(body)

    def send(self, obj, code=200):
        self._write(json.dumps(obj).encode(), "application/json", code)

    def _crash(self):
        import traceback
        tb = traceback.format_exc()
        try:
            open(os.path.join(config.DATA_DIR, "app.log"), "a", encoding="utf-8").write(time.strftime("%Y-%m-%d %H:%M:%S ") + self.path + "\n" + tb + "\n")
        except Exception:
            pass
        try:
            self.send({"error": "Internal error: " + tb.strip().splitlines()[-1]}, 500)
        except Exception:
            pass

    def _dispatch(self, table, arg):
        u = urlparse(self.path)
        fn = table.get(u.path)
        if not fn:
            return self.send({"error": "not found"}, 404)
        c = db.connect()
        try:
            if u.path not in OPEN and not lic.is_active(c):
                return self.send({"error": "A valid license is required.", "locked": True}, 403)
            r = self.send(fn(c, arg(u)))
            if u.path == "/api/shell":
                UI["ok"] = time.time()
            return r
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as e:
            self.send({"error": str(e) if isinstance(e, ValueError) else f"{type(e).__name__}: {e}"}, 400)
        except (mail.MailError, discord.DiscordError, lic.LicenseError) as e:
            self.send({"error": str(e)}, 400)
        finally:
            c.close()

    def do_GET(self):
        try:
            u = urlparse(self.path)
            if u.path.startswith("/api/"):
                return self._dispatch(GET, lambda u: parse_qs(u.query))
            f = "index.html" if u.path in ("/", "") else u.path.lstrip("/")
            p = os.path.normpath(os.path.join(config.WEB_DIR, f))
            if not p.startswith(os.path.normpath(config.WEB_DIR)) or not os.path.isfile(p):
                return self.send({"error": "not found"}, 404)
            self._write(open(p, "rb").read(), (mimetypes.guess_type(p)[0] or "text/plain") + ("; charset=utf-8" if p.endswith((".html", ".js", ".css")) else ""))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self._crash()

    def do_POST(self):
        try:
            n = int(self.headers.get("Content-Length") or 0)
            raw = self.rfile.read(n) or b"{}"
            self._dispatch(POST, lambda u: json.loads(raw))
        except (BrokenPipeError, ConnectionResetError):
            pass
        except Exception:
            self._crash()


class _Srv(ThreadingHTTPServer):
    """On Windows SO_REUSEADDR lets two programs share one port, so right after an update the new app could attach to the port of the
    dying old one and every request hung. Bind exclusively instead."""
    allow_reuse_address = False
    daemon_threads = True

    def server_bind(self):
        if os.name == "nt":
            import socket
            try:
                self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            except Exception:
                pass
        super().server_bind()


def make_server(port=8765):
    db.connect().close()
    deadline = time.time() + 8  # the previous instance may still be closing: give it a few seconds to free the preferred port
    while True:
        try:
            return _Srv(("127.0.0.1", port), H), port
        except OSError:
            if time.time() > deadline:
                break
            time.sleep(0.4)
    for p in range(port + 1, port + 30):
        try:
            return _Srv(("127.0.0.1", p), H), p
        except OSError:
            continue
    raise RuntimeError("No free port found")


def start_background():
    for fn in (mail.live_loop, discord.poll_loop, delivery.poll_loop, presence.loop, lic.refresh_loop):
        threading.Thread(target=fn, daemon=True).start()
