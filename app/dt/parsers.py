"""Turn retailer emails into order events.

A retailer is recognised by the sender's domain (or, for forwarded mail, by the original sender / brand in the text).
Anything that looks like an order but can't be read with confidence is returned as None + a reason so it lands in
"Needs attention" instead of being guessed.
"""
import re
from datetime import datetime
from email.utils import parsedate_to_datetime

RETAILERS = {
    "Pokémon Center": ["pokemoncenter.com", "pokemon.com"],
    "Target": ["target.com"],
    "Walmart": ["walmart.com"],
    "Best Buy": ["bestbuy.com"],
    "GameStop": ["gamestop.com"],
    "Costco": ["costco.com"],
    "Sam's Club": ["samsclub.com"],
    "Amazon": ["amazon.com"],
    "TCGplayer": ["tcgplayer.com"],
    "Newegg": ["newegg.com"],
    "Micro Center": ["microcenter.com"],
}
BRANDS = {"Pokémon Center": ["pokemon center", "pokémon center", "pokemoncenter"], "Target": ["target.com", "target order", "target brands, inc", "target circle"], "Walmart": ["walmart"],
          "Best Buy": ["best buy", "bestbuy"], "GameStop": ["gamestop"], "Costco": ["costco"], "Sam's Club": ["sam's club", "samsclub"],
          "Amazon": ["amazon"], "TCGplayer": ["tcgplayer"], "Newegg": ["newegg"], "Micro Center": ["micro center", "microcenter"]}
RETAILER_COLORS = {"Pokémon Center": "#f5c400", "Target": "#e5304f", "Walmart": "#2f7de1", "Best Buy": "#f0d000", "GameStop": "#e11d48",
                   "Costco": "#d33a3a", "Sam's Club": "#2f7de1", "Amazon": "#f59e0b", "TCGplayer": "#34a0e8", "Newegg": "#f97316", "Micro Center": "#4aa3ff"}

STATUS_ORDER = ["placed", "shipped", "out_for_delivery", "delivered"]
STATUS_LABEL = {"placed": "Placed", "shipped": "Shipped", "out_for_delivery": "Out for delivery", "delivered": "Delivered",
                "cancelled": "Cancelled", "partially_cancelled": "Partially cancelled", "refunded": "Refunded"}

STATUS_RULES = [  # first match wins; checked against the subject, then the start of the body
    ("refunded", r"refund(ed)? (has been |was |is )?(issued|processed|initiated|on its way)|your refund|refund (confirmation|issued|processed)"),
    ("partially_cancelled", r"partial(ly)? cancel|some items? (in|from) your order (was|were|has been|have been|got) cancel|some items? (was|were|has been|have been) cancel|an item (in|from) your order (was|has been) cancel|item(s)? (was|were|has been|have been) cancel|part of your order|had to cancel (an|some|one) item"),
    ("cancelled", r"cancel+ed|has been cancel|order cancellation|cancellation (confirm|notice)|unable to (fulfill|ship)|we.?re sorry.*order"),
    ("out_for_delivery", r"out for delivery|arriv(ing|es) today|driver is on the way|on (its|the) way to you today|your delivery is (almost here|on the way)"),
    ("delivered", r"\bdelivered\b|has been delivered|was delivered|ready for pickup|picked up"),
    ("shipped", r"\bshipped\b|has shipped|on its way|tracking number|shipment (confirmation|notification)|in transit"),
    ("placed", r"order (confirmation|confirmed|received|placed|summary|details)|we got your order|order (has been|was) (received|placed)|here.?s your order|thank(s| you) for (your|shopping|ordering)|thank(s| you) for (your )?.{0,40}order|we.?ve received your order|your .{0,40}order|order #|confirmation"),
]
ORDER_NO = [
    r"order\s*(?:number|no\.?|#|id)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-]{5,24})",
    r"order\s*#\s*([A-Z0-9][A-Z0-9\-]{5,24})",
    r"(?:confirmation|reference)\s*(?:number|no\.?|#|code|id)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-]{5,24})",
    r"\border\s*[:\-]\s*#?\s*([A-Z0-9][A-Z0-9\-]{5,24})",
    r"\border\s+([0-9]{7,15})\b",
    r"#\s*([0-9]{6,15})",
]
# What each big retailer's order emails actually look like. Tried before the generic patterns.
PROFILES = {
    "Walmart": {
        # 2000140-12345678 (shown with a dash) or the same 15 digits run together
        "order": [r"order\s*(?:#|number|no\.?)?\s*[:#]?\s*(\d{7}-\d{8})\b", r"\b(\d{7}-\d{8})\b", r"order\s*(?:#|number|no\.?)\s*[:#]?\s*(\d{13,16})\b"],
        "status": [("cancelled", r"^(your )?order (was|has been) cancel+ed"), ("partially_cancelled", r"(item|items) (was|were|has been|have been)? ?cancel+ed"),
                   ("delivered", r"^delivered[:!]|your (package|order|delivery) (was|has been) delivered"), ("shipped", r"^shipped[:!]|your (package|order|item)s? (has |have )?shipped"),
                   ("out_for_delivery", r"arriv(es|ing) today|out for delivery")],
    },
    "Target": {
        "order": [r"order\s*(?:#|number|no\.?)\s*[:#]?\s*(\d{9,16})\b", r"here.?s your order\s*#?\s*:?\s*(\d{9,16})"],
        "status": [("placed", r"thanks for shopping with us|here.?s your order"), ("delivered", r"(was|has been) delivered|is ready for (pick ?up|drive ?up)|picked up"),
                   ("shipped", r"(is|are) on (its|the|their) way|has shipped|have shipped|shipped")],
        "skip_sender": r"targetnews@|@em\.target\.com|@e\.target\.com",
    },
    "Best Buy": {
        "order": [r"\b(BBY\d{2}-\d{9,14})\b", r"order\s*(?:#|number|no\.?)\s*[:#]?\s*(BBY\d{2}-?\d{9,14})"],
        "status": [("delivered", r"(was|has been) delivered|ready for (store )?pick ?up|picked up"), ("shipped", r"(has|have) shipped|is on (its|the) way|shipping confirmation"),
                   ("placed", r"thanks for (your )?(order|shopping)|order (has been )?received|we.?ve got your order")],
        "skip_sender": r"bestbuy@email\.bestbuy\.com|@e\.bestbuy\.com",
    },
}
NOT_ORDER_SUBJECT = re.compile(r"\b(welcome to|verify your|confirm your email|password|sign[- ]?in|security code|one[- ]time (pass)?code|verification code|"
                               r"account (created|update)|create your account|survey|review your (purchase|item)|rate your|how did we do|tell us what you think)\b", re.I)
TRACKING = [r"\b(1Z[0-9A-Z]{16})\b", r"\b(9[2345]\d{18,22})\b", r"tracking\s*(?:number|no\.?|#)?\s*[:#]?\s*([A-Z0-9]{10,30})"]
TOTAL = r"(?:order\s+total|total(?:\s+charged)?|grand total|amount charged|estimated total)\s*[:\-]?\s*\$\s*([\d,]+\.\d{2})"
TOTAL_ALL = re.compile(r"(?<![A-Za-z])(order\s+total|grand\s+total|total\s+charged|amount\s+charged|estimated\s+total|payment\s+total|total)\s*[:\-]?\s*(?:\(\d+\s+items?\))?\s*\$\s*([\d,]+\.\d{2})", re.I)


def find_total(body):
    """The order total, not the subtotal: prefer an explicit 'order/grand total', otherwise the last plain 'Total'."""
    best = None
    for m in TOTAL_ALL.finditer(body or ""):
        before = (body[max(0, m.start() - 4):m.start()]).lower()
        if "sub" in before:
            continue
        label = m.group(1).lower()
        if label != "total":
            return m.group(2)
        best = m.group(2)
    return best or ""
PRICE = re.compile(r"\$\s*([\d,]+\.\d{2})")
SKU_RE = re.compile(r"(?:sku|dpci|item\s*#|item number|model)\s*[:#]?\s*([A-Z0-9\-]{5,20})", re.I)
NOT_ITEM = re.compile(r"\b(total|subtotal|sub-total|tax|shipping|handling|discount|savings?|save|from|gift|balance|estimated|points|was|price|payment|visa|"
                      r"mastercard|amex|paypal|promo|coupon|order|delivery|fee|refund)\b", re.I)
QTY_ONLY = re.compile(r"^(?:qty|quantity)\s*[:x]?\s*(\d{1,3})\b|^x\s*(\d{1,3})$|^(\d{1,3})\s*x$", re.I)
ITEM_A = re.compile(r"^\s*(\d{1,3})\s*[x×]\s+(.{6,120}?)(?:\s+[-–@]\s*|\s+)\$\s*([\d,]+\.\d{2})\s*$", re.I)
ITEM_B = re.compile(r"^\s*(.{6,120}?)\s+(?:qty|quantity)\s*[:x]?\s*(\d{1,3})\s+(?:\$\s*)?([\d,]+\.\d{2})\s*$", re.I)
ITEM_C = re.compile(r"^(.{6,120}?)\s{2,}(\d{1,3})\s{2,}\$\s*([\d,]+\.\d{2})(?:\s{2,}\$\s*[\d,]+\.\d{2})?\s*$")


_RELAY = re.compile(r"([A-Za-z0-9.+%-]+(?:_[A-Za-z0-9.+%-]+)*?)_at_([A-Za-z0-9_-]+)_[A-Za-z0-9]{3,}@(?:icloud\.com|me\.com|privaterelay\.appleid\.com)", re.I)


def unrelay(sender):
    """iCloud Hide My Email rewrites the sender so replies go through Apple, e.g. Target <orders_at_oe_target_com_x7k2qz@icloud.com>.
    Put the real address back (orders@oe.target.com) so the store can be recognised; anything else is returned unchanged."""
    if not sender or "_at_" not in sender:
        return sender
    def fix(m):
        return f"{m.group(1)}@{m.group(2).replace('_', '.')}"
    return _RELAY.sub(fix, sender)


def _display_name(sender):
    from email.utils import parseaddr
    return re.sub(r"[^a-z0-9' ]+", " ", parseaddr(sender or "")[0].lower()).strip()


NAME_ALIASES = {"target": "Target", "target com": "Target", "target orders": "Target", "walmart": "Walmart", "walmart com": "Walmart",
                "best buy": "Best Buy", "my best buy": "Best Buy", "bestbuy": "Best Buy", "pok mon center": "Pokémon Center", "pokemon center": "Pokémon Center"}


def detect_retailer(sender, extra="", default=None):
    sender = unrelay(sender)
    s = (sender or "").lower()
    for name, doms in RETAILERS.items():
        if any(d in s for d in doms):
            return name
    nm = _display_name(sender)  # the sender's name ("Target") when the address is relayed or unusual
    if nm in NAME_ALIASES:
        return NAME_ALIASES[nm]
    e = (extra or "").lower()
    for name, doms in RETAILERS.items():
        if any(d in e for d in doms):
            return name
    for name, words in BRANDS.items():
        if any(w in e for w in words):
            return name
    return default


def detect_status(subject, body, retailer=None):
    prof = PROFILES.get(retailer or "", {})
    for hay in (subject or "",):
        for status, pat in prof.get("status", []):
            if re.search(pat, hay.strip(), re.I):
                return status
    for hay in (subject or "", (body or "")[:1500]):
        for status, pat in STATUS_RULES:
            if re.search(pat, hay, re.I):
                return status
    return None


def _first(patterns, text, flags=re.I):
    for p in patterns:
        m = re.search(p, text, flags)
        if m:
            return m.group(1).strip()
    return ""


def _name_like(l):
    return len(re.findall(r"[A-Za-z]", l)) >= 6 and not PRICE.fullmatch(l.strip()) and not re.match(r"^(item|price|qty|quantity|sku|total|subtotal)\b[:\s]*$", l.strip(), re.I)


def _loose_items(lines):
    items = []
    for i, ln in enumerate(lines):
        m = QTY_ONLY.match(ln.strip())
        if not m:
            continue
        qty = int(next(g for g in m.groups() if g))
        name = next((lines[j].strip() for j in range(i - 1, max(-1, i - 5), -1) if _name_like(lines[j]) and not NOT_ITEM.search(lines[j].split("$")[0][:40] or "")), None) \
            or next((lines[j].strip() for j in range(i - 1, max(-1, i - 5), -1) if _name_like(lines[j])), None)
        pm = next((PRICE.search(w) for w in lines[max(0, i - 1):i + 4] if PRICE.search(w)), None)
        if name and pm and qty:
            amt = float(pm.group(1).replace(",", ""))
            items.append({"name": PRICE.sub("", name).strip(" -–:|"), "qty": qty, "price": round(amt / qty, 2), "_amt": amt})
    if items:
        return items
    for ln in lines:
        m = re.match(r"^(.{8,120}?)\s{1,}[-–:|]?\s*\$\s*([\d,]+\.\d{2})\s*$", ln.strip())
        if m and _name_like(m.group(1)) and not NOT_ITEM.search(m.group(1)):
            items.append({"name": m.group(1).strip(" -–:|"), "qty": 1, "price": float(m.group(2).replace(",", "")), "_amt": float(m.group(2).replace(",", ""))})
    return items


def _money(label_re, body):
    m = re.search(r"(?<![A-Za-z])(?:" + label_re + r")\s*[:\-]?\s*\$\s*([\d,]+\.\d{2})", body or "", re.I)
    return float(m.group(1).replace(",", "")) if m else None


def amounts(body):
    """Subtotal, tax and shipping as printed in the email (None when not shown). 'Free' shipping counts as 0."""
    sub = _money(r"sub-?\s?total|items? subtotal|merchandise(?: subtotal)?|item\(s\) subtotal", body)
    tax = _money(r"(?:estimated\s+)?(?:sales\s+)?tax(?:es)?", body)
    ship = _money(r"shipping(?:\s*(?:&|and)\s*handling)?|delivery(?: fee)?|estimated shipping", body)
    if ship is None and re.search(r"(?<![A-Za-z])(shipping|delivery)\s*[:\-]?\s*free\b", body or "", re.I):
        ship = 0.0
    return {"subtotal": sub, "tax": tax, "shipping": ship}


def fix_item_prices(items, subtotal=None, total=None):
    """An amount next to an item is sometimes the price of one and sometimes the line total (price × qty). Pick whichever reading matches
    the email's subtotal (or, without one, doesn't exceed the order total). Returns items with a per-unit 'price'."""
    if not items:
        return items
    as_line = sum(it.get("_amt", it["price"] * it["qty"]) for it in items)            # amount was the line total
    as_unit = sum(it.get("_amt", it["price"]) * it["qty"] for it in items)            # amount was one unit
    target = subtotal or None
    pick_unit = None
    if target:
        dl, du = abs(as_line - target), abs(as_unit - target)
        if min(dl, du) <= max(0.05, target * 0.02):
            pick_unit = du < dl
    elif total and as_line != as_unit:
        fits = [(total - v, is_unit) for v, is_unit in ((as_line, False), (as_unit, True)) if v <= total * 1.02]
        if fits:  # tax and shipping only ever add to the items, so the reading closest to (but not above) the total wins
            pick_unit = min(fits)[1]
    for it in items:
        amt = it.pop("_amt", None)
        unit_flag = it.pop("_unit", False)
        if amt is None:
            continue
        use_unit = pick_unit if pick_unit is not None else unit_flag
        it["price"] = round(amt if use_unit else amt / max(1, it["qty"]), 2)
    return items


def parse_items(body):
    items, lines = [], body.splitlines()
    for ln in lines:
        m = ITEM_A.match(ln)
        if m:
            q, p = int(m.group(1)), float(m.group(3).replace(",", ""))
            items.append({"name": m.group(2).strip(" -–"), "qty": q, "price": round(p / q, 2) if q else p, "_amt": p})
            continue
        m = ITEM_B.match(ln)
        if m:
            items.append({"name": m.group(1).strip(" -–"), "qty": int(m.group(2)), "price": float(m.group(3).replace(",", "")), "_amt": float(m.group(3).replace(",", "")), "_unit": True})
    if not items:
        for ln in lines:
            m = ITEM_C.match(ln)
            if m and _name_like(m.group(1)):
                items.append({"name": m.group(1).strip(" -–"), "qty": int(m.group(2)), "price": float(m.group(3).replace(",", "")), "_amt": float(m.group(3).replace(",", "")), "_unit": True})
    if not items:
        items = _loose_items([l for l in lines if l.strip()])
    for i, ln in enumerate(lines):
        sm = SKU_RE.search(ln)
        if sm and items:
            for it in items:
                if it["name"] and it["name"] in "\n".join(lines[max(0, i - 3):i + 1]):
                    it.setdefault("sku", sm.group(1))
    return items


CARRIERS = [("UPS", r"^1Z[0-9A-Z]{16}$"), ("USPS", r"^(9[2345]\d{18,22}|[A-Z]{2}\d{9}US)$"), ("FedEx", r"^(\d{12}|\d{15}|\d{20})$"),
            ("Amazon Logistics", r"^TBA\d{9,}$"), ("DHL", r"^\d{10}$")]


def guess_carrier(n):
    n = (n or "").upper().replace(" ", "")
    return next((c for c, p in CARRIERS if re.match(p, n)), "")


def unwrap_forward(body):
    """For a forwarded email, return (original sender, original subject) if the forward header is in the text."""
    m = re.search(r"-{2,}\s*Forwarded message\s*-{2,}.*?From:\s*(.+?)\n(?:.*?\n)*?\s*Subject:\s*(.+?)\n", body or "", re.I | re.S)
    return (m.group(1).strip(), m.group(2).strip()) if m else ("", "")


def parse_email(sender, subject, body, date_header=None, extra="", default=None):
    """Return (event | None, reason)."""
    fwd_from, fwd_subj = unwrap_forward(body)
    retailer = detect_retailer(fwd_from or sender, extra or f"{fwd_subj or subject}\n{(body or '')[:800]}", default)
    if not retailer:
        return None, "unknown retailer"
    prof = PROFILES.get(retailer, {})
    if prof.get("skip_sender") and re.search(prof["skip_sender"], unrelay(fwd_from or sender or ""), re.I):
        return None, "marketing email"
    if NOT_ORDER_SUBJECT.search(fwd_subj or subject or ""):
        return None, "not an order email"
    status = detect_status(fwd_subj or subject, body, retailer)
    if not status:
        return None, "could not tell the order status"
    text = f"{subject}\n{fwd_subj}\n{body}"
    order_no = _first(prof.get("order", []), text) or _first(ORDER_NO, text)
    if not order_no:
        return None, "no order number found"
    total = find_total(body)
    tracking = ""
    if status in ("shipped", "out_for_delivery", "delivered", "placed"):
        tracking = _first(TRACKING, body) if status != "placed" else ""
    try:
        d = parsedate_to_datetime(date_header).date().isoformat() if date_header else None
    except Exception:
        d = None
    money = amounts(body)
    tot = float(total.replace(",", "")) if total else None
    items = parse_items(body) if status in ("placed", "shipped", "delivered", "out_for_delivery", "partially_cancelled") else []
    items = fix_item_prices(items, money["subtotal"], tot)
    return {"retailer": retailer, "order_number": order_no.upper(), "status": status, "date": d or datetime.now().date().isoformat(),
            "total": tot, "tracking": tracking, "carrier": guess_carrier(tracking), "items": items, **money}, ""
