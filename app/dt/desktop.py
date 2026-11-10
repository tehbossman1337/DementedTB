"""Windows niceties: system-tray icon, close to tray, start with Windows (HKCU Run key, no admin needed), start minimized."""
import os
import sys
import threading

from . import config, db

RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
RUN_NAME = "DementedToolbox"
DEFAULTS = {"close_to_tray": True, "start_with_windows": False, "start_minimized": True}
HOOKS = {"show": None, "quit": None, "sync": None}
STATE = {"tray": False}


def settings(c):
    out = dict(DEFAULTS)
    for k in DEFAULTS:
        v = db.get(c, "desktop." + k, "")
        if v != "":
            out[k] = v in ("1", "true", "True")
    out["start_with_windows"] = run_key_present() if os.name == "nt" else out["start_with_windows"]
    out["tray_available"] = STATE["tray"]
    out["windows"] = os.name == "nt"
    return out


def save(c, b):
    for k in DEFAULTS:
        if k in b:
            db.put(c, "desktop." + k, "1" if b[k] else "0")
    if "start_with_windows" in b and os.name == "nt":
        set_run_key(bool(b["start_with_windows"]))
    return settings(c)


def _exe():
    return sys.executable if getattr(sys, "frozen", False) else ""


def run_key_present():
    try:
        import winreg
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY) as k:
            winreg.QueryValueEx(k, RUN_NAME)
            return True
    except OSError:
        return False


def set_run_key(on):
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER, RUN_KEY, 0, winreg.KEY_SET_VALUE) as k:
        if on:
            exe = _exe()
            if not exe:
                raise ValueError("Start with Windows only works in the installed app")
            winreg.SetValueEx(k, RUN_NAME, 0, winreg.REG_SZ, f'"{exe}" --autostart')
        else:
            try:
                winreg.DeleteValue(k, RUN_NAME)
            except OSError:
                pass


def refresh_run_key():
    """After an update the exe path is the same, but rewrite it anyway so a moved install keeps starting."""
    if os.name == "nt" and run_key_present() and _exe():
        try:
            set_run_key(True)
        except OSError:
            pass


def _icon_image():
    from PIL import Image, ImageDraw
    for p in (os.path.join(getattr(sys, "_MEIPASS", ""), "app.ico"), os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "app.ico")):
        if p and os.path.isfile(p):
            try:
                return Image.open(p)
            except Exception:
                pass
    im = Image.new("RGBA", (64, 64), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((2, 2, 62, 62), 14, fill=(229, 48, 79, 255))
    d.text((22, 14), "D", fill="white")
    return im


def start_tray(log=lambda m: None):
    """Run the tray icon on its own thread. Returns True if it is up."""
    try:
        import pystray
    except Exception as e:
        log(f"tray unavailable: {e}")
        return False
    call = lambda name: (lambda icon=None, item=None: HOOKS[name] and HOOKS[name]())
    menu = pystray.Menu(pystray.MenuItem("Open Demented Toolbox", call("show"), default=True),
                        pystray.MenuItem("Check mail now", call("sync")),
                        pystray.Menu.SEPARATOR,
                        pystray.MenuItem("Quit", call("quit")))
    try:
        icon = pystray.Icon(RUN_NAME, _icon_image(), config.APP_NAME, menu)
        threading.Thread(target=icon.run, daemon=True).start()
        STATE["tray"] = True
        STATE["icon"] = icon
        return True
    except Exception as e:
        log(f"tray failed: {e}")
        return False


def stop_tray():
    try:
        STATE.get("icon") and STATE["icon"].stop()
    except Exception:
        pass
