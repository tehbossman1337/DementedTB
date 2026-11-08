"""Demented Toolbox desktop entry point: starts the local server and opens it in its own frameless window."""
import os
import sys
import threading
import time
import traceback
import webbrowser

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from dt import config, server  # noqa: E402


def _log(msg):
    try:
        open(os.path.join(config.DATA_DIR, "app.log"), "a", encoding="utf-8").write(time.strftime("%Y-%m-%d %H:%M:%S ") + msg + "\n")
    except Exception:
        pass


class WindowApi:
    """Buttons of the custom title bar."""
    def __init__(self):
        self.window = None

    def minimize(self):
        self.window.minimize()

    def maximize(self):
        try:
            self.window.toggle_fullscreen() if False else (self.window.restore() if getattr(self, "_max", False) else self.window.maximize())
            self._max = not getattr(self, "_max", False)
        except Exception:
            pass

    def close(self):
        self.window.destroy()
        os._exit(0)


def check():
    """Build smoke test (python main.py --check): everything the packaged app needs is present and the core code runs. Exit code 0 = ok."""
    import tempfile
    try:
        from dt import db, inventory, profiles, orders, mail  # noqa: F401
        c = db.connect(os.path.join(tempfile.mkdtemp(), "check.db"))
        assert inventory.lists(c)["pokemon_sets"], "inventory lists missing"
        inventory.dashboard(c)
        profiles.groups(c)
        assert os.path.isfile(os.path.join(config.WEB_DIR, "index.html")), "web files missing"
        for f in ("core.js", "pages.js", "pages2.js", "pages3.js", "pages4.js", "boot.js", "app.css"):
            assert os.path.isfile(os.path.join(config.WEB_DIR, f)), f + " missing"
        assert len(server.GET) > 10 and len(server.POST) > 60
        return 0
    except Exception:
        _log("check failed:\n" + traceback.format_exc())
        return 3


def main():
    if "--check" in sys.argv:
        os._exit(check())
    _log("starting")
    sys.excepthook = lambda *a: _log("unhandled:\n" + "".join(traceback.format_exception(*a)))
    try:  # safety net: remember what is in the database, bring a snapshot back if it was emptied by accident
        from dt import db as _db
        _db.connect().close()
        n0 = _db.counts()
        _log(f"data folder {config.DATA_DIR}; accounts={n0.get('mail_accounts')} orders={n0.get('orders')} bots={n0.get('bots')} profiles={n0.get('vprofiles')}")
        back = _db.restore_if_emptied()
        if back:
            _log("database was empty - restored from " + back)
        else:
            _db.snapshot("auto")
    except Exception:
        _log("safety net failed:\n" + traceback.format_exc())
    server.start_background()
    srv, port = server.make_server(8765)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    url = f"http://127.0.0.1:{port}"
    import urllib.request
    for _ in range(50):
        try:
            urllib.request.urlopen(url + "/api/version", timeout=2).read()
            break
        except Exception:
            time.sleep(0.2)
    if "--browser" in sys.argv:
        webbrowser.open(url)
        while True:
            time.sleep(3600)
    from dt import relaunch
    flag = os.path.join(config.DATA_DIR, "retry.flag")
    retried = os.path.isfile(flag) and time.time() - os.path.getmtime(flag) < 180
    _log(f"started pid={os.getpid()} port={port} frozen={getattr(sys, 'frozen', False)} retried={retried}")
    relaunch.clear_orphans()

    def watchdog():  # the window opened but never managed to talk to the server (seen right after an update): restart once, cleanly
        time.sleep(25)
        if server.UI["ok"]:
            try:
                os.remove(flag)
            except OSError:
                pass
            return
        _log("window never reached the local server within 25s")
        if retried:
            return
        try:
            open(flag, "w").write(str(time.time()))
        except OSError:
            pass
        if relaunch.spawn(relaunch.exe_path(), wait_pid=os.getpid(), kill_pid=os.getpid()):
            _log("restarting the app")
    threading.Thread(target=watchdog, daemon=True).start()
    for attempt in (1, 2):  # right after an update the previous window may still be shutting down; one calm retry fixes that
        try:
            import webview
            api = WindowApi()
            w = webview.create_window(config.APP_NAME, url, width=1280, height=820, min_size=(980, 640), frameless=True, easy_drag=False,
                                      background_color="#0a0a0f", js_api=api)
            api.window = w
            webview.start(storage_path=os.path.join(config.DATA_DIR, "webview"), private_mode=False)
            return
        except Exception:
            _log(f"native window failed (attempt {attempt}):\n" + traceback.format_exc())
            time.sleep(2.5)
    webbrowser.open(url)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
