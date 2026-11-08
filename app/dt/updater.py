"""In-app updates from GitHub Releases: check, download with progress, run the installer silently. Your data is never touched."""
import json
import os
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import build_info, config, db

API = os.environ.get("DT_API_BASE", "https://api.github.com")
STATE = {"phase": "idle", "done": 0, "total": 0, "error": "", "path": ""}


class _NoAuthOnRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None and urllib.parse.urlparse(newurl).netloc != urllib.parse.urlparse(req.full_url).netloc:
            new.headers.pop("Authorization", None)
            new.unredirected_hdrs.pop("Authorization", None)
        return new


def _open(url, token="", accept="application/vnd.github+json", timeout=30):
    h = {"User-Agent": "DementedToolbox", "Accept": accept}
    if token:
        h["Authorization"] = f"Bearer {token}"
    return urllib.request.build_opener(_NoAuthOnRedirect).open(urllib.request.Request(url, headers=h), timeout=timeout)


def repo():
    return build_info.REPO or config.UPDATE_REPO


def check(token=""):
    if not repo():
        return {"ok": False, "error": "This copy isn't linked to a release feed, so it can't update itself. Install the newest Setup file from your Releases page once."}
    try:
        rel = json.load(_open(f"{API}/repos/{repo()}/releases/latest", token))
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return {"ok": False, "error": "No release found yet. If the repository is private, add a GitHub token (paste a read-only token and check again)."}
        if e.code in (401, 403):
            return {"ok": False, "error": "GitHub refused the request. Check the token (it needs read access to the repository)."}
        return {"ok": False, "error": f"GitHub said {e.code}"}
    except Exception as e:
        return {"ok": False, "error": f"Couldn't reach GitHub: {e}"}
    tag = rel.get("tag_name", "")
    try:
        latest = int(tag.split("-")[-1])
    except ValueError:
        return {"ok": False, "error": f"Unrecognised release tag {tag}"}
    asset = next((a for a in rel.get("assets", []) if a["name"].lower().endswith(".exe")), None)
    return {"ok": True, "current": build_info.BUILD, "latest": latest, "tag": tag, "update": latest > build_info.BUILD and bool(asset),
            "url": asset["url"] if asset else "", "size": asset["size"] if asset else 0, "notes": rel.get("body", "")}


def _download(url, token, size):
    STATE.update(phase="downloading", done=0, total=size, error="")
    path = os.path.join(tempfile.gettempdir(), "DementedToolbox-Setup.exe")
    try:
        with _open(url, token, accept="application/octet-stream", timeout=120) as r, open(path, "wb") as f:
            STATE["total"] = int(r.headers.get("Content-Length") or size or 0)
            while True:
                chunk = r.read(256 * 1024)
                if not chunk:
                    break
                f.write(chunk)
                STATE["done"] += len(chunk)
        if STATE["total"] and STATE["done"] < STATE["total"]:
            raise IOError("download was cut short")
        STATE.update(phase="ready", path=path)
    except Exception as e:
        STATE.update(phase="error", error=f"Download failed: {e}")


def start_download(url, token="", size=0):
    if STATE["phase"] == "downloading":
        return {"ok": False, "error": "Already downloading"}
    if not url.startswith(API + "/repos/"):
        return {"ok": False, "error": "Refusing to download from an unexpected address."}
    threading.Thread(target=_download, args=(url, token, size), daemon=True).start()
    return {"ok": True}


def install():
    if STATE["phase"] != "ready" or not os.path.isfile(STATE["path"]):
        return {"ok": False, "error": "Nothing downloaded yet."}
    if os.name != "nt":
        return {"ok": False, "error": "Installing only works on Windows. The file is at " + STATE["path"]}
    STATE["phase"] = "installing"
    try:
        db.snapshot("pre-update")
    except Exception:
        pass
    # The installer (and the app it relaunches) must NOT inherit this process's PyInstaller environment: a relaunched copy that sees
    # these variables thinks it is a child of the old, now-replaced install and crashes on start. Hand it a clean environment instead.
    env = {k: v for k, v in os.environ.items() if not (k.startswith("_PYI") or k in ("_MEIPASS2", "PYTHONHOME", "PYTHONPATH", "TCL_LIBRARY", "TK_LIBRARY"))}
    env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
    args = [STATE["path"], "/SILENT", "/SUPPRESSMSGBOXES", "/CLOSEAPPLICATIONS", "/FORCECLOSEAPPLICATIONS", "/NORESTART"]
    flags = 0x00000008 | 0x00000200  # DETACHED_PROCESS | CREATE_NEW_PROCESS_GROUP
    from . import relaunch
    try:
        inst = subprocess.Popen(args, env=env, cwd=tempfile.gettempdir(), creationflags=flags | 0x01000000, close_fds=True)  # + CREATE_BREAKAWAY_FROM_JOB
    except OSError:
        inst = subprocess.Popen(args, env=env, cwd=tempfile.gettempdir(), creationflags=flags, close_fds=True)
    # The installer no longer starts the app. A helper waits until the installer has finished and this process (and its WebView2 children) is gone,
    # then opens the new version the same way a double-click would.
    relaunch.spawn(relaunch.exe_path(), wait_pid=os.getpid(), kill_pid=os.getpid(), installer_pid=inst.pid)
    return {"ok": True}
