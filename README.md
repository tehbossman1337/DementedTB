# Demented Toolbox

A Windows desktop app that watches your inboxes for retailer order emails (Order Tracker) and scrapes your bots' success posts from Discord (Arsenal), with license-key sign-in.

```
app/             the desktop app (Python + a local web UI in an Edge WebView2 window)
license-server/  the license-key server you host (Python, one SQLite file)
tests/           self-test (backend + license round trip) and a Playwright UI test
installer.iss    Inno Setup installer script
.github/         builds the installer on every push and publishes it as a release
```

## Features

**Order Tracker** — Tracking (stats, 14-day activity, by-retailer, filters, sortable/column-pickable table, order detail with history, add/edit/merge/move/delete) · Needs attention (emails that look like orders but can't be read) · Email accounts (any IMAP provider, single or bulk add, live watching, Backfill, `.eml` import, "your other addresses" for forwards) · Discord webhooks (choose events per webhook).

**Arsenal** — Checkouts (stats, search/filters, tracker match: matched / suggested / rejected, success picture, add by hand) · Servers & channels (your own Discord bot token; link servers, watch channels, sync / backfill / rescan) · Bots & proxies (monthly costs, active-from dates, archive, name mappings) · Price rules (preview before applying, "From your price rule" label).

**Settings** — updates, Discord status (Rich Presence), support logs (email addresses hidden), backup/import (optional passphrase encryption), this device, delivery updates (17TRACK), deleted orders, exceptions, reset tracker / Arsenal data, fresh start.

## License keys

Keys look like `DT-AB3CD-EF4GH-JK5MN-PQ6RS`. They are checked by **your** license server:

1. The app sends the key and a computer ID to the server.
2. The server checks it (valid, not revoked, not expired, not already active on another computer) and returns a **token signed with a private key that only the server has**.
3. The app verifies the signature with the matching public key. Edit the token or make your own and it fails.
4. The token is tied to that computer, expires if the key does, and must be renewed online every ≤72 hours (the app does this in the background). Revoke a key and the app signs itself out the next time it checks (within ~30 minutes while online; hard limit 72 hours offline).
5. One key = one computer at a time by default (`--devices 2` allows more). Moving to another computer asks for confirmation and signs the old one out.

### Run the license server

Locally, to try it:

```bash
cd license-server
pip install -r requirements.txt
ADMIN_TOKEN="pick-a-long-random-password" python server.py     # http://localhost:8787/admin
python admin.py create --name "Demented" --days 30              # prints a key (shown once)
```

Hosting it for real (the app needs a URL that stays up):

* **Render / Railway / Fly.io** — deploy the `license-server` folder using its `Dockerfile`. Add a **persistent disk/volume mounted at `/data`** (the signing key and key database live there — if it is lost every key stops working and the app must re-fetch the public key) and set the environment variable `ADMIN_TOKEN`. Use the https URL you are given.
* **Your own VPS** — `python server.py` under systemd behind Caddy/nginx with HTTPS; keep `DATA_DIR` on disk and back it up.

Open `https://YOUR-URL/admin`, enter the admin token, and create / revoke / extend keys or free a computer. `python admin.py …` does the same on the server's command line.

### Point the app at your server

In your GitHub repository: **Settings → Secrets and variables → Actions → Variables**:

| Variable | Value |
|---|---|
| `LICENSE_URL` | `https://YOUR-URL` (required) |
| `LICENSE_PUBKEY` | optional, the "Public key" shown at the top of `/admin`. If set, the key is built into the app and a fake server can't impersonate yours. If not set, the app fetches and remembers it the first time a key is activated. |

The next push builds an installer that already knows your server. (Users can also change the server on the activation screen.)

### Honest limits

This stops casual sharing and hand-edited tokens, and gives you revocation, expiry and one-computer-at-a-time. Any software that runs on the customer's machine can in theory be patched by a determined reverse engineer; the only complete protection is keeping the valuable part on your server.

## Development

```bash
pip install cryptography
python tests/selftest.py            # backend + license round trip
python tests/dev_stack.py           # demo stack; prints a license key and the app URL
python app/main.py --browser        # run the real app in your browser (data in ~/.demented-toolbox)
```

Build locally on Windows: `python -m PyInstaller --noconfirm --windowed --onedir --name DementedToolbox --icon app/app.ico --paths app --add-data "app/web;web" --collect-all webview app/main.py`, then Inno Setup on `installer.iss`.

## Notes

* Mail is only ever read (`BODY.PEEK`); nothing is deleted or marked read. Passwords stay in a local SQLite file in `%APPDATA%\DementedToolbox`.
* "Live" is a fast check of each inbox every ~20 seconds, not a held-open IMAP IDLE connection.
* Outlook/Hotmail personal accounts usually reject password sign-in; "Add Outlook" only works where an app password is still allowed.
* Discord scraping uses a bot **you** create and invite to your own server; nothing is posted.

## Running without licensing (default until you set up a server)
If a build has no license server address, the app runs open: no lock screen, nothing to activate. Licensing switches on
automatically once the `LICENSE_URL` repo variable is set and the app is rebuilt (or `DT_LICENSE_URL` is set when running from source).
All the license code stays in place.
