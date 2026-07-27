"""
Daily snapshot job: records today's price for ALL listed GSE symbols so
history accumulates even for stocks nobody holds yet. Sends a Telegram
alert if the upstream API fails 3+ days in a row.

Usage: python snapshot_job.py
"""
import asyncio
import json
import logging
import os
import httpx

import db
import portfolio
import auth

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("snapshot-job")

FAILURE_FILE = os.path.join(os.path.dirname(db.DB_PATH), "snapshot_failures.json")
ALERT_THRESHOLD = 3


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
        f"GH₵ Portfolio snapshot has failed {count} days in a row. "
        "The upstream price API may be down — the progress graph is stale."
    )
    try:
        httpx.post(
            f"https://api.telegram.org/bot{token}/sendMessage",
            json={"chat_id": chat_id, "text": text},
            timeout=10,
        )
        log.info("Alert sent to Telegram user %s", chat_id)
    except httpx.HTTPError as e:
        log.error("Failed to send Telegram alert: %s", e)


async def main():
    db.init_db()

    try:
        prices = await portfolio.fetch_live_prices()
    except portfolio.PriceFetchError as e:
        log.error("Could not fetch live prices, skipping today's snapshot: %s", e)
        _record_failure()
        return

    _clear_failures()
    saved = 0
    for sym, entry in prices.items():
        db.save_snapshot(sym, entry["price"],
                         change=entry["change"], volume=entry["volume"])
        saved += 1

    log.info("Snapshot done: %d symbols saved.", saved)


if __name__ == "__main__":
    asyncio.run(main())
