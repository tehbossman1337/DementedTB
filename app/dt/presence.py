"""Discord status (Rich Presence): shows 'Playing Demented Toolbox' on your Discord profile while the app is open.
Talks to the Discord desktop app on this computer over its local pipe. Needs an application ID from discord.com/developers."""
import json
import os
import struct
import threading
import time
import uuid

from . import db

STATE = {"connected": False, "note": "Discord not detected yet — this connects on its own when Discord starts."}
START = int(time.time())


def settings(c):
    return {"enabled": db.get(c, "presence_enabled", "0") == "1", "counts": db.get(c, "presence_counts", "0") == "1", "client_id": db.get(c, "presence_client_id")}


def save(c, d):
    if "enabled" in d:
        db.put(c, "presence_enabled", "1" if d["enabled"] else "0")
    if "counts" in d:
        db.put(c, "presence_counts", "1" if d["counts"] else "0")
    if "client_id" in d:
        cid = str(d["client_id"] or "").strip()
        if cid and not cid.isdigit():
            raise ValueError("The application ID is a long number (Discord developer portal → your app → General Information).")
        db.put(c, "presence_client_id", cid)
    return settings(c)


def _paths():
    if os.name == "nt":
        return [rf"\\?\pipe\discord-ipc-{i}" for i in range(10)]
    base = os.environ.get("XDG_RUNTIME_DIR") or os.environ.get("TMPDIR") or "/tmp"
    return [os.path.join(base, f"discord-ipc-{i}") for i in range(10)]


class Pipe:
    def __init__(self, client_id):
        self.f = None
        for p in _paths():
            try:
                if os.name == "nt":
                    self.f = open(p, "r+b", buffering=0)
                else:
                    import socket
                    s = socket.socket(socket.AF_UNIX)
                    s.connect(p)
                    self.f = s.makefile("rwb", buffering=0)
                    self._s = s
                break
            except OSError:
                self.f = None
        if not self.f:
            raise OSError("Discord not running")
        self.send(0, {"v": 1, "client_id": client_id})
        self.recv()

    def send(self, op, payload):
        data = json.dumps(payload).encode()
        self.f.write(struct.pack("<ii", op, len(data)) + data)

    def recv(self):
        hdr = self.f.read(8)
        if len(hdr) < 8:
            raise OSError("pipe closed")
        op, n = struct.unpack("<ii", hdr)
        return op, json.loads(self.f.read(n) or b"{}")

    def activity(self, details, state=None):
        act = {"details": details, "timestamps": {"start": START}}
        if state:
            act["state"] = state
        self.send(1, {"cmd": "SET_ACTIVITY", "args": {"pid": os.getpid(), "activity": act}, "nonce": str(uuid.uuid4())})
        self.recv()

    def close(self):
        try:
            self.f.close()
        except Exception:
            pass


def loop():
    if os.environ.get("DT_NO_AUTO"):
        return
    pipe, cid = None, None
    while True:
        try:
            c = db.connect()
            try:
                s = settings(c)
                n = c.execute("SELECT COUNT(*) FROM orders").fetchone()[0] if s["counts"] else None
            finally:
                c.close()
            if not (s["enabled"] and s["client_id"]):
                if pipe:
                    pipe.close()
                    pipe = None
                STATE.update(connected=False, note="Turn this on and add your Discord application ID." if not s["client_id"] else "Off.")
            else:
                if pipe is None or cid != s["client_id"]:
                    if pipe:
                        pipe.close()
                    pipe, cid = Pipe(s["client_id"]), s["client_id"]
                pipe.activity("Tracking orders" if n is None else f"Tracking {n} order{'s' if n != 1 else ''}", "Demented Toolbox")
                STATE.update(connected=True, note="Showing on your Discord profile.")
        except OSError:
            if pipe:
                pipe.close()
            pipe = None
            STATE.update(connected=False, note="Discord not detected yet — this connects on its own when Discord starts.")
        except Exception as e:
            STATE.update(connected=False, note=f"Discord status error: {e}")
            pipe = None
        time.sleep(15)
