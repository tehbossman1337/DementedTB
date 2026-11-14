"""Email accounts (any IMAP provider), syncing, the live watcher and .eml import. Mail is only ever read (BODY.PEEK)."""
import email
import imaplib
import re
import socket
import threading
import time
from datetime import datetime
from email import policy
from email.header import decode_header, make_header
from email.utils import getaddresses, parseaddr

from . import db, notify, orders, parsers

PROVIDERS = {
    "icloud": {"label": "iCloud Mail", "host": "imap.mail.me.com", "hint": "Use an app-specific password from account.apple.com (Sign-In and Security), with your @icloud.com address."},
    "gmail": {"label": "Gmail / Google Workspace", "host": "imap.gmail.com",
              "hint": "Use a Google App Password (Google Account → Security → 2-Step Verification → App passwords). Workspace domains work too."},
    "outlook": {"label": "Outlook / Hotmail", "host": "outlook.office365.com",
                "hint": "Microsoft has turned off password sign-in for most personal Outlook accounts. This only works where an app password is still allowed."},
    "yahoo": {"label": "Yahoo Mail", "host": "imap.mail.yahoo.com", "hint": "Generate an app password in Yahoo Account Security."},
    "aol": {"label": "AOL Mail", "host": "imap.aol.com", "hint": "Generate an app password in AOL Account Security."},
    "fastmail": {"label": "Fastmail", "host": "imap.fastmail.com", "hint": "Create an app password in Fastmail Settings → Privacy & Security."},
    "custom": {"label": "Other (custom IMAP)", "host": "", "hint": "Any provider with IMAP over TLS (usually port 993)."},
}
DOMAINS = {"icloud.com": "icloud", "me.com": "icloud", "mac.com": "icloud", "gmail.com": "gmail", "googlemail.com": "gmail", "outlook.com": "outlook",
           "hotmail.com": "outlook", "live.com": "outlook", "msn.com": "outlook", "yahoo.com": "yahoo", "ymail.com": "yahoo", "aol.com": "aol",
           "fastmail.com": "fastmail", "fastmail.fm": "fastmail"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
SKIP_FOLDERS = re.compile(r"(^|/)(drafts?|trash|deleted (messages|items)|junk|spam|sent( mail| items| messages)?|outbox|archive/trash)$|\[gmail\]/(drafts|trash|spam|sent mail|important|starred)", re.I)
ORDER_WORDS = re.compile(r"order|ship|deliver|cancel|receipt|confirm|tracking|pick ?up|purchase|package|parcel|refund|invoice|payment|thank(s| you)|pre-?order|arriv|on (its|the) way|out for|expected|delay|label", re.I)
RETAIL_SENDER = re.compile("|".join(re.escape(d) for ds in parsers.RETAILERS.values() for d in ds), re.I)
PARSER_VERSION = 1
DBLOCK = threading.Lock()
LIVE = {"running": False, "since": 0, "accounts": {}, "syncing": set()}


class MailError(Exception):
    pass


def detect_provider(addr):
    return DOMAINS.get(addr.rsplit("@", 1)[-1].lower(), "custom")


def public(r):
    d = dict(r)
    d["has_password"] = bool(d.pop("password", ""))
    d["enabled"] = bool(d["enabled"])
    d["live"] = d["id"] in LIVE["accounts"] and LIVE["accounts"][d["id"]].get("live", False) and d["enabled"]
    d["provider_label"] = PROVIDERS.get(d["provider"], PROVIDERS["custom"])["label"]
    return d


def list_accounts(c):
    return [public(r) for r in c.execute("SELECT * FROM mail_accounts ORDER BY id")]


def get_account(c, aid):
    r = c.execute("SELECT * FROM mail_accounts WHERE id=?", (aid,)).fetchone()
    if not r:
        raise ValueError("That email account no longer exists")
    return dict(r)


def _clean(d):
    em = str(d.get("email") or "").strip().lower()
    if not EMAIL_RE.match(em):
        raise ValueError(f"'{em or 'blank'}' is not a valid email address")
    prov = d.get("provider") or detect_provider(em)
    if prov not in PROVIDERS:
        prov = "custom"
    host = str(d.get("host") or "").strip() or PROVIDERS[prov]["host"]
    if not host:
        raise ValueError("Enter the IMAP server (for example imap.mydomain.com)")
    try:
        port = int(d.get("port") or 993)
    except ValueError:
        raise ValueError("Port must be a number")
    return em, prov, host, port


def save_account(c, d, aid=None):
    em, prov, host, port = _clean(d)
    pw = str(d.get("password") or "").replace(" ", " ").strip()
    if aid:
        old = get_account(c, aid)
        c.execute("UPDATE mail_accounts SET email=?, username=?, provider=?, host=?, port=?, password=? WHERE id=?",
                  (em, str(d.get("username") or "").strip(), prov, host, port, pw or old["password"], aid))
    else:
        if not pw:
            raise ValueError("Enter the app password")
        if c.execute("SELECT 1 FROM mail_accounts WHERE lower(email)=?", (em,)).fetchone():
            raise ValueError(f"{em} is already connected")
        aid = c.execute("INSERT INTO mail_accounts(email,username,provider,host,port,password,enabled,created_at) VALUES(?,?,?,?,?,?,1,?)",
                        (em, str(d.get("username") or "").strip(), prov, host, port, pw, db.now())).lastrowid
    c.commit()
    from . import inbox
    inbox._drop(aid)  # sign in again with the new details
    threading.Thread(target=inbox.check_all, daemon=True).start()  # show its inbox right away
    return aid


def delete_account(c, aid):
    c.execute("DELETE FROM mail_accounts WHERE id=?", (aid,))
    c.commit()
    LIVE["accounts"].pop(aid, None)
    from . import inbox
    inbox.forget_account(c, aid)


def set_enabled(c, aid, on):
    c.execute("UPDATE mail_accounts SET enabled=? WHERE id=?", (1 if on else 0, aid))
    c.commit()
    if not on:
        LIVE["accounts"].pop(aid, None)


def login(acct):
    try:
        M = imaplib.IMAP4_SSL(acct["host"], int(acct.get("port") or 993), timeout=25)
    except (OSError, socket.timeout) as e:
        raise MailError(f"Couldn't reach {acct['host']}: {e}")
    try:
        M.login(acct.get("username") or acct["email"], acct["password"])
    except imaplib.IMAP4.error as e:
        msg = str(e)
        raise MailError("The mail server rejected the sign-in. Check the app password" + (f" ({msg[:80]})" if msg else "") + ".")
    return M


def test_account(acct):
    M = login(acct)
    try:
        typ, data = M.list()
        n = len(data or [])
    finally:
        try:
            M.logout()
        except Exception:
            pass
    return {"folders": n}


def bulk_add(c, text, test=True):
    """Lines of email:apppassword or email:apppassword:host:port. Returns a result per line."""
    out = []
    for n, line in enumerate(str(text or "").splitlines(), 1):
        line = line.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split(":")
        em = parts[0].strip()
        try:
            if len(parts) >= 4 and parts[-1].strip().isdigit():
                port, host, pw = int(parts[-1]), parts[-2].strip(), ":".join(parts[1:-2])
            elif len(parts) >= 3 and "." in parts[-1] and not parts[-1].strip().isdigit() and parts[-1].strip().count(" ") == 0 and len(parts) == 3:
                host, port, pw = parts[-1].strip(), 993, parts[1]
            else:
                host, port, pw = "", 993, ":".join(parts[1:])
            d = {"email": em, "password": pw, "host": host, "port": port}
            e2, prov, h, p = _clean(d)
            if not pw.strip():
                raise ValueError("no password on this line")
            if test:
                test_account({"email": e2, "host": h, "port": p, "password": pw.replace(" ", " ").strip()})
            aid = save_account(c, d)
            out.append({"line": n, "email": em, "ok": True, "id": aid})
        except (ValueError, MailError) as e:
            out.append({"line": n, "email": em, "ok": False, "error": str(e)})
    return out


# ------------------------------------------------------------------ own addresses
def own_addresses(c):
    return sorted({r["address"] for r in c.execute("SELECT address FROM own_addresses")} | {r["email"].lower() for r in c.execute("SELECT email FROM mail_accounts")})


def add_own(c, addr):
    addr = (addr or "").strip().lower()
    if not EMAIL_RE.match(addr):
        raise ValueError("That isn't a valid email address")
    c.execute("INSERT OR IGNORE INTO own_addresses(address) VALUES(?)", (addr,))
    c.commit()


def remove_own(c, addr):
    c.execute("DELETE FROM own_addresses WHERE address=?", (addr,))
    c.commit()


# ------------------------------------------------------------------ message reading
def _dec(v):
    try:
        return str(make_header(decode_header(v or "")))
    except Exception:
        return str(v or "")


def _html_to_text(h):
    h = re.sub(r"(?is)<(script|style|head).*?</\1>", " ", h)
    h = re.sub(r"(?i)<br\s*/?>|</(p|div|tr|li|h\d|table)>|</t[dh]>", "\n", h)
    h = re.sub(r"<[^>]+>", " ", h)
    import html
    h = html.unescape(h)
    return "\n".join(re.sub(r"[ \t\xa0]+", " ", l).strip() for l in h.splitlines() if l.strip())


def body_text(msg):
    plain, html_ = "", ""
    for part in msg.walk():
        ct = part.get_content_type()
        if ct not in ("text/plain", "text/html") or part.get_content_disposition() == "attachment":
            continue
        try:
            t = part.get_content()
        except Exception:
            try:
                t = part.get_payload(decode=True).decode(part.get_content_charset() or "utf-8", "replace")
            except Exception:
                continue
        if ct == "text/plain":
            plain += t + "\n"
        else:
            html_ += t + "\n"
    htext = _html_to_text(html_) if html_ else ""
    return htext if len(htext) > len(plain) * 1.2 else (plain or htext)


def recipient(msg, mailbox):
    """The address the mail was sent to (Hide-My-Email aliases show up here) - that's the 'Account' of the order."""
    addrs = [a.lower() for _, a in getaddresses(msg.get_all("To", []) + msg.get_all("Delivered-To", []) + msg.get_all("X-Original-To", [])) if a]
    mine = [a for a in addrs if a != mailbox.lower()]
    return (addrs[0] if addrs and not mine else (mine[0] if mine else mailbox)).lower()


def process_message(c, mid, msg, mailbox, excs, own, announce=True):
    sender = _dec(msg.get("From", ""))
    subject = _dec(msg.get("Subject", ""))
    if orders.is_excepted(excs, sender, subject):
        c.execute("INSERT OR REPLACE INTO processed VALUES(?,?,?,?,?)", (mid, mailbox, "", "ignored (exception)", db.now()))
        return "ignored"
    body = body_text(msg)
    extra = f"{msg.get('Reply-To', '')}\n{subject}\n{body[:800]}"
    forced = rule_retailer(db.rows(c, "SELECT * FROM retailer_rules"), sender)
    ev, why = parsers.parse_email(sender, subject, body, msg.get("Date"), extra=extra, default=forced)
    if ev and forced:
        ev["retailer"] = forced  # your rule wins over the app's guess
    if ev:
        outcome, oid = orders.apply_event(c, ev, account=recipient(msg, mailbox), announce=announce)
        c.execute("INSERT OR REPLACE INTO processed VALUES(?,?,?,?,?)", (mid, mailbox, ev["retailer"], outcome, db.now()))
        return "order"
    looks = bool(RETAIL_SENDER.search(sender + (msg.get("Reply-To") or "")) or forced or re.search(r"\border\b", subject, re.I)) and bool(ORDER_WORDS.search(subject))
    if looks and why != "unknown retailer" or (looks and RETAIL_SENDER.search(sender)):
        guess = parsers.detect_retailer(sender, extra) or ""
        c.execute("INSERT OR IGNORE INTO attention(message_id,account,sender,subject,reason,snippet,guess,created_at,body,date_hdr) VALUES(?,?,?,?,?,?,?,?,?,?)",
                  (mid, mailbox, sender[:200], subject[:200], why, body[:400], guess, db.now(), body[:30000], str(msg.get("Date") or "")))
        c.execute("INSERT OR REPLACE INTO processed VALUES(?,?,?,?,?)", (mid, mailbox, guess, "needs attention: " + why, db.now()))
        notify.notify(c, "attention", "An email needs your attention", subject[:120], link="attention", dedupe=f"att:{mid}")
        return "attention"
    c.execute("INSERT OR REPLACE INTO processed VALUES(?,?,?,?,?)", (mid, mailbox, "", "not an order", db.now()))
    return "skipped"


def _folders(M, acct):
    typ, data = M.list()
    names = []
    for raw in data or []:
        s = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        if "\\Noselect" in s:
            continue
        m = re.search(r'"([^"]*)"\s*$', s) or re.search(r"\s(\S+)\s*$", s)
        if m and not SKIP_FOLDERS.search(m.group(1)):
            names.append(m.group(1))
    if acct["provider"] == "gmail" and "[Gmail]/All Mail" in names:
        return ["[Gmail]/All Mail"]
    return names or ["INBOX"]


def _hdr_fetch(M, uids):
    """Headers only, big batches. Returns {uid: message}."""
    out = {}
    spec = "(UID BODY.PEEK[HEADER.FIELDS (FROM SUBJECT DATE MESSAGE-ID REPLY-TO TO)])"
    for i in range(0, len(uids), 400):
        typ, data = M.uid("FETCH", ",".join(uids[i:i + 400]), spec)
        for item in data or []:
            if isinstance(item, tuple):
                um = re.search(rb"UID (\d+)", item[0])
                if um:
                    out[um.group(1).decode()] = email.message_from_bytes(item[1], policy=policy.default)
    return out


def _bodies_fetch(M, uids):
    """Full messages for the few candidates, many per round trip. Yields (uid, raw bytes)."""
    for i in range(0, len(uids), 20):
        typ, data = M.uid("FETCH", ",".join(uids[i:i + 20]), "(UID BODY.PEEK[])")
        for item in data or []:
            if isinstance(item, tuple):
                um = re.search(rb"UID (\d+)", item[0])
                if um:
                    yield um.group(1).decode(), item[1]


def _wm(c, aid, folder, validity):
    return f"wm:{aid}:{folder}:{validity}"


def _msg_ts(h):
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(h.get("Date")).timestamp()
    except Exception:
        return 0


def sync_account(aid, full=False, progress=lambda m: None, announce=True):
    """Pull new mail for one account. First run only looks back `sync_days` (default 180); Backfill (full=True) reads everything.
    Headers are fetched in big batches, only mail that looks like an order is downloaded in full, and writes are batched."""
    stats = {"seen": 0, "orders": 0, "attention": 0, "errors": 0}
    c = db.connect()
    try:
        acct = get_account(c, aid)
        excs = db.rows(c, "SELECT * FROM exceptions")
        own = own_addresses(c)
        try:
            days = int(db.get(c, "sync_days", "180") or 180)
        except ValueError:
            days = 180
        done = set(r[0] for r in c.execute("SELECT message_id FROM processed"))
        rules = db.rows(c, "SELECT * FROM retailer_rules")
    finally:
        c.close()
    M = None
    try:
        M = login(acct)
        folders = sorted(_folders(M, acct), key=lambda f: 0 if f.upper() == "INBOX" else 1)
        for folder in folders:
            try:
                typ, _ = M.select('"' + folder.replace('"', '\\"') + '"', readonly=True)
                if typ != "OK":
                    continue
                vt = M.response("UIDVALIDITY")[1]
                validity = (vt[0].decode() if vt and vt[0] else "0")
                cc = db.connect()
                last = 0 if full else int(db.get(cc, _wm(cc, aid, folder, validity), "0") or 0)
                cc.close()
                if last:
                    crit = f"UID {last + 1}:*"
                elif not full and days > 0:
                    crit = "SINCE " + time.strftime("%d-%b-%Y", time.gmtime(time.time() - days * 86400))
                else:
                    crit = "ALL"
                typ, data = M.uid("SEARCH", None, crit)
                uids = [u.decode() for u in (data[0] or b"").split()] if data and data[0] else []
                uids = [u for u in uids if int(u) > last]
                if not uids:
                    continue
                progress(f"{acct['email']} · {folder}: {len(uids)} new")
                headers = _hdr_fetch(M, uids)
                cand, skip = [], []
                for u in uids:
                    h = headers.get(u)
                    if h is None:
                        continue
                    stats["seen"] += 1
                    sender, subject = _dec(h.get("From", "")), _dec(h.get("Subject", ""))
                    mid = (h.get("Message-ID") or f"{acct['email']}:{folder}:{validity}:{u}").strip()
                    if mid in done and not full:
                        continue
                    if RETAIL_SENDER.search(sender + (h.get("Reply-To") or "")) or ORDER_WORDS.search(subject) or rule_retailer(rules, sender):
                        cand.append((_msg_ts(h), u, mid))
                    else:
                        skip.append((mid, acct["email"], "", "not an order", db.now()))
                        done.add(mid)
                if skip:
                    with DBLOCK:
                        cc = db.connect()
                        cc.executemany("INSERT OR IGNORE INTO processed VALUES(?,?,?,?,?)", skip)
                        cc.commit()
                        cc.close()
                cand.sort()  # oldest first so placed -> shipped -> delivered arrive in order
                by_uid = {u: mid for _, u, mid in cand}
                order_uids = [u for _, u, _ in cand]
                with DBLOCK:
                    cc = db.connect()
                    try:
                        for u, raw in _bodies_fetch(M, order_uids):
                            mid = by_uid.get(u)
                            if not mid:
                                continue
                            msg = email.message_from_bytes(raw, policy=policy.default)
                            r = process_message(cc, mid, msg, acct["email"], excs, own, announce)
                            done.add(mid)
                            time.sleep(0.002)  # let the window's own requests through while a big mailbox is processed
                            if r == "order":
                                stats["orders"] += 1
                            elif r == "attention":
                                stats["attention"] += 1
                        cc.commit()
                    finally:
                        cc.close()
                with DBLOCK:
                    cc = db.connect()
                    db.put(cc, _wm(cc, aid, folder, validity), str(max(int(u) for u in uids)))
                    cc.close()
            except (imaplib.IMAP4.error, OSError) as e:
                stats["errors"] += 1
                progress(f"{acct['email']} · {folder}: {e}")
        with DBLOCK:
            cc = db.connect()
            cc.execute("UPDATE mail_accounts SET last_checked=?, last_error='' WHERE id=?", (db.now(), aid))
            cc.commit()
            cc.close()
    except MailError as e:
        stats["errors"] += 1
        with DBLOCK:
            cc = db.connect()
            cc.execute("UPDATE mail_accounts SET last_error=?, last_checked=? WHERE id=?", (str(e), db.now(), aid))
            cc.commit()
            cc.close()
        progress(f"{acct['email']}: {e}")
    finally:
        if M:
            try:
                M.logout()
            except Exception:
                pass
    return stats


SYNC = {"running": False, "log": [], "stats": None}


def sync_all(full=False, account_id=None, announce=True):
    if SYNC["running"]:
        return SYNC["stats"]
    SYNC.update(running=True, log=[], stats=None)
    total = {"seen": 0, "orders": 0, "attention": 0, "errors": 0}
    try:
        c = db.connect()
        ids = [r["id"] for r in c.execute("SELECT id FROM mail_accounts WHERE enabled=1" + (" AND id=?" if account_id else ""), (account_id,) if account_id else ())]
        c.close()
        ths, res = [], []
        def one(i):
            LIVE["syncing"].add(i)
            try:
                res.append(sync_account(i, full, SYNC["log"].append, announce))
            finally:
                LIVE["syncing"].discard(i)
        for i in ids:
            t = threading.Thread(target=one, args=(i,), daemon=True)
            t.start()
            ths.append(t)
        for t in ths:
            t.join()
        for r in res:
            for k in total:
                total[k] += r[k]
        SYNC["stats"] = total
    finally:
        SYNC["running"] = False
    return total


# ------------------------------------------------------------------ live watcher
def _watch(aid, stop):
    """One thread per inbox: keeps its own connection and checks UIDNEXT every few seconds; new mail syncs at once."""
    M = None
    last_full = 0
    st = LIVE["accounts"].setdefault(aid, {"live": False, "uidnext": None})
    while not stop.is_set():
        try:
            c = db.connect()
            r = c.execute("SELECT * FROM mail_accounts WHERE id=? AND enabled=1", (aid,)).fetchone()
            c.close()
            if not r:
                break
            a = dict(r)
            try:
                if M is None:
                    M = login(a)
                typ, data = M.status("INBOX", "(UIDNEXT)")
                nxt = re.search(rb"UIDNEXT (\d+)", data[0]).group(1) if data and data[0] else None
                st["live"] = True
                changed = st["uidnext"] is not None and nxt != st["uidnext"]
                st["uidnext"] = nxt
                due = time.time() - last_full > 600
                if (changed or due) and aid not in LIVE["syncing"] and not SYNC["running"]:
                    last_full = time.time()
                    LIVE["syncing"].add(aid)
                    try:
                        sync_account(aid)
                    finally:
                        LIVE["syncing"].discard(aid)
                else:
                    c2 = db.connect()
                    c2.execute("UPDATE mail_accounts SET last_checked=?, last_error='' WHERE id=?", (db.now(), aid))
                    c2.commit()
                    c2.close()
            except (MailError, imaplib.IMAP4.error, OSError, AttributeError) as e:
                st["live"] = False
                try:
                    M.logout()
                except Exception:
                    pass
                M = None
                c2 = db.connect()
                c2.execute("UPDATE mail_accounts SET last_error=?, last_checked=? WHERE id=?", (str(e)[:200], db.now(), aid))
                c2.commit()
                c2.close()
                stop.wait(30)  # back off after a failure instead of hammering the server
                continue
        except Exception:
            pass
        stop.wait(LIVE.get("interval", 10))
    if M:
        try:
            M.logout()
        except Exception:
            pass
    LIVE["accounts"].pop(aid, None)


def live_loop(interval=10):
    """Supervisor: starts a watcher thread for every enabled account (and stops them when an account is removed or paused)."""
    import os
    if os.environ.get("DT_NO_AUTO"):
        return
    LIVE.update(running=True, since=time.time(), interval=interval)
    threads = {}
    while True:
        try:
            c = db.connect()
            ids = {r["id"] for r in c.execute("SELECT id FROM mail_accounts WHERE enabled=1")}
            c.close()
            for aid in ids:
                if aid not in threads or not threads[aid][0].is_alive():
                    ev = threading.Event()
                    t = threading.Thread(target=_watch, args=(aid, ev), daemon=True)
                    threads[aid] = (t, ev)
                    t.start()
            for aid in set(threads) - ids:
                threads.pop(aid)[1].set()
        except Exception:
            pass
        time.sleep(3)


def live_summary(c):
    accts = list_accounts(c)
    return {"total": len(accts), "live": sum(1 for a in accts if a["live"]), "syncing": bool(LIVE["syncing"] or SYNC["running"])}


def describe(a):
    if not a["enabled"]:
        return "Paused"
    if a.get("last_error"):
        return "Problem: " + a["last_error"]
    t = ""
    if a.get("last_checked"):
        try:
            t = datetime.fromisoformat(a["last_checked"]).strftime("%-I:%M:%S %p") if os.name != "nt" else datetime.fromisoformat(a["last_checked"]).strftime("%I:%M:%S %p").lstrip("0")
        except Exception:
            t = a["last_checked"]
    return ("Live — watching for new mail" if a["live"] else "Connecting…") + (f" · last checked {t}" if t else "")


import os  # noqa: E402  (used by describe)


# ------------------------------------------------------------------ .eml import
def import_eml(c, files):
    """files: [{name, text}] raw .eml contents. Processed exactly like mail found in an inbox."""
    excs = db.rows(c, "SELECT * FROM exceptions")
    own = own_addresses(c)
    res = {"files": 0, "orders": 0, "attention": 0, "skipped": 0}
    for f in files:
        try:
            raw = f.get("text") or ""
            msg = email.message_from_bytes(raw.encode("utf-8", "surrogateescape") if isinstance(raw, str) else raw, policy=policy.default)
            mid = (msg.get("Message-ID") or "eml:" + str(abs(hash(raw)))).strip()
            if c.execute("SELECT 1 FROM processed WHERE message_id=?", (mid,)).fetchone():
                res["skipped"] += 1
                continue
            r = process_message(c, mid, msg, "imported", excs, own)
            c.commit()
            res["files"] += 1
            res["orders" if r == "order" else "attention" if r == "attention" else "skipped"] += 1
        except Exception:
            res["skipped"] += 1
    return res


# ------------------------------------------------------------------ attention
def list_attention(c):
    return db.rows(c, "SELECT * FROM attention WHERE resolved=0 ORDER BY id DESC")


def resolve_attention(c, aid, ignore=None):
    r = c.execute("SELECT * FROM attention WHERE id=?", (aid,)).fetchone()
    if not r:
        return 0
    n = 1
    if ignore in ("sender", "domain"):
        addr = parseaddr(r["sender"])[1].lower()
        orders.add_exception(c, ignore, addr if ignore == "sender" else addr.rsplit("@", 1)[-1])
        excs = db.rows(c, "SELECT * FROM exceptions")
        others = [x["id"] for x in c.execute("SELECT id, sender, subject FROM attention WHERE resolved=0 AND id<>?", (aid,)) if orders.is_excepted(excs, x["sender"], x["subject"])]
        c.executemany("UPDATE attention SET resolved=1 WHERE id=?", [(i,) for i in others])
        n += len(others)
    c.execute("UPDATE attention SET resolved=1 WHERE id=?", (aid,))
    c.commit()
    return n


# ---------------------------------------------------------------- retailer rules ("always treat this sender as …")
def _rule_key(kind, sender):
    addr = parseaddr(sender or "")[1].lower() or (sender or "").lower().strip()
    return addr if kind == "sender" else addr.rsplit("@", 1)[-1]


def rule_retailer(rules, sender):
    if not rules:
        return None
    addr = _rule_key("sender", sender)
    dom = addr.rsplit("@", 1)[-1]
    for r in rules:
        if (r["kind"] == "sender" and r["value"] == addr) or (r["kind"] == "domain" and (dom == r["value"] or dom.endswith("." + r["value"]))):
            return r["retailer"]
    return None


def list_rules(c):
    return db.rows(c, "SELECT * FROM retailer_rules ORDER BY id DESC")


def add_rule(c, kind, value, retailer, announce=True):
    """Save the rule, then re-read every waiting email it covers. Emails saved before this feature have no stored text: those are released
    so the next Backfill reads them again."""
    kind, retailer = (kind or "sender").strip(), (retailer or "").strip()
    value = _rule_key(kind, value) if "@" in (value or "") else (value or "").strip().lower()
    if kind not in ("sender", "domain") or not value or not retailer:
        raise ValueError("Pick a retailer and a sender or website")
    c.execute("INSERT OR REPLACE INTO retailer_rules(kind,value,retailer,created_at) VALUES(?,?,?,?)", (kind, value, retailer[:60], db.now()))
    rules = list_rules(c)
    added = later = 0
    for a in db.rows(c, "SELECT * FROM attention WHERE resolved=0"):
        if rule_retailer(rules, a["sender"]) != retailer:
            continue
        if not a.get("body"):
            c.execute("DELETE FROM processed WHERE message_id=?", (a["message_id"],))
            later += 1
            continue
        ev, why = parsers.parse_email(a["sender"], a["subject"], a["body"], a.get("date_hdr") or None, extra=a["subject"], default=retailer)
        if ev:
            ev["retailer"] = retailer
            outcome, _ = orders.apply_event(c, ev, account=a["account"], announce=announce)
            c.execute("INSERT OR REPLACE INTO processed VALUES(?,?,?,?,?)", (a["message_id"], a["account"], retailer, outcome, db.now()))
            c.execute("UPDATE attention SET resolved=1 WHERE id=?", (a["id"],))
            added += 1
        else:
            c.execute("UPDATE attention SET reason=? WHERE id=?", (why, a["id"]))
    c.commit()
    return {"orders": added, "on_backfill": later}


def delete_rule(c, rid):
    c.execute("DELETE FROM retailer_rules WHERE id=?", (rid,))
    c.commit()
