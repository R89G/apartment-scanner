import sqlite3
import logging
from datetime import datetime
from pathlib import Path

from models.listing import Listing

logger = logging.getLogger(__name__)

_conn: sqlite3.Connection | None = None


def init_db(path: str) -> None:
    global _conn
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    _conn = sqlite3.connect(path, check_same_thread=False)
    _conn.execute("""
        CREATE TABLE IF NOT EXISTS seen_listings (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            url TEXT,
            composite_key TEXT,
            inserted_at TEXT NOT NULL
        )
    """)
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_url ON seen_listings(url)")
    _conn.execute("CREATE INDEX IF NOT EXISTS idx_composite ON seen_listings(composite_key)")
    _conn.commit()
    logger.debug("SQLite DB initialised at %s", path)


def _composite_key(listing: Listing) -> str:
    parts = [
        (listing.street or "").lower().strip(),
        str(listing.price_nis or ""),
        str(listing.floor or ""),
        str(listing.rooms or ""),
    ]
    return "|".join(parts)


def is_seen(listing: Listing) -> bool:
    if _conn is None:
        raise RuntimeError("DB not initialised — call init_db() first")
    if listing.url:
        row = _conn.execute(
            "SELECT 1 FROM seen_listings WHERE url = ? LIMIT 1", (listing.url,)
        ).fetchone()
        if row:
            return True
    key = _composite_key(listing)
    if key.replace("|", "").strip():
        row = _conn.execute(
            "SELECT 1 FROM seen_listings WHERE composite_key = ? LIMIT 1", (key,)
        ).fetchone()
        if row:
            return True
    return False


def mark_seen(listing: Listing) -> None:
    if _conn is None:
        raise RuntimeError("DB not initialised — call init_db() first")
    _conn.execute(
        "INSERT INTO seen_listings (url, composite_key, inserted_at) VALUES (?, ?, ?)",
        (listing.url or None, _composite_key(listing), datetime.utcnow().isoformat()),
    )
    _conn.commit()
