"""Restart helpers. A relaunched app has to start exactly like a double-click: no inherited environment, no leftover WebView2 processes from the
copy that just closed (they hold the window's profile and make the new window hang), and no overlap with the installer. A small detached
batch file does that outside this process, then starts the app through Explorer."""
import os
import subprocess
import sys
import tempfile

from . import config

PS_KILL = ("Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'msedgewebview2.exe' -and $_.CommandLine -like '*DementedToolbox*' } | "
           "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")


def exe_path():
    return os.path.join(os.path.dirname(sys.executable), "DementedToolbox.exe") if getattr(sys, "frozen", False) else ""


def script(exe, wait_pid, kill_pid=0, installer_pid=0, extra_args=""):
    """Batch text: stop kill_pid (+children), wait for wait_pid / installer_pid to exit, clear WebView2 leftovers, start exe via Explorer."""
    q = lambda p: '"' + p + '"'
    lines = ["@echo off", "setlocal", f'set "LOG={os.path.join(config.DATA_DIR, "app.log")}"', 'echo %date% %time% relaunch helper started>>"%LOG%"']
    if kill_pid:
        lines.append(f"taskkill /F /PID {int(kill_pid)} >nul 2>&1")
    for pid in (wait_pid, installer_pid):
        if pid:
            n = int(pid)  # wait (at most ~60s) until that process id is gone; the spaces keep 111 from matching 1111
            lines += [f"set n=0", f":w{n}", "set /a n+=1", f"if %n% gtr 60 goto d{n}", f'tasklist /FI "PID eq {n}" 2>nul | find " {n} " >nul',
                      f"if not errorlevel 1 (ping -n 2 127.0.0.1 >nul & goto w{n})", f":d{n}"]
    lines += ["ping -n 3 127.0.0.1 >nul",
              f'powershell -NoProfile -ExecutionPolicy Bypass -Command "{PS_KILL}" >nul 2>&1',
              "ping -n 3 127.0.0.1 >nul",
              f'tasklist /FI "IMAGENAME eq DementedToolbox.exe" 2>nul | find /I "DementedToolbox.exe" >nul',
              f'if errorlevel 1 (echo %date% %time% relaunch helper starting app>>"%LOG%" & start "" explorer.exe {q(exe)}) else (echo %date% %time% app already running>>"%LOG%")',
              '(goto) 2>nul & del "%~f0"']
    return "\r\n".join(lines) + "\r\n"


def spawn(exe, wait_pid=0, kill_pid=0, installer_pid=0):
    if os.name != "nt" or not exe:
        return False
    try:
        p = os.path.join(tempfile.gettempdir(), f"dt-relaunch-{os.getpid()}.bat")
        open(p, "w", newline="").write(script(exe, wait_pid, kill_pid, installer_pid))
        env = {k: v for k, v in os.environ.items() if not (k.startswith("_PYI") or k in ("_MEIPASS2", "PYTHONHOME", "PYTHONPATH", "TCL_LIBRARY", "TK_LIBRARY"))}
        env["PYINSTALLER_RESET_ENVIRONMENT"] = "1"
        flags = 0x08000000 | 0x00000200  # CREATE_NO_WINDOW | CREATE_NEW_PROCESS_GROUP
        try:
            subprocess.Popen(["cmd.exe", "/c", p], env=env, cwd=tempfile.gettempdir(), creationflags=flags | 0x01000000, close_fds=True)
        except OSError:
            subprocess.Popen(["cmd.exe", "/c", p], env=env, cwd=tempfile.gettempdir(), creationflags=flags, close_fds=True)
        return True
    except Exception:
        import time, traceback
        try:
            open(os.path.join(config.DATA_DIR, "app.log"), "a", encoding="utf-8").write(time.strftime("%Y-%m-%d %H:%M:%S ") + "relaunch helper failed:\n" + traceback.format_exc())
        except Exception:
            pass
        return False


def clear_orphans(timeout=10):
    """At startup: stop WebView2 processes of this app whose owner is gone (left behind by a crash, kill or update)."""
    if os.name != "nt":
        return
    ps = ("$ids=(Get-Process).Id; Get-CimInstance Win32_Process | Where-Object { $_.Name -eq 'msedgewebview2.exe' -and $_.CommandLine -like '*DementedToolbox*' -and ($ids -notcontains $_.ParentProcessId) } | "
          "ForEach-Object { Stop-Process -Id $_.ProcessId -Force -ErrorAction SilentlyContinue }")
    try:
        subprocess.run(["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps], timeout=timeout, creationflags=0x08000000, capture_output=True)
    except Exception:
        pass
