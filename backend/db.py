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
            """
        )
        _migrate_snapshots(conn)


def _migrate_snapshots(conn):
    cols = {row[1] for row in conn.execute("PRAGMA table_info(price_snapshots)").fetchall()}
    if "change" not in cols:
        conn.execute("ALTER TABLE price_snapshots ADD COLUMN change REAL DEFAULT 0")
    if "volume" not in cols:
        conn.execute("ALTER TABLE price_snapshots ADD COLUMN volume INTEGER DEFAULT 0")


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


# ---------- transactions ----------

def add_transaction(telegram_id: int, symbol: str, side: str, shares: float,
                     price: float, trade_date: str | None = None):
    symbol = symbol.strip().upper()
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
                (telegram_id, symbol.upper()),
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
