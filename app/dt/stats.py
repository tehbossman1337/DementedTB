"""Stick rates: how many orders survive (aren't cancelled or refunded), grouped by the email account they were placed with, the checkout
profile that placed them, and the card on that profile. Profiles are found through the linked bot checkout, or else by the order's email."""
import json
import re
from datetime import date, timedelta

LOST = ("cancelled", "refunded")


def _card_label(card):
    n = re.sub(r"\D", "", str((card or {}).get("number") or ""))
    if len(n) < 4:
        return ""
    t = ((card or {}).get("type") or "").strip() or {"4": "visa", "5": "mastercard", "3": "amex", "6": "discover"}.get(n[0], "card")
    return f"{t.title()} ···· {n[-4:]}"


def stick_rates(c, days=0, retailer=""):
    q, args = "SELECT id, retailer, status, account, order_date, total FROM orders WHERE 1=1", []
    if days:
        q += " AND COALESCE(order_date,'') >= ?"
        args.append((date.today() - timedelta(days=int(days))).isoformat())
    if retailer:
        q += " AND retailer = ?"
        args.append(retailer)
    orders = [dict(r) for r in c.execute(q, args)]
    co_prof = {r[0]: r[1] for r in c.execute("SELECT link_order_id, profile FROM checkouts WHERE link_order_id IS NOT NULL AND match_status='matched' AND deleted_at IS NULL AND COALESCE(profile,'')<>''")}
    by_name, by_email = {}, {}
    for r in c.execute("SELECT name, email, data FROM vprofiles"):
        try:
            d = json.loads(r["data"])
        except ValueError:
            d = {}
        info = {"card": _card_label(d.get("card")), "email": (r["email"] or d.get("email") or "").lower()}
        by_name.setdefault((r["name"] or "").strip().lower(), info)
        if info["email"]:
            by_email.setdefault(info["email"], (r["name"] or "").strip())
    groups = {"accounts": {}, "profiles": {}, "cards": {}, "retailers": {}}

    def add(kind, key, o):
        g = groups[kind].setdefault(key, {"key": key, "total": 0, "stuck": 0, "cancelled": 0, "delivered": 0, "partial": 0, "spent": 0.0})
        g["total"] += 1
        lost = o["status"] in LOST
        g["stuck"] += not lost
        g["cancelled"] += lost
        g["delivered"] += o["status"] == "delivered"
        g["partial"] += o["status"] == "partially_cancelled"
        g["spent"] = round(g["spent"] + (0 if lost else (o["total"] or 0)), 2)

    unassigned = 0
    for o in orders:
        acct = (o["account"] or "").strip().lower()
        add("accounts", acct or "(no email)", o)
        add("retailers", o["retailer"] or "(unknown)", o)
        prof = co_prof.get(o["id"]) or by_email.get(acct, "")
        if prof:
            add("profiles", prof, o)
            card = (by_name.get(prof.strip().lower()) or {}).get("card")
            if card:
                add("cards", card, o)
        else:
            unassigned += 1
    out = {}
    for k, g in groups.items():
        rows = sorted(g.values(), key=lambda x: (-x["total"], x["key"]))
        for r in rows:
            r["rate"] = round(r["stuck"] / r["total"], 4) if r["total"] else None
        out[k] = rows
    tot = len(orders)
    stuck = sum(o["status"] not in LOST for o in orders)
    out["overall"] = {"total": tot, "stuck": stuck, "rate": round(stuck / tot, 4) if tot else None, "unassigned": unassigned}
    out["retailer_list"] = sorted({r[0] for r in c.execute("SELECT DISTINCT retailer FROM orders") if r[0]})
    return out
