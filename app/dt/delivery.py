"""Delivery updates: when a retailer doesn't email a shipping update, ask the carrier through 17TRACK (you add your own key).
Only the tracking number is sent to 17TRACK."""
import json
import os
import threading
import time
import urllib.error
import urllib.request

from . import db, orders

MAP17 = {"InTransit": "shipped", "InfoReceived": "shipped", "OutForDelivery": "out_for_delivery", "AvailableForPickup": "delivered", "Delivered": "delivered"}
STATE = {"running": False, "last": "", "error": "", "checked": 0, "changed": 0}


def settings(c):
    return {"enabled": db.get(c, "delivery_enabled", "0") == "1", "has_key": bool(db.get(c, "delivery_key")), "interval": int(db.get(c, "delivery_interval", "30") or 30)}


def save_settings(c, d):
    if "enabled" in d:
        db.put(c, "delivery_enabled", "1" if d["enabled"] else "0")
    if d.get("key"):
        db.put(c, "delivery_key", str(d["key"]).strip())
    if d.get("clear_key"):
        db.put(c, "delivery_key", "")
    if "interval" in d:
        try:
            db.put(c, "delivery_interval", str(max(10, min(1440, int(d["interval"])))))
        except (TypeError, ValueError):
            raise ValueError("Interval must be a number of minutes (10 or more)")
    return settings(c)


def _api(path, body, key):
    base = os.environ.get("TRACK_API_BASE", "https://api.17track.net/track/v2.2")
    req = urllib.request.Request(f"{base}/{path}", data=json.dumps(body).encode(), method="POST",
                                 headers={"17token": key, "Content-Type": "application/json", "User-Agent": "DementedToolbox"})
    try:
        return json.load(urllib.request.urlopen(req, timeout=25))
    except urllib.error.HTTPError as e:
        raise RuntimeError("17TRACK didn't accept the key" if e.code in (401, 403) else f"17TRACK answered {e.code}")
    except Exception as e:
        raise RuntimeError(f"Couldn't reach 17TRACK: {e}")


def refresh():
    if STATE["running"]:
        return STATE
    STATE.update(running=True, error="", checked=0, changed=0)
    try:
        c = db.connect()
        try:
            key = db.get(c, "delivery_key")
            if not key:
                raise RuntimeError("Add your 17TRACK key first")
            rows = db.rows(c, "SELECT * FROM orders WHERE tracking!='' AND status IN ('placed','shipped','out_for_delivery')")
            todo = [r for r in rows if not r["track_registered"]]
            for i in range(0, len(todo), 40):
                data = (_api("register", [{"number": r["tracking"]} for r in todo[i:i + 40]], key).get("data") or {})
                ok = {a["number"] for a in data.get("accepted") or []} | {rj["number"] for rj in data.get("rejected") or [] if (rj.get("error") or {}).get("code") == -18019901}
                for r in todo[i:i + 40]:
                    if r["tracking"] in ok:
                        c.execute("UPDATE orders SET track_registered=1, track_error='' WHERE id=?", (r["id"],))
                c.commit()
            reg = [r for r in rows if r["track_registered"] or r in todo]
            by = {r["tracking"]: r for r in reg}
            nums = list(by)
            for i in range(0, len(nums), 40):
                data = (_api("gettrackinfo", [{"number": n} for n in nums[i:i + 40]], key).get("data") or {})
                for a in data.get("accepted") or []:
                    r = by.get(a.get("number"))
                    ti = a.get("track_info") or {}
                    st = MAP17.get((ti.get("latest_status") or {}).get("status"))
                    ev = ti.get("latest_event") or {}
                    c.execute("UPDATE orders SET delivery_detail=?, eta=?, track_error='' WHERE id=?",
                              ((ev.get("description") or "")[:200], str(((ti.get("time_metrics") or {}).get("estimated_delivery_date") or {}).get("from") or "")[:10], r["id"]))
                    STATE["checked"] += 1
                    if st:
                        new = orders.next_status(r["status"], st)
                        if new != r["status"]:
                            orders.apply_event(c, {"retailer": r["retailer"], "order_number": r["order_number"], "status": new}, announce=True)
                            STATE["changed"] += 1
                for rj in data.get("rejected") or []:
                    if rj.get("number") in by:
                        c.execute("UPDATE orders SET track_registered=0, track_error=? WHERE id=?", ((rj.get("error") or {}).get("message", "not found yet")[:150], by[rj["number"]]["id"]))
                c.commit()
        finally:
            c.close()
        STATE["last"] = db.now()
    except Exception as e:
        STATE["error"] = str(e)
    finally:
        STATE["running"] = False
    return STATE


def poll_loop():
    if os.environ.get("DT_NO_AUTO"):
        return
    time.sleep(40)
    while True:
        wait = 1800
        try:
            c = db.connect()
            try:
                s = settings(c)
            finally:
                c.close()
            wait = s["interval"] * 60
            if s["enabled"] and s["has_key"]:
                refresh()
        except Exception:
            pass
        time.sleep(wait)
