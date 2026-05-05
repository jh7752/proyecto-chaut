from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="CHAUT_")

    environment: str = Field(default="dev")
    fee_percent: float = Field(default=0.5)
    database_url: str = Field(default="sqlite:///./data/chaut.db")
    coinsenda_mode: str = Field(default="mock")
    coinsenda_app_origin: str = Field(default="https://app.coinsenda.com")
    coinsenda_runtime_dir: str = Field(default="./vendor/coinsenda")
