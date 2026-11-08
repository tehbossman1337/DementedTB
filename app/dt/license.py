"""License client: activates a key with the license server, keeps a signed token, and re-checks in the background.

The token is signed by the server's private key (Ed25519). The app only holds the public key, so a token can't be forged
or edited on this computer. It is bound to this computer, expires, and must be refreshed online every few days.
"""
import base64
import hashlib
import json
import os
import platform
import socket
import threading
import time
import urllib.error
import urllib.request
import uuid

from . import config, db

DEFAULT_URL = "http://127.0.0.1:8787"
_state = {"error": "", "checked": 0, "lock": threading.Lock()}


def server_url(c=None):
    own = False
    if c is None:
        c, own = db.connect(), True
    try:
        v = db.get(c, "license_url") or os.environ.get("DT_LICENSE_URL") or config.read_res("license_url.txt") or DEFAULT_URL
    finally:
        if own:
            c.close()
    return v.rstrip("/")


def required(c=None):
    """Licensing is enforced only when this build points at a license server (license_url.txt baked in by CI, DT_LICENSE_URL,
    or a server address saved in the app). With none configured the app runs open - set the LICENSE_URL repo variable to turn it on."""
    own = False
    if c is None:
        c, own = db.connect(), True
    try:
        return bool(db.get(c, "license_url") or os.environ.get("DT_LICENSE_URL") or config.read_res("license_url.txt"))
    finally:
        if own:
            c.close()


def device_id():
    """Stable per-computer id: a random id kept in the data folder, mixed with the Windows MachineGuid where there is one."""
    p = os.path.join(config.DATA_DIR, "device.id")
    try:
        rnd = open(p).read().strip()
    except OSError:
        rnd = ""
    if not rnd:
        rnd = uuid.uuid4().hex
        try:
            open(p, "w").write(rnd)
        except OSError:
            pass
    guid = ""
    if os.name == "nt":
        try:
            import winreg
            with winreg.OpenKey(winreg.HKEY_LOCAL_MACHINE, r"SOFTWARE\Microsoft\Cryptography") as k:
                guid = winreg.QueryValueEx(k, "MachineGuid")[0]
        except Exception:
            pass
    return hashlib.sha256((rnd + "|" + guid + "|" + platform.node()).encode()).hexdigest()[:40]


def default_device_name():
    return f"{socket.gethostname()} ({platform.system() or 'PC'})"


def device_name(c):
    return db.get(c, "device_name") or default_device_name()


# -------------------------------------------------------------- token checks
def _unb64(s):
    return base64.urlsafe_b64decode(s + "=" * (-len(s) % 4))


def pubkey(c, fetch=True):
    """The pinned public key: shipped in the app if provided, otherwise fetched once from your server and remembered."""
    pinned = os.environ.get("DT_LICENSE_PUB") or config.read_res("license_pub.txt")
    if pinned:
        return pinned
    saved = db.get(c, "license_pub")
    if saved or not fetch:
        return saved
    j = _http("GET", server_url(c) + "/v1/pubkey", None)
    db.put(c, "license_pub", j["public_key"])
    return j["public_key"]


def verify(token, pub_b64):
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PublicKey
    body, sig = token.split(".")
    Ed25519PublicKey.from_public_bytes(base64.b64decode(pub_b64)).verify(_unb64(sig), body.encode())
    return json.loads(_unb64(body))


def _http(method, url, body, timeout=12):
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json", "User-Agent": "DementedToolbox"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            j = json.loads(e.read() or b"{}")
        except ValueError:
            j = {}
        raise LicenseError(j.get("error") or f"License server error {e.code}", j.get("code", ""), e.code, j)
    except (urllib.error.URLError, socket.timeout, OSError) as e:
        raise LicenseError("Can't reach the license server. Check your internet connection.", "offline")


class LicenseError(Exception):
    def __init__(self, msg, code="", status=0, extra=None):
        super().__init__(msg)
        self.code, self.status, self.extra = code, status, extra or {}


# -------------------------------------------------------------- status
def status(c):
    """What the UI needs: {state, user, plan, expires, hint, device_name}. state: none | active | expired | stale | invalid."""
    base = {"state": "none", "device_name": device_name(c), "server": server_url(c), "bypass": bool(os.environ.get("DT_LICENSE_BYPASS"))}
    if not required(c):
        return {**base, "state": "active", "user": "Demented", "plan": "open", "expires": None, "hint": "", "open": True}
    if os.environ.get("DT_LICENSE_BYPASS"):  # developer/test switch only; never set in a shipped build
        return {**base, "state": "active", "user": "Developer", "plan": "dev", "expires": None, "hint": "DEV"}
    tok = db.get(c, "license_token")
    if not tok:
        return base
    try:
        p = verify(tok, pubkey(c, fetch=False))
    except Exception:
        return {**base, "state": "invalid", "error": "Saved license could not be verified. Sign in again."}
    base.update(user=p.get("user", "Member"), plan=p.get("plan", "member"), expires=p.get("expires"), hint=p.get("hint", ""))
    if p.get("device") != device_id():
        return {**base, "state": "invalid", "error": "This license belongs to another computer."}
    now = time.time()
    if p.get("expires") and p["expires"] < now:
        return {**base, "state": "expired", "error": "Your license has expired."}
    if p.get("check_by", 0) < now:
        return {**base, "state": "stale", "error": "Couldn't reach the license server for a while. Connect to the internet to continue."}
    return {**base, "state": "active"}


def is_active(c):
    return status(c)["state"] == "active"


def activate(c, key, name=None, force=False):
    key = (key or "").strip().upper()
    if not key:
        raise LicenseError("Enter your license key.")
    if name:
        db.put(c, "device_name", name.strip()[:80])
    pub = pubkey(c)
    r = _http("POST", server_url(c) + "/v1/activate", {"key": key, "device_id": device_id(), "device_name": device_name(c),
                                                       "app_version": config.VERSION, "force": bool(force)})
    verify(r["token"], pub)  # refuse anything that isn't signed by the pinned key
    db.put(c, "license_token", r["token"])
    return status(c)


def refresh(c):
    """Ask the server to renew the token. A revoked / moved key signs this computer out; a network failure changes nothing."""
    tok = db.get(c, "license_token")
    if not tok:
        return status(c)
    try:
        r = _http("POST", server_url(c) + "/v1/validate", {"token": tok, "device_name": device_name(c), "app_version": config.VERSION})
        verify(r["token"], pubkey(c, fetch=False))
        db.put(c, "license_token", r["token"])
        _state["error"] = ""
    except LicenseError as e:
        if e.code in ("revoked", "moved", "invalid") and e.status in (403,):
            db.put(c, "license_token", "")
            _state["error"] = str(e)
        elif e.code == "offline":
            pass
        else:
            _state["error"] = str(e)
    _state["checked"] = time.time()
    return status(c)


def sign_out(c):
    tok = db.get(c, "license_token")
    if tok:
        try:
            _http("POST", server_url(c) + "/v1/deactivate", {"token": tok}, timeout=6)
        except LicenseError:
            pass
    db.put(c, "license_token", "")


def last_error():
    return _state["error"]


def refresh_loop(stop=None):
    """Background: renew the token about every 30 minutes while the app is open."""
    time.sleep(5)
    while not (stop and stop.is_set()):
        try:
            c = db.connect()
            try:
                if required(c) and db.get(c, "license_token") and not os.environ.get("DT_LICENSE_BYPASS"):
                    refresh(c)
            finally:
                c.close()
        except Exception:
            pass
        time.sleep(1800)
