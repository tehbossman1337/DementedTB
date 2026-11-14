"""A tiny in-memory IMAP server for tests (plain TCP). Enough of IMAP4rev1 for the app's inbox and mail sync:
LOGIN, CAPABILITY, NOOP, LIST, SELECT/EXAMINE, STATUS, UID SEARCH/FETCH/STORE/COPY/MOVE, EXPUNGE, LOGOUT."""
import re
import socketserver
import threading
import time
from email.utils import formatdate

BOXES = {}   # mailbox name -> {"validity": int, "next": int, "msgs": [{"uid", "flags": set, "raw": bytes}]}
LOCK = threading.RLock()


def box(name="INBOX"):
    return BOXES.setdefault(name, {"validity": 7, "next": 1, "msgs": []})


def add(raw, name="INBOX", flags=()):
    with LOCK:
        b = box(name)
        if isinstance(raw, str):
            raw = raw.replace("\r\n", "\n").replace("\n", "\r\n").encode()
        b["msgs"].append({"uid": b["next"], "flags": set(flags), "raw": raw})
        b["next"] += 1
        return b["next"] - 1


def make(frm, subject, body, to="me@icloud.com", html=None, when=None, attach=None):
    when = when or time.time()
    if html or attach:
        parts = [f"--B\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{body}\r\n"]
        if html:
            parts.append(f"--B\r\nContent-Type: text/html; charset=utf-8\r\n\r\n{html}\r\n")
        if attach:
            import base64
            parts.append(f"--B\r\nContent-Type: application/pdf\r\nContent-Disposition: attachment; filename=\"{attach[0]}\"\r\nContent-Transfer-Encoding: base64\r\n\r\n{base64.b64encode(attach[1]).decode()}\r\n")
        ctype = f"multipart/{'mixed' if attach else 'alternative'}; boundary=\"B\""
        content = "".join(parts) + "--B--\r\n"
    else:
        ctype, content = "text/plain; charset=utf-8", body
    return (f"From: {frm}\r\nTo: {to}\r\nSubject: {subject}\r\nDate: {formatdate(when)}\r\nMessage-ID: <{abs(hash((frm, subject, when)))}@fake>\r\n"
            f"MIME-Version: 1.0\r\nContent-Type: {ctype}\r\n\r\n{content}")


def _set(spec, msgs):
    """Messages matching a UID set like 1,4:7,9:*"""
    out = []
    maxu = max([m["uid"] for m in msgs] or [0])
    for part in spec.split(","):
        if ":" in part:
            a, b = part.split(":")
            a = maxu if a == "*" else int(a)
            b = maxu if b == "*" else int(b)
            lo, hi = min(a, b), max(a, b)
            out += [m for m in msgs if lo <= m["uid"] <= hi]
        else:
            u = maxu if part == "*" else int(part)
            out += [m for m in msgs if m["uid"] == u]
    seen, res = set(), []
    for m in out:
        if m["uid"] not in seen:
            seen.add(m["uid"])
            res.append(m)
    return res


def _header_fields(raw, fields):
    head = raw.split(b"\r\n\r\n", 1)[0]
    lines, cur = [], []
    for ln in head.split(b"\r\n"):
        if ln[:1] in (b" ", b"\t") and cur:
            cur.append(ln)
        else:
            if cur:
                lines.append(b"\r\n".join(cur))
            cur = [ln]
    if cur:
        lines.append(b"\r\n".join(cur))
    want = {f.upper() for f in fields}
    keep = [l for l in lines if l.split(b":", 1)[0].decode(errors="ignore").upper() in want]
    return b"\r\n".join(keep) + b"\r\n\r\n"


class H(socketserver.StreamRequestHandler):
    def w(self, s):
        self.wfile.write(s if isinstance(s, bytes) else s.encode())

    def handle(self):
        self.w("* OK fake IMAP ready\r\n")
        self.sel = None
        while True:
            line = self.rfile.readline()
            if not line:
                return
            line = line.decode(errors="replace").rstrip("\r\n")
            # literal arguments (e.g. LOGIN with a {n} literal) aren't used by imaplib for plain strings, so ignore that case
            parts = line.split(" ", 2)
            if len(parts) < 2:
                continue
            tag, cmd = parts[0], parts[1].upper()
            arg = parts[2] if len(parts) > 2 else ""
            try:
                if not self.cmd(tag, cmd, arg):
                    return
            except Exception as e:
                self.w(f"{tag} BAD {e}\r\n")

    def cmd(self, tag, cmd, arg):
        if cmd == "CAPABILITY":
            self.w("* CAPABILITY IMAP4rev1 UIDPLUS MOVE\r\n" + f"{tag} OK done\r\n")
        elif cmd == "LOGIN":
            if "bad" in arg.lower():
                self.w(f"{tag} NO [AUTHENTICATIONFAILED] bad password\r\n")
            else:
                self.w(f"{tag} OK logged in\r\n")
        elif cmd == "NOOP":
            self.w(f"{tag} OK noop\r\n")
        elif cmd == "LOGOUT":
            self.w(f"* BYE\r\n{tag} OK bye\r\n")
            return False
        elif cmd == "LIST":
            with LOCK:
                box("INBOX"); box("Deleted Messages")
                for n in BOXES:
                    attr = "\\HasNoChildren" + (" \\Trash" if n == "Deleted Messages" else "")
                    self.w(f'* LIST ({attr}) "/" "{n}"\r\n')
            self.w(f"{tag} OK list\r\n")
        elif cmd in ("SELECT", "EXAMINE"):
            name = arg.strip().strip('"')
            with LOCK:
                b = box(name)
                self.sel = name
                self.w(f"* {len(b['msgs'])} EXISTS\r\n* 0 RECENT\r\n* OK [UIDVALIDITY {b['validity']}] ok\r\n* OK [UIDNEXT {b['next']}] ok\r\n"
                       "* FLAGS (\\Seen \\Flagged \\Deleted \\Answered \\Draft)\r\n")
            self.w(f"{tag} OK [READ-WRITE] selected\r\n")
        elif cmd == "STATUS":
            name = re.match(r'"?([^"(]+?)"?\s*\(', arg).group(1)
            with LOCK:
                b = box(name)
                self.w(f'* STATUS "{name}" (MESSAGES {len(b["msgs"])} UIDNEXT {b["next"]} UIDVALIDITY {b["validity"]})\r\n')
            self.w(f"{tag} OK status\r\n")
        elif cmd == "EXPUNGE":
            with LOCK:
                b = box(self.sel)
                b["msgs"] = [m for m in b["msgs"] if "\\Deleted" not in m["flags"]]
            self.w(f"{tag} OK expunged\r\n")
        elif cmd == "CLOSE":
            self.w(f"{tag} OK closed\r\n")
        elif cmd == "UID":
            sub, rest = (arg.split(" ", 1) + [""])[:2]
            getattr(self, "uid_" + sub.lower())(tag, rest)
        else:
            self.w(f"{tag} BAD unknown {cmd}\r\n")
        return True

    def uid_search(self, tag, rest):
        with LOCK:
            msgs = box(self.sel)["msgs"]
            r = rest.upper().replace("CHARSET UTF-8", "").strip()
            if r.startswith("UID "):
                found = _set(r[4:].split()[0], msgs)
            elif r.startswith("SINCE"):
                found = msgs
            else:
                found = msgs
            self.w("* SEARCH " + " ".join(str(m["uid"]) for m in found) + "\r\n")
        self.w(f"{tag} OK search\r\n")

    def uid_fetch(self, tag, rest):
        spec, items = rest.split(" ", 1)
        items_u = items.upper()
        with LOCK:
            msgs = _set(spec, box(self.sel)["msgs"])
            for i, m in enumerate(msgs, 1):
                seq = box(self.sel)["msgs"].index(m) + 1
                bits = [f"UID {m['uid']}"]
                if "FLAGS" in items_u.replace("+FLAGS", ""):
                    bits.append("FLAGS (" + " ".join(sorted(m["flags"])) + ")")
                if "RFC822.SIZE" in items_u:
                    bits.append(f"RFC822.SIZE {len(m['raw'])}")
                lit = None
                hm = re.search(r"BODY(?:\.PEEK)?\[HEADER\.FIELDS \(([^)]*)\)\]", items, re.I)
                if hm:
                    lit = (f"BODY[HEADER.FIELDS ({hm.group(1)})]", _header_fields(m["raw"], hm.group(1).split()))
                elif re.search(r"BODY(?:\.PEEK)?\[\]", items, re.I) or "RFC822" in items_u.replace("RFC822.SIZE", ""):
                    lit = ("BODY[]", m["raw"])
                    if not re.search(r"\.PEEK", items, re.I):
                        m["flags"].add("\\Seen")
                if lit:
                    self.w(f"* {seq} FETCH (" + " ".join(bits) + f" {lit[0]} {{{len(lit[1])}}}\r\n")
                    self.w(lit[1])
                    self.w(")\r\n")
                else:
                    self.w(f"* {seq} FETCH (" + " ".join(bits) + ")\r\n")
        self.w(f"{tag} OK fetch\r\n")

    def uid_store(self, tag, rest):
        spec, mode, flags = rest.split(" ", 2)
        fl = set(flags.strip("()").split())
        with LOCK:
            for m in _set(spec, box(self.sel)["msgs"]):
                if mode.upper().startswith("+"):
                    m["flags"] |= fl
                elif mode.upper().startswith("-"):
                    m["flags"] -= fl
                else:
                    m["flags"] = fl
        self.w(f"{tag} OK store\r\n")

    def _copy(self, rest, move):
        spec, dest = rest.split(" ", 1)
        dest = dest.strip().strip('"')
        with LOCK:
            src = box(self.sel)
            for m in _set(spec, src["msgs"]):
                add(m["raw"], dest, m["flags"])
                if move:
                    src["msgs"].remove(m)

    def uid_copy(self, tag, rest):
        self._copy(rest, False)
        self.w(f"{tag} OK copy\r\n")

    def uid_move(self, tag, rest):
        self._copy(rest, True)
        self.w(f"{tag} OK move\r\n")

    def uid_expunge(self, tag, rest):
        with LOCK:
            b = box(self.sel)
            b["msgs"] = [m for m in b["msgs"] if "\\Deleted" not in m["flags"]]
        self.w(f"{tag} OK expunged\r\n")


class Server(socketserver.ThreadingTCPServer):
    allow_reuse_address = True
    daemon_threads = True


def start(port=0):
    s = Server(("127.0.0.1", port), H)
    threading.Thread(target=s.serve_forever, daemon=True).start()
    return s, s.server_address[1]


def patch_login(mail_module, port):
    """Make the app sign in to this server instead of a real one."""
    import imaplib

    def login(acct):
        M = imaplib.IMAP4("127.0.0.1", port)
        try:
            M.login(acct.get("username") or acct["email"], acct["password"])
        except imaplib.IMAP4.error as e:
            raise mail_module.MailError(str(e))
        return M
    mail_module.login = login
