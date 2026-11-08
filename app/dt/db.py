"""SQLite schema and small helpers."""
import json
import sqlite3
import threading
from datetime import datetime

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT);
CREATE TABLE IF NOT EXISTS mail_accounts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, email TEXT NOT NULL, username TEXT DEFAULT '', provider TEXT DEFAULT 'custom',
  host TEXT DEFAULT '', port INTEGER DEFAULT 993, password TEXT DEFAULT '', enabled INTEGER DEFAULT 1,
  status TEXT DEFAULT '', last_checked TEXT DEFAULT '', last_error TEXT DEFAULT '', created_at TEXT);
CREATE TABLE IF NOT EXISTS own_addresses(id INTEGER PRIMARY KEY AUTOINCREMENT, address TEXT NOT NULL UNIQUE);
CREATE TABLE IF NOT EXISTS orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT, retailer TEXT NOT NULL, order_number TEXT NOT NULL, status TEXT NOT NULL DEFAULT 'placed',
  order_date TEXT, total REAL, tracking TEXT DEFAULT '', carrier TEXT DEFAULT '', account TEXT DEFAULT '', product TEXT DEFAULT '',
  qty INTEGER DEFAULT 1, source TEXT DEFAULT 'email', image TEXT DEFAULT '', delivery_detail TEXT DEFAULT '', eta TEXT DEFAULT '',
  notes TEXT DEFAULT '', track_registered INTEGER DEFAULT 0, track_error TEXT DEFAULT '', created_at TEXT, updated_at TEXT, UNIQUE(retailer, order_number));
CREATE TABLE IF NOT EXISTS order_items(
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  name TEXT NOT NULL, qty INTEGER DEFAULT 1, unit_price REAL DEFAULT 0, sku TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_oi ON order_items(order_id);
CREATE INDEX IF NOT EXISTS idx_orders_key ON orders(retailer, order_number);
CREATE TABLE IF NOT EXISTS order_events(
  id INTEGER PRIMARY KEY AUTOINCREMENT, order_id INTEGER NOT NULL REFERENCES orders(id) ON DELETE CASCADE,
  ts TEXT, status TEXT, note TEXT DEFAULT '');
CREATE INDEX IF NOT EXISTS idx_oe ON order_events(order_id);
CREATE TABLE IF NOT EXISTS processed(message_id TEXT PRIMARY KEY, account TEXT, retailer TEXT, outcome TEXT, ts TEXT);
CREATE INDEX IF NOT EXISTS idx_processed_acct ON processed(account);
CREATE TABLE IF NOT EXISTS attention(
  id INTEGER PRIMARY KEY AUTOINCREMENT, message_id TEXT UNIQUE, account TEXT, sender TEXT, subject TEXT, reason TEXT,
  snippet TEXT, guess TEXT DEFAULT '', created_at TEXT, resolved INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS deleted_orders(
  id INTEGER PRIMARY KEY AUTOINCREMENT, retailer TEXT, order_number TEXT, product TEXT DEFAULT '', total REAL, deleted_at TEXT,
  UNIQUE(retailer, order_number));
CREATE TABLE IF NOT EXISTS exceptions(id INTEGER PRIMARY KEY AUTOINCREMENT, kind TEXT NOT NULL, value TEXT NOT NULL, UNIQUE(kind, value));
CREATE TABLE IF NOT EXISTS webhooks(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT DEFAULT '', url TEXT NOT NULL, events TEXT DEFAULT '[]', enabled INTEGER DEFAULT 1,
  last_status TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS notifications(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, kind TEXT, title TEXT, body TEXT, link TEXT DEFAULT '', read INTEGER DEFAULT 0,
  dedupe TEXT UNIQUE);
CREATE TABLE IF NOT EXISTS servers(
  id INTEGER PRIMARY KEY AUTOINCREMENT, guild_id TEXT NOT NULL UNIQUE, name TEXT, icon TEXT DEFAULT '', linked INTEGER DEFAULT 0);
CREATE TABLE IF NOT EXISTS channels(
  id INTEGER PRIMARY KEY AUTOINCREMENT, channel_id TEXT NOT NULL UNIQUE, guild_id TEXT, name TEXT, watched INTEGER DEFAULT 0,
  last_message_id TEXT DEFAULT '', last_sync TEXT DEFAULT '', error TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS checkouts(
  id INTEGER PRIMARY KEY AUTOINCREMENT, ts TEXT, product TEXT NOT NULL, store TEXT DEFAULT '', size TEXT DEFAULT '', qty INTEGER DEFAULT 1,
  price REAL, price_source TEXT DEFAULT '', bot TEXT DEFAULT '', profile TEXT DEFAULT '', proxy_list TEXT DEFAULT '', status TEXT DEFAULT 'success',
  order_number TEXT DEFAULT '', email TEXT DEFAULT '', image TEXT DEFAULT '', source TEXT DEFAULT 'manual', message_id TEXT,
  webhook_name TEXT DEFAULT '', link_order_id INTEGER, match_status TEXT DEFAULT 'unmatched', bot_manual INTEGER DEFAULT 0,
  channel_id TEXT DEFAULT '', notes TEXT DEFAULT '', deleted_at TEXT, created_at TEXT);
CREATE UNIQUE INDEX IF NOT EXISTS idx_co_msg ON checkouts(message_id) WHERE message_id IS NOT NULL;
CREATE TABLE IF NOT EXISTS deleted_checkout_keys(message_id TEXT PRIMARY KEY);
CREATE TABLE IF NOT EXISTS vprofiles(id TEXT PRIMARY KEY, site TEXT NOT NULL, parent_id TEXT, name TEXT, email TEXT, data TEXT NOT NULL, created_at TEXT);
CREATE INDEX IF NOT EXISTS idx_vp_site ON vprofiles(site);
CREATE TABLE IF NOT EXISTS vaccounts(site TEXT NOT NULL, id TEXT NOT NULL, email TEXT, data TEXT NOT NULL, PRIMARY KEY(site,id));
CREATE TABLE IF NOT EXISTS inv_items(
  id INTEGER PRIMARY KEY, sku TEXT NOT NULL UNIQUE, category TEXT DEFAULT 'Pokemon Card', name TEXT NOT NULL, pokemon_set TEXT DEFAULT '', card_no TEXT DEFAULT '',
  condition TEXT DEFAULT '', grading TEXT DEFAULT '', qty INTEGER DEFAULT 1, added_by TEXT DEFAULT '', purchase_date TEXT DEFAULT '', purchase_price REAL DEFAULT 0,
  purchase_source TEXT DEFAULT '', listing_platform TEXT DEFAULT '', listed_price REAL DEFAULT 0, currency TEXT DEFAULT 'USD', market_price REAL DEFAULT 0,
  location TEXT DEFAULT '', notes TEXT DEFAULT '', barcode TEXT DEFAULT '', created_at TEXT, updated_at TEXT);
CREATE TABLE IF NOT EXISTS inv_sales(
  id INTEGER PRIMARY KEY, sku TEXT NOT NULL, sale_date TEXT, sold_by TEXT DEFAULT '', platform TEXT DEFAULT '', buyer TEXT DEFAULT '', sale_price REAL DEFAULT 0,
  ship_charged REAL DEFAULT 0, ship_cost REAL DEFAULT 0, other_fees REAL DEFAULT 0, qty INTEGER DEFAULT 1, notes TEXT DEFAULT '', created_at TEXT);
CREATE INDEX IF NOT EXISTS idx_inv_sales_sku ON inv_sales(sku);
CREATE TABLE IF NOT EXISTS inv_receipts(
  id INTEGER PRIMARY KEY, date TEXT, vendor TEXT DEFAULT '', category TEXT DEFAULT '', description TEXT DEFAULT '', sku TEXT DEFAULT '', amount REAL DEFAULT 0,
  method TEXT DEFAULT '', ref TEXT DEFAULT '', notes TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS inv_fees(platform TEXT PRIMARY KEY, fee_pct REAL DEFAULT 0, fixed REAL DEFAULT 0, processing TEXT DEFAULT '', notes TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS inv_currencies(code TEXT PRIMARY KEY, name TEXT, rate REAL DEFAULT 1);
CREATE TABLE IF NOT EXISTS inv_scans(id INTEGER PRIMARY KEY, ts TEXT, action TEXT, sku TEXT, result TEXT);
CREATE TABLE IF NOT EXISTS inv_order_links(order_id INTEGER PRIMARY KEY, sku TEXT);
CREATE TABLE IF NOT EXISTS bots(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, monthly_cost REAL DEFAULT 0, active_from TEXT DEFAULT '', archived INTEGER DEFAULT 0, notes TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS proxy_lists(
  id INTEGER PRIMARY KEY AUTOINCREMENT, name TEXT NOT NULL, cost REAL DEFAULT 0, active_from TEXT DEFAULT '', archived INTEGER DEFAULT 0, notes TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS name_maps(
  id INTEGER PRIMARY KEY AUTOINCREMENT, webhook_name TEXT NOT NULL UNIQUE, bot TEXT DEFAULT '', proxy_list TEXT DEFAULT '');
CREATE TABLE IF NOT EXISTS price_rules(
  id INTEGER PRIMARY KEY AUTOINCREMENT, match TEXT NOT NULL, store TEXT DEFAULT '', bot TEXT DEFAULT '', price REAL NOT NULL, created_at TEXT);
"""

_INIT = set()
_LOCK = threading.RLock()


def now():
    return datetime.now().isoformat(timespec="seconds")


def connect(path=None):
    path = path or config.DB_PATH
    c = sqlite3.connect(path, timeout=30)
    c.row_factory = sqlite3.Row
    c.execute("PRAGMA foreign_keys=ON")
    c.execute("PRAGMA synchronous=NORMAL")
    c.execute("PRAGMA temp_store=MEMORY")
    c.execute("PRAGMA cache_size=-20000")
    if path not in _INIT:
        with _LOCK:
            if path not in _INIT:
                c.execute("PRAGMA journal_mode=WAL")
                c.executescript(SCHEMA)
                for tbl, col in (("inv_receipts", "order_id INTEGER"), ("inv_receipts", "source TEXT DEFAULT 'manual'"), ("inv_order_links", "lines TEXT DEFAULT ''")):
                    try:
                        c.execute(f"ALTER TABLE {tbl} ADD COLUMN {col}")
                    except sqlite3.OperationalError:
                        pass  # already there
                c.commit()
                _INIT.add(path)
    return c


def get(c, key, default=""):
    r = c.execute("SELECT value FROM settings WHERE key=?", (key,)).fetchone()
    return r[0] if r else default


def put(c, key, value):
    c.execute("INSERT OR REPLACE INTO settings VALUES(?,?)", (key, value if isinstance(value, str) else json.dumps(value)))
    c.commit()


def get_json(c, key, default=None):
    try:
        return json.loads(get(c, key, "") or "null") or default
    except ValueError:
        return default


def rows(c, q, args=()):
    return [dict(r) for r in c.execute(q, args)]


KEEP_ON_RESET = ("device_name",)


def wipe_tables(c, tables):
    c.execute("PRAGMA foreign_keys=OFF")
    n = 0
    for t in tables:
        n += c.execute(f'DELETE FROM "{t}"').rowcount
    c.execute("PRAGMA foreign_keys=ON")
    c.commit()
    return n


TRACKER_TABLES = ["orders", "order_items", "order_events", "processed", "attention", "notifications"]
ARSENAL_TABLES = ["checkouts", "deleted_checkout_keys", "bots", "proxy_lists", "name_maps", "price_rules", "servers", "channels"]


# ---------------------------------------------------------------- safety net: snapshots + automatic restore of an emptied database
_DATA_TABLES = ("mail_accounts", "orders", "bots", "checkouts", "vprofiles", "vaccounts", "inv_items", "webhooks", "channels")


def counts(path=None):
    path = path or config.DB_PATH
    out = {}
    try:
        c = sqlite3.connect(path, timeout=10)
        for t in _DATA_TABLES:
            try:
                out[t] = c.execute(f'SELECT COUNT(*) FROM "{t}"').fetchone()[0]
            except sqlite3.Error:
                out[t] = 0
        c.close()
    except sqlite3.Error:
        pass
    return out


def has_data(path=None):
    return any(counts(path).values())


def _backup_dirs():
    import os
    dirs = [os.path.join(config.DATA_DIR, "backups")]
    try:  # a second copy outside AppData survives anything that happens to that folder
        dirs.append(os.path.join(config.exports_dir(), "auto-backups"))
    except Exception:
        pass
    return dirs


def snapshot(tag="auto"):
    """Copy the live database (only if it holds data) into both backup folders; keep the newest few of each kind."""
    import os
    import time
    if not os.path.isfile(config.DB_PATH) or not has_data():
        return []
    try:
        c = connect()
        c.execute("DELETE FROM settings WHERE key='user_wiped'"); c.commit(); c.close()
    except sqlite3.Error:
        pass
    made = []
    for d in _backup_dirs():
        try:
            os.makedirs(d, exist_ok=True)
            dst = os.path.join(d, f"toolbox-{tag}-{time.strftime('%Y%m%d-%H%M%S')}.db")
            src, out = sqlite3.connect(config.DB_PATH, timeout=30), sqlite3.connect(dst)
            with out:
                src.backup(out)
            src.close(); out.close()
            made.append(dst)
            mine = sorted(f for f in os.listdir(d) if f.startswith(f"toolbox-{tag}-"))
            for old in mine[:-4]:
                os.remove(os.path.join(d, old))
        except Exception:
            pass
    return made


def restore_if_emptied():
    """If the database holds no accounts/orders/bots at all but a snapshot does, and the user didn't wipe it on purpose, bring the snapshot back."""
    import os
    c = connect()
    try:
        if get(c, "user_wiped", ""):
            return ""
    finally:
        c.close()
    if has_data():
        return ""
    best = ""
    for d in _backup_dirs():
        if os.path.isdir(d):
            for f in os.listdir(d):
                p = os.path.join(d, f)
                if f.endswith(".db") and has_data(p) and (not best or os.path.getmtime(p) > os.path.getmtime(best)):
                    best = p
    if not best:
        return ""
    src, dst = sqlite3.connect(best), sqlite3.connect(config.DB_PATH, timeout=30)
    with dst:
        src.backup(dst)
    src.close(); dst.close()
    _INIT.discard(config.DB_PATH)
    return best
