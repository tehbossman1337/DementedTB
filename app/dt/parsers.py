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
BRANDS = {"Pokémon Center": ["pokemon center", "pokémon center", "pokemoncenter"], "Target": ["target.com", "target order"], "Walmart": ["walmart"],
          "Best Buy": ["best buy", "bestbuy"], "GameStop": ["gamestop"], "Costco": ["costco"], "Sam's Club": ["sam's club", "samsclub"],
          "Amazon": ["amazon"], "TCGplayer": ["tcgplayer"], "Newegg": ["newegg"], "Micro Center": ["micro center", "microcenter"]}
RETAILER_COLORS = {"Pokémon Center": "#f5c400", "Target": "#e5304f", "Walmart": "#2f7de1", "Best Buy": "#f0d000", "GameStop": "#e11d48",
                   "Costco": "#d33a3a", "Sam's Club": "#2f7de1", "Amazon": "#f59e0b", "TCGplayer": "#34a0e8", "Newegg": "#f97316", "Micro Center": "#4aa3ff"}

STATUS_ORDER = ["placed", "shipped", "out_for_delivery", "delivered"]
STATUS_LABEL = {"placed": "Placed", "shipped": "Shipped", "out_for_delivery": "Out for delivery", "delivered": "Delivered",
                "cancelled": "Cancelled", "partially_cancelled": "Partially cancelled", "refunded": "Refunded"}

STATUS_RULES = [  # first match wins; checked against the subject, then the start of the body
    ("refunded", r"refund(ed)? (has been |was |is )?(issued|processed|initiated|on its way)|your refund|refund (confirmation|issued|processed)"),
    ("partially_cancelled", r"partial(ly)? cancel|some items? (in your order )?(was|were|has been|have been) cancel|item(s)? (was|were|has been|have been) cancel|part of your order"),
    ("cancelled", r"cancel+ed|has been cancel|order cancellation|cancellation (confirm|notice)|unable to (fulfill|ship)|we.?re sorry.*order"),
    ("out_for_delivery", r"out for delivery|arriving today|driver is on the way|on (its|the) way to you today"),
    ("delivered", r"\bdelivered\b|has been delivered|was delivered|ready for pickup|picked up"),
    ("shipped", r"\bshipped\b|has shipped|on its way|tracking number|shipment (confirmation|notification)|in transit"),
    ("placed", r"order (confirmation|confirmed|received|placed|summary|details)|thank(s| you) for (your|shopping|ordering)|thank(s| you) for (your )?.{0,40}order|we.?ve received your order|your .{0,40}order|order #|confirmation"),
]
ORDER_NO = [
    r"order\s*(?:number|no\.?|#|id)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-]{5,24})",
    r"order\s*#\s*([A-Z0-9][A-Z0-9\-]{5,24})",
    r"(?:confirmation|reference)\s*(?:number|no\.?|#|code|id)\s*[:#]?\s*([A-Z0-9][A-Z0-9\-]{5,24})",
    r"\border\s*[:\-]\s*#?\s*([A-Z0-9][A-Z0-9\-]{5,24})",
    r"\border\s+([0-9]{7,15})\b",
    r"#\s*([0-9]{6,15})",
]
TRACKING = [r"\b(1Z[0-9A-Z]{16})\b", r"\b(9[2345]\d{18,22})\b", r"tracking\s*(?:number|no\.?|#)?\s*[:#]?\s*([A-Z0-9]{10,30})"]
TOTAL = r"(?:order\s+total|total(?:\s+charged)?|grand total|amount charged|estimated total)\s*[:\-]?\s*\$\s*([\d,]+\.\d{2})"
PRICE = re.compile(r"\$\s*([\d,]+\.\d{2})")
SKU_RE = re.compile(r"(?:sku|dpci|item\s*#|item number|model)\s*[:#]?\s*([A-Z0-9\-]{5,20})", re.I)
NOT_ITEM = re.compile(r"\b(total|subtotal|sub-total|tax|shipping|handling|discount|savings?|save|from|gift|balance|estimated|points|was|price|payment|visa|"
                      r"mastercard|amex|paypal|promo|coupon|order|delivery|fee|refund)\b", re.I)
QTY_ONLY = re.compile(r"^(?:qty|quantity)\s*[:x]?\s*(\d{1,3})\b|^x\s*(\d{1,3})$|^(\d{1,3})\s*x$", re.I)
ITEM_A = re.compile(r"^\s*(\d{1,3})\s*[x×]\s+(.{6,120}?)(?:\s+[-–@]\s*|\s+)\$\s*([\d,]+\.\d{2})\s*$", re.I)
ITEM_B = re.compile(r"^\s*(.{6,120}?)\s+(?:qty|quantity)\s*[:x]?\s*(\d{1,3})\s+(?:\$\s*)?([\d,]+\.\d{2})\s*$", re.I)
ITEM_C = re.compile(r"^(.{6,120}?)\s{2,}(\d{1,3})\s{2,}\$\s*([\d,]+\.\d{2})(?:\s{2,}\$\s*[\d,]+\.\d{2})?\s*$")


def detect_retailer(sender, extra="", default=None):
    s = (sender or "").lower()
    for name, doms in RETAILERS.items():
        if any(d in s for d in doms):
            return name
    e = (extra or "").lower()
    for name, doms in RETAILERS.items():
        if any(d in e for d in doms):
            return name
    for name, words in BRANDS.items():
        if any(w in e for w in words):
            return name
    return default


def detect_status(subject, body):
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
            items.append({"name": PRICE.sub("", name).strip(" -–:|"), "qty": qty, "price": round(float(pm.group(1).replace(",", "")) / qty, 2)})
    if items:
        return items
    for ln in lines:
        m = re.match(r"^(.{8,120}?)\s{1,}[-–:|]?\s*\$\s*([\d,]+\.\d{2})\s*$", ln.strip())
        if m and _name_like(m.group(1)) and not NOT_ITEM.search(m.group(1)):
            items.append({"name": m.group(1).strip(" -–:|"), "qty": 1, "price": float(m.group(2).replace(",", ""))})
    return items


def parse_items(body):
    items, lines = [], body.splitlines()
    for ln in lines:
        m = ITEM_A.match(ln)
        if m:
            q, p = int(m.group(1)), float(m.group(3).replace(",", ""))
            items.append({"name": m.group(2).strip(" -–"), "qty": q, "price": round(p / q, 2) if q else p})
            continue
        m = ITEM_B.match(ln)
        if m:
            items.append({"name": m.group(1).strip(" -–"), "qty": int(m.group(2)), "price": float(m.group(3).replace(",", ""))})
    if not items:
        for ln in lines:
            m = ITEM_C.match(ln)
            if m and _name_like(m.group(1)):
                items.append({"name": m.group(1).strip(" -–"), "qty": int(m.group(2)), "price": float(m.group(3).replace(",", ""))})
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
    status = detect_status(fwd_subj or subject, body)
    if not status:
        return None, "could not tell the order status"
    text = f"{subject}\n{fwd_subj}\n{body}"
    order_no = _first(ORDER_NO, text)
    if not order_no:
        return None, "no order number found"
    total = _first([TOTAL], body)
    tracking = ""
    if status in ("shipped", "out_for_delivery", "delivered", "placed"):
        tracking = _first(TRACKING, body) if status != "placed" else ""
    try:
        d = parsedate_to_datetime(date_header).date().isoformat() if date_header else None
    except Exception:
        d = None
    return {"retailer": retailer, "order_number": order_no.upper(), "status": status, "date": d or datetime.now().date().isoformat(),
            "total": float(total.replace(",", "")) if total else None, "tracking": tracking, "carrier": guess_carrier(tracking),
            "items": parse_items(body) if status in ("placed", "shipped", "delivered", "out_for_delivery", "partially_cancelled") else []}, ""
