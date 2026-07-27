"""
Standalone Telegram bot runner. Deployed as its own systemd service
(see deploy/gse-bot.service) so it can restart independently of the web
backend.

Usage: python main.py   (needs BOT_TOKEN in the environment / .env)
"""
import os
import sys
import logging

from telegram.ext import ApplicationBuilder, CommandHandler

sys.path.insert(0, os.path.dirname(__file__))
import commands  # noqa: E402

logging.basicConfig(level=logging.INFO)
log = logging.getLogger("gse-bot")


def main():
    token = os.environ.get("BOT_TOKEN")
    if not token:
        raise SystemExit("BOT_TOKEN is not set in the environment")

    app = ApplicationBuilder().token(token).build()
    app.add_handler(CommandHandler("start", commands.start))
    app.add_handler(CommandHandler("buy", commands.buy))
    app.add_handler(CommandHandler("sell", commands.sell))
    app.add_handler(CommandHandler("holdings", commands.holdings))
    app.add_handler(CommandHandler("transactions", commands.transactions))
    app.add_handler(CommandHandler("detail", commands.detail))

    log.info("GH₵ Portfolio bot starting (polling)...")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
