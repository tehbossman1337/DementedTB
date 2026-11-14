"""Inbox: read the INBOX of every connected email account (iCloud and others) inside the app.

Headers, flags and a short preview are cached locally so the list opens instantly; message bodies are fetched when you open one. A loop checks
every account every 20 seconds over a kept-open connection (a fresh sign-in each time would trip iCloud's limits)."""
import email
import html as htmlmod
import imaplib
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from email import policy
from email.utils import getaddresses, parseaddr, parsedate_to_datetime

from . import db, mail

INTERVAL = 20
FIRST_LOAD = 200      # newest messages read the first time an account is opened
KEEP = 600            # newest messages kept in the local list per account
PREVIEWS_PER_ROUND = 40

STATE = {"rev": 0, "last": 0.0, "checking": False, "errors": {}}
_CONN = {}
_LOCKS = {}
_BODIES = {}          # small in-memory cache of opened messages
_SCHEMA_DONE = set()


def _schema(c):
    if db.config.DB_PATH in _SCHEMA_DONE:
        return
    c.executescript("""
    CREATE TABLE IF NOT EXISTS inbox_msgs(account_id INTEGER NOT NULL, uid INTEGER NOT NULL, message_id TEXT DEFAULT '', from_name TEXT DEFAULT '',
      from_addr TEXT DEFAULT '', to_addr TEXT DEFAULT '', subject TEXT DEFAULT '', ts REAL DEFAULT 0, seen INTEGER DEFAULT 0, flagged INTEGER DEFAULT 0,
      attach INTEGER DEFAULT 0, snippet TEXT, size INTEGER DEFAULT 0, PRIMARY KEY(account_id, uid));
    CREATE INDEX IF NOT EXISTS idx_inbox_ts ON inbox_msgs(ts DESC);
    CREATE TABLE IF NOT EXISTS inbox_state(account_id INTEGER PRIMARY KEY, validity INTEGER DEFAULT 0, last_uid INTEGER DEFAULT 0,
      checked REAL DEFAULT 0, error TEXT DEFAULT '', trash TEXT DEFAULT '');
    """)
    c.commit()
    _SCHEMA_DONE.add(db.config.DB_PATH)


def _conn_db():
    c = db.connect()
    _schema(c)
    return c


def _bump():
    STATE["rev"] += 1


# ---------------------------------------------------------------- IMAP helpers
def _lock(aid):
    return _LOCKS.setdefault(aid, threading.RLock())


def _drop(aid):
    M = _CONN.pop(aid, None)
    if M:
        try:
            M.logout()
        except Exception:
            pass


def _session(acct):
    """A signed-in connection with INBOX selected, reused between checks."""
    aid = acct["id"]
    M = _CONN.get(aid)
    if M is not None:
        try:
            typ, _ = M.noop()
            if typ == "OK":
                return M
        except Exception:
            pass
        _drop(aid)
    M = mail.login(acct)
    _CONN[aid] = M
    return M


def _select(M):
    typ, data = M.select("INBOX")
    if typ != "OK":
        raise mail.MailError("Couldn't open the inbox")
    typ, v = M.response("UIDVALIDITY")
    try:
        return int(v[-1]) if v and v[-1] else 0
    except (TypeError, ValueError):
        return 0


def _uids(M, crit):
    typ, data = M.uid("SEARCH", None, crit)
    if typ != "OK" or not data or not data[0]:
        return []
    return [int(x) for x in data[0].split()]


def _dec(v):
    return mail._dec(v).replace("\r", " ").replace("\n", " ").strip()


def _ts(h):
    try:
        return parsedate_to_datetime(h).timestamp()
    except Exception:
        return time.time()


def _fetch_headers(M, uids):
    out = {}
    spec = "(UID RFC822.SIZE BODY.PEEK[HEADER.FIELDS (FROM TO SUBJECT DATE MESSAGE-ID CONTENT-TYPE)])"
    for i in range(0, len(uids), 200):
        typ, data = M.uid("FETCH", ",".join(str(u) for u in uids[i:i + 200]), spec)
        for item in data or []:
            if isinstance(item, tuple):
                um = re.search(rb"UID (\d+)", item[0])
                if not um:
                    continue
                sz = re.search(rb"RFC822\.SIZE (\d+)", item[0])
                out[int(um.group(1))] = (email.message_from_bytes(item[1], policy=policy.default), int(sz.group(1)) if sz else 0)
    return out


def _fetch_flags(M, lo):
    typ, data = M.uid("FETCH", f"{lo}:*", "(UID FLAGS)")
    out = {}
    for item in data or []:
        s = item[0] if isinstance(item, tuple) else item
        if not isinstance(s, bytes):
            continue
        um, fm = re.search(rb"UID (\d+)", s), re.search(rb"FLAGS \(([^)]*)\)", s)
        if um and fm:
            out[int(um.group(1))] = fm.group(1).decode(errors="replace")
    return out


def _fetch_raw(M, uid):
    typ, data = M.uid("FETCH", str(uid), "(UID BODY.PEEK[])")
    for item in data or []:
        if isinstance(item, tuple) and re.search(rb"UID %d\b" % uid, item[0]):
            return item[1]
    for item in data or []:
        if isinstance(item, tuple):
            return item[1]
    return None


def _snippet(msg):
    t = mail.body_text(msg)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:220]


def _has_attach(msg):
    return any(p.get_content_disposition() == "attachment" for p in msg.walk())


# ---------------------------------------------------------------- checking
def check_account(acct):
    """Pick up new mail and read/unread/deleted changes for one account. Returns how many new messages arrived."""
    aid = acct["id"]
    with _lock(aid):
        c = _conn_db()
        try:
            st = c.execute("SELECT * FROM inbox_state WHERE account_id=?", (aid,)).fetchone()
            last, old_validity = (st["last_uid"], st["validity"]) if st else (0, 0)
            M = _session(acct)
            validity = _select(M)
            if old_validity and validity and validity != old_validity:  # the server renumbered the mailbox: start over
                c.execute("DELETE FROM inbox_msgs WHERE account_id=?", (aid,))
                last = 0
            if last:
                new = [u for u in _uids(M, f"UID {last + 1}:*") if u > last]
            else:
                new = _uids(M, "ALL")[-FIRST_LOAD:]
            rows = []
            if new:
                for uid, (h, size) in _fetch_headers(M, new).items():
                    fn, fa = parseaddr(h.get("From", ""))
                    to = ", ".join(a for _, a in getaddresses(h.get_all("To", [])) if a)
                    rows.append((aid, uid, str(h.get("Message-ID", ""))[:300], _dec(fn)[:120], fa.lower()[:200], to.lower()[:300], _dec(h.get("Subject", ""))[:300],
                                 _ts(h.get("Date")), 0, 0, int("multipart/mixed" in str(h.get("Content-Type", "")).lower()), None, size))
                c.executemany("INSERT OR IGNORE INTO inbox_msgs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
                last = max([last] + new)
            # read / flagged / deleted elsewhere (phone, iCloud.com…)
            lo = c.execute("SELECT MIN(uid) FROM inbox_msgs WHERE account_id=?", (aid,)).fetchone()[0]
            changed = False
            if lo:
                flags = _fetch_flags(M, lo)
                cur = {r["uid"]: (r["seen"], r["flagged"]) for r in c.execute("SELECT uid, seen, flagged FROM inbox_msgs WHERE account_id=?", (aid,))}
                gone = [u for u in cur if u not in flags]
                if gone:
                    c.executemany("DELETE FROM inbox_msgs WHERE account_id=? AND uid=?", [(aid, u) for u in gone])
                    changed = True
                upd = []
                for u, f in flags.items():
                    if u in cur:
                        nv = (int("\\Seen" in f), int("\\Flagged" in f))
                        if nv != cur[u]:
                            upd.append(nv + (aid, u))
                if upd:
                    c.executemany("UPDATE inbox_msgs SET seen=?, flagged=? WHERE account_id=? AND uid=?", upd)
                    changed = True
            # previews for the newest messages that don't have one yet
            need = [r[0] for r in c.execute("SELECT uid FROM inbox_msgs WHERE account_id=? AND snippet IS NULL ORDER BY uid DESC LIMIT ?", (aid, PREVIEWS_PER_ROUND))]
            for i in range(0, len(need), 10):
                typ, data = M.uid("FETCH", ",".join(str(u) for u in need[i:i + 10]), "(UID BODY.PEEK[])")
                for item in data or []:
                    if isinstance(item, tuple):
                        um = re.search(rb"UID (\d+)", item[0])
                        if um:
                            msg = email.message_from_bytes(item[1], policy=policy.default)
                            c.execute("UPDATE inbox_msgs SET snippet=?, attach=? WHERE account_id=? AND uid=?", (_snippet(msg), int(_has_attach(msg)), aid, int(um.group(1))))
                changed = True
            # keep the local list to the newest KEEP
            c.execute("DELETE FROM inbox_msgs WHERE account_id=? AND uid NOT IN (SELECT uid FROM inbox_msgs WHERE account_id=? ORDER BY uid DESC LIMIT ?)", (aid, aid, KEEP))
            c.execute("INSERT OR REPLACE INTO inbox_state(account_id, validity, last_uid, checked, error, trash) VALUES(?,?,?,?,?,COALESCE((SELECT trash FROM inbox_state WHERE account_id=?),''))",
                      (aid, validity, last, time.time(), "", aid))
            c.commit()
            STATE["errors"].pop(aid, None)
            if rows or changed:
                _bump()
            return len(rows)
        except Exception as e:  # one bad mailbox must never stop the others
            _drop(aid)
            STATE["errors"][aid] = str(e)[:200]
            try:
                c.execute("INSERT OR IGNORE INTO inbox_state(account_id) VALUES(?)", (aid,))
                c.execute("UPDATE inbox_state SET error=?, checked=? WHERE account_id=?", (str(e)[:200], time.time(), aid))
                c.commit()
            except Exception:
                pass
            return 0
        finally:
            c.close()


def _accounts():
    c = db.connect()
    try:
        return [dict(r) for r in c.execute("SELECT * FROM mail_accounts WHERE enabled=1 AND password<>'' ORDER BY id")]
    finally:
        c.close()


def check_all():
    if STATE["checking"]:
        return 0
    STATE["checking"] = True
    try:
        accts = _accounts()
        if not accts:
            return 0
        with ThreadPoolExecutor(max_workers=min(8, len(accts))) as ex:
            n = sum(ex.map(check_account, accts))
        if n:
            _bump()
        return n
    finally:
        STATE["last"] = time.time()
        STATE["checking"] = False


def loop(interval=INTERVAL):
    while True:
        try:
            check_all()
        except Exception:
            pass
        time.sleep(interval)


# ---------------------------------------------------------------- reading
def list_messages(c, account=0, q="", unread=False, flagged=False, limit=300, offset=0):
    _schema(c)
    where, args = ["1=1"], []
    ids = {r["id"]: r["email"] for r in c.execute("SELECT id, email FROM mail_accounts WHERE enabled=1")}
    where.append(f"account_id IN ({','.join('?' * len(ids)) or 'NULL'})")
    args += list(ids)
    if account:
        where.append("account_id=?")
        args.append(int(account))
    if unread:
        where.append("seen=0")
    if flagged:
        where.append("flagged=1")
    if q:
        where.append("(subject LIKE ? OR from_name LIKE ? OR from_addr LIKE ? OR to_addr LIKE ? OR snippet LIKE ?)")
        args += [f"%{q}%"] * 5
    sql = " AND ".join(where)
    rows = [dict(r) for r in c.execute(f"SELECT * FROM inbox_msgs WHERE {sql} ORDER BY ts DESC LIMIT ? OFFSET ?", args + [int(limit), int(offset)])]
    total = c.execute(f"SELECT COUNT(*) FROM inbox_msgs WHERE {sql}", args).fetchone()[0]
    for r in rows:
        r["account"] = ids.get(r["account_id"], "")
        r["snippet"] = r["snippet"] or ""
    return {"messages": rows, "total": total, "rev": STATE["rev"]}


def summary(c):
    _schema(c)
    accts = db.rows(c, "SELECT id, email, provider FROM mail_accounts WHERE enabled=1 ORDER BY email")
    unread = {r[0]: r[1] for r in c.execute("SELECT account_id, COUNT(*) FROM inbox_msgs WHERE seen=0 GROUP BY account_id")}
    st = {r["account_id"]: dict(r) for r in c.execute("SELECT * FROM inbox_state")}
    for a in accts:
        s = st.get(a["id"]) or {}
        a["unread"] = unread.get(a["id"], 0)
        a["error"] = STATE["errors"].get(a["id"]) or s.get("error") or ""
        a["checked"] = s.get("checked") or 0
        a["loaded"] = bool(s.get("checked"))
    return {"accounts": accts, "unread": sum(unread.get(a["id"], 0) for a in accts), "rev": STATE["rev"], "last": STATE["last"],
            "checking": STATE["checking"], "interval": INTERVAL}


_WITH_BODY = re.compile(r"(?is)<(script|iframe|object|embed|applet|noscript|frameset|frame|svg|math)\b[^>]*>.*?</\1\s*>")
_TAGS = re.compile(r"(?is)</?(script|iframe|object|embed|applet|noscript|frameset|frame|form|meta|link|base|svg|math)\b[^>]*>")


def sanitize(h, allow_remote=False, cids=None):
    """Make an email's HTML safe to show: no scripts, frames, forms or event handlers; remote images only when allowed."""
    h = re.sub(r"(?is)<!--.*?-->", "", h)
    h = _WITH_BODY.sub("", h)
    h = _TAGS.sub("", h)
    h = re.sub(r"(?i)\son\w+\s*=\s*(\"[^\"]*\"|'[^']*'|[^\s>]+)", "", h)
    h = re.sub(r"(?i)(href|src|action|background|formaction|xlink:href)\s*=\s*([\"']?)\s*(javascript|vbscript|data:text/html)[^\"'>]*\2", r'\1=""', h)
    h = re.sub(r"(?i)expression\s*\(", "(", h)
    remote = len(re.findall(r"(?i)(src|background)\s*=\s*[\"']?\s*https?:", h)) + len(re.findall(r"(?i)url\(\s*[\"']?https?:", h))
    for cid, uri in (cids or {}).items():
        h = h.replace(f"cid:{cid}", uri)
    return h, remote


def _cids(msg):
    import base64
    out = {}
    for p in msg.walk():
        cid = (p.get("Content-ID") or "").strip("<> ")
        if cid and p.get_content_maintype() == "image":
            data = p.get_payload(decode=True) or b""
            if len(data) < 1_500_000:
                out[cid] = f"data:{p.get_content_type()};base64,{base64.b64encode(data).decode()}"
    return out


def _parts(msg):
    plain = html_ = ""
    atts = []
    for i, p in enumerate(msg.walk()):
        if p.is_multipart():
            continue
        disp = p.get_content_disposition()
        ct = p.get_content_type()
        if disp == "attachment" or (p.get_filename() and ct not in ("text/plain", "text/html")):
            data = p.get_payload(decode=True) or b""
            atts.append({"idx": i, "name": _dec(p.get_filename() or "attachment"), "type": ct, "size": len(data)})
            continue
        if ct in ("text/plain", "text/html"):
            try:
                t = p.get_content()
            except Exception:
                t = (p.get_payload(decode=True) or b"").decode(p.get_content_charset() or "utf-8", "replace")
            if ct == "text/plain":
                plain += t
            else:
                html_ += t
    return plain, html_, atts


def _acct(c, aid):
    a = c.execute("SELECT * FROM mail_accounts WHERE id=?", (aid,)).fetchone()
    if not a:
        raise ValueError("That email account isn't connected any more")
    return dict(a)


def _raw(acct, uid):
    key = (acct["id"], uid)
    if key in _BODIES:
        return _BODIES[key]
    with _lock(acct["id"]):
        try:
            M = _session(acct)
            _select(M)
            raw = _fetch_raw(M, uid)
        except (imaplib.IMAP4.error, OSError, EOFError):
            _drop(acct["id"])
            M = _session(acct)
            _select(M)
            raw = _fetch_raw(M, uid)
    if raw is None:
        raise ValueError("That email was moved or deleted")
    _BODIES[key] = raw
    while len(_BODIES) > 30:
        _BODIES.pop(next(iter(_BODIES)))
    return raw


def open_message(c, aid, uid, images=False, mark_read=True):
    _schema(c)
    acct = _acct(c, aid)
    msg = email.message_from_bytes(_raw(acct, uid), policy=policy.default)
    plain, html_, atts = _parts(msg)
    if html_:
        body, remote = sanitize(html_, images, _cids(msg))
        kind = "html"
    else:
        body, remote, kind = htmlmod.escape(plain), 0, "text"
    fn, fa = parseaddr(msg.get("From", ""))
    out = {"account_id": aid, "uid": uid, "subject": _dec(msg.get("Subject", "")) or "(no subject)", "from_name": _dec(fn), "from_addr": fa,
           "to": _dec(msg.get("To", "")), "cc": _dec(msg.get("Cc", "")), "date": _ts(msg.get("Date")), "kind": kind, "body": body,
           "remote_images": remote, "images": bool(images), "attachments": atts}
    row = c.execute("SELECT seen FROM inbox_msgs WHERE account_id=? AND uid=?", (aid, uid)).fetchone()
    if mark_read and row and not row["seen"]:
        try:
            set_flags(c, aid, [uid], "seen", True)
        except Exception:
            pass
    return out


def attachment(c, aid, uid, idx):
    acct = _acct(c, aid)
    msg = email.message_from_bytes(_raw(acct, uid), policy=policy.default)
    for i, p in enumerate(msg.walk()):
        if i == int(idx):
            return _dec(p.get_filename() or "attachment"), p.get_content_type(), p.get_payload(decode=True) or b""
    raise ValueError("Attachment not found")


# ---------------------------------------------------------------- actions
FLAG = {"seen": "\\Seen", "flagged": "\\Flagged"}


def set_flags(c, aid, uids, which, on):
    _schema(c)
    acct = _acct(c, aid)
    uids = [int(u) for u in uids]
    with _lock(aid):
        M = _session(acct)
        _select(M)
        typ, _ = M.uid("STORE", ",".join(map(str, uids)), "+FLAGS" if on else "-FLAGS", f"({FLAG[which]})")
        if typ != "OK":
            raise mail.MailError("The mail server didn't accept that change")
    c.executemany(f"UPDATE inbox_msgs SET {which}=? WHERE account_id=? AND uid=?", [(int(on), aid, u) for u in uids])
    c.commit()
    _bump()


def _trash_folder(M):
    typ, data = M.list()
    names = []
    for raw in data or []:
        s = raw.decode("utf-8", "replace") if isinstance(raw, bytes) else str(raw)
        m = re.search(r'"([^"]*)"\s*$', s) or re.search(r"\s(\S+)\s*$", s)
        if not m:
            continue
        if "\\Trash" in s:
            return m.group(1)
        names.append(m.group(1))
    for n in ("Deleted Messages", "Trash", "Deleted Items", "[Gmail]/Trash"):
        if n in names:
            return n
    return None


def delete(c, aid, uids):
    """Move to the account's trash (Deleted Messages on iCloud), like deleting on your phone."""
    _schema(c)
    acct = _acct(c, aid)
    uids = [int(u) for u in uids]
    with _lock(aid):
        M = _session(acct)
        _select(M)
        trash = _trash_folder(M)
        s = ",".join(map(str, uids))
        if trash:
            typ, _ = M.uid("MOVE", s, f'"{trash}"') if "MOVE" in (M.capabilities or ()) else ("NO", None)
            if typ != "OK":
                typ, _ = M.uid("COPY", s, f'"{trash}"')
                if typ != "OK":
                    raise mail.MailError("Couldn't move that to the trash")
                M.uid("STORE", s, "+FLAGS", "(\\Deleted)")
                M.expunge()
        else:
            M.uid("STORE", s, "+FLAGS", "(\\Deleted)")
            M.expunge()
    c.executemany("DELETE FROM inbox_msgs WHERE account_id=? AND uid=?", [(aid, u) for u in uids])
    c.commit()
    for u in uids:
        _BODIES.pop((aid, u), None)
    _bump()


def forget_account(c, aid):
    _schema(c)
    _drop(aid)
    c.execute("DELETE FROM inbox_msgs WHERE account_id=?", (aid,))
    c.execute("DELETE FROM inbox_state WHERE account_id=?", (aid,))
    c.commit()
    _bump()
