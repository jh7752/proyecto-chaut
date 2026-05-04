from datetime import UTC, datetime
from uuid import uuid4

from fastapi import FastAPI
from pydantic import BaseModel, Field, PositiveInt


class CreateOrderRequest(BaseModel):
    client_id: str = Field(min_length=1)
    amount_cop_gross: PositiveInt


class OrderResponse(BaseModel):
    external_id: str
    client_id: str
    amount_cop_gross: int
    fee_percent: float
    fee_cop: float
    amount_cop_net: float
    payment_status: str
    conversion_status: str
    created_at: str


def create_app() -> FastAPI:
    app = FastAPI(title="Proyecto Chaut API", version="0.1.0")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok", "service": "proyecto-chaut"}

    @app.post("/orders", response_model=OrderResponse)
    def create_order(payload: CreateOrderRequest) -> OrderResponse:
        fee_percent = 0.5
        fee_cop = round(payload.amount_cop_gross * fee_percent / 100, 2)
        amount_cop_net = round(payload.amount_cop_gross - fee_cop, 2)
        return OrderResponse(
            external_id=f"chaut-{uuid4().hex[:12]}",
            client_id=payload.client_id,
            amount_cop_gross=payload.amount_cop_gross,
            fee_percent=fee_percent,
            fee_cop=fee_cop,
            amount_cop_net=amount_cop_net,
            payment_status="draft",
            conversion_status="not_started",
            created_at=datetime.now(UTC).isoformat(),
        )

    return app


app = create_app()
