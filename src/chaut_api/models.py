from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field, PositiveFloat, PositiveInt


class AccountIdentityRequest(BaseModel):
    provider: str = Field(default="telegram", min_length=1)
    provider_user_id: str = Field(min_length=1)
    chat_id: str | None = None
    username: str | None = None
    display_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    phone_number: str | None = None
    email: str | None = None
    metadata: dict = Field(default_factory=dict)


class AccountIdentityResponse(BaseModel):
    provider: str
    provider_user_id: str
    chat_id: str | None = None
    username: str | None = None
    display_name: str | None = None
    first_name: str | None = None
    last_name: str | None = None
    phone_number: str | None = None
    email: str | None = None
    metadata: dict = Field(default_factory=dict)
    created_at: str
    updated_at: str


class AccountResponse(BaseModel):
    customer_id: str
    status: str
    display_name: str | None = None
    phone_number: str | None = None
    email: str | None = None
    created_at: str
    updated_at: str
    identities: list[AccountIdentityResponse] = Field(default_factory=list)


class CheckoutRequest(BaseModel):
    client_id: str = Field(min_length=1)
    identity: AccountIdentityRequest | None = None
    amount_cop: PositiveInt
    expiration_minutes: PositiveInt = Field(default=60, le=1440)
    method: str = Field(default="Bre-B")
    max_price_slippage_cop: PositiveFloat = 1.0
    max_retries: int = Field(default=1, ge=0, le=3)


class CheckoutResponse(BaseModel):
    external_id: str
    customer_id: str | None = None
    status: str
    checkout_status: str
    amount_cop: int
    pay_amount_cop: str | None
    pay_amount_cop_numeric: float | None
    price_slippage_cop: float | None
    attempts: int
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
    customer_id: str | None = None
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
    customer_id: str | None = None
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


class BybitHealthResponse(BaseModel):
    status: str
    source: str
    symbol: str


class BybitTickerResponse(BaseModel):
    category: str
    symbol: str
    lastPrice: str | None = None
    bid1Price: str | None = None
    ask1Price: str | None = None
    highPrice24h: str | None = None
    lowPrice24h: str | None = None
    volume24h: str | None = None
    turnover24h: str | None = None
    raw: dict


class BybitInstrumentResponse(BaseModel):
    category: str
    symbol: str
    baseCoin: str | None = None
    quoteCoin: str | None = None
    status: str | None = None
    lotSizeFilter: dict | None = None
    priceFilter: dict | None = None
    raw: dict


class XautQuoteResponse(BaseModel):
    external_id: str
    customer_id: str | None = None
    payment_status: str
    confirmed_usdt: float
    xaut_ask_price: float
    fee_percent: float
    fee_xaut: float
    xaut_gross: float
    xaut_net: float
    gold_grams_gross: float
    gold_grams_net: float
    status: str
    source: str
    ticker: dict


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
        customer_id=payload.customer_id,
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
