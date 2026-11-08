"""Demented Toolbox license server.

Runs anywhere Python 3.10+ runs (a VPS, Render, Railway, Fly.io ...). One SQLite file + one signing key.

  ADMIN_TOKEN=<long random text> python server.py          # listens on $PORT (default 8787)
  open  http://localhost:8787/admin                         # create / revoke / extend keys

The app never sees the private signing key. It only gets short-lived signed tokens that it checks with the public key.
"""
import base64
import hashlib
import hmac
import html
import json
import os
import secrets
import sqlite3
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

DATA = os.environ.get("DATA_DIR", os.path.join(os.path.dirname(os.path.abspath(__file__)), "data"))
os.makedirs(DATA, exist_ok=True)
DB = os.path.join(DATA, "licenses.db")
KEY_FILE = os.path.join(DATA, "signing_key.pem")
CHECK_HOURS = int(os.environ.get("CHECK_HOURS", "72"))  # how long an app may run without reaching this server
LOCK = threading.Lock()


# ---------------------------------------------------------------- storage
def db():
    c = sqlite3.connect(DB, timeout=30)
    c.row_factory = sqlite3.Row
    c.executescript("""
    CREATE TABLE IF NOT EXISTS licenses(
      id INTEGER PRIMARY KEY, key_hash TEXT UNIQUE NOT NULL, key_hint TEXT, label TEXT DEFAULT '', plan TEXT DEFAULT 'member',
      created_at INTEGER, expires_at INTEGER, revoked INTEGER DEFAULT 0, max_devices INTEGER DEFAULT 1, note TEXT DEFAULT '');
    CREATE TABLE IF NOT EXISTS devices(
      id INTEGER PRIMARY KEY, license_id INTEGER NOT NULL, device_id TEXT NOT NULL, name TEXT DEFAULT '', first_seen INTEGER,
      last_seen INTEGER, app_version TEXT DEFAULT '', ip TEXT DEFAULT '', UNIQUE(license_id, device_id));
    """)
    return c


def load_key():
    if os.path.exists(KEY_FILE):
        return serialization.load_pem_private_key(open(KEY_FILE, "rb").read(), None)
    k = Ed25519PrivateKey.generate()
    with open(KEY_FILE, "wb") as f:
        f.write(k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()))
    try:
        os.chmod(KEY_FILE, 0o600)
    except OSError:
        pass
    return k


KEY = load_key()
PUB_B64 = base64.b64encode(KEY.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)).decode()


def b64u(b):
    return base64.urlsafe_b64encode(b).rstrip(b"=").decode()


def sign_token(payload):
    body = b64u(json.dumps(payload, separators=(",", ":"), sort_keys=True).encode())
    return body + "." + b64u(KEY.sign(body.encode()))


def hash_key(k):
    return hashlib.sha256(("dt1:" + k.strip().upper()).encode()).hexdigest()


def new_key():
    a = "ABCDEFGHJKLMNPQRSTUVWXYZ23456789"
    return "DT-" + "-".join("".join(secrets.choice(a) for _ in range(5)) for _ in range(4))


def make_license(c, label="", plan="member", days=None, max_devices=1, note=""):
    key = new_key()
    exp = int(time.time() + days * 86400) if days else None
    c.execute("INSERT INTO licenses(key_hash,key_hint,label,plan,created_at,expires_at,max_devices,note) VALUES(?,?,?,?,?,?,?,?)",
              (hash_key(key), key[-5:], label, plan, int(time.time()), exp, max_devices, note))
    c.commit()
    return key


def lic_by_key(c, key):
    return c.execute("SELECT * FROM licenses WHERE key_hash=?", (hash_key(key or ""),)).fetchone()


def check_license(l):
    if not l:
        return "That license key isn't valid. Check for typos."
    if l["revoked"]:
        return "This license has been revoked. Contact the seller."
    if l["expires_at"] and l["expires_at"] < time.time():
        return "This license has expired."
    return None


def token_for(l, device_id, name):
    now = int(time.time())
    return sign_token({"v": 1, "lid": l["id"], "user": l["label"] or "Member", "plan": l["plan"], "device": device_id, "device_name": name,
                       "issued": now, "expires": l["expires_at"], "check_by": now + CHECK_HOURS * 3600, "hint": l["key_hint"]})


def verify_token(tok):
    """Server-side check of a token we issued earlier (used for refreshes)."""
    try:
        body, sig = tok.split(".")
        KEY.public_key().verify(base64.urlsafe_b64decode(sig + "=" * (-len(sig) % 4)), body.encode())
        return json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4)))
    except Exception:
        return None


# ---------------------------------------------------------------- rate limit
_HITS = {}


def limited(ip, n=20, per=60):
    now = time.time()
    with LOCK:
        h = [t for t in _HITS.get(ip, []) if now - t < per]
        h.append(now)
        _HITS[ip] = h
        return len(h) > n


# ---------------------------------------------------------------- API logic
def activate(c, b, ip, refresh_token=None):
    key, dev = (b.get("key") or "").strip(), (b.get("device_id") or "").strip()[:80]
    name = (b.get("device_name") or "Unknown device").strip()[:80]
    if not dev:
        return 400, {"error": "Missing device id"}
    l = lic_by_key(c, key)
    err = check_license(l)
    if err:
        return 403, {"error": err, "code": "invalid"}
    row = c.execute("SELECT * FROM devices WHERE license_id=? AND device_id=?", (l["id"], dev)).fetchone()
    if not row:
        others = c.execute("SELECT * FROM devices WHERE license_id=? ORDER BY last_seen DESC", (l["id"],)).fetchall()
        if len(others) >= l["max_devices"]:
            if not b.get("force"):
                o = others[0]
                return 409, {"error": f"This key is active on another computer ({o['name'] or 'unnamed'}). Use it here instead?", "code": "in_use", "other": o["name"]}
            for o in others[: len(others) - l["max_devices"] + 1]:  # the oldest sessions give way
                c.execute("DELETE FROM devices WHERE id=?", (o["id"],))
        c.execute("INSERT INTO devices(license_id,device_id,name,first_seen,last_seen,app_version,ip) VALUES(?,?,?,?,?,?,?)",
                  (l["id"], dev, name, int(time.time()), int(time.time()), b.get("app_version", ""), ip))
    else:
        c.execute("UPDATE devices SET name=?, last_seen=?, app_version=?, ip=? WHERE id=?", (name, int(time.time()), b.get("app_version", ""), ip, row["id"]))
    c.commit()
    return 200, {"token": token_for(l, dev, name), "user": l["label"] or "Member", "plan": l["plan"], "expires": l["expires_at"]}


def validate(c, b, ip):
    p = verify_token(b.get("token") or "")
    if not p:
        return 403, {"error": "Invalid token", "code": "invalid"}
    l = c.execute("SELECT * FROM licenses WHERE id=?", (p["lid"],)).fetchone()
    err = check_license(l)
    if err:
        return 403, {"error": err, "code": "revoked"}
    d = c.execute("SELECT * FROM devices WHERE license_id=? AND device_id=?", (l["id"], p["device"])).fetchone()
    if not d:
        return 403, {"error": "This key is now active on another computer.", "code": "moved"}
    name = (b.get("device_name") or d["name"])[:80]
    c.execute("UPDATE devices SET last_seen=?, name=?, app_version=?, ip=? WHERE id=?", (int(time.time()), name, b.get("app_version", ""), ip, d["id"]))
    c.commit()
    return 200, {"token": token_for(l, p["device"], name), "user": l["label"] or "Member", "plan": l["plan"], "expires": l["expires_at"]}


def deactivate(c, b):
    p = verify_token(b.get("token") or "")
    if p:
        c.execute("DELETE FROM devices WHERE license_id=? AND device_id=?", (p["lid"], p["device"]))
        c.commit()
    return 200, {"ok": True}


def admin_list(c):
    out = []
    for l in c.execute("SELECT * FROM licenses ORDER BY id DESC"):
        devs = [dict(d) for d in c.execute("SELECT name,device_id,last_seen,app_version,ip FROM devices WHERE license_id=?", (l["id"],))]
        out.append({**dict(l), "devices": devs})
    return out


ADMIN_HTML = """<!doctype html><meta charset=utf-8><meta name=viewport content="width=device-width,initial-scale=1"><title>Demented Toolbox licenses</title>
<style>body{font:14px system-ui;background:#0a0a0f;color:#e8e8ee;margin:0;padding:24px;max-width:1000px;margin:auto}
input,select,button{background:#15151d;color:#e8e8ee;border:1px solid #2a2a36;border-radius:8px;padding:8px 10px;font:inherit}
button{cursor:pointer}button.p{background:#e5304f;border-color:#e5304f}table{width:100%;border-collapse:collapse;margin-top:16px}
td,th{padding:8px;border-bottom:1px solid #1f1f2a;text-align:left;vertical-align:top}.m{color:#8a8a99}.k{font:600 16px ui-monospace,monospace;color:#34d399}
.box{background:#12121a;border:1px solid #1f1f2a;border-radius:12px;padding:16px;margin:12px 0}h1{margin:0 0 4px}</style>
<h1>Demented Toolbox licenses</h1><div class=m>Public key (the app pins this): <code id=pk></code></div>
<div class=box id=login><input id=tok type=password placeholder="Admin token" style="width:260px"> <button class=p onclick="go()">Open</button></div>
<div id=main style="display:none"><div class=box><b>New key</b><br><br>
<input id=lab placeholder="Name (shown in the app)"> <select id=plan><option>member</option><option>pro</option><option>trial</option></select>
<input id=days type=number placeholder="Days (blank = lifetime)" style="width:180px"> <input id=md type=number value=1 min=1 style="width:70px" title="Computers at once">
<button class=p onclick="mk()">Create</button><div id=out style="margin-top:12px"></div></div>
<table id=t></table></div>
<script>
const $=id=>document.getElementById(id);let T=localStorage.getItem('dtadmin')||'';$('tok').value=T;
async function api(p,b){const r=await fetch(p,{method:b?'POST':'GET',headers:{'X-Admin-Token':T,'Content-Type':'application/json'},body:b?JSON.stringify(b):undefined});
 const j=await r.json();if(!r.ok)throw new Error(j.error||r.status);return j}
function esc(s){return String(s??'').replace(/[&<>"]/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;'}[c]))}
function d(t){return t?new Date(t*1000).toLocaleString():'—'}
async function go(){T=$('tok').value;try{await load();localStorage.setItem('dtadmin',T);$('login').style.display='none';$('main').style.display=''}catch(e){alert(e.message)}}
async function load(){const j=await api('/admin/api/list');$('pk').textContent=j.public_key;
 $('t').innerHTML='<tr><th>Key</th><th>Name / plan</th><th>Expires</th><th>Computers</th><th></th></tr>'+j.licenses.map(l=>`<tr><td class=k>…${esc(l.key_hint)}</td>
 <td>${esc(l.label)||'<span class=m>(no name)</span>'}<div class=m>${esc(l.plan)}${l.revoked?' · <b style="color:#f87171">revoked</b>':''}</div></td><td>${l.expires_at?d(l.expires_at):'Never'}</td>
 <td>${l.devices.map(x=>esc(x.name)+'<div class=m>'+d(x.last_seen)+'</div>').join('')||'<span class=m>none</span>'}</td>
 <td><button onclick="act(${l.id},'reset')">Free computer</button> <button onclick="act(${l.id},'extend')">+30 days</button>
 <button onclick="act(${l.id},'${l.revoked?'unrevoke':'revoke'}')">${l.revoked?'Restore':'Revoke'}</button></td></tr>`).join('')}
async function mk(){const j=await api('/admin/api/create',{label:$('lab').value,plan:$('plan').value,days:+$('days').value||null,max_devices:+$('md').value||1});
 $('out').innerHTML='Give this to the customer (it is shown only once):<br><span class=k>'+esc(j.key)+'</span>';load()}
async function act(id,a){await api('/admin/api/act',{id,action:a});load()}
if(T)go();
</script>"""


class H(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def log_message(self, *a):
        pass

    def ip(self):
        return (self.headers.get("X-Forwarded-For") or self.client_address[0]).split(",")[0].strip()

    def out(self, code, obj, ctype="application/json"):
        data = obj.encode() if isinstance(obj, str) else json.dumps(obj).encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def admin_ok(self):
        tok = os.environ.get("ADMIN_TOKEN", "")
        return bool(tok) and hmac.compare_digest(self.headers.get("X-Admin-Token", ""), tok)

    def do_GET(self):
        p = urlparse(self.path).path
        if p == "/v1/pubkey":
            return self.out(200, {"public_key": PUB_B64})
        if p == "/admin":
            return self.out(200, ADMIN_HTML, "text/html; charset=utf-8")
        if p == "/admin/api/list":
            if not self.admin_ok():
                return self.out(401, {"error": "Wrong admin token"})
            c = db()
            try:
                return self.out(200, {"public_key": PUB_B64, "licenses": admin_list(c)})
            finally:
                c.close()
        if p in ("/", "/health"):
            return self.out(200, {"ok": True, "service": "demented-toolbox-license"})
        self.out(404, {"error": "not found"})

    def do_POST(self):
        p = urlparse(self.path).path
        try:
            b = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        except ValueError:
            return self.out(400, {"error": "bad json"})
        c = db()
        try:
            if p.startswith("/v1/"):
                if limited(self.ip()):
                    return self.out(429, {"error": "Too many attempts. Wait a minute."})
                if p == "/v1/activate":
                    return self.out(*activate(c, b, self.ip()))
                if p == "/v1/validate":
                    return self.out(*validate(c, b, self.ip()))
                if p == "/v1/deactivate":
                    return self.out(*deactivate(c, b))
            if p.startswith("/admin/api/"):
                if not self.admin_ok():
                    return self.out(401, {"error": "Wrong admin token"})
                if p == "/admin/api/create":
                    k = make_license(c, b.get("label", ""), b.get("plan", "member"), b.get("days"), int(b.get("max_devices") or 1), b.get("note", ""))
                    return self.out(200, {"key": k})
                if p == "/admin/api/act":
                    i, a = int(b["id"]), b.get("action")
                    if a == "reset":
                        c.execute("DELETE FROM devices WHERE license_id=?", (i,))
                    elif a == "revoke":
                        c.execute("UPDATE licenses SET revoked=1 WHERE id=?", (i,))
                    elif a == "unrevoke":
                        c.execute("UPDATE licenses SET revoked=0 WHERE id=?", (i,))
                    elif a == "extend":
                        c.execute("UPDATE licenses SET expires_at=MAX(COALESCE(expires_at,0),?)+30*86400 WHERE id=? AND expires_at IS NOT NULL", (int(time.time()), i))
                    c.commit()
                    return self.out(200, {"ok": True})
            self.out(404, {"error": "not found"})
        except Exception as e:
            self.out(500, {"error": str(e)})
        finally:
            c.close()


def make_server(port):
    return ThreadingHTTPServer(("0.0.0.0", port), H)


if __name__ == "__main__":
    if not os.environ.get("ADMIN_TOKEN"):
        print("WARNING: ADMIN_TOKEN is not set, so the /admin page and key creation over HTTP are disabled.")
    port = int(os.environ.get("PORT", 8787))
    print(f"License server on :{port}\nPublic key: {PUB_B64}")
    make_server(port).serve_forever()
