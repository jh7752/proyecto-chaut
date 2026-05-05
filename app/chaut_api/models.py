from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field, PositiveFloat, PositiveInt


class CreateOrderRequest(BaseModel):
    client_id: str = Field(min_length=1)
    amount_cop_gross: PositiveInt
    estimated_rate_cop_per_usdt: PositiveFloat | None = None


class OrderResponse(BaseModel):
    external_id: str
    client_id: str
    amount_cop_gross: int
    fee_percent: float
    fee_cop: float
    amount_cop_net: float
    estimated_rate_cop_per_usdt: float | None = None
    estimated_usdt: float | None = None
    payment_request_id: str | None = None
    payment_url: str | None = None
    payment_status: str
    conversion_status: str
    created_at: str
    updated_at: str


class EventResponse(BaseModel):
    event_id: str
    entity_id: str
    event_type: str
    payload: dict
    created_at: str


def build_order(payload: CreateOrderRequest, fee_percent: float) -> OrderResponse:
    now = datetime.now(UTC).isoformat()
    fee_cop = round(payload.amount_cop_gross * fee_percent / 100, 2)
    amount_cop_net = round(payload.amount_cop_gross - fee_cop, 2)
    estimated_usdt = None
    if payload.estimated_rate_cop_per_usdt:
        estimated_usdt = round(amount_cop_net / payload.estimated_rate_cop_per_usdt, 8)

    return OrderResponse(
        external_id=f"chaut-{uuid4().hex[:12]}",
        client_id=payload.client_id,
        amount_cop_gross=payload.amount_cop_gross,
        fee_percent=fee_percent,
        fee_cop=fee_cop,
        amount_cop_net=amount_cop_net,
        estimated_rate_cop_per_usdt=payload.estimated_rate_cop_per_usdt,
        estimated_usdt=estimated_usdt,
        payment_status="draft",
        conversion_status="not_started",
        created_at=now,
        updated_at=now,
    )
