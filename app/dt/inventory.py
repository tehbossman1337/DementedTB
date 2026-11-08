"""Inventory: items, sales (fees, profit, ROI), receipts (expenses), scan station, dashboard and tax summary.
Delivered orders from the tracker can be added to inventory automatically using a weighted-average cost."""
import csv
import io
import json
import os
import re
import threading
from datetime import date, datetime, timedelta

from . import db, notify

from .inv_data import DATA
CATEGORIES = ["Pokemon Card", "Graphics Card"]
DEFAULTS = {"partner1": "Me", "partner2": "Partner", "aging_days": 90, "drop_pct": 0.15, "monthly_target": 0.0, "big_sale": 0.0, "auto_from_orders": 1, "auto_receipts": 1, "tax_year": 0}
GPU_WORDS = re.compile(r"\b(rtx|gtx|radeon|geforce|gpu|graphics card|video card|nvidia)\b", re.I)
SKU_RE = re.compile(r"^[A-Z]{2,4}-\d{1,6}$")
LOCK = threading.RLock()  # anything that picks a new SKU runs under this so two requests can't take the same one


def locked(fn):
    def w(*a, **k):
        with LOCK:
            return fn(*a, **k)
    w.__name__ = fn.__name__
    return w


def now():
    return datetime.now().isoformat(timespec="seconds")


def today():
    return date.today().isoformat()


def num(v, default=0.0):
    try:
        return default if v is None or v == "" else float(str(v).replace("$", "").replace(",", "").strip())
    except (TypeError, ValueError):
        return default


def pdate(s):
    try:
        return datetime.strptime(str(s)[:10], "%Y-%m-%d").date()
    except (TypeError, ValueError):
        return None


def r2(x):
    return None if x is None else round(x + 0.0, 2)


# ------------------------------------------------------------------ settings, lists, fees, currencies
def seed(c):
    if not c.execute("SELECT 1 FROM inv_fees LIMIT 1").fetchone():
        c.executemany("INSERT INTO inv_fees VALUES(?,?,?,?,?)", [(f["platform"], f["fee_pct"], f["fixed"], f["processing"], f["notes"]) for f in DATA["fees"]])
    if not c.execute("SELECT 1 FROM inv_currencies LIMIT 1").fetchone():
        c.executemany("INSERT INTO inv_currencies VALUES(?,?,?)", [(f["code"], f["name"], f["rate"]) for f in DATA["currencies"]])
    c.commit()


def settings(c):
    out = dict(DEFAULTS)
    for k, dv in DEFAULTS.items():
        raw = db.get(c, "inv." + k, "")
        if raw != "":
            try:
                v = json.loads(raw)
                out[k] = str(v) if isinstance(dv, str) else float(v) if isinstance(dv, float) else int(v)
            except (ValueError, TypeError):
                pass
    return out


def save_settings(c, d):
    for k, dv in DEFAULTS.items():
        if k not in d:
            continue
        v = d[k]
        if isinstance(dv, str):
            v = str(v or "").strip()[:40]
        elif isinstance(dv, float):
            v = max(0.0, min(num(v, dv), 1.0)) if k == "drop_pct" else max(0.0, num(v, dv))
        else:
            v = max(0, int(num(v, dv)))
        db.put(c, "inv." + k, json.dumps(v))
    return settings(c)


def team(c):
    s = settings(c)
    return [s["partner1"] or "Me", s["partner2"] or "Partner", "Other / Unassigned"]


def lists(c):
    seed(c)
    d = dict(DATA["lists"])
    d["team"] = team(c)
    d["platforms"] = [r[0] for r in c.execute("SELECT platform FROM inv_fees ORDER BY rowid")]
    d["currencies"] = [r[0] for r in c.execute("SELECT code FROM inv_currencies ORDER BY rowid")]
    d["skus"] = [r[0] for r in c.execute("SELECT sku FROM inv_items ORDER BY sku")]
    return d


def list_fees(c):
    seed(c)
    return db.rows(c, "SELECT * FROM inv_fees ORDER BY rowid")


def save_fee(c, d, old=None):
    name = str(d.get("platform") or "").strip()
    if not name:
        raise ValueError("Give the platform a name")
    pct = num(d.get("fee_pct"))
    pct = pct / 100 if pct > 1 else pct  # people type 13.35 meaning 13.35%
    if not 0 <= pct < 1:
        raise ValueError("Fee % must be between 0 and 100")
    fixed = max(0.0, num(d.get("fixed")))
    if old and old != name:
        if c.execute("SELECT 1 FROM inv_fees WHERE platform=?", (name,)).fetchone():
            raise ValueError(f"{name} already exists")
        c.execute("UPDATE inv_fees SET platform=? WHERE platform=?", (name, old))
        c.execute("UPDATE inv_sales SET platform=? WHERE platform=?", (name, old))
        c.execute("UPDATE inv_items SET listing_platform=? WHERE listing_platform=?", (name, old))
    c.execute("INSERT INTO inv_fees(platform,fee_pct,fixed,processing,notes) VALUES(?,?,?,?,?) ON CONFLICT(platform) DO UPDATE SET fee_pct=excluded.fee_pct,fixed=excluded.fixed,"
              "processing=excluded.processing,notes=excluded.notes", (name, pct, fixed, str(d.get("processing") or ""), str(d.get("notes") or "")[:300]))
    c.commit()


def delete_fee(c, platform):
    c.execute("DELETE FROM inv_fees WHERE platform=?", (platform,))
    c.commit()


def list_currencies(c):
    seed(c)
    return db.rows(c, "SELECT * FROM inv_currencies ORDER BY rowid")


def save_currency(c, d):
    code = str(d.get("code") or "").strip().upper()
    if not re.fullmatch(r"[A-Z]{3}", code):
        raise ValueError("Currency code must be 3 letters, like EUR")
    rate = num(d.get("rate"), 0)
    if rate <= 0:
        raise ValueError("Rate (value in USD) must be above 0")
    c.execute("INSERT INTO inv_currencies(code,name,rate) VALUES(?,?,?) ON CONFLICT(code) DO UPDATE SET name=excluded.name,rate=excluded.rate", (code, str(d.get("name") or code)[:40], rate))
    c.commit()


def delete_currency(c, code):
    if code == "USD":
        raise ValueError("USD is the base currency and can't be removed")
    if c.execute("SELECT 1 FROM inv_items WHERE currency=?", (code,)).fetchone():
        raise ValueError(f"Items still use {code}")
    c.execute("DELETE FROM inv_currencies WHERE code=?", (code,))
    c.commit()


# ------------------------------------------------------------------ items
def infer_category(name):
    return "Graphics Card" if GPU_WORDS.search(name or "") else "Pokemon Card"


def next_sku(c, category):
    prefix = "GC" if category == "Graphics Card" else "PK"
    top = 0
    for (s,) in c.execute("SELECT sku FROM inv_items WHERE sku LIKE ?", (prefix + "-%",)):
        m = re.fullmatch(prefix + r"-(\d+)", s)
        if m:
            top = max(top, int(m.group(1)))
    return f"{prefix}-{top + 1:04d}"


ITEM_COLS = ["sku", "category", "name", "pokemon_set", "card_no", "condition", "grading", "qty", "added_by", "purchase_date", "purchase_price", "purchase_source",
             "listing_platform", "listed_price", "currency", "market_price", "location", "notes", "barcode"]


def _clean_item(c, d, old=None):
    seed(c)
    cat = d.get("category") or (old["category"] if old else "")
    name = str(d.get("name") or "").strip()
    if cat not in CATEGORIES:
        cat = infer_category(name) if name else "Pokemon Card"
    qty = 1 if d.get("qty") in (None, "") else int(num(d.get("qty"), -1))
    if qty < 1:
        raise ValueError("Quantity must be at least 1")
    pp, lp = num(d.get("purchase_price")), num(d.get("listed_price"))
    if pp < 0 or lp < 0:
        raise ValueError("Prices can't be negative")
    pd = str(d.get("purchase_date") or "").strip()
    if pd and not pdate(pd):
        raise ValueError("Purchase date must look like 2026-10-28")
    cur = str(d.get("currency") or "USD").upper()
    if not c.execute("SELECT 1 FROM inv_currencies WHERE code=?", (cur,)).fetchone():
        raise ValueError(f"Unknown currency {cur}. Add it under Fees & settings first.")
    if not name and not d.get("pokemon_set"):
        raise ValueError("Give the item a name")
    out = {"category": cat, "name": name or d.get("pokemon_set"), "qty": qty, "purchase_price": pp, "listed_price": lp, "purchase_date": pd, "currency": cur,
           "market_price": max(0.0, num(d.get("market_price")))}
    for k in ("pokemon_set", "card_no", "condition", "grading", "added_by", "purchase_source", "listing_platform", "location", "notes", "barcode"):
        out[k] = str(d.get(k) or "").strip()
    if out["barcode"]:
        dup = c.execute("SELECT sku FROM inv_items WHERE barcode=? AND id<>?", (out["barcode"], old["id"] if old else -1)).fetchone()
        if dup:
            raise ValueError(f"Barcode {out['barcode']} already belongs to {dup['sku']}")
    out["sku"] = str(d.get("sku") or "").strip().upper() or (old["sku"] if old else next_sku(c, cat))
    return out


@locked
def save_item(c, d, item_id=None):
    old = c.execute("SELECT * FROM inv_items WHERE id=?", (item_id,)).fetchone() if item_id else None
    if item_id and not old:
        raise ValueError("That item no longer exists")
    v = _clean_item(c, d, old)
    dup = c.execute("SELECT id FROM inv_items WHERE sku=?", (v["sku"],)).fetchone()
    if dup and dup["id"] != item_id:
        raise ValueError(f"SKU {v['sku']} is already used")
    if old:
        sold = c.execute("SELECT COALESCE(SUM(qty),0) FROM inv_sales WHERE sku=?", (old["sku"],)).fetchone()[0]
        if v["qty"] < sold:
            raise ValueError(f"{sold} already sold, so the quantity can't go below {sold}")
        if v["sku"] != old["sku"]:
            c.execute("UPDATE inv_sales SET sku=? WHERE sku=?", (v["sku"], old["sku"]))
            c.execute("UPDATE inv_receipts SET sku=? WHERE sku=?", (v["sku"], old["sku"]))
            c.execute("UPDATE inv_order_links SET sku=? WHERE sku=?", (v["sku"], old["sku"]))
        c.execute(f"UPDATE inv_items SET {','.join(k + '=?' for k in ITEM_COLS)}, updated_at=? WHERE id=?", [v[k] for k in ITEM_COLS] + [now(), item_id])
        c.commit()
        return item_id
    cur = c.execute(f"INSERT INTO inv_items({','.join(ITEM_COLS)},created_at,updated_at) VALUES({','.join('?' * len(ITEM_COLS))},?,?)", [v[k] for k in ITEM_COLS] + [now(), now()])
    c.commit()
    return cur.lastrowid


def delete_items(c, ids):
    done, blocked = 0, []
    for i in ids:
        r = c.execute("SELECT sku FROM inv_items WHERE id=?", (i,)).fetchone()
        if not r:
            continue
        n = c.execute("SELECT COUNT(*) FROM inv_sales WHERE sku=?", (r["sku"],)).fetchone()[0]
        if n:
            blocked.append(f"{r['sku']} ({n} sale{'s' if n != 1 else ''})")
            continue
        c.execute("DELETE FROM inv_items WHERE id=?", (i,))
        c.execute("DELETE FROM inv_order_links WHERE sku=?", (r["sku"],))
        done += 1
    c.commit()
    return {"deleted": done, "blocked": blocked}


# ------------------------------------------------------------------ sales
def _sale_calc(s, item, fees, fx):
    f = fees.get(s["platform"])
    pct, fixed = (f["fee_pct"], f["fixed"]) if f else (0.0, 0.0)
    pfee = (s["sale_price"] + s["ship_charged"]) * pct + fixed
    total = pfee + s["other_fees"]
    net = s["sale_price"] + s["ship_charged"] - total - s["ship_cost"]
    basis = s["qty"] * item["purchase_price"] * fx if item and item["purchase_price"] else None
    profit = None if basis is None else net - basis
    roi = None if not basis else profit / basis
    return {"fee_pct": pct, "platform_fee": r2(pfee), "total_fees": r2(total), "net": r2(net), "cost_basis": r2(basis), "profit": r2(profit), "roi": None if roi is None else round(roi, 4)}


def _load(c):
    seed(c)
    return ({r["platform"]: dict(r) for r in c.execute("SELECT * FROM inv_fees")}, {r["code"]: r["rate"] for r in c.execute("SELECT * FROM inv_currencies")},
            {r["sku"]: dict(r) for r in c.execute("SELECT * FROM inv_items")})


def list_sales(c):
    fees, fxs, items = _load(c)
    rows = db.rows(c, "SELECT * FROM inv_sales ORDER BY sale_date, id")
    buyers = {}
    for r in rows:
        b = (r["buyer"] or "").strip().lower()
        if b:
            buyers[b] = buyers.get(b, 0) + 1
    for r in rows:
        it = items.get(r["sku"])
        r["sale_id"] = f"S-{r['id']:04d}"
        r["item_name"] = it["name"] if it else "(item deleted)"
        r["category"] = it["category"] if it else ""
        r.update(_sale_calc(r, it, fees, fxs.get(it["currency"], 1.0) if it else 1.0))
        b = (r["buyer"] or "").strip().lower()
        r["buyer_count"] = buyers.get(b) if b else None
    rows.sort(key=lambda r: (r["sale_date"] or "", r["id"]), reverse=True)
    return rows


def list_items(c, sales=None):
    fees, fxs, items = _load(c)
    sales = list_sales(c) if sales is None else sales
    agg = {}
    for s in sales:
        a = agg.setdefault(s["sku"], {"qty": 0, "price": 0.0, "fees": 0.0, "net": 0.0, "profit": 0.0, "date": "", "has": False})
        a["qty"] += s["qty"]
        a["price"] += s["sale_price"]
        a["fees"] += s["total_fees"] or 0
        a["net"] += s["net"] or 0
        if s["profit"] is not None:
            a["profit"] += s["profit"]
            a["has"] = True
        a["date"] = max(a["date"], s["sale_date"] or "")
    out, t = [], date.today()
    for it in sorted(items.values(), key=lambda x: x["sku"]):
        a = agg.get(it["sku"])
        sold = a["qty"] if a else 0
        rem = max(0, it["qty"] - sold)
        fx = fxs.get(it["currency"], 1.0)
        status = ("Listed" if it["listed_price"] else "In stock") if sold == 0 else ("Sold" if rem <= 0 else "Partly sold")
        p0 = pdate(it["purchase_date"])
        days = None
        if p0:
            days = ((pdate(a["date"]) if rem <= 0 and a and a["date"] else t) - p0).days
        profit = a["profit"] if a and a["has"] else None
        basis_sold = sold * it["purchase_price"] * fx
        it.update({"qty_sold": sold, "qty_remaining": rem, "status": status, "cost_on_hand": r2(rem * it["purchase_price"] * fx), "total_cost": r2(it["qty"] * it["purchase_price"] * fx),
                   "sale_date": a["date"] if a else "", "sale_total": r2(a["price"]) if a else None, "fees_total": r2(a["fees"]) if a else None, "net_total": r2(a["net"]) if a else None,
                   "profit": r2(profit), "roi": round(profit / basis_sold, 4) if profit is not None and basis_sold > 0 else None, "days_held": days})
        out.append(it)
    return out


def save_sale(c, d, sale_id=None):
    sku = str(d.get("sku") or "").strip().upper()
    it = c.execute("SELECT * FROM inv_items WHERE sku=?", (sku,)).fetchone()
    if not it:
        raise ValueError(f"No inventory item with SKU '{sku}'. Add it under Items first.")
    old = c.execute("SELECT * FROM inv_sales WHERE id=?", (sale_id,)).fetchone() if sale_id else None
    if sale_id and not old:
        raise ValueError("That sale no longer exists")
    qty = 1 if d.get("qty") in (None, "") else int(num(d.get("qty"), -1))
    if qty < 1:
        raise ValueError("Quantity sold must be at least 1")
    sold = c.execute("SELECT COALESCE(SUM(qty),0) FROM inv_sales WHERE sku=? AND id IS NOT ?", (sku, sale_id)).fetchone()[0]
    if qty + sold > it["qty"]:
        raise ValueError(f"Only {max(0, it['qty'] - sold)} of {sku} left to sell")
    for k, label in (("sale_price", "Sale price"), ("ship_charged", "Shipping charged"), ("ship_cost", "Shipping cost"), ("other_fees", "Other fees")):
        if num(d.get(k)) < 0:
            raise ValueError(f"{label} can't be negative")
    sd = str(d.get("sale_date") or today()).strip()
    if not pdate(sd):
        raise ValueError("Sale date must look like 2026-10-28")
    if pdate(it["purchase_date"]) and pdate(sd) < pdate(it["purchase_date"]):
        raise ValueError("The sale date is before the purchase date")
    cols = "sku,sale_date,sold_by,platform,buyer,sale_price,ship_charged,ship_cost,other_fees,qty,notes"
    vals = (sku, sd, str(d.get("sold_by") or "").strip(), str(d.get("platform") or "").strip(), str(d.get("buyer") or "").strip(), num(d.get("sale_price")),
            num(d.get("ship_charged")), num(d.get("ship_cost")), num(d.get("other_fees")), qty, str(d.get("notes") or "").strip())
    if old:
        c.execute(f"UPDATE inv_sales SET {','.join(k + '=?' for k in cols.split(','))} WHERE id=?", vals + (sale_id,))
        sid = sale_id
    else:
        sid = c.execute(f"INSERT INTO inv_sales({cols},created_at) VALUES({','.join('?' * 12)})", vals + (now(),)).lastrowid
    c.commit()
    alert, thr = None, settings(c)["big_sale"]
    if not old and thr and vals[5] >= thr:
        alert = f"Big sale: ${vals[5]:,.2f} for {it['name']} ({sku})"
        try:
            notify.notify(c, "big_sale", "Big sale", alert, link="inv_sales", dedupe=f"sale:{sid}")
        except Exception:
            pass
    return {"id": sid, "alert": alert}


def delete_sales(c, ids):
    for i in ids:
        c.execute("DELETE FROM inv_sales WHERE id=?", (i,))
    c.commit()


# ------------------------------------------------------------------ receipts
def list_receipts(c):
    return db.rows(c, "SELECT * FROM inv_receipts ORDER BY date DESC, id DESC")


def save_receipt(c, d, rid=None):
    dt = str(d.get("date") or today()).strip()
    if not pdate(dt):
        raise ValueError("Date must look like 2026-10-28")
    if str(d.get("amount") if d.get("amount") is not None else "").strip() == "":
        raise ValueError("Amount is required")
    sku = str(d.get("sku") or "").strip().upper()
    if sku and not c.execute("SELECT 1 FROM inv_items WHERE sku=?", (sku,)).fetchone():
        raise ValueError(f"No inventory item with SKU '{sku}' (leave it blank if the receipt isn't for one item)")
    cols = "date,vendor,category,description,sku,amount,method,ref,notes"
    vals = (dt, str(d.get("vendor") or "").strip(), str(d.get("category") or "").strip(), str(d.get("description") or "").strip(), sku, num(d.get("amount")),
            str(d.get("method") or "").strip(), str(d.get("ref") or "").strip(), str(d.get("notes") or "").strip())
    if rid:
        c.execute(f"UPDATE inv_receipts SET {','.join(k + '=?' for k in cols.split(','))}, source='manual' WHERE id=?", vals + (rid,))
    else:
        c.execute(f"INSERT INTO inv_receipts({cols}) VALUES({','.join('?' * 9)})", vals)
    c.commit()


def delete_receipts(c, ids):
    for i in ids:
        c.execute("DELETE FROM inv_receipts WHERE id=?", (i,))
    c.commit()


# ------------------------------------------------------------------ dashboard and tax
def _month_start(d, back):
    y, m = d.year, d.month - back
    while m <= 0:
        m, y = m + 12, y - 1
    return date(y, m, 1)


def dashboard(c):
    s = settings(c)
    sales = list_sales(c)
    items = list_items(c, sales)
    exp = sum(r[0] for r in c.execute("SELECT amount FROM inv_receipts WHERE COALESCE(source,'manual')<>'email'"))
    rev, fees = sum(x["sale_price"] for x in sales), sum(x["total_fees"] or 0 for x in sales)
    prof, basis = sum(x["profit"] or 0 for x in sales), sum(x["cost_basis"] or 0 for x in sales)
    sold_units = sum(x["qty_sold"] for x in items)
    net = prof - exp
    t = date.today()
    out = {"in_stock": sum(x["qty_remaining"] for x in items), "sold": sold_units, "cost_on_hand": r2(sum(x["cost_on_hand"] or 0 for x in items)), "revenue": r2(rev), "fees": r2(fees),
           "expenses": r2(exp), "net_profit": r2(net), "roi": round(net / basis, 4) if basis else None, "market_value": r2(sum(x["qty_remaining"] * x["market_price"] for x in items)), "items": len(items)}
    out["by_category"] = [{"category": k, "units": sum(x["qty_sold"] for x in items if x["category"] == k), "revenue": r2(sum(x["sale_total"] or 0 for x in items if x["category"] == k)),
                           "profit": r2(sum(x["profit"] or 0 for x in items if x["category"] == k))} for k in CATEGORIES]
    out["by_member"] = [{"name": n, "sales": sum(1 for x in sales if x["sold_by"] == n), "revenue": r2(sum(x["sale_price"] for x in sales if x["sold_by"] == n)),
                         "profit": r2(sum(x["profit"] or 0 for x in sales if x["sold_by"] == n))} for n in team(c)]
    out["aging_count"], out["aging_days"] = sum(1 for x in items if x["qty_remaining"] > 0 and x["days_held"] is not None and x["days_held"] >= s["aging_days"]), s["aging_days"]
    out["top_sales"] = [{"item": x["item_name"], "sku": x["sku"], "profit": x["profit"], "roi": x["roi"]} for x in sorted([x for x in sales if x["profit"] is not None], key=lambda x: -x["profit"])[:5]]
    months = []
    for back in range(5, -1, -1):
        ms = _month_start(t, back)
        key = ms.strftime("%Y-%m")
        mm = [x for x in sales if (x["sale_date"] or "").startswith(key)]
        months.append({"month": key, "label": ms.strftime("%b"), "revenue": r2(sum(x["sale_price"] for x in mm)), "profit": r2(sum(x["profit"] or 0 for x in mm))})
    out["months"] = months
    cur = months[-1]["profit"]
    avg = net / sold_units if sold_units else 0
    left = max(0, s["monthly_target"] - cur)
    out["target"] = {"target": s["monthly_target"], "so_far": cur, "remaining": r2(left), "avg_profit": r2(avg), "more_sales": None if not s["monthly_target"] or avg <= 0 else int(-(-left // avg))}
    cut = (t - timedelta(days=30)).isoformat()
    out["reorder"] = []
    for k in CATEGORIES:
        s30 = sum(x["qty"] for x in sales if x["category"] == k and (x["sale_date"] or "") >= cut)
        stock = sum(x["qty_remaining"] for x in items if x["category"] == k)
        out["reorder"].append({"category": k, "sold_30d": s30, "in_stock": stock, "suggestion": "Restock soon" if s30 >= 3 and stock <= 1 else "Selling well" if s30 >= 3 else "OK"})
    old = sorted([x for x in items if x["qty_remaining"] > 0 and x["days_held"] is not None], key=lambda x: -x["days_held"])[:5]
    out["price_drops"] = [{"item": x["name"], "sku": x["sku"], "days": x["days_held"], "listed": x["listed_price"] or None, "suggested": r2(x["listed_price"] * (1 - s["drop_pct"])) if x["listed_price"] else None} for x in old]
    rep = {}
    for x in sales:
        b = (x["buyer"] or "").strip().lower()
        if b:
            rep.setdefault(b, []).append(x)
    reps = [v for v in rep.values() if len(v) > 1]
    out["repeat_buyers"] = {"count": len(reps), "revenue": r2(sum(x["sale_price"] for v in reps for x in v))}
    out["recent_sales"] = [{"sale_id": x["sale_id"], "item": x["item_name"], "date": x["sale_date"], "price": x["sale_price"], "profit": x["profit"]} for x in sales[:6]]
    return out


def tax_summary(c, year):
    year = int(year)
    allsales = list_sales(c)
    sales = [x for x in allsales if (x["sale_date"] or "").startswith(str(year))]
    rcs = list_receipts(c)
    exp = sum(r["amount"] for r in rcs if (r["date"] or "").startswith(str(year)) and (r.get("source") or "manual") != "email")
    gross, cogs = sum(x["sale_price"] for x in sales), sum(x["cost_basis"] or 0 for x in sales)
    fees, ship = sum(x["total_fees"] or 0 for x in sales), sum(x["ship_cost"] for x in sales)
    years = sorted({int(x["sale_date"][:4]) for x in allsales if x["sale_date"]} | {int(r["date"][:4]) for r in rcs if r["date"]} | {date.today().year}, reverse=True)
    by_cat = {}
    for r in rcs:
        if (r["date"] or "").startswith(str(year)):
            by_cat[r["category"] or "Uncategorised"] = round(by_cat.get(r["category"] or "Uncategorised", 0) + r["amount"], 2)
    return {"year": year, "years": years, "gross": r2(gross), "cogs": r2(cogs), "fees": r2(fees), "shipping": r2(ship), "expenses": r2(exp),
            "net": r2(gross - cogs - fees - ship - exp), "missing_basis": sum(1 for x in sales if x["cost_basis"] is None), "sales": len(sales), "expense_by_category": by_cat}


# ------------------------------------------------------------------ scan station
def _log_scan(c, action, sku, result):
    c.execute("INSERT INTO inv_scans(ts,action,sku,result) VALUES(?,?,?,?)", (now(), action, sku, result))
    c.commit()


@locked
def scan(c, mode, code, sold_by=""):
    code = (code or "").strip()
    if not code:
        raise ValueError("Nothing scanned")
    it = c.execute("SELECT * FROM inv_items WHERE sku=?", (code.upper(),)).fetchone() or c.execute("SELECT * FROM inv_items WHERE barcode=? AND barcode<>''", (code,)).fetchone()
    if mode == "receive":
        if it:
            c.execute("UPDATE inv_items SET qty=qty+1, updated_at=? WHERE id=?", (now(), it["id"]))
            c.commit()
            _log_scan(c, "Receive", it["sku"], f"+1 {it['name']} (now {it['qty'] + 1})")
            return {"id": it["id"], "sku": it["sku"], "created": False, "message": f"{it['sku']} {it['name']}: quantity is now {it['qty'] + 1}"}
        if SKU_RE.match(code.upper()):
            sku, bc, cat = code.upper(), "", "Graphics Card" if code.upper().startswith("GC") else "Pokemon Card"
        else:
            cat, bc = "Pokemon Card", code
            sku = next_sku(c, cat)
        iid = c.execute("INSERT INTO inv_items(sku,category,name,qty,purchase_date,barcode,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?)",
                        (sku, cat, "(new item - fill in details)", 1, today(), bc, now(), now())).lastrowid
        c.commit()
        _log_scan(c, "Receive", sku, "Created a new row" + (f" for barcode {bc}" if bc else ""))
        return {"id": iid, "sku": sku, "created": True, "message": f"{sku}: new row created. Open it under Items and fill in the details."}
    if mode == "sell":
        full = next((x for x in list_items(c) if it and x["sku"] == it["sku"]), None)
        if not full:
            _log_scan(c, "Sell", code, "ERROR: not in inventory")
            raise ValueError(f"{code} isn't in inventory")
        if full["qty_remaining"] <= 0:
            _log_scan(c, "Sell", full["sku"], "ERROR: none left")
            raise ValueError(f"{full['sku']} {full['name']} is already sold out")
        r = save_sale(c, {"sku": full["sku"], "qty": 1, "sale_price": full["listed_price"] or 0, "sale_date": today(), "sold_by": sold_by, "platform": full["listing_platform"]})
        _log_scan(c, "Sell", full["sku"], "Sale logged" + ("" if full["listed_price"] else " (price still needed)"))
        return {"sale_id": r["id"], "sku": full["sku"], "created": True, "needs_price": not full["listed_price"],
                "message": f"{full['sku']} {full['name']}: sale logged" + ("" if full["listed_price"] else ". Enter the sale price under Sales.")}
    raise ValueError("Unknown scan mode")


def list_scans(c, limit=40):
    return db.rows(c, "SELECT * FROM inv_scans ORDER BY id DESC LIMIT ?", (limit,))


# ------------------------------------------------------------------ from the order tracker
@locked
def on_delivered(c, oid):
    """A tracker order just became Delivered: add it to inventory (or top up the matching item at a weighted-average cost). Once per order."""
    if not settings(c)["auto_from_orders"] or c.execute("SELECT 1 FROM inv_order_links WHERE order_id=?", (oid,)).fetchone():
        return None
    o = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if not o:
        return None
    lines = [(i["name"], int(i["qty"] or 1), float(i["unit_price"] or 0)) for i in c.execute("SELECT * FROM order_items WHERE order_id=?", (oid,))] or \
            [(o["product"] or f"{o['retailer']} order {o['order_number']}", int(o["qty"] or 1), round((o["total"] or 0) / max(1, int(o["qty"] or 1)), 2))]
    last = None
    added = []
    for name, qty, unit in lines:
        name = (name or "").strip() or f"{o['retailer']} item"
        cat = infer_category(name)
        ex = c.execute("SELECT * FROM inv_items WHERE lower(name)=lower(?) AND category=?", (name, cat)).fetchone() or _find_similar(c, name, cat)
        if ex:
            nq = ex["qty"] + qty
            price = round((ex["qty"] * ex["purchase_price"] + qty * unit) / nq, 4) if nq else unit
            c.execute("UPDATE inv_items SET qty=?, purchase_price=?, updated_at=? WHERE id=?", (nq, price, now(), ex["id"]))
            last = ex["sku"]
        else:
            last = next_sku(c, cat)
            c.execute("INSERT INTO inv_items(sku,category,name,qty,purchase_date,purchase_price,purchase_source,notes,created_at,updated_at) VALUES(?,?,?,?,?,?,?,?,?,?)",
                      (last, cat, name[:200], qty, (o["order_date"] or today())[:10], unit, o["retailer"], f"From order {o['order_number']}", now(), now()))
        added.append([last, qty])
    c.execute("INSERT OR REPLACE INTO inv_order_links(order_id, sku, lines) VALUES(?,?,?)", (oid, last, json.dumps(added)))
    c.commit()
    return last


def _norm(s):
    return re.sub(r"[^a-z0-9]+", "", (s or "").lower().replace("pokémon", "pokemon"))


def _find_similar(c, name, cat):
    n = _norm(name)
    for r in c.execute("SELECT * FROM inv_items WHERE category=?", (cat,)):
        if _norm(r["name"]) == n:
            return r
    return None


def on_undelivered(c, oid):
    """The order stopped being Delivered (status changed by hand, cancelled/refunded, or deleted): take back what was added to stock."""
    link = c.execute("SELECT * FROM inv_order_links WHERE order_id=?", (oid,)).fetchone()
    if not link:
        return False
    try:
        lines = json.loads(link["lines"] or "[]")
    except ValueError:
        lines = []
    for sku, qty in lines:
        it = c.execute("SELECT qty FROM inv_items WHERE sku=?", (sku,)).fetchone()
        if it:
            c.execute("UPDATE inv_items SET qty=?, updated_at=? WHERE sku=?", (max(0, it["qty"] - int(qty)), now(), sku))
    c.execute("DELETE FROM inv_order_links WHERE order_id=?", (oid,))
    c.commit()
    return True


# ------------------------------------------------------------------ purchase-confirmation receipts (from the tracker / scanned emails)
def receipt_from_order(c, oid, drop=False):
    """One info receipt per order, made from its confirmation email. Not counted as an expense (the cost is already in the item's purchase price);
    editing it by hand turns it into a normal, counted receipt."""
    ex = c.execute("SELECT * FROM inv_receipts WHERE order_id=?", (oid,)).fetchone()
    o = c.execute("SELECT * FROM orders WHERE id=?", (oid,)).fetchone()
    if drop or not o or o["status"] in ("cancelled", "refunded"):
        if ex and (ex["source"] or "") == "email":
            c.execute("DELETE FROM inv_receipts WHERE id=?", (ex["id"],))
            c.commit()
        return False
    if not settings(c).get("auto_receipts", 1):
        return False
    desc = (o["product"] or "").strip() or f"Order {o['order_number']}"
    note = f"From your confirmation email{' (' + o['account'] + ')' if o['account'] else ''}"
    if ex:
        if (ex["source"] or "") == "email":
            c.execute("UPDATE inv_receipts SET date=?, vendor=?, description=?, amount=? WHERE id=?",
                      ((o["order_date"] or today())[:10], o["retailer"], desc[:200], float(o["total"] or 0), ex["id"]))
            c.commit()
        return False
    c.execute("INSERT INTO inv_receipts(date,vendor,category,description,sku,amount,method,ref,notes,order_id,source) VALUES(?,?,?,?,?,?,?,?,?,?,'email')",
              ((o["order_date"] or today())[:10], o["retailer"], "Inventory Purchase", desc[:200], "", float(o["total"] or 0), "", o["order_number"], note, oid))
    c.commit()
    return True


def scan_receipts(c):
    """Make receipts for every tracked order that doesn't have one yet."""
    n = 0
    for r in c.execute("SELECT id FROM orders").fetchall():
        if receipt_from_order(c, r["id"]):
            n += 1
    return n


# ------------------------------------------------------------------ csv
EXPORTS = {
    "inventory": (lambda c: list_items(c), ["sku", "category", "name", "pokemon_set", "card_no", "condition", "grading", "qty", "added_by", "purchase_date", "purchase_price", "purchase_source",
                                            "listing_platform", "listed_price", "currency", "barcode", "status", "qty_sold", "qty_remaining", "sale_date", "sale_total", "fees_total", "net_total", "profit",
                                            "roi", "days_held", "market_price", "location", "notes"]),
    "sales": (lambda c: list_sales(c), ["sale_id", "sku", "item_name", "sale_date", "sold_by", "platform", "buyer", "sale_price", "ship_charged", "ship_cost", "fee_pct", "platform_fee", "other_fees",
                                        "total_fees", "net", "cost_basis", "profit", "roi", "qty", "notes"]),
    "receipts": (lambda c: list_receipts(c), ["date", "vendor", "category", "description", "sku", "amount", "method", "ref", "notes"]),
}


def export_csv(c, name):
    if name not in EXPORTS:
        raise ValueError("Unknown export")
    fn, cols = EXPORTS[name]
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(cols)
    for r in fn(c):
        w.writerow(["" if r.get(k) is None else r.get(k) for k in cols])
    return buf.getvalue()


def import_csv(c, name, text):
    rdr = csv.DictReader(io.StringIO(text.lstrip("﻿")))
    if not rdr.fieldnames:
        raise ValueError("The file is empty")
    added, errors = 0, []
    for i, row in enumerate(rdr, start=2):
        row = {(k or "").strip().lower(): (v or "").strip() for k, v in row.items()}
        if not any(row.values()):
            continue
        try:
            if name == "inventory":
                ex = c.execute("SELECT id FROM inv_items WHERE sku=?", (row.get("sku", "").upper(),)).fetchone() if row.get("sku") else None
                save_item(c, row, ex["id"] if ex else None)
            elif name == "sales":
                save_sale(c, row)
            elif name == "receipts":
                save_receipt(c, row)
            else:
                raise ValueError("Unknown import")
            added += 1
        except ValueError as e:
            errors.append(f"Row {i}: {e}")
    return {"added": added, "errors": errors[:30], "error_count": len(errors)}
