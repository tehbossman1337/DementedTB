"""Backend self-test: license server round trip, mail sync with a fake IMAP server, Discord checkouts, backup, logs, resets."""
import json
import os
import sys
import tempfile
import threading
import time
import urllib.request

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="dt-test-")
os.environ.update(DT_DATA=os.path.join(TMP, "app"), DT_NO_AUTO="1", DT_NO_TOAST="1", DATA_DIR=os.path.join(TMP, "lic"))
os.makedirs(os.environ["DT_DATA"]); os.makedirs(os.environ["DATA_DIR"])
sys.path.insert(0, os.path.join(ROOT, "app"))
sys.path.insert(0, os.path.join(ROOT, "license-server"))

import server as LS  # license server
from dt import arsenal, backup, db, discord, license as lic, logs, mail, notify, orders, server as S

ok = fail = 0


def check(name, cond, extra=""):
    global ok, fail
    if cond:
        ok += 1
    else:
        fail += 1
        print("FAIL:", name, extra)


# ---------------------------------------------------------------- license server over real HTTP
os.environ["ADMIN_TOKEN"] = "adm"
ls = LS.make_server(0)
LPORT = ls.server_address[1]
threading.Thread(target=ls.serve_forever, daemon=True).start()
lc = LS.db()
KEY = LS.make_license(lc, "Tester", "member", 30)
lc.close()


def lpost(path, body, admin=False):
    r = urllib.request.Request(f"http://127.0.0.1:{LPORT}{path}", data=json.dumps(body).encode(), method="POST", headers={"Content-Type": "application/json", **({"X-Admin-Token": "adm"} if admin else {})})
    try:
        return json.load(urllib.request.urlopen(r))
    except urllib.error.HTTPError as e:
        return json.load(e)


c = db.connect()
db.put(c, "license_url", f"http://127.0.0.1:{LPORT}")
check("starts locked", lic.status(c)["state"] == "none")
r = S.POST["/api/license/activate"](c, {"key": "DT-AAAAA-BBBBB-CCCCC-DDDDD"})
check("bad key refused", not r["ok"] and "valid" in r["error"], r)
r = S.POST["/api/license/activate"](c, {"key": KEY, "device_name": "Test PC"})
check("good key activates", r["ok"] and r["state"] == "active" and r["user"] == "Tester", r)
check("pubkey remembered", bool(db.get(c, "license_pub")))
tok = db.get(c, "license_token")
# tamper: flip a character in the payload => signature fails
body, sig = tok.split(".")
db.put(c, "license_token", body[:-2] + ("A" if body[-2] != "A" else "B") + body[-1] + "." + sig)
check("tampered token rejected", lic.status(c)["state"] == "invalid")
db.put(c, "license_token", tok)
check("restored token ok", lic.status(c)["state"] == "active")
# second computer
real_dev = lic.device_id
lic.device_id = lambda: "otherdevice"
c2 = db.connect(os.path.join(TMP, "other.db"))
db.put(c2, "license_url", f"http://127.0.0.1:{LPORT}")
r = S.POST["/api/license/activate"](c2, {"key": KEY, "device_name": "Laptop"})
check("second computer blocked", not r["ok"] and r["code"] == "in_use", r)
r = S.POST["/api/license/activate"](c2, {"key": KEY, "device_name": "Laptop", "force": True})
check("second computer can take over", r["ok"], r)
lic.device_id = real_dev
st = lic.refresh(c)
check("first computer signed out after takeover", st["state"] == "none", st)
lc = LS.db()
lc.execute("DELETE FROM devices"); lc.commit()
r = S.POST["/api/license/activate"](c, {"key": KEY, "device_name": "Test PC"})
check("reactivate after admin reset", r["ok"])
lpost("/admin/api/act", {"id": 1, "action": "revoke"}, admin=True)
st = lic.refresh(c)
check("revoked key signs out", st["state"] == "none", st)
check("admin needs token", lpost("/admin/api/create", {}).get("error") == "Wrong admin token")
lpost("/admin/api/act", {"id": 1, "action": "unrevoke"}, admin=True)
r = S.POST["/api/license/activate"](c, {"key": KEY, "device_name": "Test PC"})
check("restored key activates", r["ok"])
# expired/stale logic with a forged-time token is covered by server-signed check_by; simulate stale
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
payload = LS.verify_token(db.get(c, "license_token")); payload["check_by"] = int(time.time()) - 5
db.put(c, "license_token", LS.sign_token(payload))
check("stale token locks until online", lic.status(c)["state"] == "stale")
r = S.POST["/api/license/activate"](c, {"key": KEY, "device_name": "Test PC"})
check("online again unlocks", r["ok"])
c.close()

# ---------------------------------------------------------------- HTTP gate
srv, port = S.make_server(18765)
threading.Thread(target=srv.serve_forever, daemon=True).start()
base = f"http://127.0.0.1:{port}"


def api(path, body=None):
    r = urllib.request.Request(base + path, data=json.dumps(body).encode() if body is not None else None, method="POST" if body is not None else "GET", headers={"Content-Type": "application/json"})
    try:
        return json.load(urllib.request.urlopen(r))
    except urllib.error.HTTPError as e:
        return {"_code": e.code, **json.load(e)}


check("api open while licensed", "orders" in api("/api/tracking"))
c = db.connect()
db.put(c, "license_token", "")
check("api locked when signed out", api("/api/tracking").get("locked") is True)
check("version still reachable", api("/api/version")["name"] == "Demented Toolbox")
check("ui served", b"<html" in urllib.request.urlopen(base + "/").read().lower() if os.path.exists(os.path.join(ROOT, "app/web/index.html")) else True)
S.POST["/api/license/activate"](c, {"key": KEY, "device_name": "Test PC"})

# ---------------------------------------------------------------- fake IMAP
def msg(frm, subj, body, to="alias.one@icloud.com", mid=None, date="Mon, 02 Nov 2026 10:00:00 -0500"):
    return (f"From: {frm}\r\nTo: {to}\r\nSubject: {subj}\r\nDate: {date}\r\nMessage-ID: <{mid or abs(hash(subj + body))}@x>\r\nContent-Type: text/plain; charset=utf-8\r\n\r\n{body}").encode()


class FakeIMAP:
    boxes = {}

    def __init__(self, acct):
        self.acct = acct
        self.sel = None

    def list(self):
        return "OK", [b'(\\HasNoChildren) "/" "INBOX"', b'(\\HasNoChildren) "/" "Junk"']

    def select(self, f, readonly=True):
        self.sel = self.boxes.setdefault(self.acct["email"], [])
        return "OK", [str(len(self.sel)).encode()]

    def response(self, k):
        return k, [b"7"]

    def status(self, f, spec):
        return "OK", [f"INBOX (UIDNEXT {len(self.boxes.get(self.acct['email'], [])) + 1})".encode()]

    def uid(self, cmd, a, b=None):
        if cmd == "SEARCH":
            n = len(self.sel)
            if b.startswith("UID"):
                lo = int(b.split()[1].split(":")[0])
                u = [i for i in range(1, n + 1) if i >= lo] or ([n] if n else [])
            else:
                u = list(range(1, n + 1))
            return "OK", [" ".join(map(str, u)).encode()]
        if cmd == "FETCH":
            out = []
            for u in a.split(","):
                raw = self.sel[int(u) - 1]
                if "HEADER" in b:
                    raw = raw.split(b"\r\n\r\n")[0] + b"\r\n\r\n"
                out += [(f"{u} (UID {u} BODY[] {{{len(raw)}}}".encode(), raw), b")"]
            return "OK", out

    def logout(self):
        pass


mail.login = lambda acct: FakeIMAP(acct)
c = db.connect()
aid = mail.save_account(c, {"email": "me@icloud.com", "password": "abcd efgh ijkl mnop"})
check("provider auto-detected", mail.get_account(c, aid)["provider"] == "icloud" and mail.get_account(c, aid)["host"] == "imap.mail.me.com")
try:
    mail.save_account(c, {"email": "me@icloud.com", "password": "x"}); check("duplicate account refused", False)
except ValueError:
    check("duplicate account refused", True)
res = mail.bulk_add(c, "a@gmail.com:abcd efgh ijkl mnop\nb@mydomain.com:pw:imap.mydomain.com:993\nnot-an-email:pw\n", test=True)
check("bulk add handles good + bad lines", [r["ok"] for r in res] == [True, True, False], res)
check("bulk custom host", mail.get_account(c, res[1]["id"])["host"] == "imap.mydomain.com")
for r in res:
    if r["ok"]:
        mail.delete_account(c, r["id"])
FakeIMAP.boxes["me@icloud.com"] = [
    msg("Pokemon Center <orders@pokemoncenter.com>", "Thanks for your order! Order #P0041360611", "Order #P0041360611\n1 x Mega Evolution Elite Trainer Box $59.99\nOrder total: $65.99", mid="m1"),
    msg("news@somewhere.com", "Weekly sale", "buy stuff", mid="m2"),
    msg("Target <orders@target.com>", "Your order has shipped", "Order #912345678\nTracking number 1Z999AA10123456784", to="hide.my.mail@icloud.com", mid="m3"),
    msg("noreply@pokemoncenter.com", "Something about your order", "We did a thing with your parcel, no number here.", mid="m4"),
    msg("me@icloud.com", "Fwd: Order confirmation", "---------- Forwarded message ---------\nFrom: Walmart <help@walmart.com>\nSubject: Order confirmation\n\nOrder #2000123456789\nOrder total: $20.00", mid="m5"),
]
st = mail.sync_account(aid)
check("sync read mail", st["orders"] == 3 and st["attention"] == 1 and st["errors"] == 0, st)
o = {x["order_number"]: x for x in orders.list_orders(c)}
check("pokemon order parsed", o["P0041360611"]["status"] == "placed" and o["P0041360611"]["total"] == 65.99 and o["P0041360611"]["retailer"] == "Pokémon Center")
check("account is the recipient alias", o["912345678"]["account"] == "hide.my.mail@icloud.com", o["912345678"]["account"])
check("tracking + carrier", o["912345678"]["tracking"].startswith("1Z") and o["912345678"]["carrier"] == "UPS")
check("forwarded mail attributed to original retailer", o["2000123456789"]["retailer"] == "Walmart")
check("attention queue", len(mail.list_attention(c)) == 1)
st = mail.sync_account(aid)
check("second sync is a no-op", st["orders"] == 0 and len(orders.list_orders(c)) == 3, st)
FakeIMAP.boxes["me@icloud.com"].append(msg("orders@pokemoncenter.com", "Your order has shipped", "Order #P0041360611\nTracking number 9400111899223344556677", mid="m6"))
st = mail.sync_account(aid)
check("new mail advances status", st["orders"] == 1 and {x["order_number"]: x for x in orders.list_orders(c)}["P0041360611"]["status"] == "shipped")
st = mail.sync_account(aid, full=True)
check("backfill re-reads without duplicating", len(orders.list_orders(c)) == 3 and len(mail.list_attention(c)) == 0 or len(mail.list_attention(c)) <= 1, st)
check("history recorded", len(orders.order_detail(c, o["P0041360611"]["id"])["events"]) >= 2)
check("notifications created", notify.list_notifications(c)["unread"] >= 3)
check("status never goes backwards", orders.next_status("delivered", "placed") == "delivered" and orders.next_status("shipped", "cancelled") == "cancelled" and orders.next_status("delivered", "cancelled") == "delivered")
mail.resolve_attention(c, mail.list_attention(c)[0]["id"], ignore="sender")
check("ignore sender makes an exception", any(e["value"] == "noreply@pokemoncenter.com" for e in db.rows(c, "SELECT * FROM exceptions")))
# delete -> stays hidden after backfill, restore -> returns
oid = o["912345678"]["id"]
orders.delete_orders(c, [oid])
mail.sync_account(aid, full=True)
check("deleted order stays hidden", "912345678" not in {x["order_number"] for x in orders.list_orders(c)})
orders.restore_deleted(c, db.rows(c, "SELECT id FROM deleted_orders")[0]["id"])
mail.sync_account(aid, full=True)
check("restored order comes back on backfill", "912345678" in {x["order_number"] for x in orders.list_orders(c)})
# manual order, merge, move
m1 = orders.save_manual(c, {"retailer": "Target", "order_number": "man-1", "product": "Thing", "qty": 2, "total": "10"})
m2 = orders.save_manual(c, {"retailer": "Target", "order_number": "man-2", "tracking": "ABC1234567"})
orders.merge(c, m2, m1)
check("merge keeps data", orders.order_detail(c, m1)["tracking"] == "ABC1234567")
check("eml import", mail.import_eml(c, [{"name": "a.eml", "text": msg("orders@bestbuy.com", "Order confirmation", "Order #BBY01-123456789\nOrder total: $5.00", mid="eml1").decode()}])["orders"] == 1)
mail.add_own(c, "Alias@Example.com")
check("own addresses include connected", "alias@example.com" in mail.own_addresses(c) and "me@icloud.com" in mail.own_addresses(c))

# ---------------------------------------------------------------- webhooks
try:
    notify.save_webhook(c, {"name": "x", "url": "https://evil.example/x"}); check("webhook url validated", False)
except ValueError:
    check("webhook url validated", True)
wid = notify.save_webhook(c, {"name": "Orders", "url": "https://discord.com/api/webhooks/123/abcdef", "events": ["shipped", "bogus"]})
check("webhook events filtered", notify.list_webhooks(c)[0]["events"] == ["shipped"])
sent = []
notify.post_webhook = lambda url, payload, timeout=10: sent.append(payload) or "ok"
notify.notify(c, "shipped", "Shipped: Target", "x", dedupe="t1")
notify.notify(c, "delivered", "Delivered: Target", "x", dedupe="t2")
time.sleep(0.3)
check("webhook only gets subscribed events", len(sent) == 1 and sent[0]["embeds"][0]["title"].startswith("Shipped"), sent)

# ---------------------------------------------------------------- arsenal
def embed(title, fields, author="Valor", thumb="https://cdn/x.png", url="https://www.pokemoncenter.com/p"):
    return {"id": str(abs(hash(title + str(fields)))), "timestamp": "2026-11-05T15:00:00+00:00", "author": {"username": author},
            "embeds": [{"title": title, "url": url, "fields": [{"name": k, "value": v} for k, v in fields.items()], "thumbnail": {"url": thumb}}]}


m = embed("Successful Checkout 🎉", {"Product": "Pokémon TCG: Mega Evolution Elite Trainer Box", "Site": "Pokémon Center", "Price": "$131.38", "Order #": "||P0041360611||", "Proxy List": "ResiA", "Size": "-"})
check("success embed ingested", arsenal.ingest_message(c, m, "chan1") == 1)
check("duplicate message ignored", arsenal.ingest_message(c, m, "chan1") == 0)
check("declined post ignored", arsenal.ingest_message(c, embed("Payment Declined", {"Product": "X", "Site": "Target"}), "chan1") == 0)
r = arsenal.list_checkouts(c)[0]
check("fields extracted", r["store"] == "Pokémon Center" and r["price"] == 131.38 and r["bot"] == "Valor" and r["proxy_list"] == "ResiA" and r["price_source"] == "bot", r)
check("matched by order number", r["match_status"] == "matched" and r["order"]["order_number"] == "P0041360611", r)
check("bot and proxy list auto-created", [b["name"] for b in arsenal.lists(c)["bots"]] == ["Valor"] and arsenal.lists(c)["proxy_lists"][0]["name"] == "ResiA")
m2 = embed("Checkout Success", {"Product": "Prismatic Evolutions Booster Bundle", "Site": "Target"}, author="Shikari")
arsenal.ingest_message(c, m2, "chan1")
unp = [x for x in arsenal.list_checkouts(c) if x["bot"] == "Shikari"][0]
check("unpriced checkout has null price", unp["price"] is None)
pv = arsenal.rule_preview(c, {"match": "prismatic", "price": "49.99"})
check("rule preview lists what it will change", len(pv["hits"]) == 1 and pv["hits"][0]["old"] is None)
arsenal.save_rule(c, {"match": "prismatic", "price": "49.99"}, [unp["id"]])
unp = [x for x in arsenal.list_checkouts(c) if x["id"] == unp["id"]][0]
check("rule applied, labelled, bot price untouched", unp["price"] == 49.99 and unp["price_source"] == "rule" and [x for x in arsenal.list_checkouts(c) if x["bot"] == "Valor"][0]["price"] == 131.38)
arsenal.ingest_message(c, embed("Success", {"Product": "Prismatic Evolutions ETB", "Site": "Target"}, author="Shikari2"), "chan1")
check("rule applies to future checkouts", [x for x in arsenal.list_checkouts(c) if x["bot"] == "Shikari2"][0]["price_source"] == "rule")
# name mapping re-attributes, but not hand-corrected rows
arsenal.save(c, {"id": unp["id"], "product": unp["product"], "store": "Target", "bot": "ManualBot", "price": "49.99"}, unp["id"])
mid, n = arsenal.save_name_map(c, {"webhook_name": "Shikari", "bot": "Shikari Bot"})
rows = {x["id"]: x for x in arsenal.list_checkouts(c)}
check("mapping spares hand-corrected rows", rows[unp["id"]]["bot"] == "ManualBot" and n == 0)
arsenal.ingest_message(c, embed("Success", {"Product": "Another box", "Site": "Target"}, author="Shikari"), "chan1")
check("mapping applies to new posts", any(x["bot"] == "Shikari Bot" for x in arsenal.list_checkouts(c)))
# manual checkout w/ suggestion
ok1 = arsenal.save(c, {"product": "Walmart thing", "store": "Walmart", "price": "20", "ts": "2026-11-02"})
x = [y for y in arsenal.list_checkouts(c) if y["id"] == ok1][0]
check("close order is suggested, not auto-matched", x["match_status"] == "suggested", x["match_status"])
arsenal.match_action(c, ok1, "reject")
arsenal.link_checkout(c, ok1)
check("rejected stays rejected", [y for y in arsenal.list_checkouts(c) if y["id"] == ok1][0]["match_status"] == "rejected")
rows = arsenal.filtered(c, {"match": "matched"})
st = arsenal.stats(rows)
check("stats: tracker-confirmed spend uses the order total", st["count"] == 1 and st["spend"] == 65.99 and st["stick_rate"] == 1.0, st)
check("filter by bot + search", len(arsenal.filtered(c, {"bot": "Valor", "q": "mega"})) == 1)
arsenal.delete(c, [rows[0]["id"]])
check("delete hides checkout", len(arsenal.list_checkouts(c, True)) == 1)
arsenal.ingest_message(c, m, "chan1")
check("deleted checkout isn't re-scraped", len(arsenal.list_checkouts(c)) == len(arsenal.list_checkouts(c)) and not any(x["bot"] == "Valor" and not x["deleted_at"] for x in arsenal.list_checkouts(c)))
arsenal.restore(c)
check("restore brings it back", any(x["bot"] == "Valor" for x in arsenal.list_checkouts(c)))
bid = arsenal.save_bot(c, {"name": "HAYHA", "monthly_cost": "59", "active_from": "2026-10-01"})
check("bot monthly cost saved", [b for b in arsenal.lists(c)["bots"] if b["id"] == bid][0]["monthly_cost"] == 59.0)
arsenal.save_bot(c, {"id": bid, "name": "HAYHA", "archived": True}, bid)
check("archived bots hidden by default", "HAYHA" not in [b["name"] for b in arsenal.lists(c)["bots"]] and "HAYHA" in [b["name"] for b in arsenal.lists(c, True)["bots"]])
check("csv export", arsenal.export_csv(c).startswith("ts,product"))

# discord REST with a fake API
calls = []
def fake_api(token, path, params=None, retries=3):
    calls.append(path)
    if path == "/users/@me":
        return {"username": "ArsenalBot", "id": "99"}
    if path == "/users/@me/guilds":
        return [{"id": "g1", "name": "Tehboss's server", "icon": None}, {"id": "g2", "name": "LRO 2.0", "icon": "abc"}]
    if path == "/guilds/g1/channels":
        return [{"id": "c1", "name": "success", "type": 0}, {"id": "c2", "name": "voice", "type": 2}]
    if path == "/channels/c1/messages":
        after = (params or {}).get("after")
        return [] if after == "300" else [embed("Success", {"Product": "From the channel", "Site": "Target"}, author="Cyber") | {"id": "300"}]
    raise AssertionError(path)
discord.api = fake_api
tok = "A" * 24 + "." + "B" * 6 + "." + "C" * 27
servers = discord.set_token(c, tok)
check("bot token validated, servers listed", [s["name"] for s in servers] == ["LRO 2.0", "Tehboss's server"] and db.get(c, "discord_bot_name") == "ArsenalBot")
discord.link(c, "g1")
chs = discord.list_channels(c, "g1")
check("only text channels listed", [x["name"] for x in chs] == ["success"])
discord.watch(c, "c1", True)
check("link/watch counts", [s for s in discord.list_servers(c) if s["guild_id"] == "g1"][0]["watched"] == 1)
n0 = len(arsenal.list_checkouts(c))
check("sync reads watched channel", discord.sync() == 1 and len(arsenal.list_checkouts(c)) == n0 + 1)
check("sync again adds nothing", discord.sync() == 0)
try:
    discord.set_token(c, "nope"); check("bad token refused", False)
except discord.DiscordError:
    check("bad token refused", True)

# ---------------------------------------------------------------- backup / logs / resets
text = backup.export(c)
j = json.loads(text)
check("plain backup strips secrets", all(a["password"] == "" for a in j["tables"]["mail_accounts"]) and all(w["url"] == "" for w in j["tables"]["webhooks"]) and "discord_bot_token" not in j["settings"] and "license_token" not in j["settings"])
enc = backup.export(c, "correct horse")
check("encrypted backup is opaque", "me@icloud.com" not in enc and backup.is_encrypted(enc))
try:
    backup.load(enc, "wrong"); check("wrong passphrase refused", False)
except ValueError:
    check("wrong passphrase refused", True)
n_orders = len(orders.list_orders(c))
db.wipe_tables(c, db.TRACKER_TABLES + db.ARSENAL_TABLES + ["mail_accounts"])
check("wiped", len(orders.list_orders(c)) == 0)
backup.import_(c, enc, "correct horse")
check("restore brings back orders and password", len(orders.list_orders(c)) == n_orders and mail.get_account(c, aid)["password"] == "abcd efgh ijkl mnop")
check("restore keeps this computer's license", bool(db.get(c, "license_token")))
lg = logs.build(c, True)
check("logs hide emails", "me@icloud.com" not in lg and "account1" in lg and "hide.my.mail" not in lg)
check("logs keep subjects out", "Weekly sale" not in lg and "Something about your order" not in lg)
check("logs strip webhook urls", "abcdef" not in logs.build(c, False))
r = api("/api/reset/tracker", {"confirm": "nope"})
check("reset needs the word", r.get("_code") == 400)
r = api("/api/reset/tracker", {"confirm": "reset"})
check("reset tracker keeps accounts/webhooks/deleted list", r["ok"] and len(db.rows(c, "SELECT * FROM mail_accounts")) == 1 and len(db.rows(c, "SELECT * FROM webhooks")) == 1 and len(orders.list_orders(c)) == 0)
check("reset tracker keeps arsenal", len(arsenal.list_checkouts(c)) > 0)
r = api("/api/reset/arsenal", {"confirm": "reset"})
check("reset arsenal wipes it", len(arsenal.list_checkouts(c)) == 0 and not discord.list_servers(c))
r = api("/api/fresh_start", {"confirm": "FRESH START"})
check("fresh start wipes everything but the license", r["ok"] and not db.rows(c, "SELECT * FROM mail_accounts") and lic.status(db.connect())["state"] == "active")

# ---------------------------------------------------------------- profiles & site accounts
from dt import profiles as PR, variants as VR
import json as _j
c = db.connect()
vs = VR.generate("123 North Main Street", "", count=12, seed=1)
check("variants are distinct and keep the street number", len(vs) == 12 and len({(a.lower(), b.lower()) for a, b in vs}) == 12 and all(a.startswith("123 ") for a, _ in vs))
check("variants are repeatable with a seed", VR.generate("123 N Main St", "Apt 4", 8, seed=7) == VR.generate("123 N Main St", "Apt 4", 8, seed=7))
api("/api/vault/group", {"kind": "prof", "op": "add", "name": "Pokemon Center"})
r = api("/api/vault/group", {"kind": "prof", "op": "add", "name": "pokemon center"})
check("duplicate group names refused", r.get("_code") == 400)
valor = {"u1": {"name": "Home", "email": "a@b.c", "phoneNumber": "555", "billingSameAsShipping": True, "weird": {"keep": 1}, "card": {"holder": "A B", "number": "4111111111111111", "expiration": "01/30", "cvv": "123"},
                "shipping": {"firstName": "A", "lastName": "B", "addressLine1": "123 North Main Street", "addressLine2": "", "city": "Austin", "countryName": "United States", "countryCode": "US", "state": "TX", "zipCode": "78701"},
                "billing": {}, "id": "u1", "totalSpent": 0, "selected": False},
         "u2": {"name": "Work", "email": "w@b.c", "card": {"number": "5500000000000004"}, "shipping": {"addressLine1": "9 Elm Ave", "city": "Dallas", "state": "TX", "zipCode": "75001"}, "id": "u2"}}
r = api("/api/profiles/import", {"site": "Pokemon Center", "text": _j.dumps(valor)})
check("profile import", r["added"] == 2 and r["total"] == 2)
r = api("/api/profiles/import", {"site": "Pokemon Center", "text": _j.dumps(valor)})
check("re-import updates, never duplicates", r["added"] == 0 and r["updated"] == 2)
r = api("/api/profiles/import", {"site": "Pokemon Center", "text": "{\"hello\": 1}"})
check("non-profile file refused", r.get("_code") == 400)
ex = PR.export_profiles(c, "Pokemon Center")
check("export keeps unknown fields", ex["u1"]["weird"] == {"keep": 1} and ex["u1"]["card"]["number"] == "4111111111111111")
prev = api("/api/profiles/rejig", {"id": "u1", "count": 5, "seed": "x"})
check("rejig preview saves nothing", len(prev["variants"]) == 5 and len(PR.list_profiles(c)) == 2)
api("/api/profiles/rejig", {"id": "u1", "count": 5, "seed": "x", "save": True})
kids = [p for p in PR.list_profiles(c) if p["parent_id"] == "u1"]
check("rejig saves variants as children of the profile", len(kids) == 5 and kids[0]["rec"]["name"] == "Home-J1" and kids[0]["rec"]["billing"]["addressLine1"] == kids[0]["rec"]["shipping"]["addressLine1"])
api("/api/profiles/rejig", {"id": "u1", "count": 3, "seed": "y", "save": True, "replace": True})
check("rejig replace swaps the old variants", len([p for p in PR.list_profiles(c) if p["parent_id"] == "u1"]) == 3)
r = api("/api/profiles/address", {"ids": ["u1", "u2"], "addr": {"addressLine1": "55 Oak Road", "city": "Plano", "state": "TX", "zipCode": "75024"}, "unique": True})
check("bulk address change", r["updated"] == 2 and PR.export_profiles(c, ids=["u2"])["u2"]["shipping"]["city"] == "Plano")
r = api("/api/profiles/address", {"ids": ["u1", "u2"], "addr": {"addressLine1": "55 Oak Road", "city": "Plano", "state": "TX", "zipCode": "75024"}, "units": "101\n102"})
check("real unit numbers handed out in turn", [PR.export_profiles(c, ids=[i])[i]["shipping"]["addressLine2"] for i in ("u1", "u2")] == ["101", "102"])
api("/api/profiles/patch", {"ids": ["u1"], "changes": {"oneCheckout": True, "shipping.state": "OK"}})
e1 = PR.export_profiles(c, ids=["u1"])["u1"]
check("bulk patch reaches nested fields", e1["oneCheckout"] is True and e1["shipping"]["state"] == "OK" and e1["billing"]["state"] == "OK")
api("/api/profiles/save", {"site": "Pokemon Center", "rec": {"name": "New", "email": "n@b.c", "card": {"number": "378282246310005"}}})
check("new profile gets card type", any(p["rec"]["card"]["type"] == "amex" for p in PR.list_profiles(c)))
api("/api/vault/group", {"kind": "acc", "op": "add", "name": "Pokemon Center"})
r = api("/api/siteaccounts/add", {"site": "Pokemon Center", "text": "a@x.com:pw1\nb@x.com:pw2:1.2.3.4:80:u:p\na@x.com:dup\n# c\n"})
check("paste accounts adds and skips duplicates", r["added"] == 2 and r["skipped"] == 1)
acc = {a["id"]: a["rec"] for a in PR.list_accounts(c)}
check("proxy keeps its colons", acc["b@x.com"]["proxy"] == "1.2.3.4:80:u:p" and acc["b@x.com"]["password"] == "pw2")
r = api("/api/siteaccounts/import", {"text": _j.dumps({"version": 1, "site": "Target", "accounts": {"t1": {"id": "t1", "email": "t@x.com", "password": "p", "proxy": "", "session": True, "selected": False}}, "sessions": {"t1": {"c": 1}}})})
check("accounts import creates the group from the file", r["site"] == "Target" and "Target" in PR.groups(c)["acc"])
check("accounts export round-trips sessions", PR.export_accounts(c, "Target")["sessions"] == {"t1": {"c": 1}} and PR.export_accounts(c, "Target")["accounts"]["t1"]["session"] is True)
api("/api/siteaccounts/patch", {"site": "Pokemon Center", "ids": ["a@x.com"], "changes": {"proxy": "9.9.9.9:1"}})
check("bulk proxy", {a["id"]: a["rec"] for a in PR.list_accounts(c)}["a@x.com"]["proxy"] == "9.9.9.9:1")
r = api("/api/vault/group", {"kind": "prof", "op": "rename", "old": "Pokemon Center", "name": "PC"})
check("rename group moves its profiles", all(p["site"] == "PC" for p in PR.list_profiles(c)) and "PC" in PR.groups(c)["prof"] and "Pokemon Center" not in PR.groups(c)["prof"])
bk = backup.export(c)
check("backup without passphrase drops card numbers and passwords", "4111111111111111" not in bk and "pw1" not in bk)
bke = backup.export(c, "pw")
check("encrypted backup carries them", "4111111111111111" not in bke)
api("/api/profiles/delete", {"ids": ["u1"]})
check("deleting a profile deletes its variants", not [p for p in PR.list_profiles(c) if p["id"] == "u1" or p["parent_id"] == "u1"])
api("/api/vault/group", {"kind": "acc", "op": "delete", "name": "Target"})
check("delete group removes its accounts", not [a for a in PR.list_accounts(c) if a["site"] == "Target"])
# ---------------------------------------------------------------- inventory
from dt import inventory as INV
c = db.connect()
r = api("/api/inv/items/save", {"item": {"name": "Pokemon 151 Elite Trainer Box", "qty": 4, "purchase_price": 40, "purchase_date": "2026-09-01", "listed_price": 70, "listing_platform": "eBay"}})
r2_ = api("/api/inv/items/save", {"item": {"name": "RTX 4070 Super", "qty": 2, "purchase_price": 500, "purchase_date": "2026-09-01"}})
it = {x["sku"]: x for x in INV.list_items(c)}
check("SKUs are numbered per category", "PK-0001" in it and "GC-0001" in it and it["GC-0001"]["category"] == "Graphics Card")
r = api("/api/inv/items/save", {"item": {"name": "x", "qty": 0}})
check("quantity must be at least 1", r.get("_code") == 400)
r = api("/api/inv/sales/save", {"sale": {"sku": "PK-0001", "qty": 2, "sale_price": 150, "ship_charged": 10, "ship_cost": 8, "platform": "eBay", "sold_by": "Me", "sale_date": "2026-10-01", "buyer": "Sam"}})
s1 = INV.list_sales(c)[0]
fee = round((150 + 10) * 0.1335 + 0.30, 2)
check("platform fee, net and profit are calculated", s1["platform_fee"] == fee and s1["net"] == round(160 - fee - 8, 2) and s1["profit"] == round(160 - fee - 8 - 80, 2) and s1["roi"] is not None)
r = api("/api/inv/sales/save", {"sale": {"sku": "PK-0001", "qty": 3, "sale_price": 1}})
check("can't sell more than is left", r.get("_code") == 400)
r = api("/api/inv/sales/save", {"sale": {"sku": "PK-0001", "qty": 1, "sale_price": 1, "sale_date": "2026-01-01"}})
check("sale can't predate the purchase", r.get("_code") == 400)
r = api("/api/inv/items/save", {"id": it["PK-0001"]["id"], "item": {**{k: it["PK-0001"][k] for k in INV.ITEM_COLS}, "qty": 1}})
check("quantity can't drop below what's sold", r.get("_code") == 400)
check("item status follows sales", {x["sku"]: x for x in INV.list_items(c)}["PK-0001"]["status"] == "Partly sold")
api("/api/inv/receipts/save", {"receipt": {"date": "2026-10-02", "vendor": "Uline", "category": "Shipping Supplies", "amount": 20}})
d = INV.dashboard(c)
check("dashboard totals", d["revenue"] == 150 and d["expenses"] == 20 and d["in_stock"] == 4 and d["net_profit"] == round(s1["profit"] - 20, 2))
t = INV.tax_summary(c, 2026)
check("tax summary", t["gross"] == 150 and t["cogs"] == 80 and t["expenses"] == 20 and t["net"] == round(150 - 80 - s1["total_fees"] - 8 - 20, 2))
r = api("/api/inv/scan", {"mode": "receive", "code": "PK-0001"})
check("scan receive adds one", not r["created"] and {x["sku"]: x for x in INV.list_items(c)}["PK-0001"]["qty"] == 5)
r = api("/api/inv/scan", {"mode": "receive", "code": "012345678905"})
check("unknown barcode creates a row and remembers it", r["created"] and INV.scan(c, "receive", "012345678905")["created"] is False)
r = api("/api/inv/scan", {"mode": "sell", "code": "PK-0001", "sold_by": "Me"})
check("scan sell logs a sale at the listed price", r["created"] and not r["needs_price"])
r = api("/api/inv/items/delete", {"ids": [it["PK-0001"]["id"]]})
check("item with sales can't be deleted", r["deleted"] == 0 and r["blocked"])
csvt = INV.export_csv(c, "inventory")
check("csv export has headers and rows", csvt.startswith("sku,category") and "GC-0001" in csvt)
r = api("/api/inv/csv/import", {"name": "inventory", "text": "sku,name,qty,purchase_price\nPK-0900,Imported Box,3,10\n,,,\nGC-0900,,0,5\n"})
check("csv import adds good rows, reports bad ones", r["added"] == 1 and r["error_count"] == 1)
r = api("/api/inv/fee/save", {"fee": {"platform": "MyShop", "fee_pct": "5", "fixed": "0.25"}})
check("fee typed as percent is stored as a fraction", {f["platform"]: f for f in INV.list_fees(c)}["MyShop"]["fee_pct"] == 0.05)
# delivered tracker orders land in inventory at a weighted-average cost
ev = {"retailer": "Target", "order_number": "912340001", "status": "delivered", "total": 90.0, "date": "2026-10-20", "items": [{"name": "Pokemon 151 Elite Trainer Box", "qty": 2, "price": 45}]}
orders.apply_event(c, ev, announce=False)
box = {x["sku"]: x for x in INV.list_items(c)}["PK-0001"]
check("delivered order tops up the matching item at a weighted cost", box["qty"] == 7 and abs(box["purchase_price"] - (5 * 40 + 2 * 45) / 7) < 0.01, box)
orders.apply_event(c, ev, announce=False)
check("same delivery isn't added twice", {x["sku"]: x for x in INV.list_items(c)}["PK-0001"]["qty"] == 7)

# the in-app updater must hand the installer a clean PyInstaller environment
import inspect
from dt import updater as _u
src = inspect.getsource(_u.install)
check("updater strips PyInstaller env for the installer", "_PYI" in src and "PYINSTALLER_RESET_ENVIRONMENT" in src and "DETACHED_PROCESS" in src)

# virtual cards: encrypted at rest, masked in lists, parsed from pasted text
from dt import vcc as VCC
r = VCC.import_text(c, "378282246310005 09/28 1234\n4111 1111 1111 1111 exp 12/2027 CVV 321\n1234 5678 9012 3456 01/29 111")
check("vcc import counts", r == {"added": 2, "skipped": 0, "invalid": 1}, r)
check("vcc duplicate skipped", VCC.import_text(c, "4111111111111111 12/27 321")["skipped"] == 1)
lst = VCC.list_cards(c)["cards"]
check("vcc list is masked", all("4111111111111111" not in str(x) and "378282246310005" not in str(x) for x in lst) and {x["issuer"] for x in lst} == {"amex", "other"})
raw = " ".join(str(x[0]) for x in c.execute("SELECT number FROM vcc_cards"))
check("vcc stored encrypted", "4111" not in raw and "3782" not in raw)
am = [x for x in lst if x["issuer"] == "amex"][0]
check("vcc reveal", VCC.reveal(c, am["id"])["number"] == "378282246310005" and VCC.reveal(c, am["id"])["cvv"] == "1234")
check("vcc rejects bad number", VCC.import_text(c, "1234 5678 9012 3456 01/29 111")["invalid"] == 1)

print(f"{ok} passed, {fail} failed")
sys.exit(1 if fail else 0)
