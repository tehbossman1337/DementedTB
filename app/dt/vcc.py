"""Virtual card manager (Amex, Capital One, others). Numbers and CVVs are encrypted at rest: the key lives next to the database and, on
Windows, is wrapped with DPAPI so only this Windows user can unlock it. The list API only ever returns masked numbers; the full
number is released one card at a time by reveal()."""
import base64
import csv
import io
import json
import os
import re
import sys

from . import config, db

ISSUERS = {"amex": "American Express", "capone": "Capital One", "other": "Other"}
_KEYFILE = lambda: os.path.join(config.DATA_DIR, "vcc.key")


# ---------------------------------------------------------------- key handling
def _dpapi(data, protect=True):
    import ctypes
    from ctypes import wintypes

    class BLOB(ctypes.Structure):
        _fields_ = [("cbData", wintypes.DWORD), ("pbData", ctypes.POINTER(ctypes.c_char))]
    buf = ctypes.create_string_buffer(data, len(data))
    inp, out = BLOB(len(data), ctypes.cast(buf, ctypes.POINTER(ctypes.c_char))), BLOB()
    f = ctypes.windll.crypt32.CryptProtectData if protect else ctypes.windll.crypt32.CryptUnprotectData
    if not f(ctypes.byref(inp), None, None, None, None, 0, ctypes.byref(out)):
        raise OSError("DPAPI failed")
    try:
        return ctypes.string_at(out.pbData, out.cbData)
    finally:
        ctypes.windll.kernel32.LocalFree(out.pbData)


def _key():
    from cryptography.fernet import Fernet
    p = _KEYFILE()
    if os.path.isfile(p):
        raw = open(p, "rb").read()
        if raw.startswith(b"DPAPI:"):
            return _dpapi(base64.b64decode(raw[6:]), False)
        return raw
    k = Fernet.generate_key()
    blob = b"DPAPI:" + base64.b64encode(_dpapi(k)) if sys.platform == "win32" else k
    os.makedirs(config.DATA_DIR, exist_ok=True)
    with open(p, "wb") as f:
        f.write(blob)
    try:
        os.chmod(p, 0o600)
    except OSError:
        pass
    return k


def _enc(text):
    from cryptography.fernet import Fernet
    return Fernet(_key()).encrypt((text or "").encode()).decode()


def _dec(tok):
    from cryptography.fernet import Fernet
    try:
        return Fernet(_key()).decrypt((tok or "").encode()).decode() if tok else ""
    except Exception:
        raise ValueError("This card was saved on another computer or user account and can't be unlocked here.")


# ---------------------------------------------------------------- helpers
def _digits(s):
    return re.sub(r"\D", "", str(s or ""))


def luhn(n):
    d = [int(x) for x in n][::-1]
    return (sum(d[0::2]) + sum(sum(divmod(x * 2, 10)) for x in d[1::2])) % 10 == 0


def _issuer(num, hint=""):
    h = (hint or "").lower()
    if "amex" in h or "american" in h or re.match(r"^3[47]", num):
        return "amex"
    if "capital" in h or "cap one" in h or "capone" in h or "eno" in h:
        return "capone"
    return "other"


def _exp(s):
    m = re.search(r"(\d{1,2})\s*[/\-]\s*(\d{2,4})", str(s or ""))
    if not m:
        return ""
    y = m.group(2)[-2:]
    return f"{int(m.group(1)):02d}/{y}"


def _mask(num):
    return ("•••• " * 3 + num[-4:]) if len(num) >= 4 else "••••"


def _public(r):
    num = _dec(r["number"])
    return {"id": r["id"], "issuer": r["issuer"], "issuer_label": ISSUERS.get(r["issuer"], r["issuer"]), "label": r["label"], "merchant": r["merchant"],
            "last4": num[-4:], "masked": _mask(num), "exp": r["exp"], "limit": r["lim"], "status": r["status"], "notes": r["notes"], "created_at": r["created_at"],
            "used": r["used"]}


def seed(c):
    c.execute("""CREATE TABLE IF NOT EXISTS vcc_cards(id INTEGER PRIMARY KEY AUTOINCREMENT, issuer TEXT, label TEXT DEFAULT '', merchant TEXT DEFAULT '',
        number TEXT, cvv TEXT DEFAULT '', exp TEXT DEFAULT '', lim REAL DEFAULT 0, status TEXT DEFAULT 'active', notes TEXT DEFAULT '', used INTEGER DEFAULT 0,
        fp TEXT DEFAULT '', created_at TEXT)""")


# ---------------------------------------------------------------- API
def list_cards(c, issuer="", q=""):
    seed(c)
    out = [_public(r) for r in c.execute("SELECT * FROM vcc_cards ORDER BY id DESC")]
    if issuer:
        out = [x for x in out if x["issuer"] == issuer]
    q = (q or "").lower().strip()
    if q:
        out = [x for x in out if q in " ".join(str(x[k]) for k in ("label", "merchant", "last4", "notes", "issuer_label")).lower()]
    return {"cards": out, "issuers": ISSUERS, "counts": {k: sum(1 for r in c.execute("SELECT issuer FROM vcc_cards") if r[0] == k) for k in ISSUERS}}


def save(c, rec, cid=None):
    seed(c)
    num = _digits(rec.get("number"))
    if cid and not num:
        old = c.execute("SELECT number FROM vcc_cards WHERE id=?", (cid,)).fetchone()
        num = _dec(old["number"]) if old else ""
    if len(num) < 13 or len(num) > 19 or not luhn(num):
        raise ValueError("That card number doesn't look valid.")
    cvv = _digits(rec.get("cvv"))
    if cid and not cvv:
        old = c.execute("SELECT cvv FROM vcc_cards WHERE id=?", (cid,)).fetchone()
        cvv = _dec(old["cvv"]) if old else ""
    issuer = rec.get("issuer") if rec.get("issuer") in ISSUERS else _issuer(num)
    vals = (issuer, str(rec.get("label") or "").strip()[:80], str(rec.get("merchant") or "").strip()[:80], _enc(num), _enc(cvv), _exp(rec.get("exp")),
            float(rec.get("limit") or 0), rec.get("status") if rec.get("status") in ("active", "used", "closed") else "active", str(rec.get("notes") or "")[:500])
    fp = base64.b16encode(__import__("hashlib").sha256(num.encode()).digest()[:8]).decode()
    if cid:
        c.execute("UPDATE vcc_cards SET issuer=?,label=?,merchant=?,number=?,cvv=?,exp=?,lim=?,status=?,notes=?,fp=? WHERE id=?", vals + (fp, cid))
    else:
        if c.execute("SELECT 1 FROM vcc_cards WHERE fp=?", (fp,)).fetchone():
            raise ValueError("That card is already saved.")
        cid = c.execute("INSERT INTO vcc_cards(issuer,label,merchant,number,cvv,exp,lim,status,notes,fp,created_at) VALUES(?,?,?,?,?,?,?,?,?,?,?)", vals + (fp, db.now())).lastrowid
    c.commit()
    return cid


def reveal(c, cid):
    seed(c)
    r = c.execute("SELECT * FROM vcc_cards WHERE id=?", (cid,)).fetchone()
    if not r:
        raise ValueError("Card not found")
    return {"number": _dec(r["number"]), "cvv": _dec(r["cvv"]), "exp": r["exp"]}


def delete(c, ids):
    seed(c)
    c.executemany("DELETE FROM vcc_cards WHERE id=?", [(int(i),) for i in ids])
    c.commit()


def set_status(c, ids, status):
    seed(c)
    if status not in ("active", "used", "closed"):
        raise ValueError("Bad status")
    c.executemany("UPDATE vcc_cards SET status=? WHERE id=?", [(status, int(i)) for i in ids])
    c.commit()


_NUM = r"\b(?:3[47]\d{2}[ \-]?\d{6}[ \-]?\d{5}|(?:\d{4}[ \-]?){3}\d{1,4})\b"


def parse(text, issuer_hint=""):
    """Accepts CSV with a header row (number/card/pan, exp/expiry, cvv/cvc/security, label/name, merchant, limit) or free text where each card is a
    number followed by an expiry and a CVV, on one line or on a few lines."""
    text = (text or "").strip()
    cards = []
    if "," in text.splitlines()[0] if text else False:
        rows = list(csv.DictReader(io.StringIO(text)))
        for r in rows:
            g = lambda *ks: next((str(v) for k, v in r.items() if k and any(x in k.lower() for x in ks) and v), "")
            num = _digits(g("number", "card", "pan"))
            if num:
                cards.append({"number": num, "exp": g("exp"), "cvv": g("cvv", "cvc", "security"), "label": g("label", "name", "nick"), "merchant": g("merchant", "site", "vendor"),
                              "limit": re.sub(r"[^\d.]", "", g("limit", "amount")) or 0, "issuer": _issuer(num, g("issuer", "bank") or issuer_hint)})
        if cards:
            return cards
    flat = re.sub(r"[ \t]*[\n;|]+[ \t]*", " | ", text)
    for block in re.split(r"\s\|\s(?=" + _NUM + r")|\n\n+", flat):
        m = re.search("(" + _NUM + ")", block)
        if not m:
            continue
        num = _digits(m.group(1))
        rest = block.replace(m.group(1), " ")
        exp = re.search(r"\b(0?[1-9]|1[0-2])\s*[/\-]\s*(\d{4}|\d{2})\b", rest)
        cv = re.search(r"(?:cvv2?|cvc|csc|cid|security(?: code)?)\D{0,4}(\d{3,4})\b", rest, re.I)
        if not cv:
            r2 = rest.replace(exp.group(0), " ") if exp else rest
            cv = re.search(r"\b(\d{3,4})\b", r2)
        cards.append({"number": num, "exp": exp.group(0) if exp else "", "cvv": cv.group(1) if cv else "", "issuer": _issuer(num, issuer_hint)})
    return cards


def import_text(c, text, issuer="", merchant=""):
    added = skipped = bad = 0
    for r in parse(text, issuer):
        if issuer in ISSUERS:
            r["issuer"] = issuer
        if merchant and not r.get("merchant"):
            r["merchant"] = merchant
        try:
            save(c, r)
            added += 1
        except ValueError as e:
            if "already" in str(e):
                skipped += 1
            else:
                bad += 1
    return {"added": added, "skipped": skipped, "invalid": bad}
