from fastapi import FastAPI, HTTPException

from .bybit import create_bybit_client
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
    BybitHealthResponse,
    BybitInstrumentResponse,
    BybitTickerResponse,
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
    PaymentInstructionsResponse,
    XautQuoteResponse,
    build_order,
)
from .payment_instructions import extract_payment_instructions, parse_cop_amount
from .reconciliation import reconcile_payment_status
from .settings import Settings
from .store import OrderStore, create_store


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

    @app.get("/bybit/health", response_model=BybitHealthResponse)
    def bybit_health() -> BybitHealthResponse:
        return BybitHealthResponse(**create_bybit_client(settings.bybit_worker_instance_id, settings.bybit_worker_region).health())

    @app.get("/bybit/xaut-ticker", response_model=BybitTickerResponse)
    def bybit_xaut_ticker() -> BybitTickerResponse:
        return BybitTickerResponse(**create_bybit_client(settings.bybit_worker_instance_id, settings.bybit_worker_region).get_xaut_ticker())

    @app.get("/bybit/xaut-instrument", response_model=BybitInstrumentResponse)
    def bybit_xaut_instrument() -> BybitInstrumentResponse:
        return BybitInstrumentResponse(**create_bybit_client(settings.bybit_worker_instance_id, settings.bybit_worker_region).get_xaut_instrument())


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

    @app.post("/orders/{external_id}/xaut-prepare-order")
    def prepare_xaut_order(external_id: str) -> dict:
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
        store.add_event(order.external_id, "xaut.order_prepared", payload)
        return payload

    @app.post("/orders/{external_id}/xaut-execute-market-buy")
    def execute_xaut_market_buy(external_id: str, confirm: str = "") -> dict:
        if confirm != "EXECUTE_HTX_XAUT_BUY":
            raise HTTPException(status_code=409, detail="Missing explicit EXECUTE_HTX_XAUT_BUY confirmation")
        prepared = prepare_xaut_order(external_id)
        client = create_htx_private_client(settings.htx_worker_instance_id, settings.htx_worker_region)
        result = client.place_market_buy(prepared["symbol"], prepared["funds"])
        order_id = str(result.get("data"))
        order_detail = client.order(order_id)
        fill = summarize_filled_order(order_detail)
        payload = {"external_id": external_id, "prepared": prepared, "htx": result, "order": fill}
        store.add_event(external_id, "xaut.order_submitted", payload)
        if fill["state"] == "filled":
            store.add_event(external_id, "xaut.order_filled", payload)
        return payload

    @app.post("/checkout", response_model=CheckoutResponse)
    def checkout(payload: CheckoutRequest) -> CheckoutResponse:
        account = store.upsert_account_identity(payload.identity) if payload.identity else None
        attempts = []
        last_result: dict | None = None
        max_attempts = payload.max_retries + 1

        for attempt_number in range(1, max_attempts + 1):
            sell_price = getattr(coinsenda_client, "get_usdt_cop_sell_price", get_usdt_cop_sell_price)()
            order_payload = CreateOrderRequest(
                client_id=payload.client_id,
                customer_id=account.customer_id if account else None,
                amount_cop_gross=payload.amount_cop,
                estimated_rate_cop_per_usdt=sell_price,
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
        if payload.currency == "usdt":
            if sell_price is None:
                raise HTTPException(
                    status_code=422,
                    detail="sell_price_cop_per_usdt is required for USDT payment requests",
                )
            payment_amount = calculate_usdt_from_cop(order.amount_cop_gross, sell_price)

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
