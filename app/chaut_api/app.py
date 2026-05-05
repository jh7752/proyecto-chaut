from fastapi import FastAPI, HTTPException

from .coinsenda import CoinsendaClient, create_coinsenda_client
from .models import (
    CreateOrderRequest,
    CreatePaymentRequestRequest,
    EventResponse,
    OrderResponse,
    build_order,
)
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
    )
    app = FastAPI(title="Proyecto Chaut API", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {
            "status": "ok",
            "service": "proyecto-chaut",
            "environment": settings.environment,
        }

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

        payment_request = coinsenda_client.create_payment_request(order, payload.expiration_minutes)
        updated_order = store.update_payment_request(
            external_id=order.external_id,
            payment_request_id=payment_request.payment_request_id,
            payment_url=payment_request.payment_url,
            payment_status=payment_request.status,
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
                "coinsenda": payment_request.raw,
            },
        )
        return updated_order

    @app.get("/orders/{external_id}/events", response_model=list[EventResponse])
    def list_order_events(external_id: str) -> list[EventResponse]:
        order = store.get_order(external_id)
        if order is None:
            raise HTTPException(status_code=404, detail="Order not found")
        return store.list_events(external_id)

    return app


app = create_app()
