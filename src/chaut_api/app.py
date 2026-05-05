from fastapi import FastAPI, HTTPException

from .models import CreateOrderRequest, OrderResponse, build_order
from .settings import Settings
from .store import OrderStore, create_store


def create_app(settings: Settings | None = None, store: OrderStore | None = None) -> FastAPI:
    settings = settings or Settings()
    store = store or create_store(settings.database_url)
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

    return app


app = create_app()
