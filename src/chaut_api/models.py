from datetime import UTC, datetime
from uuid import uuid4

from pydantic import BaseModel, Field, PositiveFloat, PositiveInt

MIN_ORDER_COP = 5000
DEFAULT_PAYMENT_EXPIRATION_MINUTES = 45


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
    amount_cop: int = Field(ge=MIN_ORDER_COP)
    expiration_minutes: PositiveInt = Field(default=DEFAULT_PAYMENT_EXPIRATION_MINUTES, le=1440)
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
    reference_rate_cop_per_usdt: float | None = None
    reference_rate_source: str | None = None
    reference_rate_date: str | None = None
    spread_profit_cop_estimated: float | None = None
    payment_request_id: str | None
    payment_url: str | None
    instructions: dict
    expires_in_minutes: int


class CreateOrderRequest(BaseModel):
    client_id: str = Field(min_length=1)
    customer_id: str | None = None
    amount_cop_gross: int = Field(ge=MIN_ORDER_COP)
    estimated_rate_cop_per_usdt: PositiveFloat | None = None
    reference_rate_cop_per_usdt: PositiveFloat | None = None
    reference_rate_source: str | None = None
    reference_rate_date: str | None = None


class CreatePaymentRequestRequest(BaseModel):
    expiration_minutes: PositiveInt = Field(default=DEFAULT_PAYMENT_EXPIRATION_MINUTES, le=1440)
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
    reference_rate_cop_per_usdt: float | None = None
    reference_rate_source: str | None = None
    reference_rate_date: str | None = None
    spread_profit_cop_estimated: float | None = None
    estimated_rate_cop_per_usdt: float | None = None
    estimated_usdt: float | None = None
    payment_request_id: str | None = None
    payment_url: str | None = None
    payment_status: str
    conversion_status: str
    created_at: str
    updated_at: str
    ledger_entry_created_at: str | None = None


class KucoinHealthResponse(BaseModel):
    status: str
    source: str
    symbol: str


class KucoinTickerResponse(BaseModel):
    category: str
    symbol: str
    price: str | None = None
    size: str | None = None
    bestBid: str | None = None
    bestBidSize: str | None = None
    bestAsk: str | None = None
    bestAskSize: str | None = None
    raw: dict


class KucoinInstrumentResponse(BaseModel):
    category: str
    symbol: str
    baseCurrency: str | None = None
    quoteCurrency: str | None = None
    feeCurrency: str | None = None
    baseMinSize: str | None = None
    quoteMinSize: str | None = None
    baseIncrement: str | None = None
    quoteIncrement: str | None = None
    priceIncrement: str | None = None
    priceLimitRate: str | None = None
    minFunds: str | None = None
    enableTrading: bool | None = None
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


class LedgerEntryResponse(BaseModel):
    entry_id: str
    customer_id: str
    external_id: str
    entry_type: str
    asset: str
    amount: float
    gold_grams: float
    usdt_spent: float
    cop_gross: float
    exchange_order_id: str | None = None
    payload: dict = Field(default_factory=dict)
    created_at: str


class PortfolioResponse(BaseModel):
    customer_id: str
    xaut_net: float
    gold_grams_net: float
    usdt_spent: float
    cop_invested: float
    entries_count: int
    entries: list[LedgerEntryResponse] = Field(default_factory=list)


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
