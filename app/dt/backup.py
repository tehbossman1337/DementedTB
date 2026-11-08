"""Backup / move to another computer: one file with everything. Secrets (email passwords, bot token, webhook URLs, API keys)
are only included when you set a passphrase - and then the whole file is encrypted."""
import base64
import hashlib
import json
import os

from . import db

SECRET_SETTINGS = ("discord_bot_token", "delivery_key")
LOCAL_ONLY = ("license_token", "license_pub", "license_url", "device_name", "github_token")
FORMAT = "dt-backup"
TABLES = ["mail_accounts", "own_addresses", "orders", "order_items", "order_events", "processed", "attention", "deleted_orders", "exceptions", "webhooks",
          "notifications", "servers", "channels", "checkouts", "deleted_checkout_keys", "bots", "proxy_lists", "name_maps", "price_rules", "vprofiles", "vaccounts"]


def _key(passphrase, salt):
    return base64.urlsafe_b64encode(hashlib.pbkdf2_hmac("sha256", passphrase.encode(), salt, 300_000, 32))


def export(c, passphrase=""):
    secrets = bool(passphrase)
    data = {"format": FORMAT, "version": 1, "created": db.now(), "tables": {}, "settings": {}}
    for t in TABLES:
        rows = db.rows(c, f'SELECT * FROM "{t}"')
        for r in rows:
            if not secrets:
                if t == "mail_accounts":
                    r["password"] = ""
                if t == "webhooks":
                    r["url"] = ""
                if t == "vaccounts":
                    rec = json.loads(r["data"])
                    rec["password"] = ""
                    r["data"] = json.dumps(rec)
                if t == "vprofiles":
                    rec = json.loads(r["data"])
                    rec.get("card", {}).update(number="", cvv="")
                    r["data"] = json.dumps(rec)
        data["tables"][t] = rows
    for r in c.execute("SELECT key,value FROM settings"):
        k = r["key"]
        if k in LOCAL_ONLY or k.startswith("wm:") or (k in SECRET_SETTINGS and not secrets):
            continue
        data["settings"][k] = r["value"]
    raw = json.dumps(data).encode()
    if not passphrase:
        return raw.decode()
    from cryptography.fernet import Fernet
    salt = os.urandom(16)
    tok = Fernet(_key(passphrase, salt)).encrypt(raw)
    return json.dumps({"format": FORMAT, "encrypted": True, "salt": base64.b64encode(salt).decode(), "data": tok.decode()})


def is_encrypted(text):
    try:
        return bool(json.loads(text).get("encrypted"))
    except ValueError:
        return False


def load(text, passphrase=""):
    try:
        j = json.loads(text)
    except ValueError:
        raise ValueError("That file isn't a Demented Toolbox backup.")
    if j.get("format") != FORMAT:
        raise ValueError("That file isn't a Demented Toolbox backup.")
    if j.get("encrypted"):
        if not passphrase:
            raise ValueError("This backup is encrypted. Enter its passphrase.")
        from cryptography.fernet import Fernet, InvalidToken
        try:
            j = json.loads(Fernet(_key(passphrase, base64.b64decode(j["salt"]))).decrypt(j["data"].encode()))
        except InvalidToken:
            raise ValueError("Wrong passphrase.")
    return j


def import_(c, text, passphrase=""):
    j = load(text, passphrase)
    n = 0
    c.execute("PRAGMA foreign_keys=OFF")
    try:
        for t in TABLES:
            if t not in j["tables"]:
                continue
            c.execute(f'DELETE FROM "{t}"')
            cols = [r[1] for r in c.execute(f'PRAGMA table_info("{t}")')]
            for r in j["tables"][t]:
                use = [k for k in r if k in cols]
                if t == "mail_accounts" and not r.get("password"):
                    pass
                c.execute(f'INSERT OR REPLACE INTO "{t}"({",".join(use)}) VALUES({",".join("?" * len(use))})', [r[k] for k in use])
                n += 1
        for k, v in (j.get("settings") or {}).items():
            if k not in LOCAL_ONLY:
                c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (k, v))
        c.commit()
    except Exception:
        c.rollback()
        raise
    finally:
        c.execute("PRAGMA foreign_keys=ON")
    return n
