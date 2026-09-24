"""SQLite storage for tracked products and their price samples."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_DB = Path.home() / ".pricepulse" / "prices.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS products (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    url TEXT NOT NULL,
    provider TEXT NOT NULL,
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS samples (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    product_id INTEGER NOT NULL REFERENCES products(id) ON DELETE CASCADE,
    price REAL NOT NULL,
    currency TEXT NOT NULL,
    in_stock INTEGER NOT NULL,
    checked_at TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_samples_product ON samples(product_id, checked_at);
"""


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def connect(db_path=None) -> sqlite3.Connection:
    path = Path(db_path) if db_path else DEFAULT_DB
    path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(_SCHEMA)
    return conn


@contextmanager
def _session(db_path=None):
    conn = connect(db_path)
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def add_product(name: str, url: str, provider: str, db_path=None) -> int:
    """Track a new product. Raises ValueError if the name is taken."""
    with _session(db_path) as conn:
        try:
            cur = conn.execute(
                "INSERT INTO products (name, url, provider, created_at)"
                " VALUES (?, ?, ?, ?)",
                (name, url, provider, _now()),
            )
        except sqlite3.IntegrityError as exc:
            raise ValueError(f"product {name!r} is already tracked") from exc
        return cur.lastrowid


def get_product(name: str, db_path=None) -> dict | None:
    with _session(db_path) as conn:
        row = conn.execute(
            "SELECT * FROM products WHERE name = ?", (name,)
        ).fetchone()
        return dict(row) if row else None


def list_products(db_path=None) -> list[dict]:
    with _session(db_path) as conn:
        rows = conn.execute("SELECT * FROM products ORDER BY name").fetchall()
        return [dict(row) for row in rows]


def record_sample(
    product_id: int,
    price: float,
    currency: str = "CAD",
    in_stock: bool = True,
    checked_at: str | None = None,
    db_path=None,
) -> int:
    """Append one price observation for a product."""
    with _session(db_path) as conn:
        cur = conn.execute(
            "INSERT INTO samples (product_id, price, currency, in_stock, checked_at)"
            " VALUES (?, ?, ?, ?, ?)",
            (product_id, float(price), currency, int(in_stock), checked_at or _now()),
        )
        return cur.lastrowid


def history(product_id: int, db_path=None) -> list[dict]:
    """All samples for a product, oldest first."""
    with _session(db_path) as conn:
        rows = conn.execute(
            "SELECT price, currency, in_stock, checked_at FROM samples"
            " WHERE product_id = ? ORDER BY checked_at, id",
            (product_id,),
        ).fetchall()
        return [dict(row) for row in rows]
