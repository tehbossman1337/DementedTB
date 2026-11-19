"""Inbox: read every connected email account (iCloud and others) inside the app — the main inbox and the folders your mail rules file
mail into (Target, Walmart, …). Sent, Drafts, Junk and Deleted are left out.

Headers, flags and a short preview are cached locally so the list opens instantly; message bodies are fetched when you open one. A loop checks
every account every 20 seconds over a kept-open connection (a fresh sign-in each time would trip iCloud's limits). Folders that haven't changed
(same STATUS) are skipped, so many folders stay cheap."""
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
KEEP = 600            # newest messages kept in the local list per folder
FOLDER_REFRESH = 120  # re-list folders every 2 minutes (new rules, renames)
RESYNC = 300          # look at an unchanged folder at least every 5 minutes (flag changes don't show in STATUS)
PREVIEWS_PER_ROUND = 40

STATE = {"rev": 0, "last": 0.0, "checking": False, "errors": {}}
_CONN = {}
_LOCKS = {}
_BODIES = {}          # small in-memory cache of opened messages
_FOLDERS = {}         # account id -> (folder names, when listed)
_STATUS = {}          # (account id, folder) -> (STATUS answer, when last synced)
_SCHEMA_DONE = set()


def _schema(c):
    if db.config.DB_PATH in _SCHEMA_DONE:
        return
    cols = [r[1] for r in c.execute("PRAGMA table_info(inbox_msgs)")]
    if cols and "folder" not in cols:  # the first Inbox only cached INBOX; it's only a cache, so rebuild it with folders
        c.execute("DROP TABLE inbox_msgs")
        c.execute("DROP TABLE IF EXISTS inbox_state")
    c.executescript("""
    CREATE TABLE IF NOT EXISTS inbox_msgs(account_id INTEGER NOT NULL, folder TEXT NOT NULL DEFAULT 'INBOX', uid INTEGER NOT NULL, message_id TEXT DEFAULT '',
      from_name TEXT DEFAULT '', from_addr TEXT DEFAULT '', to_addr TEXT DEFAULT '', subject TEXT DEFAULT '', ts REAL DEFAULT 0, seen INTEGER DEFAULT 0,
      flagged INTEGER DEFAULT 0, attach INTEGER DEFAULT 0, snippet TEXT, size INTEGER DEFAULT 0, PRIMARY KEY(account_id, folder, uid));
    CREATE INDEX IF NOT EXISTS idx_inbox_ts ON inbox_msgs(ts DESC);
    CREATE TABLE IF NOT EXISTS inbox_state(account_id INTEGER NOT NULL, folder TEXT NOT NULL DEFAULT 'INBOX', validity INTEGER DEFAULT 0,
      last_uid INTEGER DEFAULT 0, checked REAL DEFAULT 0, error TEXT DEFAULT '', PRIMARY KEY(account_id, folder));
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


def _q(folder):
    return '"' + folder.replace("\\", "\\\\").replace('"', '\\"') + '"'


def _select(M, folder="INBOX"):
    typ, data = M.select(_q(folder))
    if typ != "OK":
        raise mail.MailError(f"Couldn't open the folder {folder_label(folder)}")
    typ, v = M.response("UIDVALIDITY")
    try:
        return int(v[-1]) if v and v[-1] else 0
    except (TypeError, ValueError):
        return 0


def folder_label(name):
    """IMAP folder names are stored in 'modified UTF-7' (Pok&AOk-mon). Turn them into normal text."""
    import base64
    def dec(m):
        b = m.group(1)
        if not b:
            return "&"
        b = b.replace(",", "/")
        try:
            return base64.b64decode(b + "=" * (-len(b) % 4)).decode("utf-16-be")
        except Exception:
            return m.group(0)
    return re.sub(r"&([A-Za-z0-9+,]*)-", dec, name or "")


def _folders(M, acct):
    aid = acct["id"]
    got = _FOLDERS.get(aid)
    if got and time.time() - got[1] < FOLDER_REFRESH:
        return got[0]
    names = mail._folders(M, acct)
    names = sorted(set(names), key=lambda f: (f.upper() != "INBOX", folder_label(f).lower()))
    _FOLDERS[aid] = (names, time.time())
    return names


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
def _status(M, folder):
    try:
        typ, data = M.status(_q(folder), "(UIDNEXT MESSAGES UNSEEN)")
        return data[0] if typ == "OK" and data else None
    except imaplib.IMAP4.error:
        return None


def _check_folder(c, M, aid, folder):
    """New mail and read/unread/deleted changes for one folder. Returns (new messages, anything changed)."""
    st = c.execute("SELECT * FROM inbox_state WHERE account_id=? AND folder=?", (aid, folder)).fetchone()
    last, old_validity = (st["last_uid"], st["validity"]) if st else (0, 0)
    validity = _select(M, folder)
    if old_validity and validity and validity != old_validity:  # the server renumbered the folder: start over
        c.execute("DELETE FROM inbox_msgs WHERE account_id=? AND folder=?", (aid, folder))
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
            rows.append((aid, folder, uid, str(h.get("Message-ID", ""))[:300], _dec(fn)[:120], fa.lower()[:200], to.lower()[:300], _dec(h.get("Subject", ""))[:300],
                         _ts(h.get("Date")), 0, 0, int("multipart/mixed" in str(h.get("Content-Type", "")).lower()), None, size))
        c.executemany("INSERT OR IGNORE INTO inbox_msgs VALUES(?,?,?,?,?,?,?,?,?,?,?,?,?,?)", rows)
        last = max([last] + new)
    # read / flagged / deleted elsewhere (phone, iCloud.com…)
    lo = c.execute("SELECT MIN(uid) FROM inbox_msgs WHERE account_id=? AND folder=?", (aid, folder)).fetchone()[0]
    changed = False
    if lo:
        flags = _fetch_flags(M, lo)
        cur = {r["uid"]: (r["seen"], r["flagged"]) for r in c.execute("SELECT uid, seen, flagged FROM inbox_msgs WHERE account_id=? AND folder=?", (aid, folder))}
        gone = [u for u in cur if u not in flags]
        if gone:
            c.executemany("DELETE FROM inbox_msgs WHERE account_id=? AND folder=? AND uid=?", [(aid, folder, u) for u in gone])
            changed = True
        upd = []
        for u, f in flags.items():
            if u in cur:
                nv = (int("\\Seen" in f), int("\\Flagged" in f))
                if nv != cur[u]:
                    upd.append(nv + (aid, folder, u))
        if upd:
            c.executemany("UPDATE inbox_msgs SET seen=?, flagged=? WHERE account_id=? AND folder=? AND uid=?", upd)
            changed = True
    # previews for the newest messages that don't have one yet
    need = [r[0] for r in c.execute("SELECT uid FROM inbox_msgs WHERE account_id=? AND folder=? AND snippet IS NULL ORDER BY uid DESC LIMIT ?", (aid, folder, PREVIEWS_PER_ROUND))]
    for i in range(0, len(need), 10):
        typ, data = M.uid("FETCH", ",".join(str(u) for u in need[i:i + 10]), "(UID BODY.PEEK[])")
        for item in data or []:
            if isinstance(item, tuple):
                um = re.search(rb"UID (\d+)", item[0])
                if um:
                    msg = email.message_from_bytes(item[1], policy=policy.default)
                    c.execute("UPDATE inbox_msgs SET snippet=?, attach=? WHERE account_id=? AND folder=? AND uid=?", (_snippet(msg), int(_has_attach(msg)), aid, folder, int(um.group(1))))
        changed = True
    c.execute("DELETE FROM inbox_msgs WHERE account_id=? AND folder=? AND uid NOT IN (SELECT uid FROM inbox_msgs WHERE account_id=? AND folder=? ORDER BY uid DESC LIMIT ?)",
              (aid, folder, aid, folder, KEEP))
    c.execute("INSERT OR REPLACE INTO inbox_state(account_id, folder, validity, last_uid, checked, error) VALUES(?,?,?,?,?,'')", (aid, folder, validity, last, time.time()))
    c.commit()
    return len(rows), changed


def check_account(acct):
    """Pick up new mail and changes in every folder of one account. Returns how many new messages arrived."""
    aid = acct["id"]
    with _lock(aid):
        c = _conn_db()
        try:
            M = _session(acct)
            folders = _folders(M, acct)
            # folders that disappeared (deleted or renamed on the phone)
            stale = [r[0] for r in c.execute("SELECT DISTINCT folder FROM inbox_state WHERE account_id=?", (aid,)) if r[0] not in folders]
            for f in stale:
                c.execute("DELETE FROM inbox_msgs WHERE account_id=? AND folder=?", (aid, f))
                c.execute("DELETE FROM inbox_state WHERE account_id=? AND folder=?", (aid, f))
            total, changed = 0, bool(stale)
            for f in folders:
                stat = _status(M, f)
                prev = _STATUS.get((aid, f))
                if prev and stat is not None and prev[0] == stat and time.time() - prev[1] < RESYNC:
                    continue  # nothing new, nothing read or deleted
                n, ch = _check_folder(c, M, aid, f)
                _STATUS[(aid, f)] = (_status(M, f) if (n or ch) else stat, time.time())
                total += n
                changed = changed or ch or bool(n)
            c.commit()
            STATE["errors"].pop(aid, None)
            if changed:
                _bump()
            return total
        except Exception as e:  # one bad mailbox must never stop the others
            _drop(aid)
            STATE["errors"][aid] = str(e)[:200]
            try:
                c.execute("INSERT OR IGNORE INTO inbox_state(account_id, folder) VALUES(?, 'INBOX')", (aid,))
                c.execute("UPDATE inbox_state SET error=?, checked=? WHERE account_id=? AND folder='INBOX'", (str(e)[:200], time.time(), aid))
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
def list_messages(c, account=0, q="", unread=False, flagged=False, limit=300, offset=0, folder=""):
    _schema(c)
    where, args = ["1=1"], []
    ids = {r["id"]: r["email"] for r in c.execute("SELECT id, email FROM mail_accounts WHERE enabled=1")}
    where.append(f"account_id IN ({','.join('?' * len(ids)) or 'NULL'})")
    args += list(ids)
    if account:
        where.append("account_id=?")
        args.append(int(account))
    if folder:
        where.append("folder=?")
        args.append(folder)
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
        r["folder_label"] = folder_label(r["folder"]) if r["folder"].upper() != "INBOX" else "Inbox"
    return {"messages": rows, "total": total, "rev": STATE["rev"]}


def summary(c):
    _schema(c)
    accts = db.rows(c, "SELECT id, email, provider FROM mail_accounts WHERE enabled=1 ORDER BY email")
    unread = {r[0]: r[1] for r in c.execute("SELECT account_id, COUNT(*) FROM inbox_msgs WHERE seen=0 GROUP BY account_id")}
    funread = {(r[0], r[1]): r[2] for r in c.execute("SELECT account_id, folder, COUNT(*) FROM inbox_msgs WHERE seen=0 GROUP BY account_id, folder")}
    fcount = {(r[0], r[1]): r[2] for r in c.execute("SELECT account_id, folder, COUNT(*) FROM inbox_msgs GROUP BY account_id, folder")}
    st = {}
    for r in c.execute("SELECT * FROM inbox_state"):
        st.setdefault(r["account_id"], []).append(dict(r))
    for a in accts:
        ss = st.get(a["id"]) or []
        a["unread"] = unread.get(a["id"], 0)
        a["error"] = STATE["errors"].get(a["id"]) or next((x["error"] for x in ss if x["error"]), "")
        a["checked"] = max([x["checked"] or 0 for x in ss] or [0])
        a["loaded"] = any(x["checked"] for x in ss)
        names = (_FOLDERS.get(a["id"]) or ([x["folder"] for x in ss], 0))[0]
        a["folders"] = [{"name": f, "label": "Inbox" if f.upper() == "INBOX" else folder_label(f), "unread": funread.get((a["id"], f), 0),
                         "count": fcount.get((a["id"], f), 0)} for f in sorted(set(names), key=lambda f: (f.upper() != "INBOX", folder_label(f).lower()))]
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


def _raw(acct, uid, folder="INBOX"):
    key = (acct["id"], folder, uid)
    if key in _BODIES:
        return _BODIES[key]
    with _lock(acct["id"]):
        try:
            M = _session(acct)
            _select(M, folder)
            raw = _fetch_raw(M, uid)
        except (imaplib.IMAP4.error, OSError, EOFError):
            _drop(acct["id"])
            M = _session(acct)
            _select(M, folder)
            raw = _fetch_raw(M, uid)
    if raw is None:
        raise ValueError("That email was moved or deleted")
    _BODIES[key] = raw
    while len(_BODIES) > 30:
        _BODIES.pop(next(iter(_BODIES)))
    return raw


def open_message(c, aid, uid, images=False, mark_read=True, folder="INBOX"):
    _schema(c)
    acct = _acct(c, aid)
    msg = email.message_from_bytes(_raw(acct, uid, folder), policy=policy.default)
    plain, html_, atts = _parts(msg)
    if html_:
        body, remote = sanitize(html_, images, _cids(msg))
        kind = "html"
    else:
        body, remote, kind = htmlmod.escape(plain), 0, "text"
    fn, fa = parseaddr(msg.get("From", ""))
    out = {"account_id": aid, "folder": folder, "uid": uid, "subject": _dec(msg.get("Subject", "")) or "(no subject)", "from_name": _dec(fn), "from_addr": fa,
           "to": _dec(msg.get("To", "")), "cc": _dec(msg.get("Cc", "")), "date": _ts(msg.get("Date")), "kind": kind, "body": body,
           "remote_images": remote, "images": bool(images), "attachments": atts}
    row = c.execute("SELECT seen FROM inbox_msgs WHERE account_id=? AND folder=? AND uid=?", (aid, folder, uid)).fetchone()
    if mark_read and row and not row["seen"]:
        try:
            set_flags(c, aid, [uid], "seen", True, folder)
        except Exception:
            pass
    return out


def attachment(c, aid, uid, idx, folder="INBOX"):
    acct = _acct(c, aid)
    msg = email.message_from_bytes(_raw(acct, uid, folder), policy=policy.default)
    for i, p in enumerate(msg.walk()):
        if i == int(idx):
            return _dec(p.get_filename() or "attachment"), p.get_content_type(), p.get_payload(decode=True) or b""
    raise ValueError("Attachment not found")


# ---------------------------------------------------------------- actions
FLAG = {"seen": "\\Seen", "flagged": "\\Flagged"}


def set_flags(c, aid, uids, which, on, folder="INBOX"):
    _schema(c)
    acct = _acct(c, aid)
    uids = [int(u) for u in uids]
    with _lock(aid):
        M = _session(acct)
        _select(M, folder)
        typ, _ = M.uid("STORE", ",".join(map(str, uids)), "+FLAGS" if on else "-FLAGS", f"({FLAG[which]})")
        if typ != "OK":
            raise mail.MailError("The mail server didn't accept that change")
    c.executemany(f"UPDATE inbox_msgs SET {which}=? WHERE account_id=? AND folder=? AND uid=?", [(int(on), aid, folder, u) for u in uids])
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


def delete(c, aid, uids, folder="INBOX"):
    """Move to the account's trash (Deleted Messages on iCloud), like deleting on your phone."""
    _schema(c)
    acct = _acct(c, aid)
    uids = [int(u) for u in uids]
    with _lock(aid):
        M = _session(acct)
        _select(M, folder)
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
    c.executemany("DELETE FROM inbox_msgs WHERE account_id=? AND folder=? AND uid=?", [(aid, folder, u) for u in uids])
    c.commit()
    for u in uids:
        _BODIES.pop((aid, folder, u), None)
    _STATUS.pop((aid, folder), None)
    _bump()


def forget_account(c, aid):
    _schema(c)
    _drop(aid)
    _FOLDERS.pop(aid, None)
    for k in [k for k in _STATUS if k[0] == aid]:
        _STATUS.pop(k, None)
    c.execute("DELETE FROM inbox_msgs WHERE account_id=?", (aid,))
    c.execute("DELETE FROM inbox_state WHERE account_id=?", (aid,))
    c.commit()
    _bump()


# ---------------------------------------------------------------- order reader check (what the tracker makes of this email)
def read_as_order(c, aid, uid, folder="INBOX"):
    from . import parsers
    acct = _acct(c, aid)
    msg = email.message_from_bytes(_raw(acct, uid, folder), policy=policy.default)
    sender, subject = parsers.unrelay(_dec(msg.get("From", ""))), _dec(msg.get("Subject", ""))
    body = mail.body_text(msg)
    forced = mail.rule_retailer(db.rows(c, "SELECT * FROM retailer_rules"), sender)
    ev, why = parsers.parse_email(sender, subject, body, msg.get("Date"), extra=f"{msg.get('Reply-To', '')}\n{subject}\n{body[:800]}", default=forced)
    if ev and forced:
        ev["retailer"] = forced
    known = None
    if ev:
        r = c.execute("SELECT id, status FROM orders WHERE retailer=? AND order_number=?", (ev["retailer"], ev["order_number"])).fetchone()
        known = dict(r) if r else None
    return {"event": ev, "reason": why, "tracked": known, "account": mail.recipient(msg, acct["email"]),
            "retailer_guess": parsers.detect_retailer(sender, f"{subject}\n{body[:800]}") or ""}


def add_as_order(c, aid, uid, folder="INBOX"):
    r = read_as_order(c, aid, uid, folder)
    if not r["event"]:
        raise ValueError("This email can't be read as an order: " + r["reason"])
    from . import orders
    outcome, oid = orders.apply_event(c, r["event"], account=r["account"], announce=False)
    c.commit()
    return {"outcome": outcome, "order_id": oid}


def raw_message(c, aid, uid, folder="INBOX"):
    return _raw(_acct(c, aid), uid, folder)
