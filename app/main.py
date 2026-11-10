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
    """Buttons of the custom title bar.
    The window is kept in a _private attribute on purpose: pywebview walks every public attribute of this object to expose it to JavaScript,
    and walking window.native (the WebView2/.NET objects) from a background thread blocked the whole app at start-up (spinner, "not responding")."""
    def __init__(self):
        self._window = None
        self._max = False

    def minimize(self):
        self._window.minimize()

    def maximize(self):
        try:
            self._window.restore() if self._max else self._window.maximize()
            self._max = not self._max
        except Exception:
            pass

    def close(self):
        """Title-bar X: hide to the tray when that's on (mail keeps being watched), otherwise quit."""
        from dt import db, desktop
        try:
            c = db.connect()
            to_tray = desktop.STATE["tray"] and desktop.settings(c)["close_to_tray"]
            c.close()
        except Exception:
            to_tray = False
        if to_tray:
            self._window.hide()
            if not getattr(self, "_told", False):
                self._told = True
                try:
                    from dt import notify
                    notify.toast("Still running", "Demented Toolbox keeps watching your inboxes from the tray. Right-click the tray icon to quit.")
                except Exception:
                    pass
            return
        quit_app(self._window)


def quit_app(window=None):
    try:
        from dt import desktop
        desktop.stop_tray()
        window and window.destroy()
    finally:
        os._exit(0)


def _already_running():
    """If another copy is already up, bring its window forward and say so."""
    import json
    import urllib.request
    try:
        d = json.loads(urllib.request.urlopen("http://127.0.0.1:8765/api/diag", timeout=1.5).read())
        if d.get("pid") and d["pid"] != os.getpid() and "data_dir" in d:
            urllib.request.urlopen(urllib.request.Request("http://127.0.0.1:8765/api/window/show", data=b"{}", method="POST"), timeout=3).read()
            return True
    except Exception:
        pass
    return False


def check():
    """Build smoke test (python main.py --check): everything the packaged app needs is present and the core code runs. Exit code 0 = ok."""
    import tempfile
    try:
        from dt import db, inventory, profiles, orders, mail  # noqa: F401
        c = db.connect(os.path.join(tempfile.mkdtemp(), "check.db"))
        assert inventory.lists(c)["pokemon_sets"], "inventory lists missing"
        inventory.dashboard(c)
        profiles.groups(c)
        from dt import stats, desktop
        stats.stick_rates(c, 90)
        desktop.settings(c)
        if os.name == "nt":
            import pystray._win32  # noqa: F401  (tray icon must be bundled)
            desktop._icon_image()
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
    try:  # native crashes (inside WebView2 / .NET) leave a trace here; pywebview's own messages go to app.log
        import faulthandler
        global _CRASH
        _CRASH = open(os.path.join(config.DATA_DIR, "crash.log"), "a")
        _CRASH.write(time.strftime("\n==== %Y-%m-%d %H:%M:%S start\n")); _CRASH.flush()
        faulthandler.enable(_CRASH)
    except Exception:
        pass
    try:
        import logging
        h = logging.FileHandler(os.path.join(config.DATA_DIR, "app.log"), encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s [%(name)s] %(levelname)s %(message)s", "%Y-%m-%d %H:%M:%S"))
        lg = logging.getLogger("pywebview"); lg.addHandler(h); lg.setLevel(logging.INFO)
    except Exception:
        pass
    sys.excepthook = lambda *a: _log("unhandled:\n" + "".join(traceback.format_exception(*a)))
    if "--browser" not in sys.argv and _already_running():
        _log("already running - brought the open window forward")
        os._exit(0)
    from dt import relaunch
    cleaner = threading.Thread(target=relaunch.clear_orphans, daemon=True)  # runs while the rest starts up
    if "--browser" not in sys.argv:
        cleaner.start()
    try:  # safety net: remember what is in the database, bring a snapshot back if it was emptied by accident
        from dt import db as _db
        _db.connect().close()
        n0 = _db.counts()
        _log(f"data folder {config.DATA_DIR}; accounts={n0.get('mail_accounts')} orders={n0.get('orders')} bots={n0.get('bots')} profiles={n0.get('vprofiles')}")
        back = _db.restore_if_emptied()
        if back:
            _log("database was empty - restored from " + back)
        else:  # one copy a day is plenty; taken in the background so it never delays the window
            import glob as _g
            today = time.strftime("%Y%m%d")
            if not _g.glob(os.path.join(config.DATA_DIR, "backups", f"toolbox-auto-{today}-*.db")):
                threading.Thread(target=_db.snapshot, args=("auto",), daemon=True).start()
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
    flag = os.path.join(config.DATA_DIR, "retry.flag")
    retried = os.path.isfile(flag) and time.time() - os.path.getmtime(flag) < 180
    _log(f"started pid={os.getpid()} port={port} frozen={getattr(sys, 'frozen', False)} retried={retried}")
    cleaner.join(timeout=6)

    def watchdog():  # the window opened but never managed to talk to the server (seen right after an update): restart once, cleanly
        time.sleep(45)
        if server.UI["ok"]:
            try:
                os.remove(flag)
            except OSError:
                pass
            return
        _log("window never reached the local server within 45s")
        if retried:
            return
        try:
            open(flag, "w").write(str(time.time()))
        except OSError:
            pass
        if relaunch.spawn(relaunch.exe_path(), wait_pid=os.getpid(), kill_pid=os.getpid()):
            _log("restarting the app")
    threading.Thread(target=watchdog, daemon=True).start()
    from dt import db as _dbm, desktop, mail as _mail
    try:
        _c = _dbm.connect(); dset = desktop.settings(_c); _c.close()
    except Exception:
        dset = dict(desktop.DEFAULTS)
    desktop.refresh_run_key()
    tray = desktop.start_tray(_log)
    hide_at_start = "--autostart" in sys.argv and dset.get("start_minimized") and tray
    if "--autostart" in sys.argv:
        _log(f"started with Windows (minimized={bool(hide_at_start)})")
    for attempt in (1, 2):  # right after an update the previous window may still be shutting down; one calm retry fixes that
        try:
            import webview
            api = WindowApi()
            w = webview.create_window(config.APP_NAME, url, width=1280, height=820, min_size=(980, 640), frameless=True, easy_drag=False,
                                      background_color="#0a0a0f", js_api=api, minimized=bool(hide_at_start))
            api._window = w

            def show(w=w):
                try:
                    w.show(); w.restore()
                except Exception:
                    pass
            desktop.HOOKS.update(show=show, quit=lambda w=w: quit_app(w),
                                 sync=lambda: threading.Thread(target=_mail.sync_all, daemon=True).start())
            if hide_at_start:  # start with Windows: load the page, then tuck the window into the tray
                w.events.loaded += lambda *a: (not getattr(api, "_hid", False)) and (setattr(api, "_hid", True), w.hide())
            for ev in ("shown", "loaded", "closing", "closed"):
                try:
                    getattr(w.events, ev).__iadd__((lambda n: (lambda *a: _log("window " + n)))(ev))
                except Exception:
                    pass
            _log(f"opening window (attempt {attempt}, webview {getattr(webview, '__version__', '?')}, gui {os.environ.get('PYWEBVIEW_GUI', 'auto')})")
            webview.start(storage_path=os.path.join(config.DATA_DIR, "webview"), private_mode=False)
            _log("window loop ended")
            return
        except Exception:
            _log(f"native window failed (attempt {attempt}):\n" + traceback.format_exc())
            time.sleep(2.5)
    webbrowser.open(url)
    while True:
        time.sleep(3600)


if __name__ == "__main__":
    main()
