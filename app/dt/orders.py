"""Orders: the state machine fed by emails, plus everything you can do to an order by hand."""
import json
import re

from . import db, notify
from .parsers import STATUS_LABEL, STATUS_ORDER, RETAILER_COLORS

TERMINAL = {"cancelled", "refunded"}
ALL_STATUSES = list(STATUS_LABEL)


def _rank(s):
    return STATUS_ORDER.index(s) if s in STATUS_ORDER else -1


def next_status(old, new):
    """Which status wins when a new email arrives. Progress only moves forward; cancel/refund override unless delivered."""
    if new == old:
        return old
    if old == "refunded":
        return old
    if new == "refunded":
        return new
    if old in ("cancelled",):
        return old
    if new in ("cancelled", "partially_cancelled"):
        return old if old == "delivered" else new
    if old == "partially_cancelled":
        return new if new in ("shipped", "out_for_delivery", "delivered") else old
    return new if _rank(new) > _rank(old) else old


def is_deleted(c, retailer, number):
    return bool(c.execute("SELECT 1 FROM deleted_orders WHERE retailer=? AND order_number=?", (retailer, number)).fetchone())


def _product_summary(items):
    if not items:
        return "", 1
    first = items[0]["name"]
    return (first if len(items) == 1 else f"{first} +{len(items) - 1} more"), sum(int(i.get("qty") or 1) for i in items)


def log_event(c, oid, status, note=""):
    c.execute("INSERT INTO order_events(order_id,ts,status,note) VALUES(?,?,?,?)", (oid, db.now(), status, note))


def apply_event(c, ev, account="", manual=False, announce=True):
    """Apply one parsed email event. Returns (outcome text, order id or None)."""
    r, n = ev["retailer"], ev["order_number"]
    if is_deleted(c, r, n) and not manual:
        return "skipped (you deleted this order)", None
    t = db.now()
    row = c.execute("SELECT * FROM orders WHERE retailer=? AND order_number=?", (r, n)).fetchone()
    if row is None:
        items = ev.get("items") or []
        prod, qty = _product_summary(items)
        oid = c.execute("INSERT INTO orders(retailer,order_number,status,order_date,total,tracking,carrier,account,product,qty,source,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (r, n, ev["status"], ev.get("date"), ev.get("total"), ev.get("tracking") or "", ev.get("carrier") or "", account, prod, qty,
                         "manual" if manual else "email", t, t)).lastrowid
        for it in items:
            c.execute("INSERT INTO order_items(order_id,name,qty,unit_price,sku) VALUES(?,?,?,?,?)", (oid, it["name"], it.get("qty", 1), it.get("price", 0), it.get("sku", "")))
        log_event(c, oid, ev["status"], "Order added")
        outcome, changed = f"new order ({ev['status']})", True
        if announce:
            notify.notify(c, ev["status"], f"{STATUS_LABEL[ev['status']]}: {r}", prod or f"Order {n}", link="tracking", dedupe=f"o:{oid}:{ev['status']}",
                          fields={"Order": n, "Total": f"${ev['total']:.2f}" if ev.get("total") else "", "Account": account})
    else:
        oid = row["id"]
        new = next_status(row["status"], ev["status"])
        changed = new != row["status"]
        outcome = f"{row['status']} -> {new}" if changed else f"no change ({row['status']})"
        if changed:
            c.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?", (new, t, oid))
            log_event(c, oid, new, "Updated from email")
            if announce:
                notify.notify(c, new, f"{STATUS_LABEL[new]}: {r}", row["product"] or f"Order {n}", link="tracking", dedupe=f"o:{oid}:{new}",
                              fields={"Order": n, "Account": row["account"] or account})
        if ev.get("total") and not row["total"]:
            c.execute("UPDATE orders SET total=? WHERE id=?", (ev["total"], oid))
        if ev.get("tracking") and not row["tracking"]:
            c.execute("UPDATE orders SET tracking=?, carrier=? WHERE id=?", (ev["tracking"], ev.get("carrier") or "", oid))
        if not row["account"] and account:
            c.execute("UPDATE orders SET account=? WHERE id=?", (account, oid))
        if ev.get("date") and (not row["order_date"] or ev["status"] == "placed"):
            c.execute("UPDATE orders SET order_date=? WHERE id=?", (ev["date"], oid))
        if ev.get("items") and not c.execute("SELECT 1 FROM order_items WHERE order_id=?", (oid,)).fetchone():
            for it in ev["items"]:
                c.execute("INSERT INTO order_items(order_id,name,qty,unit_price,sku) VALUES(?,?,?,?,?)", (oid, it["name"], it.get("qty", 1), it.get("price", 0), it.get("sku", "")))
            prod, qty = _product_summary(ev["items"])
            c.execute("UPDATE orders SET product=?, qty=? WHERE id=?", (prod, qty, oid))
    c.commit()
    try:
        from . import arsenal
        arsenal.link_order(c, oid)  # a new/updated order may be the proof a checkout was waiting for
    except Exception:
        pass
    _to_inventory(c, oid)
    return outcome, oid


# ------------------------------------------------------------------ reads
def list_orders(c):
    orders = db.rows(c, "SELECT * FROM orders ORDER BY COALESCE(order_date,'') DESC, id DESC")
    items = {}
    for it in db.rows(c, "SELECT * FROM order_items ORDER BY id"):
        items.setdefault(it["order_id"], []).append(it)
    for o in orders:
        o["items"] = items.get(o["id"], [])
        o["color"] = RETAILER_COLORS.get(o["retailer"], "#8a8a99")
        o["status_label"] = STATUS_LABEL.get(o["status"], o["status"])
    return orders


def order_detail(c, oid):
    o = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not o:
        raise ValueError("That order no longer exists")
    d = dict(o)
    d["items"] = db.rows(c, "SELECT * FROM order_items WHERE order_id=? ORDER BY id", (oid,))
    d["events"] = db.rows(c, "SELECT * FROM order_events WHERE order_id=? ORDER BY id", (oid,))
    d["checkouts"] = db.rows(c, "SELECT id,product,store,bot,price,ts FROM checkouts WHERE link_order_id=? AND deleted_at IS NULL", (oid,))
    return d


def overview(c, orders=None):
    from datetime import date, timedelta
    orders = orders if orders is not None else list_orders(c)
    live = [o for o in orders if o["status"] not in TERMINAL]
    ok = [o for o in orders if o["status"] not in TERMINAL and o["status"] != "cancelled"]
    today = date.today()
    days = [(today - timedelta(days=13 - i)).isoformat() for i in range(14)]
    per = {d: {"day": d, "count": 0, "spent": 0.0} for d in days}
    for o in orders:
        d = (o["order_date"] or "")[:10]
        if d in per and o["status"] not in TERMINAL:
            per[d]["count"] += 1
            per[d]["spent"] = round(per[d]["spent"] + (o["total"] or 0), 2)
    by = {}
    for o in orders:
        e = by.setdefault(o["retailer"], {"retailer": o["retailer"], "total": 0, "ok": 0, "color": o["color"]})
        e["total"] += 1
        e["ok"] += o["status"] not in ("cancelled", "refunded")
    last = max(orders, key=lambda o: o["order_date"] or "", default=None)
    return {"total": len(orders), "placed": sum(o["status"] == "placed" for o in orders),
            "in_transit": sum(o["status"] in ("shipped", "out_for_delivery") for o in orders),
            "delivered": sum(o["status"] == "delivered" for o in orders), "cancelled": sum(o["status"] in ("cancelled", "refunded") for o in orders),
            "stick_rate": round(len(ok) / len(orders), 4) if orders else None, "spent_14d": round(sum(d["spent"] for d in per.values()), 2),
            "days": list(per.values()), "retailers": sorted(by.values(), key=lambda e: -e["total"]),
            "last": {"retailer": last["retailer"], "date": last["order_date"]} if last else None}


# ------------------------------------------------------------------ edits
def _need(c, oid):
    o = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not o:
        raise ValueError("That order no longer exists")
    return o


def save_manual(c, d, oid=None):
    r, n = str(d.get("retailer") or "").strip(), str(d.get("order_number") or "").strip().upper()
    if not r or not n:
        raise ValueError("Retailer and order number are required")
    status = d.get("status") or "placed"
    if status not in ALL_STATUSES:
        raise ValueError("Unknown status")
    try:
        total = float(str(d.get("total") or "").replace("$", "").replace(",", "")) if str(d.get("total") or "").strip() else None
    except ValueError:
        raise ValueError("Total must be a number")
    name = str(d.get("product") or "").strip()
    qty = max(1, int(d.get("qty") or 1))
    if oid:
        _need(c, oid)
        dup = c.execute("SELECT id FROM orders WHERE retailer=? AND order_number=? AND id!=?", (r, n, oid)).fetchone()
        if dup:
            raise ValueError("Another order already has that number - merge them instead")
        c.execute("UPDATE orders SET retailer=?, order_number=?, status=?, order_date=?, total=?, tracking=?, carrier=?, account=?, product=?, qty=?, notes=?, updated_at=? WHERE id=?",
                  (r, n, status, d.get("order_date") or None, total, str(d.get("tracking") or "").strip(), str(d.get("carrier") or "").strip(), str(d.get("account") or "").strip(),
                   name, qty, str(d.get("notes") or "")[:500], db.now(), oid))
        log_event(c, oid, status, "Edited by hand")
    else:
        if c.execute("SELECT 1 FROM orders WHERE retailer=? AND order_number=?", (r, n)).fetchone():
            raise ValueError("You already track that order")
        c.execute("DELETE FROM deleted_orders WHERE retailer=? AND order_number=?", (r, n))
        oid = c.execute("INSERT INTO orders(retailer,order_number,status,order_date,total,tracking,carrier,account,product,qty,source,notes,created_at,updated_at) "
                        "VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
                        (r, n, status, d.get("order_date") or db.now()[:10], total, str(d.get("tracking") or "").strip(), str(d.get("carrier") or "").strip(),
                         str(d.get("account") or "").strip(), name, qty, "manual", str(d.get("notes") or "")[:500], db.now(), db.now())).lastrowid
        if name:
            c.execute("INSERT INTO order_items(order_id,name,qty,unit_price) VALUES(?,?,?,?)", (oid, name, qty, round((total or 0) / qty, 2)))
        log_event(c, oid, status, "Added by hand")
    c.commit()
    try:
        from . import arsenal
        arsenal.link_order(c, oid)
    except Exception:
        pass
    return oid


def _to_inventory(c, oid):
    try:
        if c.execute("SELECT status FROM orders WHERE id=?", (oid,)).fetchone()["status"] == "delivered":
            from . import inventory
            inventory.on_delivered(c, oid)
    except Exception:
        pass


def set_status(c, ids, status):
    if status not in ALL_STATUSES:
        raise ValueError("Unknown status")
    for i in ids:
        _need(c, i)
        c.execute("UPDATE orders SET status=?, updated_at=? WHERE id=?", (status, db.now(), i))
        log_event(c, i, status, "Set by hand")
    c.commit()
    for i in ids:
        _to_inventory(c, i)


def delete_orders(c, ids):
    for i in ids:
        o = c.execute("SELECT * FROM orders WHERE id=?", (i,)).fetchone()
        if o:
            c.execute("INSERT OR REPLACE INTO deleted_orders(retailer,order_number,product,total,deleted_at) VALUES(?,?,?,?,?)",
                      (o["retailer"], o["order_number"], o["product"], o["total"], db.now()))
            c.execute("UPDATE checkouts SET link_order_id=NULL, match_status='unmatched' WHERE link_order_id=?", (i,))
            c.execute("DELETE FROM orders WHERE id=?", (i,))
    c.commit()


def move_retailer(c, oid, retailer):
    o = _need(c, oid)
    retailer = (retailer or "").strip()
    if not retailer:
        raise ValueError("Pick a retailer")
    if c.execute("SELECT 1 FROM orders WHERE retailer=? AND order_number=? AND id!=?", (retailer, o["order_number"], oid)).fetchone():
        raise ValueError("That retailer already has an order with this number - merge instead")
    c.execute("UPDATE orders SET retailer=? WHERE id=?", (retailer, oid))
    c.commit()


def merge(c, from_id, into_id):
    a, b = _need(c, from_id), _need(c, into_id)
    if from_id == into_id:
        raise ValueError("Pick two different orders")
    for col in ("total", "tracking", "carrier", "account", "product"):
        if not b[col] and a[col]:
            c.execute(f"UPDATE orders SET {col}=? WHERE id=?", (a[col], into_id))
    c.execute("UPDATE order_items SET order_id=? WHERE order_id=?", (into_id, from_id))
    c.execute("UPDATE order_events SET order_id=? WHERE order_id=?", (into_id, from_id))
    c.execute("UPDATE checkouts SET link_order_id=? WHERE link_order_id=?", (into_id, from_id))
    c.execute("DELETE FROM orders WHERE id=?", (from_id,))
    c.commit()


def not_an_order(c, oid, rule=None):
    """Delete a wrongly-read order and optionally tell the app to ignore that sender/subject from now on."""
    o = _need(c, oid)
    delete_orders(c, [oid])
    if rule in ("sender", "subject"):
        pass  # the sender/subject isn't stored on the order; the Needs-attention flow handles ignoring by sender
    return o["retailer"]


def restore_deleted(c, did):
    c.execute("DELETE FROM deleted_orders WHERE id=?", (did,))
    c.commit()


def purge_deleted(c):
    c.execute("DELETE FROM deleted_orders")
    c.commit()


# ------------------------------------------------------------------ exceptions
KINDS = {"sender": "Everything from a sender", "domain": "A whole website / domain", "subject": "Subjects containing…"}


def add_exception(c, kind, value):
    kind, value = (kind or "sender").strip(), (value or "").strip().lower()
    if kind not in KINDS or not value:
        raise ValueError("Enter an email address or website to ignore")
    c.execute("INSERT OR IGNORE INTO exceptions(kind,value) VALUES(?,?)", (kind, value))
    c.commit()


def remove_exception(c, eid):
    c.execute("DELETE FROM exceptions WHERE id=?", (eid,))
    c.commit()


def is_excepted(excs, sender, subject):
    s, sub = (sender or "").lower(), (subject or "").lower()
    dom = s.rsplit("@", 1)[-1].strip("> ") if "@" in s else s
    for e in excs:
        v = e["value"]
        if (e["kind"] == "sender" and v in s) or (e["kind"] == "domain" and (dom == v or dom.endswith("." + v) or v in dom)) or (e["kind"] == "subject" and v in sub):
            return True
    return False
