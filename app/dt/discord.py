"""Discord bot access: list the servers your own bot is in, pick channels to watch, read success posts from them.

Uses only the plain REST API with a bot token that you create in the Discord developer portal. Nothing is posted.
"""
import json
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from . import arsenal, db

API = "https://discord.com/api/v10"
STATE = {"running": False, "last": "", "error": "", "watching": 0, "added": 0}
LOCK = threading.Lock()


class DiscordError(Exception):
    pass


def _token(c):
    t = db.get(c, "discord_bot_token")
    if not t:
        raise DiscordError("Add your Discord bot token first (Add a server).")
    return t


def api(token, path, params=None, retries=3):
    url = API + path + ("?" + urllib.parse.urlencode(params) if params else "")
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"Authorization": "Bot " + token, "User-Agent": "DiscordBot (https://localhost, 1.0)"})
        try:
            with urllib.request.urlopen(req, timeout=15) as r:
                return json.loads(r.read() or b"null")
        except urllib.error.HTTPError as e:
            body = e.read() or b"{}"
            try:
                j = json.loads(body)
            except ValueError:
                j = {}
            if e.code == 429:
                time.sleep(min(float(j.get("retry_after", 1)), 10) + 0.2)
                continue
            if e.code == 401:
                raise DiscordError("Discord rejected the bot token. Paste it again (Bot → Reset Token in the developer portal).")
            if e.code == 403:
                raise DiscordError("The bot can't see that. Give it View Channel + Read Message History there.")
            raise DiscordError(j.get("message") or f"Discord error {e.code}")
        except (urllib.error.URLError, OSError) as e:
            raise DiscordError("Can't reach Discord. Check your internet connection.")
    raise DiscordError("Discord is rate-limiting requests. Try again in a moment.")


def set_token(c, token):
    token = (token or "").strip().replace("Bot ", "")
    if len(token) < 30 or token.count(".") != 2:
        raise DiscordError("That doesn't look like a bot token (three parts separated by dots).")
    me = api(token, "/users/@me")
    db.put(c, "discord_bot_token", token)
    db.put(c, "discord_bot_name", me.get("username", "bot"))
    db.put(c, "discord_bot_id", me.get("id", ""))
    return refresh_servers(c)


def bot_info(c):
    return {"has_token": bool(db.get(c, "discord_bot_token")), "name": db.get(c, "discord_bot_name"), "id": db.get(c, "discord_bot_id")}


def invite_url(c):
    bid = db.get(c, "discord_bot_id")
    # View Channels (1024) + Read Message History (65536)
    return f"https://discord.com/oauth2/authorize?client_id={bid}&scope=bot&permissions=66560" if bid else ""


def refresh_servers(c):
    guilds = api(_token(c), "/users/@me/guilds") or []
    ids = set()
    for g in guilds:
        ids.add(g["id"])
        icon = f"https://cdn.discordapp.com/icons/{g['id']}/{g['icon']}.png?size=64" if g.get("icon") else ""
        c.execute("INSERT INTO servers(guild_id,name,icon) VALUES(?,?,?) ON CONFLICT(guild_id) DO UPDATE SET name=excluded.name, icon=excluded.icon", (g["id"], g["name"], icon))
    c.execute("DELETE FROM servers WHERE guild_id NOT IN (%s)" % ",".join("?" * len(ids)) if ids else "DELETE FROM servers", list(ids))
    c.commit()
    return list_servers(c)


def list_servers(c):
    out = []
    for s in db.rows(c, "SELECT * FROM servers ORDER BY name COLLATE NOCASE"):
        s["linked"] = bool(s["linked"])
        s["watched"] = c.execute("SELECT COUNT(*) FROM channels WHERE guild_id=? AND watched=1", (s["guild_id"],)).fetchone()[0]
        out.append(s)
    return out


def link(c, guild_id, on=True):
    c.execute("UPDATE servers SET linked=? WHERE guild_id=?", (1 if on else 0, guild_id))
    if not on:
        c.execute("UPDATE channels SET watched=0 WHERE guild_id=?", (guild_id,))
    c.commit()


def list_channels(c, guild_id, refresh=True):
    if refresh:
        chans = api(_token(c), f"/guilds/{guild_id}/channels") or []
        for ch in chans:
            if ch.get("type") in (0, 5):
                c.execute("INSERT INTO channels(channel_id,guild_id,name) VALUES(?,?,?) ON CONFLICT(channel_id) DO UPDATE SET name=excluded.name", (ch["id"], guild_id, ch["name"]))
        c.commit()
    out = db.rows(c, "SELECT * FROM channels WHERE guild_id=? ORDER BY name COLLATE NOCASE", (guild_id,))
    for ch in out:
        ch["watched"] = bool(ch["watched"])
    return out


def watch(c, channel_id, on):
    c.execute("UPDATE channels SET watched=? WHERE channel_id=?", (1 if on else 0, channel_id))
    c.commit()


def _pull(c, token, ch, backfill=False, limit=3000):
    """Read a channel's messages (oldest first for new ones) and hand each to Arsenal. Returns how many checkouts were added."""
    added, got = 0, 0
    last = "" if backfill else (ch["last_message_id"] or "")
    newest = ch["last_message_id"] or ""
    if last or not backfill:
        params = {"limit": 100}
        if last:
            params["after"] = last
        first = True
        while True:
            msgs = api(token, f"/channels/{ch['channel_id']}/messages", params) or []
            if not msgs:
                break
            msgs.sort(key=lambda m: int(m["id"]))
            for m in msgs:
                added += arsenal.ingest_message(c, m, ch["channel_id"])
                newest = max(newest or "0", m["id"], key=int)
            got += len(msgs)
            if len(msgs) < 100 or got >= limit:
                break
            params["after"] = msgs[-1]["id"]
            if not last and first:  # first ever read without a position: take the most recent page only unless backfilling
                break
    else:
        before = None
        while got < limit:
            params = {"limit": 100}
            if before:
                params["before"] = before
            msgs = api(token, f"/channels/{ch['channel_id']}/messages", params) or []
            if not msgs:
                break
            for m in msgs:
                added += arsenal.ingest_message(c, m, ch["channel_id"])
                newest = max(newest or "0", m["id"], key=int)
            got += len(msgs)
            before = min(m["id"] for m in msgs)
            if len(msgs) < 100:
                break
    c.execute("UPDATE channels SET last_message_id=?, last_sync=?, error='' WHERE channel_id=?", (newest, db.now(), ch["channel_id"]))
    c.commit()
    return added


def sync(backfill=False, rescan=False):
    """Read every watched channel. backfill: also go back through older posts; rescan: forget the position and re-read."""
    with LOCK:
        STATE.update(running=True, error="")
        added = 0
        try:
            c = db.connect()
            try:
                token = db.get(c, "discord_bot_token")
                if not token:
                    return 0
                chans = db.rows(c, "SELECT * FROM channels WHERE watched=1")
                STATE["watching"] = len(chans)
                for ch in chans:
                    try:
                        if rescan:
                            ch["last_message_id"] = ""
                        added += _pull(c, token, ch, backfill=backfill or rescan)
                    except DiscordError as e:
                        STATE["error"] = f"#{ch['name']}: {e}"
                        c.execute("UPDATE channels SET error=? WHERE channel_id=?", (str(e), ch["channel_id"]))
                        c.commit()
                STATE.update(last=db.now(), added=added)
            finally:
                c.close()
        finally:
            STATE["running"] = False
        return added


def status(c):
    watching = c.execute("SELECT COUNT(*) FROM channels WHERE watched=1").fetchone()[0]
    return {**STATE, "watching": watching, "bot": bot_info(c), "invite_url": invite_url(c)}


def poll_loop(interval=30):
    import os
    if os.environ.get("DT_NO_AUTO"):
        return
    time.sleep(10)
    while True:
        try:
            c = db.connect()
            try:
                go = bool(db.get(c, "discord_bot_token")) and c.execute("SELECT 1 FROM channels WHERE watched=1").fetchone()
            finally:
                c.close()
            if go:
                sync()
        except Exception:
            pass
        time.sleep(interval)
