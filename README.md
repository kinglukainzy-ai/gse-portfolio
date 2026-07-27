# GH₵ Portfolio

Tracks your IC Wealth (GSE) stock buys/sells and shows profit/loss and a
progress-over-time graph. Built for two people (you + a friend) sharing one
server — Telegram login just keeps your two portfolios from mixing; it's
not the product, the P&L and the graph are.

## How it works

- You log every buy/sell yourself (web form or `/buy` `/sell` in the bot).
  There's no API into IC Wealth itself (it's KYC-gated), so this is the only
  way to get your real trade history in.
- The backend reconstructs your position (shares held, weighted-average
  cost) from that log, and marks it to market using the free public GSE
  price API (`dev.kwayisi.org`).
- That API has **no historical prices** — only live/current. So the
  "progress" graph works like this:
  - Before you start running the tracker: a straight line from your
    purchase price to today's price (2 points — it's a placeholder, not
    real history).
  - Going forward: a systemd timer runs once a day, snapshots that day's
    price for everything anyone holds, and the graph fills in with real
    points from then on.
- One combined portfolio-value graph by default, with a toggle to split it
  into one line per stock.

No sector chart, no watchlist, no ticker tape — just holdings + this graph,
per your last call on scope.

## Project layout

```
gse-portfolio/
├── backend/            FastAPI app (this is what Caddy proxies to)
│   ├── main.py          routes
│   ├── auth.py          Telegram login-widget verification + session cookies
│   ├── db.py             SQLite access
│   ├── portfolio.py      P&L math, price fetching, history construction
│   ├── snapshot_job.py    run once/day to record prices (see systemd timer)
│   ├── requirements.txt
│   └── static/           index.html / app.js / styles.css (the dashboard)
├── bot/                Telegram bot (optional convenience layer, same DB)
│   ├── main.py
│   ├── commands.py
│   └── requirements.txt
├── deploy/             Caddyfile + systemd units
└── .env.example
```

## Local test run (no real Telegram bot needed)

```bash
cd backend
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

export SECRET_KEY=$(python3 -c "import secrets; print(secrets.token_hex(32))")
export BOT_TOKEN=dummy         # only needed for signature verification
export BOT_USERNAME=dummy
export ALLOWED_IDS=111111111
export COOKIE_SECURE=false     # only for local http, not production

uvicorn main:app --reload
```
Then hit `http://127.0.0.1:8000` — the login widget needs a real bot to
actually complete a login, but `/api/config`, `/api/holdings` etc. will
respond once you have a valid session cookie.

**Before you trust this fully:** the live price feed
(`https://dev.kwayisi.org/apis/gse/live`) could not be reached from the
sandbox this was built in — the proxy there blocks that domain, so all
testing above ran with price fetches unavailable (the dashboard correctly
degrades: it shows "prices unavailable" instead of pretending a price of
GH₵0). Run this from your actual VM once deployed:
```bash
curl -s https://dev.kwayisi.org/apis/gse/live | head -c 300
```
If that returns JSON like `[{"name":"MTNGH","price":...}, ...]`, the core
feature is real end-to-end. If it times out or 403s, the live-price/P&L
flow needs a different data source — worth checking before you rely on it
for real money decisions.

## Deploying on your Oracle VM

1. **Create the bot**: message `@BotFather` on Telegram, `/newbot`, note the
   token. Also set the domain for the Login Widget:
   `/setdomain` → your VM's domain (must match what's in the Caddyfile).
2. **Get your Telegram numeric IDs**: message `@userinfobot`, note yours and
   your friend's.
3. **Copy the project** to the VM, e.g. `/opt/gse-portfolio/`.
4. **Fill in `.env`** (copy from `.env.example`):
   - `SECRET_KEY` — generate with
     `python3 -c "import secrets; print(secrets.token_hex(32))"`.
     The backend refuses to start without a real one — this is what makes
     session cookies unforgeable.
   - `BOT_TOKEN`, `BOT_USERNAME` — from BotFather.
   - `ALLOWED_IDS` — your and your friend's Telegram numeric IDs.
   - `COOKIE_SECURE=true` (Caddy serves HTTPS).
5. **Set up each venv**:
   ```bash
   cd /opt/gse-portfolio/backend && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   cd /opt/gse-portfolio/bot && python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
   ```
6. **Caddy**: edit `deploy/Caddyfile` with your real domain, copy to
   `/etc/caddy/Caddyfile`, `systemctl reload caddy`. Make sure port 80/443
   on the Oracle Cloud security list are open (this trips people up on OCI
   specifically — the VM firewall *and* the cloud security list both need
   the rule).
7. **systemd**: copy the three `.service` files and the `.timer` file from
   `deploy/` into `/etc/systemd/system/`, then:
   ```bash
   sudo systemctl daemon-reload
   sudo systemctl enable --now gse-backend@youruser.service
   sudo systemctl enable --now gse-bot@youruser.service
   sudo systemctl enable --now gse-snapshot.timer
   ```
8. **First trades**: log in on the web dashboard (or DM the bot `/start`),
   then log your real buys with the trade-log modal or `/buy SYMBOL SHARES
   PRICE`. The progress graph starts as a 2-point straight line and fills
   in daily from there.

## Known limitations (worth knowing, not hidden)

- **No historical price data.** The free GSE API is live-only — this is a
  structural limit of the data source, not something more engineering
  fixes. The straight-line-then-real-history approach is the workaround.
- **Logout doesn't revoke the session token itself**, only the browser
  cookie — sessions are stateless signed tokens (no server-side session
  store), so a captured token would still verify until it expires (30
  days) or the person's ID is removed from `ALLOWED_IDS`. Fine for a
  2-person app on a server you control; wouldn't be for anything higher
  stakes.
- **No rate limiting** on the public endpoints (`/api/config`). Low risk
  for a personal app, but worth knowing if this ever gets a wider domain.
- The upstream price API is a single hobbyist-run box with no SLA — the
  "prices unavailable" state in the UI exists specifically because this can
  and does happen.
