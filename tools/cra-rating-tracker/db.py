"""SQLite storage for watchlist companies and their rating actions."""

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent / "ratings.db"
WATCHLIST_SEED = Path(__file__).parent / "watchlist.json"

SCHEMA = """
CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    aliases TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS rating_actions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    agency TEXT NOT NULL,
    instrument TEXT,
    amount_text TEXT,
    amount_crore REAL,
    rating TEXT,
    outlook TEXT,
    action_type TEXT,
    action_date TEXT,
    source_url TEXT,
    raw_text TEXT,
    fetched_at TEXT NOT NULL,
    UNIQUE(company_id, agency, source_url)
);
"""


@contextmanager
def get_conn():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


def init_db():
    with get_conn() as conn:
        conn.executescript(SCHEMA)
        seed_watchlist_if_empty(conn)


def seed_watchlist_if_empty(conn):
    """On first run, load watchlist.json so the dashboard isn't empty."""
    count = conn.execute("SELECT COUNT(*) FROM companies").fetchone()[0]
    if count > 0 or not WATCHLIST_SEED.exists():
        return
    try:
        entries = json.loads(WATCHLIST_SEED.read_text())
    except (json.JSONDecodeError, OSError):
        return
    for entry in entries:
        name = entry.get("name", "").strip()
        if not name:
            continue
        aliases = ", ".join(entry.get("aliases", []))
        add_company(conn, name, aliases)


def list_companies(conn):
    return conn.execute("SELECT * FROM companies ORDER BY name").fetchall()


def get_company(conn, company_id):
    return conn.execute("SELECT * FROM companies WHERE id = ?", (company_id,)).fetchone()


def add_company(conn, name, aliases=""):
    conn.execute(
        "INSERT OR IGNORE INTO companies (name, aliases) VALUES (?, ?)",
        (name.strip(), aliases.strip()),
    )


def delete_company(conn, company_id):
    conn.execute("DELETE FROM companies WHERE id = ?", (company_id,))


def upsert_rating_action(conn, action: dict):
    """Insert a rating action, ignoring exact duplicates (same company+agency+source_url)."""
    conn.execute(
        """
        INSERT OR IGNORE INTO rating_actions
            (company_id, agency, instrument, amount_text, amount_crore, rating,
             outlook, action_type, action_date, source_url, raw_text, fetched_at)
        VALUES (:company_id, :agency, :instrument, :amount_text, :amount_crore, :rating,
                :outlook, :action_type, :action_date, :source_url, :raw_text, :fetched_at)
        """,
        action,
    )


def history_for_company(conn, company_id):
    return conn.execute(
        """
        SELECT * FROM rating_actions
        WHERE company_id = ?
        ORDER BY (action_date IS NULL), action_date DESC, fetched_at DESC
        """,
        (company_id,),
    ).fetchall()


def latest_per_agency(conn, company_id):
    """Most recent rating action per agency for a company, for the dashboard summary."""
    rows = history_for_company(conn, company_id)
    latest = {}
    for row in rows:
        if row["agency"] not in latest:
            latest[row["agency"]] = row
    return latest
