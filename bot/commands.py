"""
Bot command handlers. Chat is an optional convenience layer over the same
database the web dashboard uses -- it is not a separate source of truth,
and it enforces the same ALLOWED_IDS allow-list as the web login.
"""
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

import db  # noqa: E402
import auth  # noqa: E402
import portfolio  # noqa: E402

from telegram import Update
from telegram.ext import ContextTypes


def _check_allowed(update: Update) -> bool:
    return auth.is_allowed(update.effective_user.id)


async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_allowed(update):
        await update.message.reply_text("You're not on the allow-list for this bot.")
        return
    db.upsert_user(update.effective_user.id, update.effective_user.username, update.effective_user.first_name)
    await update.message.reply_text(
        "GH₵ Portfolio bot.\n\n"
        "/buy SYMBOL SHARES PRICE — log a buy\n"
        "/sell SYMBOL SHARES PRICE — log a sell\n"
        "/holdings — see your current positions\n"
        "/transactions — recent trade history\n"
        "/detail SYMBOL — stock fundamentals\n"
    )


def _parse_trade_args(args: list[str]):
    if len(args) != 3:
        raise ValueError("usage: SYMBOL SHARES PRICE  (e.g. MTNGH 100 2.35)")
    symbol, shares_raw, price_raw = args
    try:
        shares = float(shares_raw)
        price = float(price_raw)
    except ValueError:
        raise ValueError("shares and price must be numbers")
    return symbol.upper(), shares, price


async def buy(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_allowed(update):
        await update.message.reply_text("You're not on the allow-list for this bot.")
        return
    try:
        symbol, shares, price = _parse_trade_args(context.args)
        db.add_transaction(update.effective_user.id, symbol, "buy", shares, price)
    except ValueError as e:
        await update.message.reply_text(f"Couldn't log that: {e}")
        return
    await update.message.reply_text(f"Logged: bought {shares} {symbol} @ GH₵{price:.2f}")


async def sell(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_allowed(update):
        await update.message.reply_text("You're not on the allow-list for this bot.")
        return
    try:
        symbol, shares, price = _parse_trade_args(context.args)
        db.add_transaction(update.effective_user.id, symbol, "sell", shares, price)
    except ValueError as e:
        await update.message.reply_text(f"Couldn't log that: {e}")
        return
    await update.message.reply_text(f"Logged: sold {shares} {symbol} @ GH₵{price:.2f}")


async def holdings(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_allowed(update):
        await update.message.reply_text("You're not on the allow-list for this bot.")
        return
    data = await portfolio.get_holdings(update.effective_user.id)
    if not data["holdings"]:
        await update.message.reply_text("No holdings yet. Log a trade with /buy first.")
        return

    lines = []
    for h in data["holdings"]:
        price = f"GH₵{h['current_price']:.2f}" if h["current_price"] is not None else "n/a"
        pl = h["unrealized_pl"]
        pl_str = f"GH₵{pl:+.2f}" if pl is not None else "n/a"
        lines.append(f"{h['symbol']}: {h['shares_held']} sh @ avg GH₵{h['avg_cost']:.2f} | now {price} | P&L {pl_str}")

    t = data["totals"]
    lines.append("")
    lines.append(f"Total: GH₵{t['market_value']:.2f} value, GH₵{t['unrealized_pl']:+.2f} unrealized P&L")
    if data["any_price_stale"]:
        lines.append("(some prices are from the last stored snapshot, not live)")

    await update.message.reply_text("\n".join(lines))


async def transactions(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_allowed(update):
        await update.message.reply_text("You're not on the allow-list for this bot.")
        return
    txs = db.get_transactions(update.effective_user.id)
    if not txs:
        await update.message.reply_text("No transactions yet. Log a trade with /buy first.")
        return

    lines = []
    for t in txs[-10:]:
        lines.append(
            f"{t['trade_date']} {t['side'].upper()} {t['shares']} {t['symbol']} @ GH₵{t['price']:.2f}"
        )
    if len(txs) > 10:
        lines.insert(0, f"(showing last 10 of {len(txs)})\n")
    await update.message.reply_text("\n".join(lines))


async def detail(update: Update, context: ContextTypes.DEFAULT_TYPE):
    if not _check_allowed(update):
        await update.message.reply_text("You're not on the allow-list for this bot.")
        return
    if not context.args:
        await update.message.reply_text("Usage: /detail SYMBOL  (e.g. /detail MTNGH)")
        return
    symbol = context.args[0].upper()
    try:
        d = await portfolio.fetch_stock_detail(symbol)
    except portfolio.PriceFetchError:
        await update.message.reply_text("Couldn't reach the GSE data API right now.")
        return
    if d is None:
        await update.message.reply_text(f"Symbol {symbol} not found.")
        return

    def fmt(val, prefix=""):
        if val is None:
            return "—"
        if isinstance(val, (int, float)):
            return f"{prefix}{val:,.2f}" if isinstance(val, float) else f"{prefix}{val:,}"
        return str(val)

    lines = [
        f"{d['company_name'] or symbol} ({symbol})",
        f"Sector: {d['sector'] or '—'}",
        f"Industry: {d['industry'] or '—'}",
        f"Market cap: GH₵{fmt(d['market_cap'])}",
        f"Shares outstanding: {fmt(d['shares_outstanding'])}",
        f"EPS: {fmt(d['eps'], 'GH₵')}",
        f"DPS: {fmt(d['dps'], 'GH₵')}",
    ]
    await update.message.reply_text("\n".join(lines))
