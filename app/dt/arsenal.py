"""Arsenal: checkouts scraped from your bots' success posts (or added by hand), matched to the orders the retailer confirms."""
import csv
import io
import re
from datetime import datetime, timedelta

from . import db, notify

MATCH_STATES = ("unmatched", "matched", "suggested", "rejected")
SUCCESS_WORDS = re.compile(r"success|checked out|checkout complete|order placed|purchase|copped|you got", re.I)
FAIL_WORDS = re.compile(r"declin|fail|error|out of stock|cart|queue|oos|blocked|retry", re.I)


def _num(v, field="Price", lo=0.0, hi=1e7, blank=None):
    if v is None or str(v).strip() == "":
        return blank
    try:
        n = float(str(v).replace("$", "").replace(",", "").strip())
    except ValueError:
        raise ValueError(f"{field} must be a number")
    if not (lo <= n <= hi):
        raise ValueError(f"{field} is out of range")
    return n


def _date(v, field="Date"):
    v = str(v or "").strip()
    if not v:
        return ""
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(v[:10], fmt).strftime("%Y-%m-%d")
        except ValueError:
            pass
    raise ValueError(f"{field} must look like 2026-11-07")


def _ts(v):
    v = str(v or "").strip()
    if not v:
        return db.now().replace("T", " ")
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%d %H:%M", "%Y-%m-%d", "%m/%d/%Y %H:%M", "%m/%d/%Y"):
        try:
            return datetime.strptime(v, fmt).strftime("%Y-%m-%d %H:%M:%S")
        except ValueError:
            pass
    raise ValueError("Date must look like 2026-11-07 or 2026-11-07 14:30")


# ------------------------------------------------------------------ bots / proxy lists / names
def ensure_named(c, table, name, **extra):
    """Create a bot / proxy list row the first time something reports it."""
    name = (name or "").strip()
    if not name:
        return
    if not c.execute(f"SELECT 1 FROM {table} WHERE lower(name)=lower(?)", (name,)).fetchone():
        cols = ["name", *extra]
        c.execute(f"INSERT INTO {table}({','.join(cols)}) VALUES({','.join('?' * len(cols))})", [name, *extra.values()])


def save_bot(c, d, bid=None):
    name = str(d.get("name") or "").strip()[:60]
    if not name:
        raise ValueError("Enter the bot's name")
    if c.execute("SELECT 1 FROM bots WHERE lower(name)=lower(?) AND id != ?", (name, bid or 0)).fetchone():
        raise ValueError("You already have a bot with that name")
    vals = (name, _num(d.get("monthly_cost"), "Monthly cost", blank=0.0), _date(d.get("active_from"), "Active from"), 1 if d.get("archived") else 0, str(d.get("notes") or "")[:300])
    if bid:
        c.execute("UPDATE bots SET name=?, monthly_cost=?, active_from=?, archived=?, notes=? WHERE id=?", (*vals, bid))
    else:
        bid = c.execute("INSERT INTO bots(name,monthly_cost,active_from,archived,notes) VALUES(?,?,?,?,?)", vals).lastrowid
    c.commit()
    return bid


def save_proxy_list(c, d, pid=None):
    name = str(d.get("name") or "").strip()[:60]
    if not name:
        raise ValueError("Enter a name for the proxy list")
    vals = (name, _num(d.get("cost"), "Cost", blank=0.0), _date(d.get("active_from"), "Active from"), 1 if d.get("archived") else 0, str(d.get("notes") or "")[:300])
    # the same name may repeat on purpose: a repurchase is a new row with its own active-from date
    if pid:
        c.execute("UPDATE proxy_lists SET name=?, cost=?, active_from=?, archived=?, notes=? WHERE id=?", (*vals, pid))
    else:
        pid = c.execute("INSERT INTO proxy_lists(name,cost,active_from,archived,notes) VALUES(?,?,?,?,?)", vals).lastrowid
    c.commit()
    return pid


def remove(c, table, rid):
    if table not in ("bots", "proxy_lists", "name_maps", "price_rules"):
        raise ValueError("Unknown list")
    c.execute(f"DELETE FROM {table} WHERE id=?", (rid,))
    c.commit()


def save_name_map(c, d, mid=None):
    w = str(d.get("webhook_name") or "").strip()[:100]
    bot, pl = str(d.get("bot") or "").strip()[:60], str(d.get("proxy_list") or "").strip()[:60]
    if not w or not (bot or pl):
        raise ValueError("Enter the webhook name and the bot or proxy list it should become")
    if c.execute("SELECT 1 FROM name_maps WHERE lower(webhook_name)=lower(?) AND id != ?", (w, mid or 0)).fetchone():
        raise ValueError("There is already a mapping for that webhook name")
    if mid:
        c.execute("UPDATE name_maps SET webhook_name=?, bot=?, proxy_list=? WHERE id=?", (w, bot, pl, mid))
    else:
        mid = c.execute("INSERT INTO name_maps(webhook_name,bot,proxy_list) VALUES(?,?,?)", (w, bot, pl)).lastrowid
    if bot:
        ensure_named(c, "bots", bot)
    if pl:
        ensure_named(c, "proxy_lists", pl)
    # re-attribute matching rows now, except ones corrected by hand
    n = 0
    for r in c.execute("SELECT id FROM checkouts WHERE lower(webhook_name)=lower(?) AND bot_manual=0", (w,)).fetchall():
        c.execute("UPDATE checkouts SET bot=COALESCE(NULLIF(?,''),bot), proxy_list=COALESCE(NULLIF(?,''),proxy_list) WHERE id=?", (bot, pl, r["id"]))
        n += 1
    c.commit()
    return mid, n


def lists(c, archived=False):
    q = "" if archived else " WHERE archived=0"
    return {"bots": db.rows(c, f"SELECT * FROM bots{q} ORDER BY name COLLATE NOCASE"),
            "proxy_lists": db.rows(c, f"SELECT * FROM proxy_lists{q} ORDER BY name COLLATE NOCASE, active_from DESC"),
            "name_maps": db.rows(c, "SELECT * FROM name_maps ORDER BY webhook_name COLLATE NOCASE"),
            "rules": db.rows(c, "SELECT * FROM price_rules ORDER BY id DESC")}


# ------------------------------------------------------------------ price rules
def _rule_hits(c, rule):
    m = rule["match"].lower()
    out = []
    for r in c.execute("SELECT * FROM checkouts WHERE deleted_at IS NULL AND (price IS NULL OR price_source='rule')").fetchall():
        if m in r["product"].lower() and (not rule.get("store") or rule["store"].lower() in (r["store"] or "").lower()) \
                and (not rule.get("bot") or rule["bot"].lower() == (r["bot"] or "").lower()):
            out.append(r)
    return out


def rule_preview(c, d):
    m = str(d.get("match") or "").strip()
    price = _num(d.get("price"), "Price", 0.01, blank=None)
    if not m or price is None:
        raise ValueError("Enter part of the product name and a price")
    rule = {"match": m, "store": str(d.get("store") or "").strip(), "bot": str(d.get("bot") or "").strip(), "price": price}
    return {"rule": rule, "hits": [{"id": r["id"], "product": r["product"], "store": r["store"], "bot": r["bot"], "old": r["price"], "new": price, "qty": r["qty"], "ts": r["ts"]} for r in _rule_hits(c, rule)]}


def save_rule(c, d, apply_ids=None):
    pv = rule_preview(c, d)
    r = pv["rule"]
    rid = c.execute("INSERT INTO price_rules(match,store,bot,price,created_at) VALUES(?,?,?,?,?)", (r["match"], r["store"], r["bot"], r["price"], db.now())).lastrowid
    n = 0
    for cid in apply_ids or []:
        if any(h["id"] == int(cid) for h in pv["hits"]):  # only rows the preview showed; hand-priced and bot-priced rows are never touched
            c.execute("UPDATE checkouts SET price=?, price_source='rule' WHERE id=?", (r["price"], int(cid)))
            n += 1
    c.commit()
    return rid, n


def rule_for(c, product, store, bot):
    p = (product or "").lower()
    for r in c.execute("SELECT * FROM price_rules ORDER BY length(match) DESC, id DESC"):
        if r["match"].lower() in p and (not r["store"] or r["store"].lower() in (store or "").lower()) and (not r["bot"] or r["bot"].lower() == (bot or "").lower()):
            return r["price"]
    return None


# ------------------------------------------------------------------ checkouts
def _prep(c, d, existing=None):
    product = str(d.get("product") or "").strip()
    if not product:
        raise ValueError("Enter the product name")
    price = _num(d.get("price"), "Price", blank=None)
    source = (existing or {}).get("price_source", "") if existing else ""
    if price is None:
        rp = rule_for(c, product, d.get("store"), d.get("bot"))
        price, source = (rp, "rule") if rp is not None else (None, "")
    elif existing is None or price != existing.get("price"):
        source = "manual"
    q = d.get("qty")
    qty = int(_num(1 if q in (None, "") else q, "Quantity", 1, 10000))
    return {"ts": _ts(d.get("ts")), "product": product[:200], "store": str(d.get("store") or "").strip()[:60], "size": str(d.get("size") or "").strip()[:40], "qty": qty,
            "price": price, "price_source": source, "bot": str(d.get("bot") or "").strip()[:60], "profile": str(d.get("profile") or "").strip()[:60],
            "proxy_list": str(d.get("proxy_list") or "").strip()[:60], "order_number": str(d.get("order_number") or "").strip()[:60],
            "email": str(d.get("email") or "").strip()[:120], "notes": str(d.get("notes") or "").strip()[:500]}


def save(c, d, cid=None):
    ex = None
    if cid:
        ex = c.execute("SELECT * FROM checkouts WHERE id=?", (cid,)).fetchone()
        if not ex:
            raise ValueError("That checkout no longer exists")
        ex = dict(ex)
    v = _prep(c, d, ex)
    if cid:
        if (v["bot"] != ex["bot"] or v["proxy_list"] != ex["proxy_list"]):
            v["bot_manual"] = 1  # a hand correction: name mappings leave this row alone from now on
        c.execute("UPDATE checkouts SET " + ",".join(f"{k}=?" for k in v) + " WHERE id=?", [*v.values(), cid])
    else:
        v["source"], v["created_at"] = "manual", db.now()
        cid = c.execute("INSERT INTO checkouts(" + ",".join(v) + ") VALUES(" + ",".join("?" * len(v)) + ")", list(v.values())).lastrowid
    if v["bot"]:
        ensure_named(c, "bots", v["bot"])
    if v["proxy_list"]:
        ensure_named(c, "proxy_lists", v["proxy_list"])
    c.commit()
    link_checkout(c, cid)
    return cid


def set_image(c, cid, data):
    if data and (not data.startswith("data:image/") or len(data) > 700_000):
        raise ValueError("Pick a smaller picture (it is resized automatically)")
    c.execute("UPDATE checkouts SET image=? WHERE id=?", (data or "", cid))
    c.commit()


def list_checkouts(c, deleted=False):
    rows = db.rows(c, "SELECT * FROM checkouts WHERE deleted_at IS " + ("NOT " if deleted else "") + "NULL ORDER BY ts DESC, id DESC")
    ords = {o["id"]: o for o in db.rows(c, "SELECT id,retailer,order_number,status,total,account FROM orders")}
    for r in rows:
        o = ords.get(r["link_order_id"]) if r["link_order_id"] else None
        r["order"] = o
        r["retailer"] = o["retailer"] if o else r["store"]
    return rows


def delete(c, ids):
    for cid in ids:
        r = c.execute("SELECT message_id FROM checkouts WHERE id=?", (cid,)).fetchone()
        c.execute("UPDATE checkouts SET deleted_at=? WHERE id=? AND deleted_at IS NULL", (db.now(), cid))
        if r and r["message_id"]:
            c.execute("INSERT OR IGNORE INTO deleted_checkout_keys VALUES(?)", (r["message_id"],))
    c.commit()


def restore(c, cid=None):
    ids = [cid] if cid else [r[0] for r in c.execute("SELECT id FROM checkouts WHERE deleted_at IS NOT NULL")]
    for i in ids:
        r = c.execute("SELECT message_id FROM checkouts WHERE id=?", (i,)).fetchone()
        c.execute("UPDATE checkouts SET deleted_at=NULL WHERE id=?", (i,))
        if r and r["message_id"]:
            c.execute("DELETE FROM deleted_checkout_keys WHERE message_id=?", (r["message_id"],))
    c.commit()


def purge(c):
    c.execute("DELETE FROM checkouts WHERE deleted_at IS NOT NULL")
    c.commit()


# ------------------------------------------------------------------ matching with the Order Tracker
def _norm_no(s):
    return re.sub(r"[^A-Z0-9]", "", str(s or "").upper())


def link_checkout(c, cid):
    r = c.execute("SELECT * FROM checkouts WHERE id=?", (cid,)).fetchone()
    if not r or r["match_status"] in ("matched", "rejected") or r["deleted_at"]:
        return
    orders = db.rows(c, "SELECT * FROM orders")
    taken = {x[0] for x in c.execute("SELECT link_order_id FROM checkouts WHERE link_order_id IS NOT NULL AND match_status='matched' AND id!=?", (cid,))}
    n = _norm_no(r["order_number"])
    if n:
        for o in orders:
            if _norm_no(o["order_number"]) == n and o["id"] not in taken:
                c.execute("UPDATE checkouts SET link_order_id=?, match_status='matched' WHERE id=?", (o["id"], cid))
                c.commit()
                return
    # otherwise suggest: same store, close in time, similar total
    try:
        t = datetime.strptime(r["ts"][:10], "%Y-%m-%d")
    except ValueError:
        return
    best = None
    for o in orders:
        if o["id"] in taken or not o["order_date"] or (r["store"] and r["store"].lower() not in o["retailer"].lower() and o["retailer"].lower() not in r["store"].lower()):
            continue
        try:
            dd = abs((datetime.strptime(o["order_date"][:10], "%Y-%m-%d") - t).days)
        except ValueError:
            continue
        if dd > 3:
            continue
        score = dd
        if r["price"] is not None and o["total"]:
            if abs(o["total"] - r["price"] * r["qty"]) / max(o["total"], 1) > 0.25:
                continue
        elif o["total"] is None:
            score += 1
        if r["email"] and o["account"] and r["email"].lower() == o["account"].lower():
            score -= 2
        if best is None or score < best[0]:
            best = (score, o)
    if best:
        c.execute("UPDATE checkouts SET link_order_id=?, match_status='suggested' WHERE id=?", (best[1]["id"], cid))
        c.commit()


def link_order(c, oid):
    for r in c.execute("SELECT id FROM checkouts WHERE deleted_at IS NULL AND match_status IN ('unmatched','suggested') ORDER BY id DESC LIMIT 400").fetchall():
        link_checkout(c, r["id"])


def match_action(c, cid, action, order_id=None):
    r = c.execute("SELECT * FROM checkouts WHERE id=?", (cid,)).fetchone()
    if not r:
        raise ValueError("That checkout no longer exists")
    if action == "confirm":
        if not r["link_order_id"]:
            raise ValueError("There is no suggested order to confirm")
        c.execute("UPDATE checkouts SET match_status='matched' WHERE id=?", (cid,))
    elif action == "reject":
        c.execute("UPDATE checkouts SET match_status='rejected', link_order_id=NULL WHERE id=?", (cid,))
    elif action == "link":
        if not c.execute("SELECT 1 FROM orders WHERE id=?", (order_id,)).fetchone():
            raise ValueError("Pick an order from the list")
        c.execute("UPDATE checkouts SET link_order_id=?, match_status='matched' WHERE id=?", (order_id, cid))
    elif action == "unlink":
        c.execute("UPDATE checkouts SET link_order_id=NULL, match_status='unmatched' WHERE id=?", (cid,))
    else:
        raise ValueError("Unknown action")
    c.commit()


# ------------------------------------------------------------------ reading success posts
FIELD_KEYS = {"product": ("product", "item", "product name", "name"), "store": ("site", "store", "retailer", "website", "shop", "merchant"),
              "size": ("size", "sizes", "variant"), "qty": ("quantity", "qty", "amount of items"), "price": ("price", "total", "amount", "cost", "paid"),
              "profile": ("profile", "billing profile", "payment profile", "profile name"),
              "proxy_list": ("proxy list", "proxy group", "proxy", "proxies", "proxy name"),
              "order_number": ("order", "order #", "order number", "order id", "order no", "order no."), "email": ("email", "e-mail", "account", "account email")}


def _clean_val(v):
    v = re.sub(r"\|\||[*_`~]", "", str(v or ""))
    v = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", v)
    return v.strip()


def _store_from_url(u):
    m = re.search(r"https?://(?:www\.)?([^/]+)", u or "")
    if not m:
        return ""
    host = m.group(1).lower()
    for name, doms in __import__("dt.parsers", fromlist=["x"]).RETAILERS.items():
        if any(d in host for d in doms):
            return name
    return host.split(".")[-2].title() if "." in host else host


def parse_embed(emb):
    """Pull checkout details out of one Discord embed. Returns a dict or None if it isn't a success post."""
    title, desc = _clean_val(emb.get("title")), _clean_val(emb.get("description"))
    head = f"{title} {desc[:200]}"
    fields = {_clean_val(f.get("name")).lower().rstrip(":"): _clean_val(f.get("value")) for f in emb.get("fields") or []}
    if not SUCCESS_WORDS.search(head) and not fields:
        return None
    if FAIL_WORDS.search(title) and not SUCCESS_WORDS.search(title):
        return None
    out = {}
    for k, names in FIELD_KEYS.items():
        for n in names:
            if fields.get(n):
                out[k] = fields[n]
                break
    if "product" not in out:
        t = re.sub(SUCCESS_WORDS, "", title).strip(" -–:!🎉✅")
        out["product"] = t or (desc.splitlines()[0] if desc else "")
    if not out.get("product"):
        return None
    if not out.get("store"):
        out["store"] = _store_from_url(emb.get("url") or "")
    img = (emb.get("thumbnail") or {}).get("url") or (emb.get("image") or {}).get("url") or ""
    out["image_url"] = img
    out["footer"] = _clean_val((emb.get("footer") or {}).get("text"))
    out["author"] = _clean_val((emb.get("author") or {}).get("name"))
    return out


def ingest_message(c, m, channel_id):
    """One Discord message -> at most one new checkout. Returns 1 if added."""
    mkey = f"discord:{channel_id}:{m['id']}"
    if c.execute("SELECT 1 FROM checkouts WHERE message_id=?", (mkey,)).fetchone() or c.execute("SELECT 1 FROM deleted_checkout_keys WHERE message_id=?", (mkey,)).fetchone():
        return 0
    added = 0
    for i, emb in enumerate(m.get("embeds") or []):
        p = parse_embed(emb)
        if not p:
            continue
        webhook = _clean_val((m.get("author") or {}).get("username")) or p["author"] or p["footer"].split("|")[0].split("•")[0].strip()
        nm = c.execute("SELECT * FROM name_maps WHERE lower(webhook_name)=lower(?)", (webhook,)).fetchone()
        bot = (nm["bot"] if nm and nm["bot"] else webhook)[:60]
        pl = (nm["proxy_list"] if nm and nm["proxy_list"] else p.get("proxy_list", ""))[:60]
        try:
            price = _num(re.sub(r"[^0-9.,]", "", p.get("price", "")) or None, blank=None)
        except ValueError:
            price = None
        qty = 1
        try:
            qty = max(1, int(re.sub(r"\D", "", p.get("qty", "")) or 1))
        except ValueError:
            pass
        src = "bot" if price is not None else ""
        if price is None:
            rp = rule_for(c, p["product"], p.get("store"), bot)
            price, src = (rp, "rule") if rp is not None else (None, "")
        ts = (m.get("timestamp") or "")[:19].replace("T", " ") or db.now().replace("T", " ")
        try:
            c.execute("INSERT INTO checkouts(ts,product,store,size,qty,price,price_source,bot,profile,proxy_list,status,order_number,email,image,source,message_id,webhook_name,channel_id,created_at) "
                      "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                      (ts, p["product"][:200], p.get("store", "")[:60], p.get("size", "")[:40], qty, price, src, bot, p.get("profile", "")[:60], pl, "success",
                       re.sub(r"[^A-Za-z0-9\-# ]", "", p.get("order_number", ""))[:60], p.get("email", "")[:120], p.get("image_url", ""), "discord",
                       mkey if i == 0 else f"{mkey}:{i}", webhook, channel_id, db.now()))
        except Exception:
            continue
        cid = c.execute("SELECT last_insert_rowid()").fetchone()[0]
        ensure_named(c, "bots", bot)
        if pl:
            ensure_named(c, "proxy_lists", pl)
        c.commit()
        link_checkout(c, cid)
        notify.notify(c, "checkout", f"Checkout: {p['product'][:80]}", f"{p.get('store', '')} · {bot}", link="checkouts", dedupe=f"co:{cid}",
                      fields={"Store": p.get("store"), "Bot": bot, "Price": f"${price:.2f}" if price is not None else "", "Size": p.get("size")})
        added += 1
    return added


# ------------------------------------------------------------------ stats / filters
def filtered(c, f):
    rows = list_checkouts(c)
    q = (f.get("q") or "").lower()
    if q:
        rows = [r for r in rows if q in " ".join(str(r.get(k) or "") for k in ("product", "order_number", "bot", "profile", "store", "email", "proxy_list", "size")).lower()]
    for key, col in (("retailer", "retailer"), ("bot", "bot"), ("proxy", "proxy_list")):
        if f.get(key):
            rows = [r for r in rows if (r.get(col) or "") == f[key]]
    if f.get("match") and f["match"] != "all":
        rows = [r for r in rows if r["match_status"] == f["match"]]
    rng = f.get("range") or "all"
    cut = {"24h": 1, "7d": 7, "30d": 30, "90d": 90}.get(rng)
    if cut:
        cutoff = (datetime.now() - timedelta(days=cut)).strftime("%Y-%m-%d %H:%M:%S")
        rows = [r for r in rows if r["ts"] >= cutoff]
    elif rng == "custom":
        rows = [r for r in rows if (not f.get("from") or r["ts"][:10] >= f["from"]) and (not f.get("to") or r["ts"][:10] <= f["to"])]
    return rows


def stats(rows):
    spend, seen_orders = 0.0, set()
    for r in rows:
        o = r.get("order")
        if r["match_status"] == "matched" and o and o.get("total") is not None:
            if o["id"] not in seen_orders:
                seen_orders.add(o["id"])
                spend += o["total"]
        elif r["price"] is not None:
            spend += r["price"] * r["qty"]
    matched = [r for r in rows if r["match_status"] == "matched" and r.get("order")]
    stuck = [r for r in matched if r["order"]["status"] not in ("cancelled", "refunded")]
    return {"count": len(rows), "units": sum(r["qty"] for r in rows), "spend": round(spend, 2),
            "stick_rate": round(len(stuck) / len(matched), 4) if matched else None, "rated": len(matched),
            "confirmed": len(matched), "bot_reported": len([r for r in rows if r["match_status"] != "matched"]),
            "unpriced": len([r for r in rows if r["price"] is None])}


def export_csv(c):
    out = io.StringIO()
    w = csv.writer(out)
    cols = ("ts", "product", "store", "size", "qty", "price", "bot", "profile", "proxy_list", "order_number", "email", "match_status")
    w.writerow(cols)
    for r in list_checkouts(c):
        w.writerow([r[k] for k in cols])
    return out.getvalue()
