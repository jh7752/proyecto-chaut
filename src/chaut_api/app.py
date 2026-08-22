import threading
from datetime import UTC, datetime, timedelta
from uuid import uuid4

from fastapi import FastAPI, Form, HTTPException, Request
from fastapi.responses import RedirectResponse

from .admin import (
    admin_account_detail,
    admin_accounts,
    admin_dashboard,
    admin_login_page,
    admin_order_detail,
    admin_orders,
    admin_withdrawals,
    admin_csrf_token,
    clear_admin_session_response,
    create_admin_session_response,
    require_admin,
    require_admin_csrf,
    require_admin_login,
    valid_admin_credentials,
)
from .trm import get_cached_seticap_trm, get_seticap_trm, refresh_seticap_trm_cache
from .htx import (
    create_htx_client,
    create_htx_private_client,
    prepare_xaut_market_buy,
    quote_xaut_from_usdt,
    summarize_accounts as summarize_htx_accounts,
    summarize_filled_order,
    summarize_sold_order,
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
from .coinsenda_payout import CoinsendaPayoutClient, create_coinsenda_payout_client
from .models import (
    AccountIdentityRequest,
    AccountResponse,
    CreditProfileResponse,
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
    WithdrawalMarkFailedRequest,
    WithdrawalPaymentConfirmationRequest,
    WithdrawalDetailResponse,
    WithdrawalRequest,
    WithdrawalResponse,
    XautQuoteResponse,
    build_order,
    DEFAULT_PAYMENT_EXPIRATION_MINUTES,
)
from .payment_instructions import extract_payment_instructions, parse_cop_amount
from .reconciliation import reconcile_payment_status
from .settings import Settings
from .store import OrderStore, create_store

RESERVED_WITHDRAWAL_STATUSES = {"requested", "selling_xaut", "sell_review"}
POST_XAUT_SALE_WITHDRAWAL_STATUSES = {
    "xaut_sold",
    "transferring_usdt",
    "swapping_cop",
    "paying_cop",
    "swap_failed",
    "payout_failed",
}
def withdrawal_needs_available_balance_hold(withdrawal: WithdrawalDetailResponse) -> bool:
    if withdrawal.status in RESERVED_WITHDRAWAL_STATUSES:
        return True
    if withdrawal.status in POST_XAUT_SALE_WITHDRAWAL_STATUSES:
        return not withdrawal.ledger_entry_id
    return False


def withdrawal_has_external_xaut_movement(withdrawal: WithdrawalDetailResponse) -> bool:
    return bool(
        withdrawal.status in POST_XAUT_SALE_WITHDRAWAL_STATUSES
        or withdrawal.htx_order_id
        or withdrawal.ledger_entry_id
        or withdrawal.usdt_received is not None
    )


def estimate_spread_profit_cop(amount_cop: int | float, sell_price: float, reference_rate: float) -> float:
    confirmed_usdt = float(amount_cop) / float(sell_price)
    return round(max(float(reference_rate) - float(sell_price), 0) * confirmed_usdt, 2)


def apply_portfolio_valuation_markup(sell_price: float, markup_percent: float) -> float:
    return round(float(sell_price) * (1 + (float(markup_percent) / 100)), 2)


def build_spread_payload(amount_cop: int | float, sell_price: float, trm: dict | None) -> dict:
    if trm is None:
        return {
            "reference_rate_cop_per_usdt": None,
            "reference_rate_source": None,
            "reference_rate_date": None,
            "spread_profit_cop_estimated": None,
        }
    return {
        "reference_rate_cop_per_usdt": trm["reference_rate"],
        "reference_rate_source": trm["source"],
        "reference_rate_date": trm.get("reference_rate_date"),
        "spread_profit_cop_estimated": estimate_spread_profit_cop(amount_cop, sell_price, trm["reference_rate"]),
    }


def get_checkout_reference_rate() -> dict | None:
    return get_cached_seticap_trm()


def refresh_checkout_reference_rate_async(
    store: OrderStore,
    external_id: str,
    amount_cop: int | float,
    sell_price: float,
) -> None:
    def refresh() -> None:
        try:
            trm = refresh_seticap_trm_cache()
            order = store.get_order(external_id)
            if order is None or order.payment_request_id is None or order.payment_amount is None:
                return
            spread = build_spread_payload(amount_cop, sell_price, trm)
            store.update_payment_request(
                external_id=order.external_id,
                payment_request_id=order.payment_request_id,
                payment_url=order.payment_url or "",
                payment_status=order.payment_status,
                payment_currency=order.payment_currency,
                payment_amount=order.payment_amount,
                sell_price_cop_per_usdt=order.sell_price_cop_per_usdt,
                reference_rate_cop_per_usdt=spread["reference_rate_cop_per_usdt"],
                reference_rate_source=spread["reference_rate_source"],
                reference_rate_date=spread["reference_rate_date"],
                spread_profit_cop_estimated=spread["spread_profit_cop_estimated"],
            )
            store.add_event(order.external_id, "reference_rate.updated", spread)
        except Exception:
            pass

    threading.Thread(target=refresh, daemon=True).start()


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
    portfolio: PortfolioResponse,
    settings: Settings,
    coinsenda_client: CoinsendaClient,
    *,
    include_markup: bool = True,
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
        sell_price = float(coinsenda_rate() if callable(coinsenda_rate) else get_usdt_cop_sell_price())
        cop_per_usdt = apply_portfolio_valuation_markup(
            sell_price, settings.portfolio_valuation_markup_percent
        ) if include_markup else sell_price
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



def estimate_withdrawal_value_cop(portfolio: PortfolioResponse, snapshot: dict, withdraw_xaut: float) -> float | None:
    snapshot_value = snapshot.get("estimated_value_cop") if snapshot else None
    snapshot_xaut = snapshot.get("xaut_net") if snapshot else None
    if snapshot_value is not None and snapshot_xaut:
        return float(snapshot_value) * float(withdraw_xaut) / float(snapshot_xaut)
    if portfolio.estimated_value_cop and portfolio.xaut_net:
        return float(portfolio.estimated_value_cop) * float(withdraw_xaut) / float(portfolio.xaut_net)
    return portfolio.estimated_value_cop

def create_app(
    settings: Settings | None = None,
    store: OrderStore | None = None,
    coinsenda_client: CoinsendaClient | None = None,
    coinsenda_payout_client: CoinsendaPayoutClient | None = None,
) -> FastAPI:
    settings = settings or Settings()
    store = store or create_store(settings.database_url)
    coinsenda_client = coinsenda_client or create_coinsenda_client(
        settings.coinsenda_mode,
        settings.coinsenda_app_origin,
        settings.coinsenda_runtime_dir,
    )
    coinsenda_payout_client = coinsenda_payout_client or create_coinsenda_payout_client(
        settings.coinsenda_mode,
        settings.coinsenda_runtime_dir,
        settings.coinsenda_usdt_payment_account_id,
        settings.coinsenda_usdt_trade_account_id,
        settings.coinsenda_cop_trade_account_id,
    )
    app = FastAPI(
        title="Proyecto Chaut API",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

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


    def require_admin_access(request: Request) -> str | None:
        if settings.admin_username and settings.admin_password:
            require_admin_login(request, settings.admin_session_secret)
            return None
        require_admin(request, settings.admin_token)
        return request.query_params.get("token")

    @app.get("/login")
    def login_page():
        return admin_login_page()

    @app.post("/login")
    def login(username: str = Form(...), password: str = Form(...)):
        if not valid_admin_credentials(username, password, settings.admin_username, settings.admin_password):
            return admin_login_page("Usuario o clave incorrectos")
        if not settings.admin_session_secret:
            raise HTTPException(status_code=500, detail="Admin session secret is not configured")
        return create_admin_session_response(settings.admin_session_secret)

    @app.get("/logout")
    def logout():
        return clear_admin_session_response()

    @app.get("/admin")
    def admin_home(request: Request):
        expire_stale_payment_requests()
        token = require_admin_access(request)
        csrf_token = admin_csrf_token(request, settings.admin_session_secret)
        return admin_dashboard(store, token, csrf_token)

    @app.get("/admin/orders")
    def admin_orders_page(request: Request):
        expire_stale_payment_requests()
        token = require_admin_access(request)
        csrf_token = admin_csrf_token(request, settings.admin_session_secret)
        return admin_orders(store, token, csrf_token)

    @app.get("/admin/orders/{external_id}")
    def admin_order_page(external_id: str, request: Request):
        token = require_admin_access(request)
        csrf_token = admin_csrf_token(request, settings.admin_session_secret)
        return admin_order_detail(store, external_id, token, csrf_token)

    def _admin_redirect(external_id: str, token: str | None, redirect: str = "detail") -> RedirectResponse:
        path = f"/admin/orders/{external_id}" if redirect == "detail" else "/admin/orders"
        suffix = f"?token={token}" if token else ""
        return RedirectResponse(f"{path}{suffix}", status_code=303)

    @app.post("/admin/orders/{external_id}/reconcile")
    def admin_reconcile_order(external_id: str, request: Request, csrf_token: str = Form(""), redirect: str = "detail"):
        token = require_admin_access(request)
        require_admin_csrf(request, settings.admin_session_secret, csrf_token)
        reconcile_payment(external_id)
        return _admin_redirect(external_id, token, redirect)

    @app.post("/admin/orders/{external_id}/prepare-xaut")
    def admin_prepare_xaut_order(external_id: str, request: Request, csrf_token: str = Form(""), redirect: str = "detail"):
        token = require_admin_access(request)
        require_admin_csrf(request, settings.admin_session_secret, csrf_token)
        prepare_xaut_order(external_id)
        return _admin_redirect(external_id, token, redirect)

    @app.post("/admin/orders/{external_id}/settle-xaut")
    def admin_settle_xaut_order(external_id: str, request: Request, csrf_token: str = Form(""), confirm: str = "", redirect: str = "detail"):
        token = require_admin_access(request)
        require_admin_csrf(request, settings.admin_session_secret, csrf_token)
        settle_xaut_after_payment(external_id, confirm)
        return _admin_redirect(external_id, token, redirect)

    @app.post("/admin/orders/{external_id}/mark-attention")
    def admin_mark_attention_order(external_id: str, request: Request, csrf_token: str = Form(""), redirect: str = "detail"):
        token = require_admin_access(request)
        require_admin_csrf(request, settings.admin_session_secret, csrf_token)
        order = store.get_order(external_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        store.add_event(
            external_id,
            "admin.attention_marked",
            {"reason": "manual_review", "marked_at": datetime.now(UTC).isoformat()},
        )
        return _admin_redirect(external_id, token, redirect)

    @app.get("/admin/withdrawals")
    def admin_withdrawals_page(request: Request):
        token = require_admin_access(request)
        csrf_token = admin_csrf_token(request, settings.admin_session_secret)
        return admin_withdrawals(store, token, csrf_token)

    @app.post("/admin/withdrawals/{withdrawal_id}/confirm-payment")
    def admin_confirm_withdrawal_payment(withdrawal_id: str, request: Request, csrf_token: str = Form(""), cop_paid: float = Form(...), cop_tx_ref: str = Form(...), admin_note: str | None = Form(None)):
        token = require_admin_access(request)
        require_admin_csrf(request, settings.admin_session_secret, csrf_token)
        confirm_withdrawal_payment(withdrawal_id, WithdrawalPaymentConfirmationRequest(cop_paid=cop_paid, cop_tx_ref=cop_tx_ref, admin_note=admin_note))
        suffix = f"?token={token}" if token else ""
        return RedirectResponse(f"/admin/withdrawals{suffix}", status_code=303)

    @app.post("/admin/withdrawals/{withdrawal_id}/mark-failed")
    def admin_mark_withdrawal_failed(withdrawal_id: str, request: Request, csrf_token: str = Form(""), reason: str = Form(...), admin_note: str | None = Form(None)):
        token = require_admin_access(request)
        require_admin_csrf(request, settings.admin_session_secret, csrf_token)
        mark_withdrawal_failed(withdrawal_id, WithdrawalMarkFailedRequest(reason=reason, admin_note=admin_note))
        suffix = f"?token={token}" if token else ""
        return RedirectResponse(f"/admin/withdrawals{suffix}", status_code=303)

    @app.get("/admin/accounts")
    def admin_accounts_page(request: Request):
        token = require_admin_access(request)
        csrf_token = admin_csrf_token(request, settings.admin_session_secret)
        return admin_accounts(store, token, csrf_token)

    @app.get("/admin/accounts/{customer_id}")
    def admin_account_page(customer_id: str, request: Request):
        token = require_admin_access(request)
        csrf_token = admin_csrf_token(request, settings.admin_session_secret)
        return admin_account_detail(store, customer_id, token, csrf_token)

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
    def get_account_portfolio(customer_id: str, include_markup: bool = True) -> PortfolioResponse:
        account = store.get_account(customer_id)
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        return _with_estimated_portfolio_value(store.get_portfolio(customer_id), settings, coinsenda_client, include_markup=include_markup)

    @app.get("/accounts/{customer_id}/credit-profile", response_model=CreditProfileResponse)
    def get_account_credit_profile(customer_id: str) -> CreditProfileResponse:
        account = store.get_account(customer_id)
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        portfolio = _with_estimated_portfolio_value(store.get_portfolio(customer_id), settings, coinsenda_client)
        return store.get_credit_profile(customer_id, portfolio.estimated_value_cop)

    @app.get("/accounts/by-identity/{provider}/{provider_user_id}/portfolio", response_model=PortfolioResponse)
    def get_account_portfolio_by_identity(provider: str, provider_user_id: str, include_markup: bool = True) -> PortfolioResponse:
        account = store.get_account_by_identity(provider, provider_user_id)
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        return _with_estimated_portfolio_value(store.get_portfolio(account.customer_id), settings, coinsenda_client, include_markup=include_markup)

    @app.post("/withdrawals", response_model=WithdrawalDetailResponse)
    def create_withdrawal_request(payload: WithdrawalRequest, confirm: str = "") -> WithdrawalDetailResponse:
        if confirm != "EXECUTE_WITHDRAWAL_XAUT_SELL":
            raise HTTPException(status_code=409, detail="Missing explicit EXECUTE_WITHDRAWAL_XAUT_SELL confirmation")
        account = store.get_account(payload.customer_id)
        if account is None:
            raise HTTPException(status_code=404, detail="Account not found")
        linked_account = store.get_account_by_identity(payload.provider, payload.provider_user_id)
        if linked_account is None or linked_account.customer_id != payload.customer_id:
            raise HTTPException(status_code=409, detail="Identity does not match account")
        portfolio = _with_estimated_portfolio_value(store.get_portfolio(payload.customer_id), settings, coinsenda_client, include_markup=False)
        if portfolio.gold_grams_net <= 0 or portfolio.xaut_net <= 0:
            raise HTTPException(status_code=409, detail="No gold available to withdraw")
        # Subtract pending withdrawals to prevent double-spending
        pending = [
            w
            for w in store.list_withdrawals(limit=500)
            if w.customer_id == payload.customer_id and withdrawal_needs_available_balance_hold(w)
        ]
        pending_xaut = sum(w.xaut_amount for w in pending)
        available_xaut = portfolio.xaut_net - pending_xaut
        if available_xaut <= 0:
            raise HTTPException(status_code=409, detail="You already have a pending withdrawal")
        if payload.portfolio_snapshot:
            requested_xaut = float(payload.portfolio_snapshot.get("xaut_net") or portfolio.xaut_net)
            if requested_xaut - available_xaut > 0.000000000001:
                raise HTTPException(status_code=409, detail="Cannot withdraw more than available balance")
        # Determine actual withdrawal amounts
        if payload.amount_mode == "partial" and payload.portfolio_snapshot.get("xaut_net") is not None:
            withdraw_xaut = float(payload.portfolio_snapshot["xaut_net"])
            withdraw_grams = float(payload.portfolio_snapshot.get("gold_grams_net") or 0)
            if withdraw_xaut <= 0 or withdraw_xaut > available_xaut + 0.000000000001:
                raise HTTPException(status_code=409, detail="Invalid partial withdrawal amount")
        else:
            withdraw_xaut = portfolio.xaut_net
            withdraw_grams = portfolio.gold_grams_net
        withdrawal = store.create_withdrawal(WithdrawalResponse(
            withdrawal_id=f"wd-{uuid4().hex[:12]}",
            customer_id=payload.customer_id,
            provider=payload.provider,
            provider_user_id=payload.provider_user_id,
            chat_id=payload.chat_id,
            breb_key=" ".join(payload.breb_key.split()),
            amount_mode=payload.amount_mode,
            gold_grams=withdraw_grams,
            xaut_amount=withdraw_xaut,
            estimated_value_cop=estimate_withdrawal_value_cop(portfolio, payload.portfolio_snapshot, withdraw_xaut),
            status="requested",
            created_at=datetime.now(UTC).isoformat(),
        ))
        store.add_event(
            withdrawal.withdrawal_id,
            "withdrawal.requested",
            {**withdrawal.model_dump(), "portfolio_snapshot": portfolio.model_dump(), "client_snapshot": payload.portfolio_snapshot},
        )
        withdrawal = store.update_withdrawal_status(withdrawal.withdrawal_id, "selling_xaut")
        if withdrawal is None:
            raise HTTPException(status_code=404, detail="Withdrawal not found")
        store.add_event(withdrawal.withdrawal_id, "withdrawal.selling_xaut", withdrawal.model_dump())
        try:
            client = create_htx_private_client(settings.htx_worker_instance_id, settings.htx_worker_region)
            result = client.place_market_sell(settings.htx_xaut_symbol, str(withdrawal.xaut_amount))
            order_id = str(result.get("data"))
            order_detail = client.order(order_id)
            fill = summarize_sold_order(order_detail)
            if fill.get("state") != "filled":
                raise RuntimeError(f"HTX sell order not filled: {fill.get('state')}")
            usdt_received = float(fill.get("field_cash_amount") or 0)
            xaut_sold = float(fill.get("field_amount") or withdrawal.xaut_amount)
            sell_price = (usdt_received / xaut_sold) if xaut_sold else None
            entry = store.add_withdrawal_ledger_entry(
                withdrawal.withdrawal_id,
                withdrawal.customer_id,
                withdrawal.gold_grams,
                withdrawal.xaut_amount,
                usdt_received,
                order_id,
                {"withdrawal": withdrawal.model_dump(), "htx": result, "order": fill},
            )
            updated = store.update_withdrawal_status(
                withdrawal.withdrawal_id,
                "xaut_sold",
                htx_order_id=order_id,
                usdt_received=usdt_received,
                xaut_sell_price=sell_price,
                ledger_entry_id=entry.entry_id,
                processed_at=datetime.now(UTC).isoformat(),
            )
            if updated is None:
                raise HTTPException(status_code=404, detail="Withdrawal not found")
            store.add_event(updated.withdrawal_id, "withdrawal.xaut_sold", {**updated.model_dump(), "ledger_entry": entry.model_dump(), "order": fill})

            transferring = store.update_withdrawal_status(updated.withdrawal_id, "transferring_usdt")
            if transferring is None:
                raise HTTPException(status_code=404, detail="Withdrawal not found")
            store.add_event(transferring.withdrawal_id, "withdrawal.transferring_usdt", transferring.model_dump())
            transfer = coinsenda_payout_client.self_transfer_usdt(usdt_received)
            transfer_id = str(transfer.get("id") or transfer.get("withdraw_id") or transfer.get("transfer_id") or "") or None
            transferred = store.update_withdrawal_status(
                transferring.withdrawal_id,
                "transferring_usdt",
                coinsenda_self_transfer_id=transfer_id,
            )
            if transferred is None:
                raise HTTPException(status_code=404, detail="Withdrawal not found")
            store.add_event(transferred.withdrawal_id, "withdrawal.usdt_transferred", {**transferred.model_dump(), "coinsenda": transfer})

            swapping = store.update_withdrawal_status(transferred.withdrawal_id, "swapping_cop")
            if swapping is None:
                raise HTTPException(status_code=404, detail="Withdrawal not found")
            store.add_event(swapping.withdrawal_id, "withdrawal.swapping_cop", swapping.model_dump())
            sell_price_cop = float(coinsenda_payout_client.get_usdt_cop_sell_price())
            swap = coinsenda_payout_client.swap_usdt_to_cop(usdt_received)
            swap_id = str(swap.get("id") or swap.get("swap_id") or "") or None
            cop_received = float(swap.get("cop_received") or swap.get("amount_received") or swap.get("to_amount") or (usdt_received * sell_price_cop))
            coinsenda_sell_price = float(swap.get("sell_price") or swap.get("price") or sell_price_cop)
            swapped = store.update_withdrawal_status(
                swapping.withdrawal_id,
                "paying_cop",
                coinsenda_swap_id=swap_id,
                cop_received=cop_received,
                coinsenda_sell_price=coinsenda_sell_price,
            )
            if swapped is None:
                raise HTTPException(status_code=404, detail="Withdrawal not found")
            store.add_event(swapped.withdrawal_id, "withdrawal.cop_swapped", {**swapped.model_dump(), "coinsenda": swap})

            store.add_event(swapped.withdrawal_id, "withdrawal.paying_cop", swapped.model_dump())
            payout = coinsenda_payout_client.send_cop_via_breb(swapped.breb_key, cop_received)
            withdraw_id = str(payout.get("id") or payout.get("withdraw_id") or "") or None
            completed = store.update_withdrawal_status(
                swapped.withdrawal_id,
                "completed",
                coinsenda_withdraw_id=withdraw_id,
                cop_paid=cop_received,
                cop_tx_ref=withdraw_id,
                completed_at=datetime.now(UTC).isoformat(),
            )
            if completed is None:
                raise HTTPException(status_code=404, detail="Withdrawal not found")
            store.add_event(completed.withdrawal_id, "withdrawal.completed", {**completed.model_dump(), "coinsenda": payout})
            return completed
        except HTTPException:
            raise
        except Exception as exc:
            current_withdrawal = store.get_withdrawal(withdrawal.withdrawal_id)
            current_status = current_withdrawal.status if current_withdrawal else withdrawal.status
            if current_status == "swapping_cop":
                failure_status = "swap_failed"
            elif current_status == "paying_cop":
                failure_status = "payout_failed"
            elif current_status in RESERVED_WITHDRAWAL_STATUSES:
                failure_status = "sell_review"
            else:
                failure_status = "failed"
            failed = store.update_withdrawal_status(
                withdrawal.withdrawal_id,
                failure_status,
                failure_reason=str(exc),
                processed_at=datetime.now(UTC).isoformat(),
            )
            if failed is None:
                raise HTTPException(status_code=404, detail="Withdrawal not found") from exc
            store.add_event(failed.withdrawal_id, f"withdrawal.{failed.status}", failed.model_dump())
            return failed

    @app.get("/withdrawals", response_model=list[WithdrawalDetailResponse])
    def list_withdrawals(status_filter: str | None = None, limit: int = 100) -> list[WithdrawalDetailResponse]:
        return store.list_withdrawals(status_filter, limit)

    @app.get("/withdrawals/{withdrawal_id}", response_model=WithdrawalDetailResponse)
    def get_withdrawal(withdrawal_id: str) -> WithdrawalDetailResponse:
        withdrawal = store.get_withdrawal(withdrawal_id)
        if withdrawal is None:
            raise HTTPException(status_code=404, detail="Withdrawal not found")
        return withdrawal

    @app.post("/withdrawals/{withdrawal_id}/confirm-payment", response_model=WithdrawalDetailResponse)
    def confirm_withdrawal_payment(withdrawal_id: str, payload: WithdrawalPaymentConfirmationRequest) -> WithdrawalDetailResponse:
        withdrawal = store.get_withdrawal(withdrawal_id)
        if withdrawal is None:
            raise HTTPException(status_code=404, detail="Withdrawal not found")
        if withdrawal.status not in {"xaut_sold", "paying_cop", "payout_failed", "completed"}:
            raise HTTPException(status_code=409, detail=f"Withdrawal cannot be completed from status={withdrawal.status}")
        if withdrawal.status == "completed":
            return withdrawal
        paying = store.update_withdrawal_status(withdrawal_id, "paying_cop")
        store.add_event(withdrawal_id, "withdrawal.paying_cop", paying.model_dump() if paying else {})
        completed = store.update_withdrawal_status(
            withdrawal_id,
            "completed",
            cop_paid=float(payload.cop_paid),
            cop_tx_ref=payload.cop_tx_ref,
            admin_note=payload.admin_note,
            completed_at=datetime.now(UTC).isoformat(),
        )
        if completed is None:
            raise HTTPException(status_code=404, detail="Withdrawal not found")
        store.add_event(completed.withdrawal_id, "withdrawal.completed", completed.model_dump())
        return completed

    @app.post("/withdrawals/{withdrawal_id}/mark-failed", response_model=WithdrawalDetailResponse)
    def mark_withdrawal_failed(withdrawal_id: str, payload: WithdrawalMarkFailedRequest) -> WithdrawalDetailResponse:
        withdrawal = store.get_withdrawal(withdrawal_id)
        if withdrawal is None:
            raise HTTPException(status_code=404, detail="Withdrawal not found")
        if withdrawal_has_external_xaut_movement(withdrawal):
            raise HTTPException(
                status_code=409,
                detail="Withdrawal has external XAUT movement; keep it in review or confirm COP payment",
            )
        failed = store.update_withdrawal_status(
            withdrawal_id,
            "failed",
            failure_reason=payload.reason,
            admin_note=payload.admin_note,
            processed_at=withdrawal.processed_at or datetime.now(UTC).isoformat(),
        )
        if failed is None:
            raise HTTPException(status_code=404, detail="Withdrawal not found")
        store.add_event(failed.withdrawal_id, "withdrawal.failed", failed.model_dump())
        return failed

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
            spread = build_spread_payload(payload.amount_cop, sell_price, get_checkout_reference_rate())
            order_payload = CreateOrderRequest(
                client_id=payload.client_id,
                customer_id=account.customer_id if account else None,
                amount_cop_gross=payload.amount_cop,
                estimated_rate_cop_per_usdt=sell_price,
                reference_rate_cop_per_usdt=spread["reference_rate_cop_per_usdt"],
                reference_rate_source=spread["reference_rate_source"],
                reference_rate_date=spread["reference_rate_date"],
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
                reference_rate_cop_per_usdt=spread["reference_rate_cop_per_usdt"],
                reference_rate_source=spread["reference_rate_source"],
                reference_rate_date=spread["reference_rate_date"],
                spread_profit_cop_estimated=spread["spread_profit_cop_estimated"],
            )
            if updated_order is None:
                raise HTTPException(status_code=404, detail="Order not found")
            if spread["reference_rate_source"] is None or spread["reference_rate_source"] == "seticap-cache-stale":
                refresh_checkout_reference_rate_async(
                    store,
                    updated_order.external_id,
                    updated_order.amount_cop_gross,
                    sell_price,
                )
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
                    "reference_rate_cop_per_usdt": spread["reference_rate_cop_per_usdt"],
                    "reference_rate_source": spread["reference_rate_source"],
                    "reference_rate_date": spread["reference_rate_date"],
                    "spread_profit_cop_estimated": spread["spread_profit_cop_estimated"],
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
                "reference_rate_cop_per_usdt": spread["reference_rate_cop_per_usdt"],
                "reference_rate_source": spread["reference_rate_source"],
                "reference_rate_date": spread["reference_rate_date"],
                "spread_profit_cop_estimated": spread["spread_profit_cop_estimated"],
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
            if checkout_status != "ready" and attempt_number < max_attempts:
                replaced_order = store.update_payment_status(updated_order.external_id, "voided")
                if replaced_order is not None:
                    store.add_event(
                        updated_order.external_id,
                        "checkout.replaced",
                        {
                            "reason": "checkout_not_ready",
                            "checkout_status": checkout_status,
                            "next_attempt": attempt_number + 1,
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
