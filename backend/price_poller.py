"""
Price poller: fetches live GSE prices every 10 minutes and writes them to
the `current_prices` table so user-facing requests never hit the upstream API.

Sends a Telegram alert if the upstream API fails 3+ times in a row.

Usage: python price_poller.py
"""
import asyncio
import json
import logging
import os
import time

import db
import portfolio
import auth

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("price-poller")

FAILURE_FILE = os.path.join(os.path.dirname(db.DB_PATH), "poller_failures.json")
ALERT_THRESHOLD = 3
MAX_RETRIES = 3
RETRY_BACKOFF_BASE = 2  # seconds


def _read_failures() -> int:
    try:
        with open(FAILURE_FILE) as f:
            return json.load(f).get("consecutive", 0)
    except (FileNotFoundError, json.JSONDecodeError, KeyError):
        return 0


def _write_failures(count: int):
    with open(FAILURE_FILE, "w") as f:
        json.dump({"consecutive": count}, f)


def _record_failure():
    count = _read_failures() + 1
    _write_failures(count)
    if count >= ALERT_THRESHOLD:
        _send_alert(count)


def _clear_failures():
    if os.path.exists(FAILURE_FILE):
        os.remove(FAILURE_FILE)


def _send_alert(count: int):
    token = os.environ.get("BOT_TOKEN", "")
    if not token or not auth.ALLOWED_IDS:
        log.warning("Cannot send alert: BOT_TOKEN or ALLOWED_IDS not set")
        return
    chat_id = next(iter(auth.ALLOWED_IDS))
    text = (
        f"GH₵ Portfolio price poller has failed {count} times in a row. "
        "The upstream price API may be down — live prices are stale."
    )
    try:
        import httpx
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        log.info("Alert sent to Telegram user %s", chat_id)
    except Exception as e:
        log.error("Failed to send Telegram alert: %s", e)


async def main():
    db.init_db()

    prices = None
    last_err = None
    for attempt in range(1, MAX_RETRIES + 1):
        try:
            log.info("Fetching live prices (attempt %d/%d)...", attempt, MAX_RETRIES)
            prices = await portfolio.fetch_live_prices()
            break
        except portfolio.PriceFetchError as e:
            last_err = e
            if attempt < MAX_RETRIES:
                wait = RETRY_BACKOFF_BASE * attempt
                log.warning("Attempt %d failed: %s — retrying in %ds", attempt, e, wait)
                await asyncio.sleep(wait)
            else:
                log.error("All %d attempts failed: %s", MAX_RETRIES, e)

    if prices is None:
        _record_failure()
        return

    _clear_failures()
    saved = 0
    for sym, entry in prices.items():
        db.save_current_price(sym, entry["price"],
                              change=entry["change"], volume=entry["volume"])
        saved += 1

    log.info("Price poller done: %d symbols saved.", saved)


if __name__ == "__main__":
    asyncio.run(main())
