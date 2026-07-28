"""
Portfolio math and price fetching.

Everything here is intentionally simple: FIFO isn't used, we use a running
weighted-average cost basis, which is what most retail brokerage statements
(including IC Wealth's) report against.
"""
import os
import httpx
import db

GSE_LIVE_URL = os.environ.get("GSE_LIVE_URL", "https://dev.kwayisi.org/apis/gse/live")
HTTP_TIMEOUT = float(os.environ.get("GSE_HTTP_TIMEOUT", "8"))

GSE_COMPANIES = {
    "AADS": "AADS",
    "ACCESS": "Access Bank Ghana",
    "ADB": "Agricultural Development Bank",
    "AGA": "AngloGold Ashanti",
    "ALLGH": "Atlantic Lithium",
    "ASG": "Asante Gold",
    "BOPP": "Benso Oil Palm Plantation",
    "CAL": "CalBank",
    "CLYD": "Clydestone Ghana",
    "CMLT": "Camelot Ghana",
    "CPC": "Cocoa Processing Company",
    "DASPHARMA": "Dannex Ayrton Starwin",
    "DIGICUT": "Digicut Production",
    "EGH": "Ecobank Ghana",
    "EGL": "Enterprise Group",
    "ETI": "Ecobank Transnational",
    "FAB": "First Atlantic Bank",
    "FML": "Fan Milk",
    "GCB": "GCB Bank",
    "GGBL": "Guinness Ghana Breweries",
    "GLD": "NewGold ETF",
    "GOIL": "Ghana Oil Company",
    "HORDS": "Hords",
    "IIL": "Intravenous Infusions",
    "KASA": "Kasapreko",
    "MAC": "Mega African Capital",
    "MMH": "Mechanical Lloyd",
    "MTNGH": "MTN Ghana",
    "RBGH": "Republic Bank Ghana",
    "SAMBA": "Samba Foods",
    "SCB": "Standard Chartered Bank",
    "SCBPREF": "Standard Chartered (Pref)",
    "SIC": "SIC Insurance",
    "SOGEGH": "Societe Generale Ghana",
    "TBL": "Trust Bank Gambia",
    "TLW": "Tullow Oil",
    "TOTAL": "TotalEnergies Ghana",
    "UNIL": "Unilever Ghana",
    "ZEN": "ZEN Petroleum",
}


class PriceFetchError(Exception):
    pass


async def fetch_live_prices() -> dict[str, dict]:
    """
    Hits the public GSE live-price API.
    Returns {SYMBOL: {"price": float, "change": float, "volume": int}}.
    """
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        try:
            resp = await client.get(GSE_LIVE_URL)
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise PriceFetchError(f"GSE live price API unreachable: {e}") from e

    try:
        data = resp.json()
    except ValueError as e:
        raise PriceFetchError(f"GSE live price API returned non-JSON: {e}") from e

    prices = {}
    for row in data if isinstance(data, list) else []:
        symbol = row.get("name") or row.get("symbol")
        price = row.get("price")
        if symbol and price is not None:
            try:
                prices[str(symbol).upper()] = {
                    "price": float(price),
                    "change": float(row.get("change", 0)),
                    "volume": int(row.get("volume", 0)),
                }
            except (TypeError, ValueError):
                continue
    if not prices:
        raise PriceFetchError("GSE live price API returned no usable rows")
    return prices


GSE_EQUITIES_URL = os.environ.get(
    "GSE_EQUITIES_URL", "https://dev.kwayisi.org/apis/gse/equities"
)


async def fetch_stock_detail(symbol: str) -> dict | None:
    """Fetch fundamentals for a single symbol from /equities/{symbol}."""
    symbol = symbol.upper()
    async with httpx.AsyncClient(timeout=HTTP_TIMEOUT) as client:
        try:
            resp = await client.get(f"{GSE_EQUITIES_URL}/{symbol}")
            if resp.status_code == 404:
                return None
            resp.raise_for_status()
        except httpx.HTTPError as e:
            raise PriceFetchError(f"GSE equities API unreachable: {e}") from e

    try:
        data = resp.json()
    except ValueError as e:
        raise PriceFetchError(f"GSE equities API returned non-JSON: {e}") from e

    company = data.get("company") or {}
    return {
        "symbol": symbol,
        "price": data.get("price"),
        "market_cap": data.get("capital"),
        "eps": data.get("eps"),
        "dps": data.get("dps"),
        "shares_outstanding": data.get("shares"),
        "company_name": company.get("name"),
        "sector": company.get("sector"),
        "industry": company.get("industry"),
    }


async def get_price_with_fallback(symbol: str, live_cache: dict[str, dict] | None = None) -> dict:
    """
    Returns {"price": float|None, "source": str, "change": float, "volume": int}.
    Tries the live cache/API first, falls back to the last daily snapshot.
    """
    symbol = db.normalize_symbol(symbol)
    if live_cache is not None and symbol in live_cache:
        entry = live_cache[symbol]
        return {"price": entry["price"], "source": "live",
                "change": entry["change"], "volume": entry["volume"]}

    try:
        prices = await fetch_live_prices()
        if symbol in prices:
            entry = prices[symbol]
            return {"price": entry["price"], "source": "live",
                    "change": entry["change"], "volume": entry["volume"]}
    except PriceFetchError:
        pass

    snap = db.latest_snapshot_price(symbol)
    if snap is not None:
        return {"price": snap, "source": "snapshot", "change": 0.0, "volume": 0}

    return {"price": None, "source": "none", "change": 0.0, "volume": 0}


def compute_position(transactions: list[dict]) -> dict:
    """
    Weighted-average-cost running position from a list of transactions
    (already sorted oldest -> newest for one symbol).

    Returns: shares_held, avg_cost, cost_basis, realized_pl
    """
    shares_held = 0.0
    avg_cost = 0.0
    realized_pl = 0.0

    for t in transactions:
        if t["side"] == "buy":
            new_shares = shares_held + t["shares"]
            avg_cost = (
                (avg_cost * shares_held + t["price"] * t["shares"]) / new_shares
                if new_shares > 0 else 0.0
            )
            shares_held = new_shares
        else:  # sell
            realized_pl += (t["price"] - avg_cost) * t["shares"]
            shares_held -= t["shares"]
            if shares_held <= 1e-9:
                shares_held = 0.0
                avg_cost = 0.0

    return {
        "shares_held": round(shares_held, 6),
        "avg_cost": round(avg_cost, 4),
        "cost_basis": round(shares_held * avg_cost, 4),
        "realized_pl": round(realized_pl, 4),
    }


async def get_holdings(telegram_id: int) -> dict:
    """Full holdings table + totals for a user, marked to market."""
    symbols = db.held_symbols(telegram_id)
    holdings = []
    total_cost_basis = 0.0
    total_market_value = 0.0
    total_realized_pl = 0.0
    any_price_stale = False
    any_price_missing = False

    live_cache = None
    if symbols:
        try:
            live_cache = db.get_current_prices()
        except Exception:
            live_cache = {}

    for sym in symbols:
        txs = db.get_transactions(telegram_id, sym)
        pos = compute_position(txs)
        pinfo = await get_price_with_fallback(sym, live_cache)
        price = pinfo["price"]
        source = pinfo["source"]
        market_value = round(pos["shares_held"] * price, 4) if price is not None else None
        unrealized_pl = (
            round(market_value - pos["cost_basis"], 4) if market_value is not None else None
        )
        unrealized_pct = (
            round((unrealized_pl / pos["cost_basis"]) * 100, 2)
            if unrealized_pl is not None and pos["cost_basis"] > 0 else None
        )
        if source != "live":
            any_price_stale = True
        if price is None:
            any_price_missing = True

        holdings.append({
            "symbol": sym,
            "shares_held": pos["shares_held"],
            "avg_cost": pos["avg_cost"],
            "cost_basis": pos["cost_basis"],
            "current_price": price,
            "price_source": source,
            "change": pinfo["change"],
            "volume": pinfo["volume"],
            "market_value": market_value,
            "unrealized_pl": unrealized_pl,
            "unrealized_pl_pct": unrealized_pct,
            "realized_pl": pos["realized_pl"],
        })
        total_cost_basis += pos["cost_basis"]
        total_realized_pl += pos["realized_pl"]
        if market_value is not None:
            total_market_value += market_value

    if any_price_missing:
        total_market_value_out = None
        total_unrealized_pl = None
        total_unrealized_pct = None
    else:
        total_market_value_out = round(total_market_value, 4)
        total_unrealized_pl = round(total_market_value - total_cost_basis, 4)
        total_unrealized_pct = (
            round((total_unrealized_pl / total_cost_basis) * 100, 2) if total_cost_basis > 0 else None
        )

    return {
        "holdings": holdings,
        "totals": {
            "cost_basis": round(total_cost_basis, 4),
            "market_value": total_market_value_out,
            "unrealized_pl": total_unrealized_pl,
            "unrealized_pl_pct": total_unrealized_pct,
            "realized_pl": round(total_realized_pl, 4),
        },
        "any_price_stale": any_price_stale,
        "any_price_missing": any_price_missing,
    }


def _first_purchase(transactions: list[dict]) -> dict | None:
    for t in transactions:
        if t["side"] == "buy":
            return t
    return None


async def get_history(telegram_id: int, symbol: str | None = None) -> dict:
    """
    Builds the 'value since purchase' line(s).

    Design (per spec): no historical price API exists, so between the
    purchase date and the day snapshots started, we only have two real data
    points -- purchase price and today's price -- connected by a straight
    line. From the day the snapshot job starts running, real daily points
    get appended and the line stops being a straight guess.

    symbol=None -> combined portfolio value over time (sum across all held
    symbols, valued at that day's stored/live price using shares held as of
    that day).
    symbol=SYM  -> single-stock series.
    """
    symbols = [symbol.upper()] if symbol else db.held_symbols(telegram_id)
    if not symbols:
        return {"series": [], "mode": "single" if symbol else "combined"}

    all_txs = {s: db.get_transactions(telegram_id, s) for s in symbols}
    live_cache = None
    try:
        live_cache = db.get_current_prices()
    except Exception:
        live_cache = {}

    today = db.today_str()
    series_by_symbol = {}

    for sym in symbols:
        txs = all_txs[sym]
        first_buy = _first_purchase(txs)
        if not first_buy:
            continue

        snapshots = db.get_snapshots(sym)  # [{snap_date, price}, ...] ascending
        points = []

        # anchor point: purchase price on purchase date, valued at shares
        # bought at that moment (approximation: first buy's own share count,
        # since that's the only price we have pre-history).
        points.append({
            "date": first_buy["trade_date"],
            "price": first_buy["price"],
        })

        # real collected history (from the daily snapshot job), deduped
        # against the anchor date/price so we don't draw a fake kink.
        for snap in snapshots:
            if snap["snap_date"] <= first_buy["trade_date"]:
                continue
            points.append({"date": snap["snap_date"], "price": snap["price"]})

        # make sure "today" is represented even if the snapshot job hasn't
        # run yet today, using live price (falls back to last snapshot).
        if not points or points[-1]["date"] != today:
            pinfo = await get_price_with_fallback(sym, live_cache)
            if pinfo["price"] is not None:
                points.append({"date": today, "price": pinfo["price"]})

        series_by_symbol[sym] = points

    if symbol:
        sym_upper = symbol.upper()
        pts = series_by_symbol.get(sym_upper, [])
        valued = []
        for p in pts:
            shares_at_date = _shares_as_of(all_txs[sym_upper], p["date"])
            cost = _cost_basis_as_of(all_txs[sym_upper], p["date"])
            valued.append({
                "date": p["date"],
                "value": round(shares_at_date * p["price"], 4),
                "cost_basis": cost,
            })
        return {"series": valued, "mode": "single", "symbol": sym_upper}

    # combined: union of all dates across symbols, each symbol's value at
    # that date computed from (shares held as of that date) x (best known
    # price at/<= that date), then summed.
    all_dates = sorted({p["date"] for pts in series_by_symbol.values() for p in pts})
    combined = []
    for d in all_dates:
        total_value = 0.0
        total_cost = 0.0
        for sym, pts in series_by_symbol.items():
            price_at_d = _price_as_of(pts, d)
            if price_at_d is None:
                continue
            shares_at_d = _shares_as_of(all_txs[sym], d)
            total_value += shares_at_d * price_at_d
            total_cost += _cost_basis_as_of(all_txs[sym], d)
        combined.append({
            "date": d,
            "value": round(total_value, 4),
            "cost_basis": round(total_cost, 4),
        })

    per_symbol_valued = {}
    for sym, pts in series_by_symbol.items():
        per_symbol_valued[sym] = [
            {
                "date": p["date"],
                "value": round(_shares_as_of(all_txs[sym], p["date"]) * p["price"], 4),
                "cost_basis": _cost_basis_as_of(all_txs[sym], p["date"]),
            }
            for p in pts
        ]

    return {"series": combined, "per_symbol": per_symbol_valued, "mode": "combined"}


def _shares_as_of(transactions: list[dict], date: str) -> float:
    total = 0.0
    for t in transactions:
        if t["trade_date"] > date:
            break
        total += t["shares"] if t["side"] == "buy" else -t["shares"]
    return round(total, 6)


def _cost_basis_as_of(transactions: list[dict], date: str) -> float:
    """Weighted-average cost basis (shares × avg_cost) at a given date."""
    shares = 0.0
    avg_cost = 0.0
    for t in transactions:
        if t["trade_date"] > date:
            break
        if t["side"] == "buy":
            new_shares = shares + t["shares"]
            avg_cost = (
                (avg_cost * shares + t["price"] * t["shares"]) / new_shares
                if new_shares > 0 else 0.0
            )
            shares = new_shares
        else:
            shares -= t["shares"]
            if shares <= 1e-9:
                shares = 0.0
                avg_cost = 0.0
    return round(shares * avg_cost, 4)


def _price_as_of(points: list[dict], date: str) -> float | None:
    """Most recent known price on or before `date` from a points list."""
    best = None
    for p in points:
        if p["date"] <= date:
            best = p["price"]
        else:
            break
    return best
