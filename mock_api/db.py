import sqlite3
import os

_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
DATA_DIR = os.path.abspath(os.path.join(_THIS_DIR, "..", "data"))
os.makedirs(DATA_DIR, exist_ok=True)
DB_PATH = os.path.join(DATA_DIR, "transactions.db")


def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def init_db():
    conn = get_conn()
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS transactions (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            sender TEXT NOT NULL,
            receiver TEXT NOT NULL,
            amount REAL NOT NULL,
            type TEXT NOT NULL,
            timestamp TEXT NOT NULL,
            is_scam INTEGER NOT NULL DEFAULT 0,
            scheme_id TEXT,
            category TEXT DEFAULT 'p2p',
            city TEXT,
            lat REAL,
            lon REAL
        )
        """
    )
    # Add columns if upgrading an older database
    existing = {r[1] for r in conn.execute("PRAGMA table_info(transactions)")}
    for col, decl in [("category", "TEXT DEFAULT 'p2p'"), ("city", "TEXT"),
                      ("lat", "REAL"), ("lon", "REAL")]:
        if col not in existing:
            conn.execute(f"ALTER TABLE transactions ADD COLUMN {col} {decl}")
    conn.commit()
    conn.close()


_NULL_SENTINELS = {"", "none", "nan", "null", "na"}


def _clean(tx: dict) -> dict:
    """Normalise sentinel strings to real NULLs before they reach SQLite.

    A scheme_id written as the string "None" is not NULL, so downstream
    .notna() checks treat every ordinary row as part of a scam ring. Catch it
    at the boundary rather than defending against it everywhere later.
    """
    tx = dict(tx)
    for field in ("scheme_id", "city", "category"):
        v = tx.get(field)
        if isinstance(v, str) and v.strip().lower() in _NULL_SENTINELS:
            tx[field] = None
    if tx.get("category") is None:
        tx["category"] = "p2p"
    return tx


def insert_transaction(tx: dict):
    tx = _clean(tx)
    conn = get_conn()
    conn.execute(
        """
        INSERT INTO transactions
          (sender, receiver, amount, type, timestamp, is_scam, scheme_id, category, city, lat, lon)
        VALUES
          (:sender, :receiver, :amount, :type, :timestamp, :is_scam, :scheme_id, :category, :city, :lat, :lon)
        """,
        tx,
    )
    conn.commit()
    conn.close()


def insert_many(txs: list):
    """Bulk insert - far faster than one-at-a-time for 13k rows."""
    txs = [_clean(t) for t in txs]
    conn = get_conn()
    conn.executemany(
        """
        INSERT INTO transactions
          (sender, receiver, amount, type, timestamp, is_scam, scheme_id, category, city, lat, lon)
        VALUES
          (:sender, :receiver, :amount, :type, :timestamp, :is_scam, :scheme_id, :category, :city, :lat, :lon)
        """,
        txs,
    )
    conn.commit()
    conn.close()


def fetch_all_transactions():
    conn = get_conn()
    rows = conn.execute("SELECT * FROM transactions ORDER BY timestamp ASC").fetchall()
    conn.close()
    return [dict(r) for r in rows]


def clear_transactions():
    conn = get_conn()
    conn.execute("DELETE FROM transactions")
    conn.commit()
    conn.close()
