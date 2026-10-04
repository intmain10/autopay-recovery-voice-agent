from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from typing import Optional

from . import config

SCHEMA = """
CREATE TABLE IF NOT EXISTS customers (
    id TEXT PRIMARY KEY,
    data TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending',   -- pending | recovered | promised | plan | escalated | dnc | unresolved
    disposition TEXT,
    recovered_amount REAL NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS calls (
    call_id TEXT PRIMARY KEY,
    customer_id TEXT NOT NULL,
    verified INTEGER NOT NULL DEFAULT 0,
    verify_attempts INTEGER NOT NULL DEFAULT 0,
    status TEXT,
    ended_reason TEXT,
    summary TEXT,
    structured TEXT,
    recording_url TEXT,
    transcript TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    call_id TEXT,
    customer_id TEXT,
    kind TEXT NOT NULL,
    payload TEXT,
    created_at TEXT DEFAULT CURRENT_TIMESTAMP
);
"""


@contextmanager
def connect():
    config.DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(config.DB_PATH)
    conn.row_factory = sqlite3.Row
    try:
        conn.executescript(SCHEMA)
        yield conn
        conn.commit()
    finally:
        conn.close()


def reset_and_seed() -> int:
    customers = json.loads(config.CUSTOMERS_PATH.read_text())
    with connect() as conn:
        conn.executescript("DELETE FROM customers; DELETE FROM calls; DELETE FROM events;")
        for c in customers:
            conn.execute("INSERT INTO customers (id, data) VALUES (?, ?)", (c["id"], json.dumps(c)))
    return len(customers)


def get_customer(customer_id: str) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM customers WHERE id = ?", (customer_id,)).fetchone()
    if not row:
        return None
    c = json.loads(row["data"])
    c.update(status=row["status"], disposition=row["disposition"],
             recovered_amount=row["recovered_amount"])
    return c


def update_customer_data(customer_id: str, **fields) -> None:
    c = get_customer(customer_id)
    data = {k: v for k, v in c.items() if k not in ("status", "disposition", "recovered_amount")}
    data.update(fields)
    with connect() as conn:
        conn.execute("UPDATE customers SET data = ? WHERE id = ?", (json.dumps(data), customer_id))


def set_status(customer_id: str, status: str, disposition: Optional[str] = None,
               recovered_amount: Optional[float] = None) -> None:
    with connect() as conn:
        conn.execute(
            "UPDATE customers SET status = ?, disposition = COALESCE(?, disposition), "
            "recovered_amount = COALESCE(?, recovered_amount) WHERE id = ?",
            (status, disposition, recovered_amount, customer_id))


def list_customers() -> list:
    with connect() as conn:
        ids = [r["id"] for r in conn.execute("SELECT id FROM customers ORDER BY id")]
    return [get_customer(i) for i in ids]


def register_call(call_id: str, customer_id: str) -> None:
    with connect() as conn:
        conn.execute("INSERT OR IGNORE INTO calls (call_id, customer_id) VALUES (?, ?)",
                     (call_id, customer_id))


def get_call(call_id: str) -> Optional[dict]:
    with connect() as conn:
        row = conn.execute("SELECT * FROM calls WHERE call_id = ?", (call_id,)).fetchone()
    return dict(row) if row else None


def update_call(call_id: str, **fields) -> None:
    if not fields:
        return
    cols = ", ".join(f"{k} = ?" for k in fields)
    with connect() as conn:
        conn.execute(f"UPDATE calls SET {cols} WHERE call_id = ?", (*fields.values(), call_id))


def list_calls() -> list:
    with connect() as conn:
        return [dict(r) for r in conn.execute("SELECT * FROM calls ORDER BY created_at DESC")]


def log_event(call_id: Optional[str], customer_id: Optional[str], kind: str, payload: dict) -> None:
    with connect() as conn:
        conn.execute("INSERT INTO events (call_id, customer_id, kind, payload) VALUES (?, ?, ?, ?)",
                     (call_id, customer_id, kind, json.dumps(payload, default=str)))


def list_events(limit: int = 200) -> list:
    with connect() as conn:
        rows = conn.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall()
    return [dict(r) for r in rows]
