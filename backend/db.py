"""
SQLite data layer for the GH₵ Portfolio tracker.

Every table (except price_snapshots, which is shared market data) is scoped
by telegram_id so two users on the same server never see each other's data.
"""
import sqlite3
import os
from contextlib import contextmanager
from datetime import datetime, timezone

DB_PATH = os.environ.get("DB_PATH", os.path.join(os.path.dirname(__file__), "portfolio.db"))


def _connect():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


@contextmanager
def get_db():
    conn = _connect()
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_db() as conn:
        conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS users (
                telegram_id   INTEGER PRIMARY KEY,
                username      TEXT,
                first_name    TEXT,
                created_at    TEXT NOT NULL
            );

            CREATE TABLE IF NOT EXISTS transactions (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                telegram_id   INTEGER NOT NULL,
                symbol        TEXT NOT NULL,
                side          TEXT NOT NULL CHECK (side IN ('buy', 'sell')),
                shares        REAL NOT NULL CHECK (shares > 0),
                price         REAL NOT NULL CHECK (price >= 0),
                trade_date    TEXT NOT NULL,
                created_at    TEXT NOT NULL,
                FOREIGN KEY (telegram_id) REFERENCES users(telegram_id)
            );
            CREATE INDEX IF NOT EXISTS idx_tx_user ON transactions(telegram_id);
            CREATE INDEX IF NOT EXISTS idx_tx_symbol ON transactions(telegram_id, symbol);

            CREATE TABLE IF NOT EXISTS price_snapshots (
                symbol        TEXT NOT NULL,
                snap_date     TEXT NOT NULL,
                price         REAL NOT NULL,
                PRIMARY KEY (symbol, snap_date)
            );

            CREATE TABLE IF NOT EXISTS current_prices (
                symbol        TEXT PRIMARY KEY,
                price         REAL NOT NULL,
                change        REAL NOT NULL DEFAULT 0,
                volume        INTEGER NOT NULL DEFAULT 0,
                updated_at    TEXT NOT NULL
            );
            """
        )
        _migrate_snapshots(conn)
        _migrate_users(conn)
        _migrate_symbol_aliases(conn)


SYMBOL_ALIASES = {
    "MTN": "MTNGH",
    "SCB-PREF": "SCBPREF",
    "SCB_PREF": "SCBPREF",
    "DAS": "DASPHARMA",
    "ECL": "EGL",
}


def normalize_symbol(symbol: str) -> str:
    if not symbol:
        return symbol
    sym = symbol.strip().upper()
    return SYMBOL_ALIASES.get(sym, sym)


def _migrate_symbol_aliases(conn):
    for alias, canonical in SYMBOL_ALIASES.items():
        conn.execute("UPDATE transactions SET symbol = ? WHERE symbol = ?", (canonical, alias))



def _migrate_users(conn):
    cols = {row[1] for row in conn.execute("PRAGMA table_info(users)").fetchall()}
    if "web_username" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN web_username TEXT")
        conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_web_username ON users(web_username)")
    if "password_hash" not in cols:
        conn.execute("ALTER TABLE users ADD COLUMN password_hash TEXT")


def _migrate_snapshots(conn):
    cols = {row[1] for row in conn.execute("PRAGMA table_info(price_snapshots)").fetchall()}
    if "change" not in cols:
        conn.execute("ALTER TABLE price_snapshots ADD COLUMN change REAL DEFAULT 0")
    if "volume" not in cols:
        conn.execute("ALTER TABLE price_snapshots ADD COLUMN volume INTEGER DEFAULT 0")


def _migrate_current_prices(conn):
    conn.execute("""
        CREATE TABLE IF NOT EXISTS current_prices (
            symbol        TEXT PRIMARY KEY,
            price         REAL NOT NULL,
            change        REAL NOT NULL DEFAULT 0,
            volume        INTEGER NOT NULL DEFAULT 0,
            updated_at    TEXT NOT NULL
        )
    """)


def now_iso():
    return datetime.now(timezone.utc).isoformat()


def today_str():
    return datetime.now(timezone.utc).date().isoformat()


# ---------- users ----------

def upsert_user(telegram_id: int, username: str | None, first_name: str | None):
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO users (telegram_id, username, first_name, created_at)
            VALUES (?, ?, ?, ?)
            ON CONFLICT(telegram_id) DO UPDATE SET
                username = excluded.username,
                first_name = excluded.first_name
            """,
            (telegram_id, username, first_name, now_iso()),
        )


def get_user(telegram_id: int):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE telegram_id = ?", (telegram_id,)
        ).fetchone()
        return dict(row) if row else None


def get_user_by_username(username: str):
    with get_db() as conn:
        row = conn.execute(
            "SELECT * FROM users WHERE web_username = ?", (username.lower(),)
        ).fetchone()
        return dict(row) if row else None


def create_web_user(username: str, password_hash: str) -> int:
    with get_db() as conn:
        row = conn.execute("SELECT MIN(telegram_id) FROM users").fetchone()
        min_id = row[0] if row[0] is not None else 0
        new_id = min(min_id - 1, -1)
        conn.execute(
            """
            INSERT INTO users (telegram_id, username, first_name, web_username, password_hash, created_at)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (new_id, username, username, username.lower(), password_hash, now_iso()),
        )
        return new_id


# ---------- transactions ----------

def add_transaction(telegram_id: int, symbol: str, side: str, shares: float,
                     price: float, trade_date: str | None = None):
    symbol = normalize_symbol(symbol)
    if side not in ("buy", "sell"):
        raise ValueError("side must be 'buy' or 'sell'")
    if shares <= 0 or price < 0:
        raise ValueError("shares must be > 0 and price must be >= 0")

    if side == "sell":
        held = shares_held(telegram_id, symbol)
        if shares > held + 1e-9:
            raise ValueError(f"cannot sell {shares} shares of {symbol}; only {held} held")

    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO transactions (telegram_id, symbol, side, shares, price, trade_date, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (telegram_id, symbol, side, shares, price, trade_date or today_str(), now_iso()),
        )


def get_transactions(telegram_id: int, symbol: str | None = None):
    with get_db() as conn:
        if symbol:
            rows = conn.execute(
                """SELECT * FROM transactions WHERE telegram_id = ? AND symbol = ?
                   ORDER BY trade_date ASC, id ASC""",
                (telegram_id, normalize_symbol(symbol)),
            ).fetchall()
        else:
            rows = conn.execute(
                """SELECT * FROM transactions WHERE telegram_id = ?
                   ORDER BY trade_date ASC, id ASC""",
                (telegram_id,),
            ).fetchall()
        return [dict(r) for r in rows]


def delete_transaction(telegram_id: int, tx_id: int) -> bool:
    with get_db() as conn:
        cur = conn.execute(
            "DELETE FROM transactions WHERE id = ? AND telegram_id = ?",
            (tx_id, telegram_id),
        )
        return cur.rowcount > 0


def shares_held(telegram_id: int, symbol: str) -> float:
    txs = get_transactions(telegram_id, symbol)
    total = 0.0
    for t in txs:
        total += t["shares"] if t["side"] == "buy" else -t["shares"]
    return round(total, 6)


def held_symbols(telegram_id: int) -> list[str]:
    """Symbols currently held with a non-zero position, earliest-trade-first."""
    txs = get_transactions(telegram_id)
    seen_order = []
    running = {}
    for t in txs:
        sym = t["symbol"]
        if sym not in running:
            running[sym] = 0.0
            seen_order.append(sym)
        running[sym] += t["shares"] if t["side"] == "buy" else -t["shares"]
    return [s for s in seen_order if round(running[s], 6) > 0]


# ---------- price snapshots ----------

def save_snapshot(symbol: str, price: float, snap_date: str | None = None,
                  change: float = 0.0, volume: int = 0):
    with get_db() as conn:
        conn.execute(
            """
            INSERT INTO price_snapshots (symbol, snap_date, price, change, volume)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(symbol, snap_date) DO UPDATE SET
                price = excluded.price, change = excluded.change, volume = excluded.volume
            """,
            (symbol.upper(), snap_date or today_str(), price, change, volume),
        )


def get_snapshots(symbol: str):
    with get_db() as conn:
        rows = conn.execute(
            "SELECT snap_date, price FROM price_snapshots WHERE symbol = ? ORDER BY snap_date ASC",
            (symbol.upper(),),
        ).fetchall()
        return [dict(r) for r in rows]


def latest_snapshot_price(symbol: str) -> float | None:
    with get_db() as conn:
        row = conn.execute(
            "SELECT price FROM price_snapshots WHERE symbol = ? ORDER BY snap_date DESC LIMIT 1",
            (symbol.upper(),),
        ).fetchone()
        return row["price"] if row else None


# ---------- current prices (poller cache) ----------

def save_current_price(symbol: str, price: float, change: float = 0.0, volume: int = 0):
    with get_db() as conn:
        _migrate_current_prices(conn)
        conn.execute(
            """
            INSERT INTO current_prices (symbol, price, change, volume, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                price = excluded.price,
                change = excluded.change,
                volume = excluded.volume,
                updated_at = excluded.updated_at
            """,
            (symbol.upper(), price, change, volume, now_iso()),
        )


def save_current_prices_bulk(prices: dict[str, dict]):
    """Upsert many prices in one transaction."""
    if not prices:
        return
    with get_db() as conn:
        _migrate_current_prices(conn)
        rows = [
            (sym.upper(), info["price"], info.get("change", 0), info.get("volume", 0), now_iso())
            for sym, info in prices.items()
        ]
        conn.executemany(
            """
            INSERT INTO current_prices (symbol, price, change, volume, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(symbol) DO UPDATE SET
                price = excluded.price,
                change = excluded.change,
                volume = excluded.volume,
                updated_at = excluded.updated_at
            """,
            rows,
        )


def get_current_prices() -> dict[str, dict]:
    with get_db() as conn:
        _migrate_current_prices(conn)
        rows = conn.execute("SELECT symbol, price, change, volume FROM current_prices").fetchall()
        result = {}
        for row in rows:
            result[row["symbol"]] = {
                "price": row["price"],
                "change": row["change"],
                "volume": row["volume"],
            }
        return result
