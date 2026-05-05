import json
import sqlite3
from pathlib import Path
from typing import Protocol

from .models import EventResponse, OrderResponse


class OrderStore(Protocol):
    def init_schema(self) -> None: ...
    def put_order(self, order: OrderResponse) -> None: ...
    def get_order(self, external_id: str) -> OrderResponse | None: ...
    def add_event(self, entity_id: str, event_type: str, payload: dict) -> EventResponse: ...


class SqliteOrderStore:
    def __init__(self, database_url: str) -> None:
        self._path = _sqlite_path(database_url)

    def _connect(self) -> sqlite3.Connection:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        conn = sqlite3.connect(self._path)
        conn.row_factory = sqlite3.Row
        return conn

    def init_schema(self) -> None:
        with self._connect() as conn:
            conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS orders (
                    external_id TEXT PRIMARY KEY,
                    client_id TEXT NOT NULL,
                    amount_cop_gross INTEGER NOT NULL,
                    fee_percent REAL NOT NULL,
                    fee_cop REAL NOT NULL,
                    amount_cop_net REAL NOT NULL,
                    payment_status TEXT NOT NULL,
                    conversion_status TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_events_entity_id_created_at
                    ON events(entity_id, created_at);
                """
            )

    def put_order(self, order: OrderResponse) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO orders (
                    external_id, client_id, amount_cop_gross, fee_percent, fee_cop,
                    amount_cop_net, payment_status, conversion_status, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order.external_id,
                    order.client_id,
                    order.amount_cop_gross,
                    order.fee_percent,
                    order.fee_cop,
                    order.amount_cop_net,
                    order.payment_status,
                    order.conversion_status,
                    order.created_at,
                ),
            )

    def get_order(self, external_id: str) -> OrderResponse | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM orders WHERE external_id = ?", (external_id,)).fetchone()
        if row is None:
            return None
        return OrderResponse(**dict(row))

    def add_event(self, entity_id: str, event_type: str, payload: dict) -> EventResponse:
        from datetime import UTC, datetime
        from uuid import uuid4

        event = EventResponse(
            event_id=f"evt-{uuid4().hex[:12]}",
            entity_id=entity_id,
            event_type=event_type,
            payload=payload,
            created_at=datetime.now(UTC).isoformat(),
        )
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO events (event_id, entity_id, event_type, payload_json, created_at)
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    event.event_id,
                    event.entity_id,
                    event.event_type,
                    json.dumps(event.payload),
                    event.created_at,
                ),
            )
        return event


def create_store(database_url: str | None) -> OrderStore:
    store = SqliteOrderStore(database_url or "sqlite:///./data/chaut.db")
    store.init_schema()
    return store


def _sqlite_path(database_url: str) -> Path:
    if database_url.startswith("sqlite:///"):
        return Path(database_url.removeprefix("sqlite:///"))
    raise ValueError("Only sqlite:/// URLs are supported in local test mode")
