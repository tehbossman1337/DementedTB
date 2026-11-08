"""Profiles (checkout identities: contact, card, shipping, billing) and site accounts (login, proxy), grouped by website.
Stored as whole JSON records so fields from imported Valor files survive an import -> export round trip unchanged."""
import copy
import json
import re
import uuid

from . import db, variants

COUNTRIES = {"US": "United States", "CA": "Canada", "GB": "United Kingdom", "AU": "Australia", "DE": "Germany", "FR": "France", "JP": "Japan", "MX": "Mexico"}


def _addr():
    return {"firstName": "", "lastName": "", "addressLine1": "", "addressLine2": "", "city": "", "countryName": "United States", "countryCode": "US", "state": "", "zipCode": ""}


def blank_profile():
    return {"name": "", "email": "", "phoneNumber": "", "billingSameAsShipping": True, "oneCheckout": False, "quickTask": False,
            "card": {"holder": "", "number": "", "expiration": "", "cvv": "", "type": ""}, "shipping": _addr(), "billing": _addr(),
            "id": "", "totalSpent": 0, "selected": False}


def card_type(number):
    n = re.sub(r"\D", "", str(number or ""))
    if n.startswith("4"):
        return "visa"
    if re.match(r"^(5[1-5]|2(2[2-9]|[3-6]\d|7[01]|720))", n):
        return "mastercard"
    if re.match(r"^3[47]", n):
        return "amex"
    if re.match(r"^(6011|65|64[4-9])", n):
        return "discover"
    return ""


def _fill(rec, base):
    """Keep every key of rec (including ones we don't know) and add any standard key it lacks."""
    out = copy.deepcopy(rec)
    for k, v in base.items():
        if k not in out:
            out[k] = copy.deepcopy(v)
        elif isinstance(v, dict) and isinstance(out[k], dict):
            for kk, vv in v.items():
                out[k].setdefault(kk, vv)
    return out


def clean(rec):
    r = _fill(rec if isinstance(rec, dict) else {}, blank_profile())
    r["id"] = r.get("id") or str(uuid.uuid4())
    if r["card"].get("number"):
        r["card"]["type"] = r["card"].get("type") or card_type(r["card"]["number"])
    for k in ("billingSameAsShipping", "oneCheckout", "quickTask", "selected"):
        r[k] = bool(r[k])
    if r["billingSameAsShipping"]:
        r["billing"] = {**r["shipping"]}
    return r


def _put_profile(c, site, rec, parent=None):
    c.execute("INSERT INTO vprofiles(id,site,parent_id,name,email,data,created_at) VALUES(?,?,?,?,?,?,?) ON CONFLICT(id) DO UPDATE SET "
              "site=excluded.site,name=excluded.name,email=excluded.email,data=excluded.data", (rec["id"], site, parent, rec["name"], rec["email"], json.dumps(rec), db.now()))


def list_profiles(c):
    return [{"id": r["id"], "site": r["site"], "parent_id": r["parent_id"], "rec": json.loads(r["data"])} for r in c.execute("SELECT * FROM vprofiles ORDER BY site, COALESCE(parent_id,id), rowid")]


def save_profile(c, site, rec, pid=None):
    if not site:
        raise ValueError("Pick a group first")
    rec = clean(rec)
    if pid:
        rec["id"] = pid
    if not rec["name"].strip():
        raise ValueError("Give the profile a name")
    old = c.execute("SELECT parent_id FROM vprofiles WHERE id=?", (rec["id"],)).fetchone()
    _put_profile(c, site, rec, old["parent_id"] if old else None)
    c.commit()
    return rec["id"]


def import_profiles(c, site, text, replace=False):
    try:
        root = json.loads(text)
    except ValueError:
        raise ValueError("That file isn't valid JSON")
    if isinstance(root, dict) and "shipping" in root:
        recs = [root]
    elif isinstance(root, dict) and root and all(isinstance(v, dict) for v in root.values()):
        recs = list(root.values())
    elif isinstance(root, list) and all(isinstance(v, dict) for v in root):
        recs = root
    else:
        raise ValueError("This doesn't look like a profiles file")
    if not recs or not any("shipping" in r or "card" in r for r in recs):
        raise ValueError("This doesn't look like a profiles file (no shipping or card fields)")
    if replace:
        c.execute("DELETE FROM vprofiles WHERE site=?", (site,))
    added = updated = 0
    for r in recs:
        rec = _fill(r, blank_profile())
        rec["id"] = rec.get("id") or str(uuid.uuid4())
        had = c.execute("SELECT 1 FROM vprofiles WHERE id=?", (rec["id"],)).fetchone()
        _put_profile(c, site, rec)
        updated += bool(had)
        added += not had
    c.commit()
    return {"added": added, "updated": updated, "total": len(recs)}


def export_profiles(c, site=None, ids=None):
    out = {}
    for r in c.execute("SELECT data, site FROM vprofiles ORDER BY site, COALESCE(parent_id,id), rowid"):
        rec = json.loads(r["data"])
        if (site and r["site"] != site) or (ids and rec["id"] not in ids):
            continue
        out[rec["id"]] = rec
    return out


def delete_profiles(c, ids):
    for i in ids:
        c.execute("DELETE FROM vprofiles WHERE id=? OR parent_id=?", (i, i))
    c.commit()
    return len(ids)


def _set_path(rec, dotted, value):
    o = rec
    parts = dotted.split(".")
    for p in parts[:-1]:
        o = o.setdefault(p, {})
    o[parts[-1]] = value


def patch_profiles(c, ids, changes):
    n = 0
    for pid in ids:
        row = c.execute("SELECT data FROM vprofiles WHERE id=?", (pid,)).fetchone()
        if not row:
            continue
        rec = json.loads(row["data"])
        for k, v in changes.items():
            _set_path(rec, k, v)
        rec = clean(rec)
        c.execute("UPDATE vprofiles SET data=?, name=?, email=? WHERE id=?", (json.dumps(rec), rec["name"], rec["email"], pid))
        n += 1
    c.commit()
    return n


def move_profiles(c, ids, site):
    if not site:
        raise ValueError("Pick a group")
    for i in ids:
        c.execute("UPDATE vprofiles SET site=? WHERE id=? OR parent_id=?", (site, i, i))
    c.commit()


def rejig(c, pid, count=10, use_units=True, seed=None, save=False, replace=True):
    """Preview (or save as child profiles) alternate spellings of one profile's shipping address."""
    row = c.execute("SELECT * FROM vprofiles WHERE id=?", (pid,)).fetchone()
    if not row or row["parent_id"]:
        raise ValueError("Pick an original profile, not one that was already rejigged")
    src = json.loads(row["data"])
    sh = src["shipping"]
    if not sh.get("addressLine1"):
        raise ValueError("That profile has no street address to vary")
    vs = variants.generate(sh["addressLine1"], sh.get("addressLine2", ""), count=max(1, min(int(count or 10), 100)), seed=seed or None, use_units=use_units)
    if save:
        if replace:
            c.execute("DELETE FROM vprofiles WHERE parent_id=?", (pid,))
        for i, (l1, l2) in enumerate(vs, 1):
            cp = copy.deepcopy(src)
            cp.update(id=str(uuid.uuid4()), name=f"{src['name']}-J{i}", selected=False)
            cp["shipping"].update(addressLine1=l1, addressLine2=l2)
            if cp.get("billingSameAsShipping"):
                cp["billing"] = {**cp["shipping"]}
            _put_profile(c, row["site"], cp, pid)
        c.commit()
    return [{"addressLine1": a, "addressLine2": b} for a, b in vs]


def bulk_address(c, ids, addr, unique=False, seed=None, use_units=True, target="both", units=None):
    """Give many profiles one address. unique=True spells it differently on each; `units` hands out real unit numbers in turn."""
    rows = [r for r in c.execute("SELECT * FROM vprofiles").fetchall() if not ids or r["id"] in set(ids)]
    if not rows:
        raise ValueError("No profiles to update")
    if not str(addr.get("addressLine1") or "").strip():
        raise ValueError("Enter the street address")
    code = (addr.get("countryCode") or "US").upper()
    name = addr.get("countryName") or COUNTRIES.get(code, code)
    l1, l2 = addr["addressLine1"].strip(), (addr.get("addressLine2") or "").strip()
    pairs, note = [(l1, l2)] * len(rows), ""
    if units:
        pairs = [(l1, units[i % len(units)]) for i in range(len(rows))]
    elif unique:
        vs = variants.generate(l1, l2, count=len(rows), seed=seed or None, use_units=use_units, keep_original=True)
        if len(vs) < len(rows):
            note = f"Only {len(vs)} distinct spellings exist for this address, so some profiles share one."
        pairs = [vs[i % len(vs)] for i in range(len(rows))]
    for r, (a1, a2) in zip(rows, pairs):
        rec = json.loads(r["data"])
        vals = {"addressLine1": a1, "addressLine2": a2, "city": addr.get("city", ""), "state": addr.get("state", ""), "zipCode": addr.get("zipCode", ""), "countryCode": code, "countryName": name}
        if target in ("both", "shipping"):
            rec["shipping"].update(vals)
        if target == "billing":
            rec["billing"].update(vals)
            rec["billingSameAsShipping"] = False
        elif target == "both" and rec.get("billingSameAsShipping"):
            rec["billing"] = {**rec["shipping"]}
        c.execute("UPDATE vprofiles SET data=? WHERE id=?", (json.dumps(rec), r["id"]))
    c.commit()
    return {"updated": len(rows), "note": note}


# ------------------------------------------------------------------ site accounts
def _acct(email=""):
    return {"id": email, "email": email, "password": "", "proxy": "", "session": False, "selected": False}


def list_accounts(c):
    return [{"site": r["site"], "id": r["id"], "rec": json.loads(r["data"])} for r in c.execute("SELECT * FROM vaccounts ORDER BY site, email")]


def save_account(c, site, rec, old_id=None):
    if not site:
        raise ValueError("Pick a group first")
    rec = {**_acct(), **rec}
    rec["email"] = str(rec["email"] or "").strip()
    if not rec["email"]:
        raise ValueError("Enter the account's email or username")
    rec["id"] = old_id or rec.get("id") or rec["email"]
    if old_id and not rec.get("id"):
        rec["id"] = old_id
    c.execute("INSERT INTO vaccounts(site,id,email,data) VALUES(?,?,?,?) ON CONFLICT(site,id) DO UPDATE SET email=excluded.email,data=excluded.data",
              (site, rec["id"], rec["email"], json.dumps(rec)))
    c.commit()
    return rec["id"]


def add_accounts_text(c, site, text):
    """Lines of email:password or email:password:proxy (a proxy is host:port or host:port:user:pass, so it's taken from the 3rd ':' on)."""
    added = skipped = 0
    for line in str(text or "").splitlines():
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(":", 2)
        if len(parts) < 2 or not parts[0].strip():
            skipped += 1
            continue
        if c.execute("SELECT 1 FROM vaccounts WHERE site=? AND id=?", (site, parts[0].strip())).fetchone():
            skipped += 1
            continue
        save_account(c, site, {"email": parts[0].strip(), "password": parts[1], "proxy": parts[2].strip() if len(parts) > 2 else ""})
        added += 1
    return {"added": added, "skipped": skipped}


def import_accounts(c, text, site_override=None, replace=False):
    try:
        root = json.loads(text)
    except ValueError:
        raise ValueError("That file isn't valid JSON")
    if not isinstance(root, dict) or "accounts" not in root:
        raise ValueError("This doesn't look like an accounts file (no \"accounts\" section)")
    site = str(site_override or root.get("site") or "").strip()
    if not site:
        raise ValueError("The file has no site name - choose a group")
    if replace:
        c.execute("DELETE FROM vaccounts WHERE site=?", (site,))
    accts = root["accounts"]
    accts = list(accts.values()) if isinstance(accts, dict) else accts
    added = updated = 0
    for a in accts:
        rec = {**_acct(a.get("email", "")), **a}
        rec["id"] = rec.get("id") or rec["email"]
        had = c.execute("SELECT 1 FROM vaccounts WHERE site=? AND id=?", (site, rec["id"])).fetchone()
        save_account(c, site, rec)
        updated += bool(had)
        added += not had
    if root.get("sessions"):
        db.put(c, f"sessions:{site}", json.dumps(root["sessions"]))
    return {"site": site, "added": added, "updated": updated}


def export_accounts(c, site, ids=None):
    out = {}
    for r in c.execute("SELECT data FROM vaccounts WHERE site=? ORDER BY email", (site,)):
        rec = json.loads(r["data"])
        if ids and rec["id"] not in ids:
            continue
        out[rec["id"]] = rec
    s = db.get(c, f"sessions:{site}")
    return {"version": 1, "site": site, "accounts": out, "sessions": json.loads(s) if s else {}}


def delete_accounts(c, site, ids):
    for i in ids:
        c.execute("DELETE FROM vaccounts WHERE site=? AND id=?", (site, i))
    c.commit()
    return len(ids)


def patch_accounts(c, site, ids, changes):
    n = 0
    for i in ids:
        row = c.execute("SELECT data FROM vaccounts WHERE site=? AND id=?", (site, i)).fetchone()
        if row:
            rec = {**json.loads(row["data"]), **{k: v for k, v in changes.items() if k in ("password", "proxy", "session", "email")}}
            c.execute("UPDATE vaccounts SET data=?, email=? WHERE site=? AND id=?", (json.dumps(rec), rec["email"], site, i))
            n += 1
    c.commit()
    return n


# ------------------------------------------------------------------ groups (a group = a website; may be empty)
def groups(c):
    out = {}
    for kind, table in (("acc", "vaccounts"), ("prof", "vprofiles")):
        try:
            named = json.loads(db.get(c, "vgroups:" + kind, "[]") or "[]")
        except ValueError:
            named = []
        used = [r[0] for r in c.execute(f"SELECT DISTINCT site FROM {table}")]
        out[kind] = sorted(set(named) | set(used), key=str.lower)
    return out


def _save_groups(c, kind, names):
    db.put(c, "vgroups:" + kind, json.dumps(sorted(set(names), key=str.lower)))


def _check_new(c, kind, name):
    name = (name or "").strip()
    if not name:
        raise ValueError("Give the group a name")
    if len(name) > 60:
        raise ValueError("Group names can be up to 60 characters")
    if name.lower() in {g.lower() for g in groups(c)[kind]}:
        raise ValueError(f"A group named {name} already exists")
    return name


def add_group(c, kind, name):
    name = _check_new(c, kind, name)
    _save_groups(c, kind, groups(c)[kind] + [name])
    return name


def rename_group(c, kind, old, new):
    new = _check_new(c, kind, new)
    table = "vaccounts" if kind == "acc" else "vprofiles"
    c.execute(f"UPDATE {table} SET site=? WHERE site=?", (new, old))
    if kind == "acc":
        c.execute("UPDATE settings SET key=? WHERE key=?", (f"sessions:{new}", f"sessions:{old}"))
    _save_groups(c, kind, [new if g == old else g for g in groups(c)[kind]])
    c.commit()
    return new


def delete_group(c, kind, name):
    table = "vaccounts" if kind == "acc" else "vprofiles"
    n = c.execute(f"DELETE FROM {table} WHERE site=?", (name,)).rowcount
    _save_groups(c, kind, [g for g in groups(c)[kind] if g != name])
    c.commit()
    return n
