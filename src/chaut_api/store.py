import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .models import EventResponse, OrderResponse


class OrderStore(Protocol):
    def init_schema(self) -> None: ...
    def put_order(self, order: OrderResponse) -> None: ...
    def get_order(self, external_id: str) -> OrderResponse | None: ...
    def update_payment_request(
        self,
        external_id: str,
        payment_request_id: str,
        payment_url: str,
        payment_status: str,
        payment_currency: str,
        payment_amount: float,
        sell_price_cop_per_usdt: float | None,
    ) -> OrderResponse | None: ...
    def update_payment_status(self, external_id: str, payment_status: str) -> OrderResponse | None: ...
    def add_event(self, entity_id: str, event_type: str, payload: dict) -> EventResponse: ...
    def list_events(self, entity_id: str) -> list[EventResponse]: ...


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
                    fee_asset TEXT NOT NULL DEFAULT 'xaut',
                    fee_cop REAL NOT NULL DEFAULT 0,
                    amount_cop_net REAL NOT NULL,
                    payment_currency TEXT NOT NULL DEFAULT 'cop',
                    payment_amount REAL,
                    sell_price_cop_per_usdt REAL,
                    estimated_rate_cop_per_usdt REAL,
                    estimated_usdt REAL,
                    payment_request_id TEXT,
                    payment_url TEXT,
                    payment_status TEXT NOT NULL,
                    conversion_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
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
            self._ensure_order_columns(conn)

    def _ensure_order_columns(self, conn: sqlite3.Connection) -> None:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(orders)").fetchall()}
        migrations = {
            "fee_asset": "ALTER TABLE orders ADD COLUMN fee_asset TEXT NOT NULL DEFAULT 'xaut'",
            "payment_currency": "ALTER TABLE orders ADD COLUMN payment_currency TEXT NOT NULL DEFAULT 'cop'",
            "payment_amount": "ALTER TABLE orders ADD COLUMN payment_amount REAL",
            "sell_price_cop_per_usdt": "ALTER TABLE orders ADD COLUMN sell_price_cop_per_usdt REAL",
            "estimated_rate_cop_per_usdt": "ALTER TABLE orders ADD COLUMN estimated_rate_cop_per_usdt REAL",
            "estimated_usdt": "ALTER TABLE orders ADD COLUMN estimated_usdt REAL",
            "payment_request_id": "ALTER TABLE orders ADD COLUMN payment_request_id TEXT",
            "payment_url": "ALTER TABLE orders ADD COLUMN payment_url TEXT",
            "updated_at": "ALTER TABLE orders ADD COLUMN updated_at TEXT",
        }
        for column, statement in migrations.items():
            if column not in existing:
                conn.execute(statement)
        conn.execute("UPDATE orders SET updated_at = created_at WHERE updated_at IS NULL")

    def put_order(self, order: OrderResponse) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO orders (
                    external_id, client_id, amount_cop_gross, fee_percent, fee_asset, fee_cop,
                    amount_cop_net, payment_currency, payment_amount, sell_price_cop_per_usdt,
                    estimated_rate_cop_per_usdt, estimated_usdt, payment_request_id, payment_url,
                    payment_status, conversion_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order.external_id,
                    order.client_id,
                    order.amount_cop_gross,
                    order.fee_percent,
                    order.fee_asset,
                    order.fee_cop,
                    order.amount_cop_net,
                    order.payment_currency,
                    order.payment_amount,
                    order.sell_price_cop_per_usdt,
                    order.estimated_rate_cop_per_usdt,
                    order.estimated_usdt,
                    order.payment_request_id,
                    order.payment_url,
                    order.payment_status,
                    order.conversion_status,
                    order.created_at,
                    order.updated_at,
                ),
            )

    def get_order(self, external_id: str) -> OrderResponse | None:
        with self._connect() as conn:
            row = conn.execute("SELECT * FROM orders WHERE external_id = ?", (external_id,)).fetchone()
        if row is None:
            return None
        return OrderResponse(**dict(row))


    def update_payment_request(
        self,
        external_id: str,
        payment_request_id: str,
        payment_url: str,
        payment_status: str,
        payment_currency: str,
        payment_amount: float,
        sell_price_cop_per_usdt: float | None,
    ) -> OrderResponse | None:
        updated_at = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE orders
                SET payment_request_id = ?, payment_url = ?, payment_status = ?,
                    payment_currency = ?, payment_amount = ?, sell_price_cop_per_usdt = ?,
                    updated_at = ?
                WHERE external_id = ?
                """,
                (
                    payment_request_id,
                    payment_url,
                    payment_status,
                    payment_currency,
                    payment_amount,
                    sell_price_cop_per_usdt,
                    updated_at,
                    external_id,
                ),
            )
        return self.get_order(external_id)


    def update_payment_status(self, external_id: str, payment_status: str) -> OrderResponse | None:
        updated_at = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE orders
                SET payment_status = ?, updated_at = ?
                WHERE external_id = ?
                """,
                (payment_status, updated_at, external_id),
            )
        return self.get_order(external_id)

    def add_event(self, entity_id: str, event_type: str, payload: dict) -> EventResponse:
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

    def list_events(self, entity_id: str) -> list[EventResponse]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT event_id, entity_id, event_type, payload_json, created_at
                FROM events
                WHERE entity_id = ?
                ORDER BY created_at ASC
                """,
                (entity_id,),
            ).fetchall()
        return [
            EventResponse(
                event_id=row["event_id"],
                entity_id=row["entity_id"],
                event_type=row["event_type"],
                payload=json.loads(row["payload_json"]),
                created_at=row["created_at"],
            )
            for row in rows
        ]


def create_store(database_url: str | None) -> OrderStore:
    store = SqliteOrderStore(database_url or "sqlite:///./data/chaut.db")
    store.init_schema()
    return store


def _sqlite_path(database_url: str) -> Path:
    if database_url.startswith("sqlite:///"):
        return Path(database_url.removeprefix("sqlite:///"))
    raise ValueError("Only sqlite:/// URLs are supported in local test mode")
