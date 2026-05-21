from datetime import UTC, datetime, timedelta

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import RedirectResponse

from .admin import admin_account_detail, admin_accounts, admin_dashboard, admin_order_detail, admin_orders, require_admin
from .trm import get_seticap_trm
from .htx import (
    create_htx_client,
    create_htx_private_client,
    prepare_xaut_market_buy,
    quote_xaut_from_usdt,
    summarize_accounts as summarize_htx_accounts,
    summarize_filled_order,
)
from .kucoin import (
    create_kucoin_client,
    create_kucoin_private_client,
    summarize_accounts,
)

from .coinsenda import (
    CoinsendaClient,
    calculate_usdt_from_cop,
    create_coinsenda_client,
    get_usdt_cop_sell_price,
)
from .models import (
    AccountIdentityRequest,
    AccountResponse,
    KucoinHealthResponse,
    KucoinInstrumentResponse,
    KucoinTickerResponse,
    CheckoutRequest,
    CheckoutResponse,
    CreateOrderRequest,
    CreatePaymentRequestRequest,
    InspectPaymentRequestRequest,
    EventResponse,
    OrderResponse,
    PortfolioResponse,
    PaymentInstructionsResponse,
    XautQuoteResponse,
    build_order,
    DEFAULT_PAYMENT_EXPIRATION_MINUTES,
)
from .payment_instructions import extract_payment_instructions, parse_cop_amount
from .reconciliation import reconcile_payment_status
from .settings import Settings
from .store import OrderStore, create_store


def estimate_spread_profit_cop(amount_cop: int | float, sell_price: float, reference_rate: float) -> float:
    confirmed_usdt = float(amount_cop) / float(sell_price)
    return round(max(float(reference_rate) - float(sell_price), 0) * confirmed_usdt, 2)


def _parse_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    parsed = datetime.fromisoformat(normalized)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _payment_request_expiration_minutes(events: list[EventResponse]) -> int:
    for event in events:
        if event.event_type != "payment_request.created":
            continue
        raw = event.payload.get("coinsenda") or {}
        value = raw.get("expiration_minutes") or event.payload.get("expiration_minutes")
        try:
            return int(float(value))
        except (TypeError, ValueError):
            return DEFAULT_PAYMENT_EXPIRATION_MINUTES
    return DEFAULT_PAYMENT_EXPIRATION_MINUTES


def _latest_portfolio_rate(portfolio: PortfolioResponse) -> float | None:
    for entry in reversed(portfolio.entries):
        prepared = entry.payload.get("prepared") if isinstance(entry.payload, dict) else None
        ask_price = prepared.get("ask_price") if isinstance(prepared, dict) else None
        if ask_price:
            return float(ask_price)
    return None


def _latest_portfolio_cop_per_usdt(portfolio: PortfolioResponse) -> float | None:
    for entry in reversed(portfolio.entries):
        if entry.usdt_spent:
            return float(entry.cop_gross) / float(entry.usdt_spent)
    return None


def _with_estimated_portfolio_value(
    portfolio: PortfolioResponse, settings: Settings, coinsenda_client: CoinsendaClient
) -> PortfolioResponse:
    if portfolio.xaut_net <= 0:
        return portfolio
    try:
        ticker = create_htx_client(settings.htx_base_url, settings.htx_xaut_symbol).get_xaut_ticker()
        xaut_price = float(ticker.get("price") or ticker.get("bestBid") or ticker.get("bestAsk"))
    except Exception:
        xaut_price = _latest_portfolio_rate(portfolio)
    try:
        coinsenda_rate = getattr(coinsenda_client, "get_usdt_cop_sell_price", None)
        cop_per_usdt = float(coinsenda_rate() if callable(coinsenda_rate) else get_usdt_cop_sell_price())
    except Exception:
        cop_per_usdt = _latest_portfolio_cop_per_usdt(portfolio)
    if xaut_price is None or cop_per_usdt is None:
        return portfolio
    estimated_value_cop = round(portfolio.xaut_net * xaut_price * cop_per_usdt, 2)
    return portfolio.model_copy(
        update={
            "estimated_value_cop": estimated_value_cop,
            "valuation_price_xaut_usdt": xaut_price,
            "valuation_rate_cop_per_usdt": cop_per_usdt,
        }
    )


def create_app(
    settings: Settings | None = None,
    store: OrderStore | None = None,
    coinsenda_client: CoinsendaClient | None = None,
) -> FastAPI:
    settings = settings or Settings()
    store = store or create_store(settings.database_url)
    coinsenda_client = coinsenda_client or create_coinsenda_client(
        settings.coinsenda_mode,
        settings.coinsenda_app_origin,
        settings.coinsenda_runtime_dir,
    )
    app = FastAPI(title="Proyecto Chaut API", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "proyecto-chaut",
            "environment": settings.environment,
        }

    def expire_stale_payment_requests(limit: int = 500) -> dict:
        now = datetime.now(UTC)
        marked = []
        for order in store.list_orders(limit):
            if order.payment_status not in {"draft", "created", "pending"}:
                continue
            if not order.payment_request_id or order.conversion_status in {"executing", "submitted", "settled"}:
                continue
            events = store.list_events(order.external_id)
            created_event = next((event for event in events if event.event_type == "payment_request.created"), None)
            created_at = _parse_dt(created_event.created_at if created_event else order.updated_at or order.created_at)
            if created_at is None:
                continue
            expiration_minutes = _payment_request_expiration_minutes(events)
            expired_at = created_at + timedelta(minutes=expiration_minutes)
            if now <= expired_at:
                continue
            previous_status = order.payment_status
            updated = store.update_payment_status(order.external_id, "expired")
            if updated is None:
                continue
            if not any(event.event_type == "payment.expired" for event in events):
                store.add_event(
                    order.external_id,
                    "payment.expired",
                    {
                        "reason": "payment_request_expired",
                        "previous_status": previous_status,
                        "expiration_minutes": expiration_minutes,
                        "payment_request_created_at": created_at.isoformat(),
                        "expired_at": expired_at.isoformat(),
                        "marked_at": now.isoformat(),
                        "payment_request_id": order.payment_request_id,
                    },
                )
            marked.append({
                "external_id": order.external_id,
                "previous_status": previous_status,
                "new_status": "expired",
                "expired_at": expired_at.isoformat(),
            })
        return {"marked_count": len(marked), "marked": marked}



    @app.get("/admin")
    def admin_home(request: Request):
        expire_stale_payment_requests()
        require_admin(request, settings.admin_token)
        return admin_dashboard(store, request.query_params.get("token"))

    @app.get("/admin/orders")
    def admin_orders_page(request: Request):
        expire_stale_payment_requests()
        require_admin(request, settings.admin_token)
        return admin_orders(store, request.query_params.get("token"))

    @app.get("/admin/orders/{external_id}")
    def admin_order_page(external_id: str, request: Request):
        require_admin(request, settings.admin_token)
        return admin_order_detail(store, external_id, request.query_params.get("token"))

    def _admin_redirect(external_id: str, token: str | None, redirect: str = "detail") -> RedirectResponse:
        path = f"/admin/orders/{external_id}" if redirect == "detail" else "/admin/orders"
        suffix = f"?token={token}" if token else ""
        return RedirectResponse(f"{path}{suffix}", status_code=303)

    @app.post("/admin/orders/{external_id}/reconcile")
    def admin_reconcile_order(external_id: str, request: Request, redirect: str = "detail"):
        require_admin(request, settings.admin_token)
        reconcile_payment(external_id)
        return _admin_redirect(external_id, request.query_params.get("token"), redirect)

    @app.post("/admin/orders/{external_id}/prepare-xaut")
    def admin_prepare_xaut_order(external_id: str, request: Request, redirect: str = "detail"):
        require_admin(request, settings.admin_token)
        prepare_xaut_order(external_id)
        return _admin_redirect(external_id, request.query_params.get("token"), redirect)

    @app.post("/admin/orders/{external_id}/settle-xaut")
    def admin_settle_xaut_order(external_id: str, request: Request, confirm: str = "", redirect: str = "detail"):
        require_admin(request, settings.admin_token)
        settle_xaut_after_payment(external_id, confirm)
        return _admin_redirect(external_id, request.query_params.get("token"), redirect)

    @app.post("/admin/orders/{external_id}/mark-attention")
    def admin_mark_attention_order(external_id: str, request: Request, redirect: str = "detail"):
        require_admin(request, settings.admin_token)
        order = store.get_order(external_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        store.add_event(
            external_id,
            "admin.attention_marked",
            {"reason": "manual_review", "marked_at": datetime.now(UTC).isoformat()},
        )
        return _admin_redirect(external_id, request.query_params.get("token"), redirect)

    @app.get("/admin/accounts")
    def admin_accounts_page(request: Request):
        require_admin(request, settings.admin_token)
        return admin_accounts(store, request.query_params.get("token"))

    @app.get("/admin/accounts/{customer_id}")
    def admin_account_page(customer_id: str, request: Request):
        require_admin(request, settings.admin_token)
        return admin_account_detail(store, customer_id, request.query_params.get("token"))

    @app.post("/accounts/identify", response_model=AccountResponse)
    def identify_account(payload: AccountIdentityRequest) -> AccountResponse:
        account = store.upsert_account_identity(payload)
        store.add_event(
            account.customer_id,
            "account.identity_upserted",
            {
                "provider": payload.provider,
                "provider_user_id": payload.provider_user_id,
                "chat_id": payload.chat_id,
                "username": payload.username,
                "display_name": payload.display_name,
                "has_phone_number": bool(payload.phone_number),
                "has_email": bool(payload.email),
            },
        )
        return account

    @app.get("/accounts/{customer_id}", response_model=AccountResponse)
    def get_account(customer_id: str) -> AccountResponse:
        account = store.get_account(customer_id)
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        return account

    @app.get("/accounts/by-identity/{provider}/{provider_user_id}", response_model=AccountResponse)
    def get_account_by_identity(provider: str, provider_user_id: str) -> AccountResponse:
        account = store.get_account_by_identity(provider, provider_user_id)
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        return account


    @app.get("/accounts/{customer_id}/portfolio", response_model=PortfolioResponse)
    def get_account_portfolio(customer_id: str) -> PortfolioResponse:
        account = store.get_account(customer_id)
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        return _with_estimated_portfolio_value(store.get_portfolio(customer_id), settings, coinsenda_client)

    @app.get("/accounts/by-identity/{provider}/{provider_user_id}/portfolio", response_model=PortfolioResponse)
    def get_account_portfolio_by_identity(provider: str, provider_user_id: str) -> PortfolioResponse:
        account = store.get_account_by_identity(provider, provider_user_id)
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        return _with_estimated_portfolio_value(store.get_portfolio(account.customer_id), settings, coinsenda_client)

    @app.get("/htx/health")
    def htx_health() -> dict:
        return create_htx_client(settings.htx_base_url, settings.htx_xaut_symbol).health()

    @app.get("/htx/xaut-ticker")
    def htx_xaut_ticker() -> dict:
        return create_htx_client(settings.htx_base_url, settings.htx_xaut_symbol).get_xaut_ticker()

    @app.get("/htx/xaut-instrument")
    def htx_xaut_instrument() -> dict:
        return create_htx_client(settings.htx_base_url, settings.htx_xaut_symbol).get_xaut_instrument()

    @app.get("/htx/accounts")
    def htx_accounts() -> dict:
        client = create_htx_private_client(settings.htx_worker_instance_id, settings.htx_worker_region)
        payload = client.accounts()
        return {"source": "htx-worker-ssm" if settings.htx_worker_instance_id else "htx-direct", "accounts": summarize_htx_accounts(payload)}

    @app.get("/kucoin/health", response_model=KucoinHealthResponse)
    def kucoin_health() -> KucoinHealthResponse:
        return KucoinHealthResponse(**create_kucoin_client(settings.kucoin_base_url, settings.kucoin_xaut_symbol).health())

    @app.get("/kucoin/xaut-ticker", response_model=KucoinTickerResponse)
    def kucoin_xaut_ticker() -> KucoinTickerResponse:
        return KucoinTickerResponse(**create_kucoin_client(settings.kucoin_base_url, settings.kucoin_xaut_symbol).get_xaut_ticker())

    @app.get("/kucoin/xaut-instrument", response_model=KucoinInstrumentResponse)
    def kucoin_xaut_instrument() -> KucoinInstrumentResponse:
        return KucoinInstrumentResponse(**create_kucoin_client(settings.kucoin_base_url, settings.kucoin_xaut_symbol).get_xaut_instrument())

    @app.get("/kucoin/accounts")
    def kucoin_accounts(currency: str | None = None) -> dict:
        client = create_kucoin_private_client(settings.kucoin_worker_instance_id, settings.kucoin_worker_region)
        payload = client.accounts(currency)
        return {"source": "kucoin-worker-ssm" if settings.kucoin_worker_instance_id else "kucoin-direct", "accounts": summarize_accounts(payload)}

    @app.post("/kucoin/transfer-main-to-trade")
    def kucoin_transfer_main_to_trade(currency: str = "USDT", amount: str = "2") -> dict:
        client = create_kucoin_private_client(settings.kucoin_worker_instance_id, settings.kucoin_worker_region)
        payload = client.inner_transfer(currency, amount, "main", "trade")
        return {"source": "kucoin-worker-ssm" if settings.kucoin_worker_instance_id else "kucoin-direct", "result": payload}

    def existing_filled_xaut_event(external_id: str) -> dict | None:
        for event in reversed(store.list_events(external_id)):
            if event.event_type == "xaut.order_filled":
                return event.payload
        return None

    def build_xaut_user_summary(external_id: str, fill: dict) -> dict:
        xaut_net = fill.get("xaut_net")
        grams_net = fill.get("gold_grams_net")
        return {
            "external_id": external_id,
            "status": "xaut_bought",
            "xaut_net": xaut_net,
            "gold_grams_net": grams_net,
            "message": f"Compra completada: recibiste {grams_net} gramos de oro digital ({xaut_net} XAUT neto).",
        }

    def run_xaut_market_buy(external_id: str) -> dict:
        order = store.get_order(external_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        already_filled = existing_filled_xaut_event(external_id)
        existing_ledger = store.get_ledger_entry_for_order(external_id)
        if already_filled is not None:
            fill = already_filled.get("order", {})
            if existing_ledger is None and order.customer_id:
                existing_ledger = store.create_ledger_entry(order, fill, already_filled)
            return {
                "external_id": external_id,
                "status": "already_settled",
                "idempotent": True,
                "order": fill,
                "ledger_entry": existing_ledger.model_dump() if existing_ledger else None,
                "user_summary": build_xaut_user_summary(external_id, fill),
                "original": already_filled,
            }

        if not store.try_start_conversion_execution(external_id):
            current = store.get_order(external_id)
            status = current.conversion_status if current else order.conversion_status
            raise HTTPException(status_code=409, detail=f"Order cannot execute with conversion_status={status}")

        prepared = prepare_xaut_order(external_id, update_status=False)
        client = create_htx_private_client(settings.htx_worker_instance_id, settings.htx_worker_region)
        try:
            result = client.place_market_buy(prepared["symbol"], prepared["funds"])
        except Exception:
            store.update_conversion_status(external_id, "prepared")
            raise
        order_id = str(result.get("data"))
        order_detail = client.order(order_id)
        fill = summarize_filled_order(order_detail)
        payload = {"external_id": external_id, "prepared": prepared, "htx": result, "order": fill}
        store.update_conversion_status(external_id, "submitted")
        store.add_event(external_id, "xaut.order_submitted", payload)
        ledger_entry = None
        if fill["state"] == "filled":
            store.update_conversion_status(external_id, "settled")
            if order.customer_id:
                ledger_entry = store.create_ledger_entry(order, fill, payload)
                payload["ledger_entry"] = ledger_entry.model_dump()
            store.add_event(external_id, "xaut.order_filled", payload)
        payload["status"] = "settled" if fill["state"] == "filled" else "submitted"
        payload["idempotent"] = False
        if ledger_entry:
            payload["ledger_entry"] = ledger_entry.model_dump()
        payload["user_summary"] = build_xaut_user_summary(external_id, fill)
        return payload

    @app.post("/orders/{external_id}/xaut-prepare-order")
    def prepare_xaut_order(external_id: str, update_status: bool = True) -> dict:
        order = store.get_order(external_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        if order.payment_status != "confirmed":
            raise HTTPException(status_code=409, detail="Order payment is not confirmed")
        if order.payment_currency != "usdt" or order.payment_amount is None:
            raise HTTPException(status_code=409, detail="Order does not have confirmed USDT amount")
        public = create_htx_client(settings.htx_base_url, settings.htx_xaut_symbol)
        ticker = public.get_xaut_ticker()
        instrument = public.get_xaut_instrument()
        try:
            prepared = prepare_xaut_market_buy(
                order.payment_amount,
                float(ticker["bestAsk"] or ticker["price"]),
                order.fee_percent,
                instrument,
                settings.htx_xaut_symbol,
            )
        except ValueError as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        payload = {"external_id": order.external_id, "customer_id": order.customer_id, "ticker": ticker, "instrument": instrument, **prepared}
        if update_status:
            store.update_conversion_status(order.external_id, "prepared")
        store.add_event(order.external_id, "xaut.order_prepared", payload)
        return payload

    @app.post("/orders/{external_id}/xaut-execute-market-buy")
    def execute_xaut_market_buy(external_id: str, confirm: str = "") -> dict:
        if confirm != "EXECUTE_HTX_XAUT_BUY":
            raise HTTPException(status_code=409, detail="Missing explicit EXECUTE_HTX_XAUT_BUY confirmation")
        return run_xaut_market_buy(external_id)

    @app.post("/orders/{external_id}/settle-xaut")
    def settle_xaut_after_payment(external_id: str, confirm: str = "") -> dict:
        expire_stale_payment_requests()
        if confirm != "EXECUTE_HTX_XAUT_BUY":
            raise HTTPException(status_code=409, detail="Missing explicit EXECUTE_HTX_XAUT_BUY confirmation")
        order = reconcile_payment(external_id)
        if order.payment_status != "confirmed":
            return {
                "external_id": external_id,
                "status": "payment_not_confirmed",
                "payment_status": order.payment_status,
                "executed": False,
            }
        result = run_xaut_market_buy(external_id)
        result["payment_status"] = order.payment_status
        result["executed"] = not result.get("idempotent", False)
        return result

    @app.post("/orders/expire-stale-payment-requests")
    def expire_stale_payment_requests_endpoint() -> dict:
        return expire_stale_payment_requests()

    @app.post("/checkout", response_model=CheckoutResponse)
    def checkout(payload: CheckoutRequest) -> CheckoutResponse:
        account = store.upsert_account_identity(payload.identity) if payload.identity else None
        attempts = []
        last_result: dict | None = None
        max_attempts = payload.max_retries + 1

        for attempt_number in range(1, max_attempts + 1):
            sell_price = getattr(coinsenda_client, "get_usdt_cop_sell_price", get_usdt_cop_sell_price)()
            trm = get_seticap_trm()
            spread_profit_cop_estimated = estimate_spread_profit_cop(payload.amount_cop, sell_price, trm["reference_rate"])
            order_payload = CreateOrderRequest(
                client_id=payload.client_id,
                customer_id=account.customer_id if account else None,
                amount_cop_gross=payload.amount_cop,
                estimated_rate_cop_per_usdt=sell_price,
                reference_rate_cop_per_usdt=trm["reference_rate"],
                reference_rate_source=trm["source"],
                reference_rate_date=trm.get("reference_rate_date"),
            )
            order = build_order(order_payload, settings.fee_percent)
            store.put_order(order)
            store.add_event(
                order.external_id,
                "order.created",
                {**order.model_dump(), "checkout_attempt": attempt_number},
            )

            payment_amount = calculate_usdt_from_cop(order.amount_cop_gross, sell_price)
            payment_request = coinsenda_client.create_payment_request(
                order,
                payload.expiration_minutes,
                "usdt",
                payment_amount,
            )
            updated_order = store.update_payment_request(
                external_id=order.external_id,
                payment_request_id=payment_request.payment_request_id,
                payment_url=payment_request.payment_url,
                payment_status=payment_request.status,
                payment_currency="usdt",
                payment_amount=payment_amount,
                sell_price_cop_per_usdt=sell_price,
                reference_rate_cop_per_usdt=trm["reference_rate"],
                reference_rate_source=trm["source"],
                reference_rate_date=trm.get("reference_rate_date"),
                spread_profit_cop_estimated=spread_profit_cop_estimated,
            )
            if updated_order is None:
                raise HTTPException(status_code=404, detail="Order not found")
            store.add_event(
                updated_order.external_id,
                "payment_request.created",
                {
                    "checkout_attempt": attempt_number,
                    "payment_request_id": payment_request.payment_request_id,
                    "payment_url": payment_request.payment_url,
                    "payment_status": payment_request.status,
                    "payment_currency": "usdt",
                    "payment_amount": payment_amount,
                    "sell_price_cop_per_usdt": sell_price,
                    "reference_rate_cop_per_usdt": trm["reference_rate"],
                    "reference_rate_source": trm["source"],
                    "reference_rate_date": trm.get("reference_rate_date"),
                    "spread_profit_cop_estimated": spread_profit_cop_estimated,
                    "fee_asset": updated_order.fee_asset,
                    "coinsenda": payment_request.raw,
                },
            )

            inspection = coinsenda_client.inspect_payment_request(updated_order, payload.method)
            instructions = extract_payment_instructions(inspection)
            pay_amount_cop = parse_cop_amount(instructions.get("amount_cop_text"))
            price_slippage_cop = None
            checkout_status = "price_unverified"
            if pay_amount_cop is not None:
                price_slippage_cop = round(pay_amount_cop - float(payload.amount_cop), 2)
                checkout_status = (
                    "ready"
                    if abs(price_slippage_cop) <= payload.max_price_slippage_cop
                    else "price_mismatch"
                )

            attempt = {
                "attempt": attempt_number,
                "external_id": updated_order.external_id,
                "customer_id": updated_order.customer_id,
                "payment_request_id": updated_order.payment_request_id,
                "sell_price_cop_per_usdt": sell_price,
                "reference_rate_cop_per_usdt": trm["reference_rate"],
                "reference_rate_source": trm["source"],
                "reference_rate_date": trm.get("reference_rate_date"),
                "spread_profit_cop_estimated": spread_profit_cop_estimated,
                "payment_amount": updated_order.payment_amount,
                "pay_amount_cop": instructions.get("amount_cop_text"),
                "pay_amount_cop_numeric": pay_amount_cop,
                "price_slippage_cop": price_slippage_cop,
                "checkout_status": checkout_status,
            }
            attempts.append(attempt)
            store.add_event(
                updated_order.external_id,
                "payment_instructions.inspected",
                {
                    "checkout_attempt": attempt_number,
                    "click_text": payload.method,
                    "instructions": instructions,
                    "inspection": inspection,
                    "price_validation": attempt,
                },
            )
            last_result = {
                "order": updated_order,
                "instructions": instructions,
                "sell_price": sell_price,
                "attempt": attempt,
            }
            if checkout_status == "ready":
                break

            store.add_event(
                updated_order.external_id,
                "checkout.price_mismatch",
                {
                    "checkout_attempt": attempt_number,
                    "target_amount_cop": payload.amount_cop,
                    "max_price_slippage_cop": payload.max_price_slippage_cop,
                    "attempt": attempt,
                    "will_retry": attempt_number < max_attempts,
                },
            )

        if last_result is None:
            raise HTTPException(status_code=500, detail="Checkout failed before creating an order")

        updated_order = last_result["order"]
        instructions = last_result["instructions"]
        attempt = last_result["attempt"]
        primary_address = (instructions.get("addresses") or [{}])[0].get("address")
        return CheckoutResponse(
            external_id=updated_order.external_id,
            customer_id=updated_order.customer_id,
            status=updated_order.payment_status,
            checkout_status=attempt["checkout_status"],
            amount_cop=updated_order.amount_cop_gross,
            pay_amount_cop=instructions.get("amount_cop_text"),
            pay_amount_cop_numeric=attempt["pay_amount_cop_numeric"],
            price_slippage_cop=attempt["price_slippage_cop"],
            attempts=len(attempts),
            pay_to=primary_address,
            method=payload.method,
            payment_currency=updated_order.payment_currency,
            payment_amount=updated_order.payment_amount,
            sell_price_cop_per_usdt=attempt["sell_price_cop_per_usdt"],
            reference_rate_cop_per_usdt=updated_order.reference_rate_cop_per_usdt,
            reference_rate_source=updated_order.reference_rate_source,
            reference_rate_date=updated_order.reference_rate_date,
            spread_profit_cop_estimated=updated_order.spread_profit_cop_estimated,
            payment_request_id=updated_order.payment_request_id,
            payment_url=updated_order.payment_url,
            instructions={**instructions, "price_validation": attempt, "checkout_attempts": attempts},
            expires_in_minutes=payload.expiration_minutes,
        )

    @app.post("/orders", response_model=OrderResponse)
    def create_order(payload: CreateOrderRequest) -> OrderResponse:
        order = build_order(payload, settings.fee_percent)
        store.put_order(order)
        store.add_event(order.external_id, "order.created", order.model_dump())
        return order

    @app.get("/orders/{external_id}", response_model=OrderResponse)
    def get_order(external_id: str) -> OrderResponse:
        order = store.get_order(external_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        return order

    @app.post("/orders/{external_id}/xaut-quote", response_model=XautQuoteResponse)
    def create_xaut_quote(external_id: str) -> XautQuoteResponse:
        order = store.get_order(external_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        if order.payment_status != "confirmed":
            raise HTTPException(status_code=409, detail="Order payment is not confirmed")
        if order.payment_currency != "usdt" or order.payment_amount is None:
            raise HTTPException(status_code=409, detail="Order does not have confirmed USDT amount")

        ticker = create_htx_client(settings.htx_base_url, settings.htx_xaut_symbol).get_xaut_ticker()
        ask_price = float(ticker["bestAsk"] or ticker["price"])
        quote = quote_xaut_from_usdt(order.payment_amount, ask_price, order.fee_percent)
        payload = {
            "external_id": order.external_id,
            "customer_id": order.customer_id,
            "payment_status": order.payment_status,
            "source": "htx_public_ticker",
            "ticker": ticker,
            **quote,
        }
        store.update_conversion_status(order.external_id, "quoted")
        store.add_event(order.external_id, "xaut.quote_created", payload)
        return XautQuoteResponse(**payload)

    @app.post("/orders/{external_id}/payment-request", response_model=OrderResponse)
    def create_payment_request(
        external_id: str,
        payload: CreatePaymentRequestRequest,
    ) -> OrderResponse:
        order = store.get_order(external_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        if order.payment_request_id:
            raise HTTPException(status_code=409, detail="Payment request already exists")

        payment_amount = float(order.amount_cop_gross)
        sell_price = payload.sell_price_cop_per_usdt
        trm = None
        spread_profit_cop_estimated = None
        if payload.currency == "usdt":
            if sell_price is None:
                raise HTTPException(
                    status_code=422,
                    detail="sell_price_cop_per_usdt is required for USDT payment requests",
                )
            payment_amount = calculate_usdt_from_cop(order.amount_cop_gross, sell_price)
            trm = get_seticap_trm()
            spread_profit_cop_estimated = estimate_spread_profit_cop(order.amount_cop_gross, sell_price, trm["reference_rate"])

        payment_request = coinsenda_client.create_payment_request(
            order,
            payload.expiration_minutes,
            payload.currency,
            payment_amount,
        )
        updated_order = store.update_payment_request(
            external_id=order.external_id,
            payment_request_id=payment_request.payment_request_id,
            payment_url=payment_request.payment_url,
            payment_status=payment_request.status,
            payment_currency=payload.currency,
            payment_amount=payment_amount,
            sell_price_cop_per_usdt=sell_price,
            reference_rate_cop_per_usdt=trm["reference_rate"] if trm else None,
            reference_rate_source=trm["source"] if trm else None,
            reference_rate_date=trm.get("reference_rate_date") if trm else None,
            spread_profit_cop_estimated=spread_profit_cop_estimated,
        )
        if updated_order is None:
            raise HTTPException(status_code=404, detail="Order not found")

        store.add_event(
            order.external_id,
            "payment_request.created",
            {
                "payment_request_id": payment_request.payment_request_id,
                "payment_url": payment_request.payment_url,
                "payment_status": payment_request.status,
                "payment_currency": payload.currency,
                "payment_amount": payment_amount,
                "sell_price_cop_per_usdt": sell_price,
                "reference_rate_cop_per_usdt": trm["reference_rate"] if trm else None,
                "reference_rate_source": trm["source"] if trm else None,
                "reference_rate_date": trm.get("reference_rate_date") if trm else None,
                "spread_profit_cop_estimated": spread_profit_cop_estimated,
                "fee_asset": updated_order.fee_asset,
                "coinsenda": payment_request.raw,
            },
        )
        return updated_order


    @app.post("/orders/{external_id}/payment-request/check", response_model=OrderResponse)
    def check_payment_request(external_id: str) -> OrderResponse:
        order = store.get_order(external_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        if not order.payment_request_id:
            raise HTTPException(status_code=409, detail="Order does not have a payment request")

        payment_status = coinsenda_client.check_payment_request(order)
        updated_order = store.update_payment_status(order.external_id, payment_status.payment_status)
        if updated_order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        store.add_event(
            order.external_id,
            payment_status.payment_status,
            {"coinsenda": payment_status.raw},
        )
        return updated_order


    @app.post("/orders/{external_id}/reconcile-payment", response_model=OrderResponse)
    def reconcile_payment(external_id: str) -> OrderResponse:
        expire_stale_payment_requests()
        order = store.get_order(external_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        if not order.payment_request_id:
            raise HTTPException(status_code=409, detail="Order does not have a payment request")

        coinsenda_status = coinsenda_client.check_payment_request(order)
        reconciliation = reconcile_payment_status(order, coinsenda_status.raw)
        updated_order = store.update_payment_status(order.external_id, reconciliation.payment_status)
        if updated_order is None:
            raise HTTPException(status_code=404, detail="Order not found")

        store.add_event(
            order.external_id,
            reconciliation.event_type,
            {
                "payment_status": reconciliation.payment_status,
                "validation": reconciliation.validation,
                "coinsenda": coinsenda_status.raw,
            },
        )
        return updated_order


    @app.post(
        "/orders/{external_id}/payment-instructions",
        response_model=PaymentInstructionsResponse,
    )
    def inspect_payment_instructions(
        external_id: str,
        payload: InspectPaymentRequestRequest,
    ) -> PaymentInstructionsResponse:
        order = store.get_order(external_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        if not order.payment_url:
            raise HTTPException(status_code=409, detail="Order does not have a payment URL")

        inspection = coinsenda_client.inspect_payment_request(order, payload.click_text)
        instructions = extract_payment_instructions(inspection)
        store.add_event(
            order.external_id,
            "payment_instructions.inspected",
            {"click_text": payload.click_text, "instructions": instructions, "inspection": inspection},
        )
        return PaymentInstructionsResponse(
            external_id=order.external_id,
            payment_request_id=order.payment_request_id,
            payment_url=order.payment_url,
            instructions=instructions,
            raw_inspection=inspection,
        )

    @app.get("/orders/{external_id}/events", response_model=list[EventResponse])
    def list_order_events(external_id: str) -> list[EventResponse]:
        order = store.get_order(external_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        return store.list_events(external_id)

    return app


app = create_app()
