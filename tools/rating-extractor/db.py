"""SQLite storage for the rating extractor.

One row per (entity, source, instrument, date) in `rating_records`, linked
to the press release it was extracted from. No hard UNIQUE constraint on
that key: if two runs produce a conflicting record for the same key, both
are kept and flagged `ambiguous` rather than one silently overwriting the
other (see `upsert_rating_record`).
"""

import csv
import hashlib
import sqlite3
from contextlib import contextmanager
from pathlib import Path

DB_PATH = Path(__file__).parent / "rating_extractor.db"
ENTITIES_CSV = Path(__file__).parent / "entities.csv"

SCHEMA = """
CREATE TABLE IF NOT EXISTS entities (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE,
    aliases TEXT NOT NULL DEFAULT ''
);

CREATE TABLE IF NOT EXISTS press_releases (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    url TEXT,
    pub_date TEXT,
    fetched_at TEXT NOT NULL,
    storage_path TEXT,
    content_hash TEXT NOT NULL,
    UNIQUE(entity_id, source, content_hash)
);

CREATE TABLE IF NOT EXISTS rating_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    entity_id INTEGER NOT NULL REFERENCES entities(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    instrument TEXT,
    record_date TEXT,
    amount_rs_cr REAL,
    amount_raw_text TEXT,
    rating_current TEXT,
    rating_previous TEXT,
    outlook_current TEXT,
    outlook_previous TEXT,
    action_type TEXT,
    is_confirmed_action INTEGER NOT NULL DEFAULT 0,
    ambiguous INTEGER NOT NULL DEFAULT 0,
    ambiguous_reason TEXT,
    evidence_text TEXT,
    press_release_id INTEGER REFERENCES press_releases(id) ON DELETE CASCADE,
    extracted_at TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_rating_records_key
    ON rating_records(entity_id, source, instrument, record_date);
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
        _seed_entities_if_empty(conn)


def _seed_entities_if_empty(conn):
    count = conn.execute("SELECT COUNT(*) FROM entities").fetchone()[0]
    if count > 0 or not ENTITIES_CSV.exists():
        return
    with open(ENTITIES_CSV, newline="") as f:
        for row in csv.DictReader(f):
            name = (row.get("name") or "").strip()
            if not name:
                continue
            aliases = (row.get("aliases") or "").strip()
            add_entity(conn, name, aliases)


def add_entity(conn, name, aliases=""):
    conn.execute(
        "INSERT OR IGNORE INTO entities (name, aliases) VALUES (?, ?)",
        (name.strip(), aliases.strip()),
    )


def get_entity_by_name(conn, name):
    return conn.execute(
        "SELECT * FROM entities WHERE name = ?", (name.strip(),)
    ).fetchone()


def list_entities(conn):
    return conn.execute("SELECT * FROM entities ORDER BY name").fetchall()


def content_hash(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", errors="ignore")).hexdigest()


def upsert_press_release(conn, entity_id, source, url, pub_date, fetched_at, storage_path, raw_text):
    chash = content_hash(raw_text)
    conn.execute(
        """
        INSERT OR IGNORE INTO press_releases
            (entity_id, source, url, pub_date, fetched_at, storage_path, content_hash)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (entity_id, source, url, pub_date, fetched_at, storage_path, chash),
    )
    row = conn.execute(
        "SELECT id FROM press_releases WHERE entity_id = ? AND source = ? AND content_hash = ?",
        (entity_id, source, chash),
    ).fetchone()
    return row["id"]


def find_rating_record(conn, entity_id, source, instrument, record_date):
    return conn.execute(
        """
        SELECT * FROM rating_records
        WHERE entity_id = ? AND source = ? AND instrument IS ? AND record_date IS ?
        """,
        (entity_id, source, instrument, record_date),
    ).fetchone()


def insert_rating_record(conn, record: dict):
    conn.execute(
        """
        INSERT INTO rating_records
            (entity_id, source, instrument, record_date, amount_rs_cr, amount_raw_text,
             rating_current, rating_previous, outlook_current, outlook_previous,
             action_type, is_confirmed_action, ambiguous, ambiguous_reason,
             evidence_text, press_release_id, extracted_at)
        VALUES
            (:entity_id, :source, :instrument, :record_date, :amount_rs_cr, :amount_raw_text,
             :rating_current, :rating_previous, :outlook_current, :outlook_previous,
             :action_type, :is_confirmed_action, :ambiguous, :ambiguous_reason,
             :evidence_text, :press_release_id, :extracted_at)
        """,
        record,
    )


def upsert_rating_record(conn, record: dict):
    """Insert a rating record for (entity, source, instrument, date).

    If an existing record for that key has different content, BOTH the
    existing and the new record are flagged ambiguous (never silently
    overwritten) so a human resolves which is correct.
    """
    existing = find_rating_record(
        conn, record["entity_id"], record["source"], record["instrument"], record["record_date"]
    )
    if existing is None:
        insert_rating_record(conn, record)
        return "inserted"

    comparable = ("amount_rs_cr", "rating_current", "rating_previous", "action_type")
    conflict = any(existing[field] != record.get(field) for field in comparable)
    if not conflict:
        return "duplicate_skipped"

    conn.execute(
        "UPDATE rating_records SET ambiguous = 1, ambiguous_reason = ? WHERE id = ?",
        ("Conflicts with a later extraction for the same entity/source/instrument/date", existing["id"]),
    )
    record["ambiguous"] = 1
    record["ambiguous_reason"] = (record.get("ambiguous_reason") or "") + \
        " | Conflicts with an earlier stored record for the same key"
    insert_rating_record(conn, record)
    return "conflict_flagged"


def all_rating_records(conn):
    return conn.execute(
        """
        SELECT e.name AS entity_name, r.*, p.url AS press_release_url, p.pub_date AS press_release_date
        FROM rating_records r
        JOIN entities e ON e.id = r.entity_id
        LEFT JOIN press_releases p ON p.id = r.press_release_id
        ORDER BY e.name, r.source, r.instrument, r.record_date
        """
    ).fetchall()
