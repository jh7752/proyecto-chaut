from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field, PositiveFloat, PositiveInt


class CheckoutRequest(BaseModel):
    client_id: str = Field(min_length=1)
    amount_cop: PositiveInt
    expiration_minutes: PositiveInt = Field(default=60, le=1440)
    method: str = Field(default="Bre-B")


class CheckoutResponse(BaseModel):
    external_id: str
    status: str
    amount_cop: int
    pay_amount_cop: str | None
    pay_to: str | None
    method: str
    payment_currency: str
    payment_amount: float | None
    sell_price_cop_per_usdt: float
    payment_request_id: str | None
    payment_url: str | None
    instructions: dict
    expires_in_minutes: int


class CreateOrderRequest(BaseModel):
    client_id: str = Field(min_length=1)
    amount_cop_gross: PositiveInt
    estimated_rate_cop_per_usdt: PositiveFloat | None = None


class CreatePaymentRequestRequest(BaseModel):
    expiration_minutes: PositiveInt = Field(default=60, le=1440)
    currency: str = Field(default="cop", pattern="^(cop|usdt)$")
    sell_price_cop_per_usdt: PositiveFloat | None = None


class InspectPaymentRequestRequest(BaseModel):
    click_text: str = Field(default="DCOP")


class PaymentInstructionsResponse(BaseModel):
    external_id: str
    payment_request_id: str | None
    payment_url: str | None
    instructions: dict
    raw_inspection: dict


class OrderResponse(BaseModel):
    external_id: str
    client_id: str
    amount_cop_gross: int
    fee_percent: float
    fee_asset: str = "xaut"
    fee_cop: float = 0.0
    amount_cop_net: float
    payment_currency: str = "cop"
    payment_amount: float | None = None
    sell_price_cop_per_usdt: float | None = None
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
    fee_cop = 0.0
    amount_cop_net = float(payload.amount_cop_gross)
    estimated_usdt = None
    if payload.estimated_rate_cop_per_usdt:
        estimated_usdt = round(amount_cop_net / payload.estimated_rate_cop_per_usdt, 8)

    return OrderResponse(
        external_id=f"chaut-{uuid4().hex[:12]}",
        client_id=payload.client_id,
        amount_cop_gross=payload.amount_cop_gross,
        fee_percent=fee_percent,
        fee_asset="xaut",
        fee_cop=fee_cop,
        amount_cop_net=amount_cop_net,
        estimated_rate_cop_per_usdt=payload.estimated_rate_cop_per_usdt,
        estimated_usdt=estimated_usdt,
        payment_status="draft",
        conversion_status="not_started",
        created_at=now,
        updated_at=now,
    )
