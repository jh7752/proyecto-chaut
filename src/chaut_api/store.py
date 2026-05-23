import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import Protocol
from uuid import uuid4

from .models import AccountIdentityRequest, AccountIdentityResponse, AccountResponse, CreditProfileResponse, EventResponse, LedgerEntryResponse, OrderResponse, PortfolioResponse


class OrderStore(Protocol):
    def init_schema(self) -> None: ...
    def upsert_account_identity(self, identity: AccountIdentityRequest) -> AccountResponse: ...
    def get_account(self, customer_id: str) -> AccountResponse | None: ...
    def get_account_by_identity(self, provider: str, provider_user_id: str) -> AccountResponse | None: ...
    def list_orders(self, limit: int = 100) -> list[OrderResponse]: ...
    def list_accounts(self, limit: int = 100) -> list[AccountResponse]: ...
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
    def update_conversion_status(self, external_id: str, conversion_status: str) -> OrderResponse | None: ...
    def try_start_conversion_execution(self, external_id: str) -> bool: ...
    def create_ledger_entry(self, order: OrderResponse, fill: dict, payload: dict) -> LedgerEntryResponse: ...
    def get_ledger_entry_for_order(self, external_id: str) -> LedgerEntryResponse | None: ...
    def get_portfolio(self, customer_id: str) -> PortfolioResponse: ...
    def get_credit_profile(self, customer_id: str, collateral_value_cop: float | None = None) -> CreditProfileResponse: ...
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
                    customer_id TEXT,
                    amount_cop_gross INTEGER NOT NULL,
                    fee_percent REAL NOT NULL,
                    fee_asset TEXT NOT NULL DEFAULT 'xaut',
                    fee_cop REAL NOT NULL DEFAULT 0,
                    amount_cop_net REAL NOT NULL,
                    payment_currency TEXT NOT NULL DEFAULT 'cop',
                    payment_amount REAL,
                    sell_price_cop_per_usdt REAL,
                    reference_rate_cop_per_usdt REAL,
                    reference_rate_source TEXT,
                    reference_rate_date TEXT,
                    spread_profit_cop_estimated REAL,
                    estimated_rate_cop_per_usdt REAL,
                    estimated_usdt REAL,
                    payment_request_id TEXT,
                    payment_url TEXT,
                    payment_status TEXT NOT NULL,
                    conversion_status TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS accounts (
                    customer_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    display_name TEXT,
                    phone_number TEXT,
                    email TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS account_identities (
                    provider TEXT NOT NULL,
                    provider_user_id TEXT NOT NULL,
                    customer_id TEXT NOT NULL,
                    chat_id TEXT,
                    username TEXT,
                    display_name TEXT,
                    first_name TEXT,
                    last_name TEXT,
                    phone_number TEXT,
                    email TEXT,
                    metadata_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (provider, provider_user_id),
                    FOREIGN KEY (customer_id) REFERENCES accounts(customer_id)
                );

                CREATE INDEX IF NOT EXISTS idx_account_identities_customer_id
                    ON account_identities(customer_id);

                CREATE TABLE IF NOT EXISTS events (
                    event_id TEXT PRIMARY KEY,
                    entity_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                );

                CREATE INDEX IF NOT EXISTS idx_events_entity_id_created_at
                    ON events(entity_id, created_at);

                CREATE TABLE IF NOT EXISTS ledger_entries (
                    entry_id TEXT PRIMARY KEY,
                    customer_id TEXT NOT NULL,
                    external_id TEXT NOT NULL,
                    entry_type TEXT NOT NULL,
                    asset TEXT NOT NULL,
                    amount REAL NOT NULL,
                    gold_grams REAL NOT NULL,
                    usdt_spent REAL NOT NULL,
                    cop_gross REAL NOT NULL,
                    exchange_order_id TEXT,
                    payload_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    UNIQUE(external_id, entry_type),
                    FOREIGN KEY (customer_id) REFERENCES accounts(customer_id)
                );

                CREATE INDEX IF NOT EXISTS idx_ledger_entries_customer_created_at
                    ON ledger_entries(customer_id, created_at);
                """
            )
            self._ensure_order_columns(conn)

    def _ensure_order_columns(self, conn: sqlite3.Connection) -> None:
        existing = {row["name"] for row in conn.execute("PRAGMA table_info(orders)").fetchall()}
        migrations = {
            "customer_id": "ALTER TABLE orders ADD COLUMN customer_id TEXT",
            "fee_asset": "ALTER TABLE orders ADD COLUMN fee_asset TEXT NOT NULL DEFAULT 'xaut'",
            "payment_currency": "ALTER TABLE orders ADD COLUMN payment_currency TEXT NOT NULL DEFAULT 'cop'",
            "payment_amount": "ALTER TABLE orders ADD COLUMN payment_amount REAL",
            "sell_price_cop_per_usdt": "ALTER TABLE orders ADD COLUMN sell_price_cop_per_usdt REAL",
            "reference_rate_cop_per_usdt": "ALTER TABLE orders ADD COLUMN reference_rate_cop_per_usdt REAL",
            "reference_rate_source": "ALTER TABLE orders ADD COLUMN reference_rate_source TEXT",
            "reference_rate_date": "ALTER TABLE orders ADD COLUMN reference_rate_date TEXT",
            "spread_profit_cop_estimated": "ALTER TABLE orders ADD COLUMN spread_profit_cop_estimated REAL",
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

    def upsert_account_identity(self, identity: AccountIdentityRequest) -> AccountResponse:
        now = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT customer_id FROM account_identities
                WHERE provider = ? AND provider_user_id = ?
                """,
                (identity.provider, identity.provider_user_id),
            ).fetchone()
            customer_id = existing["customer_id"] if existing else f"cus-{uuid4().hex[:12]}"
            if existing is None:
                conn.execute(
                    """
                    INSERT INTO accounts (customer_id, status, display_name, phone_number, email, created_at, updated_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (customer_id, "active", identity.display_name, identity.phone_number, identity.email, now, now),
                )
                created_at = now
            else:
                conn.execute(
                    """
                    UPDATE accounts
                    SET display_name = COALESCE(?, display_name),
                        phone_number = COALESCE(?, phone_number),
                        email = COALESCE(?, email),
                        updated_at = ?
                    WHERE customer_id = ?
                    """,
                    (identity.display_name, identity.phone_number, identity.email, now, customer_id),
                )
                row = conn.execute(
                    """
                    SELECT created_at FROM account_identities
                    WHERE provider = ? AND provider_user_id = ?
                    """,
                    (identity.provider, identity.provider_user_id),
                ).fetchone()
                created_at = row["created_at"] if row else now

            conn.execute(
                """
                INSERT INTO account_identities (
                    provider, provider_user_id, customer_id, chat_id, username, display_name,
                    first_name, last_name, phone_number, email, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(provider, provider_user_id) DO UPDATE SET
                    chat_id = excluded.chat_id,
                    username = excluded.username,
                    display_name = excluded.display_name,
                    first_name = excluded.first_name,
                    last_name = excluded.last_name,
                    phone_number = excluded.phone_number,
                    email = excluded.email,
                    metadata_json = excluded.metadata_json,
                    updated_at = excluded.updated_at
                """,
                (
                    identity.provider,
                    identity.provider_user_id,
                    customer_id,
                    identity.chat_id,
                    identity.username,
                    identity.display_name,
                    identity.first_name,
                    identity.last_name,
                    identity.phone_number,
                    identity.email,
                    json.dumps(identity.metadata),
                    created_at,
                    now,
                ),
            )
        account = self.get_account(customer_id)
        if account is None:
            raise RuntimeError("Account upsert failed")
        return account

    def get_account(self, customer_id: str) -> AccountResponse | None:
        with self._connect() as conn:
            account_row = conn.execute("SELECT * FROM accounts WHERE customer_id = ?", (customer_id,)).fetchone()
            if account_row is None:
                return None
            identity_rows = conn.execute(
                """
                SELECT provider, provider_user_id, chat_id, username, display_name, first_name, last_name,
                       phone_number, email, metadata_json, created_at, updated_at
                FROM account_identities
                WHERE customer_id = ?
                ORDER BY created_at ASC
                """,
                (customer_id,),
            ).fetchall()
        account = dict(account_row)
        account["identities"] = [_identity_from_row(row) for row in identity_rows]
        return AccountResponse(**account)

    def get_account_by_identity(self, provider: str, provider_user_id: str) -> AccountResponse | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT customer_id FROM account_identities
                WHERE provider = ? AND provider_user_id = ?
                """,
                (provider, provider_user_id),
            ).fetchone()
        if row is None:
            return None
        return self.get_account(row["customer_id"])


    def list_accounts(self, limit: int = 100) -> list[AccountResponse]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT customer_id FROM accounts
                ORDER BY created_at DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [account for row in rows if (account := self.get_account(row["customer_id"])) is not None]

    def put_order(self, order: OrderResponse) -> None:
        with self._connect() as conn:
            conn.execute(
                """
                INSERT INTO orders (
                    external_id, client_id, customer_id, amount_cop_gross, fee_percent, fee_asset, fee_cop,
                    amount_cop_net, payment_currency, payment_amount, sell_price_cop_per_usdt,
                    reference_rate_cop_per_usdt, reference_rate_source, reference_rate_date, spread_profit_cop_estimated,
                    estimated_rate_cop_per_usdt, estimated_usdt, payment_request_id, payment_url,
                    payment_status, conversion_status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    order.external_id,
                    order.client_id,
                    order.customer_id,
                    order.amount_cop_gross,
                    order.fee_percent,
                    order.fee_asset,
                    order.fee_cop,
                    order.amount_cop_net,
                    order.payment_currency,
                    order.payment_amount,
                    order.sell_price_cop_per_usdt,
                    order.reference_rate_cop_per_usdt,
                    order.reference_rate_source,
                    order.reference_rate_date,
                    order.spread_profit_cop_estimated,
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


    def list_orders(self, limit: int = 100) -> list[OrderResponse]:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT orders.*, ledger_entries.created_at AS ledger_entry_created_at FROM orders
                LEFT JOIN ledger_entries
                  ON ledger_entries.external_id = orders.external_id
                 AND ledger_entries.entry_type = 'xaut_purchase'
                ORDER BY COALESCE(ledger_entries.created_at, orders.updated_at, orders.created_at) DESC
                LIMIT ?
                """,
                (limit,),
            ).fetchall()
        return [OrderResponse(**dict(row)) for row in rows]

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
        reference_rate_cop_per_usdt: float | None = None,
        reference_rate_source: str | None = None,
        reference_rate_date: str | None = None,
        spread_profit_cop_estimated: float | None = None,
    ) -> OrderResponse | None:
        updated_at = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE orders
                SET payment_request_id = ?, payment_url = ?, payment_status = ?,
                    payment_currency = ?, payment_amount = ?, sell_price_cop_per_usdt = ?,
                    reference_rate_cop_per_usdt = ?, reference_rate_source = ?, reference_rate_date = ?,
                    spread_profit_cop_estimated = ?, updated_at = ?
                WHERE external_id = ?
                """,
                (
                    payment_request_id,
                    payment_url,
                    payment_status,
                    payment_currency,
                    payment_amount,
                    sell_price_cop_per_usdt,
                    reference_rate_cop_per_usdt,
                    reference_rate_source,
                    reference_rate_date,
                    spread_profit_cop_estimated,
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


    def update_conversion_status(self, external_id: str, conversion_status: str) -> OrderResponse | None:
        updated_at = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            conn.execute(
                """
                UPDATE orders
                SET conversion_status = ?, updated_at = ?
                WHERE external_id = ?
                """,
                (conversion_status, updated_at, external_id),
            )
        return self.get_order(external_id)


    def try_start_conversion_execution(self, external_id: str) -> bool:
        updated_at = datetime.now(UTC).isoformat()
        with self._connect() as conn:
            cursor = conn.execute(
                """
                UPDATE orders
                SET conversion_status = 'executing', updated_at = ?
                WHERE external_id = ?
                  AND payment_status = 'confirmed'
                  AND conversion_status NOT IN ('executing', 'submitted', 'settled')
                """,
                (updated_at, external_id),
            )
            return cursor.rowcount == 1


    def create_ledger_entry(self, order: OrderResponse, fill: dict, payload: dict) -> LedgerEntryResponse:
        if not order.customer_id:
            raise ValueError("Order must have customer_id to create ledger entry")
        now = datetime.now(UTC).isoformat()
        allocation = _allocate_client_xaut(order, fill)
        payload = {**payload, "allocation": allocation}
        entry = LedgerEntryResponse(
            entry_id=f"led-{uuid4().hex[:12]}",
            customer_id=order.customer_id,
            external_id=order.external_id,
            entry_type="xaut_purchase",
            asset="xaut",
            amount=allocation["client_xaut_net"],
            gold_grams=allocation["client_gold_grams_net"],
            usdt_spent=float(fill.get("field_cash_amount") or order.payment_amount or 0),
            cop_gross=float(order.amount_cop_gross),
            exchange_order_id=fill.get("order_id"),
            payload=payload,
            created_at=now,
        )
        with self._connect() as conn:
            existing = conn.execute(
                """
                SELECT * FROM ledger_entries
                WHERE external_id = ? AND entry_type = ?
                """,
                (entry.external_id, entry.entry_type),
            ).fetchone()
            if existing is not None:
                return _ledger_entry_from_row(existing)
            conn.execute(
                """
                INSERT INTO ledger_entries (
                    entry_id, customer_id, external_id, entry_type, asset, amount, gold_grams,
                    usdt_spent, cop_gross, exchange_order_id, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    entry.entry_id, entry.customer_id, entry.external_id, entry.entry_type,
                    entry.asset, entry.amount, entry.gold_grams, entry.usdt_spent,
                    entry.cop_gross, entry.exchange_order_id, json.dumps(entry.payload), entry.created_at,
                ),
            )
        return entry

    def get_ledger_entry_for_order(self, external_id: str) -> LedgerEntryResponse | None:
        with self._connect() as conn:
            row = conn.execute(
                """
                SELECT * FROM ledger_entries
                WHERE external_id = ? AND entry_type = 'xaut_purchase'
                """,
                (external_id,),
            ).fetchone()
        return _ledger_entry_from_row(row) if row is not None else None

    def get_portfolio(self, customer_id: str) -> PortfolioResponse:
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT * FROM ledger_entries
                WHERE customer_id = ?
                ORDER BY created_at ASC
                """,
                (customer_id,),
            ).fetchall()
        entries = [_ledger_entry_from_row(row) for row in rows]
        return PortfolioResponse(
            customer_id=customer_id,
            xaut_net=round(sum(entry.amount for entry in entries), 18),
            gold_grams_net=round(sum(entry.gold_grams for entry in entries), 12),
            usdt_spent=round(sum(entry.usdt_spent for entry in entries), 12),
            cop_invested=round(sum(entry.cop_gross for entry in entries), 2),
            entries_count=len(entries),
            entries=entries,
        )

    def get_credit_profile(self, customer_id: str, collateral_value_cop: float | None = None) -> CreditProfileResponse:
        account = self.get_account(customer_id)
        if account is None:
            raise ValueError("Account not found")
        portfolio = self.get_portfolio(customer_id)
        with self._connect() as conn:
            rows = conn.execute(
                """
                SELECT payment_status, conversion_status, amount_cop_gross FROM orders
                WHERE customer_id = ?
                """,
                (customer_id,),
            ).fetchall()
        paid_orders = sum(1 for row in rows if row["payment_status"] == "confirmed")
        expired_orders = sum(1 for row in rows if row["payment_status"] == "expired")
        unpaid_orders = sum(1 for row in rows if row["payment_status"] != "confirmed")
        identities_count = len(account.identities)
        collateral = float(collateral_value_cop if collateral_value_cop is not None else portfolio.estimated_value_cop or portfolio.cop_invested)
        score = 20
        reasons = ["Base inicial por cuenta creada"]
        activity_count = max(portfolio.entries_count, paid_orders)
        if activity_count:
            score += min(activity_count * 8, 24)
            reasons.append(f"{activity_count} pagos confirmados o movimientos settled")
        paid_volume = sum(float(row["amount_cop_gross"] or 0) for row in rows if row["payment_status"] == "confirmed")
        collateral_base = max(portfolio.cop_invested, paid_volume)
        if collateral_base:
            score += min(int(collateral_base // 50000) * 4, 20)
            reasons.append(f"{collateral_base:,.0f} COP confirmados")
        collateral = max(collateral, collateral_base)
        if collateral > 0:
            score += 6
            reasons.append("Saldo o pago confirmado disponible como referencia de garantia")
        if identities_count > 1:
            score += 6
            reasons.append("Multiples identidades vinculadas")
        if expired_orders:
            penalty = min(expired_orders * 5, 20)
            score -= penalty
            reasons.append(f"{expired_orders} ordenes expiradas descuentan {penalty} puntos")
        if unpaid_orders and not paid_orders:
            score -= 8
            reasons.append("Tiene ordenes sin pago confirmado")
        score = max(0, min(100, score))
        rating = "nuevo" if paid_orders == 0 else "A" if score >= 80 else "B" if score >= 60 else "C" if score >= 40 else "D"
        max_ltv = 0.0 if rating == "nuevo" else 0.5 if rating == "A" else 0.4 if rating == "B" else 0.25 if rating == "C" else 0.0
        suggested_limit = int((collateral * max_ltv) // 1000 * 1000)
        return CreditProfileResponse(
            customer_id=customer_id,
            score=score,
            rating=rating,
            suggested_credit_limit_cop=max(suggested_limit, 0),
            max_ltv_percent=max_ltv * 100,
            collateral_value_cop=round(collateral, 2),
            paid_orders=paid_orders,
            unpaid_orders=unpaid_orders,
            expired_orders=expired_orders,
            identities_count=identities_count,
            reasons=reasons,
        )

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


def _allocate_client_xaut(order: OrderResponse, fill: dict) -> dict:
    total_xaut = float(fill["xaut_net"])
    total_grams = float(fill["gold_grams_net"])
    execution_usdt = float(fill.get("field_cash_amount") or order.payment_amount or 0)
    reference_rate = order.reference_rate_cop_per_usdt
    coinsenda_rate = order.sell_price_cop_per_usdt
    if not reference_rate or not coinsenda_rate or reference_rate <= 0 or coinsenda_rate <= 0:
        return {
            "reference_rate_cop_per_usdt": reference_rate,
            "coinsenda_rate_cop_per_usdt": coinsenda_rate,
            "client_ratio": 1.0,
            "client_xaut_net": total_xaut,
            "client_gold_grams_net": total_grams,
            "chaut_spread_xaut": 0.0,
            "chaut_spread_gold_grams": 0.0,
            "spread_profit_cop_estimated": order.spread_profit_cop_estimated,
        }
    client_usdt_equivalent = float(order.amount_cop_gross) / float(reference_rate)
    ratio = min(max(client_usdt_equivalent / execution_usdt, 0), 1) if execution_usdt else 1
    client_xaut = round(total_xaut * ratio, 18)
    client_grams = round(total_grams * ratio, 12)
    return {
        "reference_rate_cop_per_usdt": reference_rate,
        "reference_rate_source": order.reference_rate_source,
        "reference_rate_date": order.reference_rate_date,
        "coinsenda_rate_cop_per_usdt": coinsenda_rate,
        "execution_usdt": execution_usdt,
        "client_usdt_equivalent": round(client_usdt_equivalent, 8),
        "client_ratio": round(ratio, 12),
        "client_xaut_net": client_xaut,
        "client_gold_grams_net": client_grams,
        "chaut_spread_xaut": round(total_xaut - client_xaut, 18),
        "chaut_spread_gold_grams": round(total_grams - client_grams, 12),
        "spread_profit_cop_estimated": order.spread_profit_cop_estimated,
    }


def _ledger_entry_from_row(row: sqlite3.Row) -> LedgerEntryResponse:
    data = dict(row)
    data["payload"] = json.loads(data.pop("payload_json") or "{}")
    return LedgerEntryResponse(**data)


def _identity_from_row(row: sqlite3.Row) -> AccountIdentityResponse:
    data = dict(row)
    data["metadata"] = json.loads(data.pop("metadata_json") or "{}")
    return AccountIdentityResponse(**data)


def _sqlite_path(database_url: str) -> Path:
    if database_url.startswith("sqlite:///"):
        return Path(database_url.removeprefix("sqlite:///"))
    raise ValueError("Only sqlite:/// URLs are supported in local test mode")
