"""Paths, version and build-time settings."""
import os
import sys

VERSION = "1.0.0"
APP_NAME = "Demented Toolbox"
UPDATE_REPO = os.environ.get("DT_UPDATE_REPO", "")  # "owner/repo" whose GitHub Releases hold the installer (set at build time)

FROZEN = getattr(sys, "frozen", False)
if FROZEN:
    RES_DIR = getattr(sys, "_MEIPASS", os.path.dirname(sys.executable))
else:
    RES_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
WEB_DIR = os.path.join(RES_DIR, "web")

if os.environ.get("DT_DATA"):
    DATA_DIR = os.environ["DT_DATA"]
elif os.name == "nt":
    DATA_DIR = os.path.join(os.environ.get("APPDATA") or os.path.expanduser("~"), "DementedToolbox")
else:
    DATA_DIR = os.path.join(os.path.expanduser("~"), ".demented-toolbox")
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "toolbox.db")


def read_res(name, default=""):
    """A one-line text file shipped next to the app (license_url.txt, license_pub.txt)."""
    for base in (RES_DIR, os.path.join(RES_DIR, "dt"), os.path.dirname(os.path.abspath(__file__))):
        try:
            with open(os.path.join(base, name), encoding="utf-8") as f:
                v = f.read().strip()
                if v:
                    return v
        except OSError:
            pass
    return default


def exports_dir():
    d = os.path.join(os.path.expanduser("~"), "Documents", "Demented Toolbox")
    os.makedirs(d, exist_ok=True)
    return d
