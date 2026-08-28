from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CHAUT_")

    environment: str = Field(default="dev")
    fee_percent: float = Field(default=0.0)
    portfolio_valuation_markup_percent: float = Field(default=2.0)
    coinsenda_breb_withdraw_fee_cop: float = Field(default=3000.0)
    database_url: str = Field(default="sqlite:///./data/chaut.db")
    coinsenda_mode: str = Field(default="mock")
    coinsenda_app_origin: str = Field(default="https://app.coinsenda.com")
    coinsenda_runtime_dir: str = Field(default="./vendor/coinsenda")
    coinsenda_usdt_payment_account_id: str = Field(default="69f3e0313cb748002ae1e871")
    coinsenda_usdt_trade_account_id: str = Field(default="69f295313cb748002ae1dc6b")
    coinsenda_cop_trade_account_id: str = Field(default="69f295393cb748002ae1dc73")
    kucoin_base_url: str = Field(default="https://api.kucoin.com")
    kucoin_xaut_symbol: str = Field(default="XAUT-USDT")
    kucoin_worker_instance_id: str | None = Field(default=None)
    kucoin_worker_region: str = Field(default="ap-south-1")
    htx_base_url: str = Field(default="https://api.huobi.pro")
    htx_xaut_symbol: str = Field(default="xautusdt")
    htx_worker_instance_id: str | None = Field(default=None)
    htx_worker_region: str = Field(default="ap-south-1")
    admin_token: str | None = Field(default=None)
    admin_username: str | None = Field(default=None)
    admin_password: str | None = Field(default=None)
    admin_session_secret: str | None = Field(default=None)
