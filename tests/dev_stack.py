"""Starts a license server + the app against temporary data, seeds demo data, and prints the license key. For UI tests."""
import json, os, sys, tempfile, threading, time
ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
TMP = tempfile.mkdtemp(prefix="dt-ui-")
os.environ.update(DT_DATA=os.path.join(TMP, "app"), DT_NO_AUTO="1", DT_NO_TOAST="1", DATA_DIR=os.path.join(TMP, "lic"), ADMIN_TOKEN="adm")
os.makedirs(os.environ["DT_DATA"]); os.makedirs(os.environ["DATA_DIR"])
sys.path.insert(0, os.path.join(ROOT, "app")); sys.path.insert(0, os.path.join(ROOT, "license-server"))
import server as LS
from dt import arsenal, db, mail, orders, server as S, notify, inbox
sys.path.insert(0, os.path.join(ROOT, "tests"))
import fake_imap as FI  # a local stand-in for iCloud's mail server
_fs, _fport = FI.start(); FI.patch_login(mail, _fport)
ls = LS.make_server(int(os.environ.get("LPORT", 18787))); threading.Thread(target=ls.serve_forever, daemon=True).start()
lc = LS.db(); KEY = LS.make_license(lc, "Demented", "member", 365); lc.close()
c = db.connect(); db.put(c, "license_url", f"http://127.0.0.1:{ls.server_address[1]}")
if os.environ.get("SEED", "1") == "1":
    ev = lambda r, n, st, d, t, items, acct: orders.apply_event(c, {"retailer": r, "order_number": n, "status": st, "date": d, "total": t, "items": items, "tracking": ""}, account=acct, announce=False)
    for i, (n, acct, t) in enumerate([("P0041360611", "honker.wintry-0n@icloud.com", 131.38), ("P0041359056", "after.innings.07@icloud.com", 131.38), ("P0041353486", "50.blotter.arcana@icloud.com", 131.68)]):
        ev("Pokémon Center", n, "placed", time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400 * (i + 1))), t, [{"name": "Pokémon TCG: Mega Evolution-Delta Reign Pokémon Center Elite Trainer Box", "qty": 1, "price": t}], acct)
    ev("Target", "912345678", "shipped", time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400 * 3)), 54.99, [{"name": "Prismatic Evolutions Booster Bundle", "qty": 1, "price": 54.99}], "me@icloud.com")
    ev("Walmart", "2000123456789", "delivered", time.strftime("%Y-%m-%d", time.localtime(time.time() - 86400 * 6)), 20.0, [{"name": "Charizard Collection", "qty": 1, "price": 20}], "me@icloud.com")
    c.execute("INSERT INTO attention(message_id,account,sender,subject,reason,snippet,guess,created_at) VALUES('a1','me@icloud.com','Pokemon Center <noreply@pokemoncenter.com>','Update about your order','no order number found','We changed something about your parcel','Pokémon Center',?)", (db.now(),)); c.commit()
    mail.save_account(c, {"email": "jaronsonios@icloud.com", "password": "abcd-efgh-ijkl-mnop"})
    mail.LIVE["accounts"][1] = {"live": True, "uidnext": b"2"}
    c.execute("UPDATE mail_accounts SET last_checked=?", (db.now(),)); c.commit()
    arsenal.save_bot(c, {"name": "HAYHA", "monthly_cost": "59"}); arsenal.save_bot(c, {"name": "icebox", "monthly_cost": "75"}); arsenal.save_bot(c, {"name": "valor", "monthly_cost": "50"})
    arsenal.ingest_message(c, {"id": "1", "timestamp": "2026-11-05T15:00:00+00:00", "author": {"username": "valor"}, "embeds": [{"title": "Successful Checkout", "fields": [{"name": "Product", "value": "Pokémon TCG: Mega Evolution Elite Trainer Box"}, {"name": "Site", "value": "Pokémon Center"}, {"name": "Price", "value": "$131.38"}, {"name": "Order #", "value": "P0041360611"}]}]}, "c1")
    arsenal.ingest_message(c, {"id": "2", "timestamp": "2026-11-06T15:00:00+00:00", "author": {"username": "Shikari"}, "embeds": [{"title": "Checkout Success", "fields": [{"name": "Product", "value": "Prismatic Evolutions Booster Bundle"}, {"name": "Site", "value": "Target"}]}]}, "c1")
    notify.notify(c, "shipped", "Shipped: Target", "Prismatic Evolutions Booster Bundle", link="tracking", dedupe="seed1", push=False)
# a local stand-in for iCloud's mail server, so the Inbox page has real mail to show
if os.environ.get("SEED", "1") == "1":
    now = time.time()
    FI.add(FI.make("Pokémon Center <noreply@pokemoncenter.com>", "Your Pokémon Center order P0041360611 has shipped", "Good news! Your order is on its way. Track it with UPS 1Z999AA10123456784.",
                   to="honker.wintry-0n@icloud.com", html='<div style="font-family:Arial;max-width:560px"><h2 style="color:#1d1d24">Your order is on its way</h2><p>Order <b>P0041360611</b> shipped with UPS.</p><img src="https://example.com/banner.png" width="500"><p><a href="https://www.pokemoncenter.com/">Track your package</a></p><script>alert(1)</script></div>', when=now - 600))
    FI.add(FI.make("Target <orders@target.com>", "Thanks for your order! #912345678", "We got your order for Prismatic Evolutions Booster Bundle. Total $54.99.", when=now - 7200), flags=["\\Seen"])
    FI.add(FI.make("Apple <no_reply@email.apple.com>", "Your receipt from Apple", "Receipt for iCloud+ 50GB, $0.99.", when=now - 86400 * 2, attach=("Receipt.pdf", b"%PDF-1.4 demo")), flags=["\\Seen"])
    FI.add(FI.make("Walmart <help@walmart.com>", "Delivered: Charizard Collection", "Your package was delivered to the front door.", to="after.innings.07@icloud.com", when=now - 86400 * 4), flags=["\\Seen", "\\Flagged"])
    while inbox.STATE['checking']:
        time.sleep(0.1)
    inbox.check_all()
    if os.environ.get("INBOX_LIVE") == "1":  # the UI test checks that new mail shows up on its own
        inbox.INTERVAL = 3
        threading.Thread(target=inbox.loop, args=(3,), daemon=True).start()
        threading.Timer(10, lambda: FI.add(FI.make("Best Buy <BestBuyInfo@emailinfo.bestbuy.com>", "Your Best Buy order has been received", "Order BBY01-806123456789 is confirmed."))).start()
srv, port = S.make_server(int(os.environ.get("APORT", 18766)))
print(json.dumps({"key": KEY, "app": f"http://127.0.0.1:{port}", "tmp": TMP}), flush=True)
srv.serve_forever()
