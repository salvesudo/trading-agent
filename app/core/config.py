"""
Central configuration for the trading agent.

Everything here is loaded from environment variables (via .env in dev,
real environment/secret-manager in production). Nothing sensitive is
hardcoded, and nothing here bypasses risk controls -- this module only
describes limits, it does not enforce them (enforcement lives in
app/risk/risk_engine.py, which is the system's final authority per spec
section 47).
"""
from __future__ import annotations

from enum import Enum
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic import Field, field_validator


class TradingMode(str, Enum):
    PAPER = "PAPER"
    LIVE = "LIVE"


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- Mode ---
    trading_mode: TradingMode = Field(default=TradingMode.PAPER, alias="TRADING_MODE")
    stop_trading: bool = Field(default=False, alias="STOP_TRADING")

    # --- FYERS ---
    fyers_app_id: str = Field(default="", alias="FYERS_APP_ID")
    fyers_secret_id: str = Field(default="", alias="FYERS_SECRET_ID")
    fyers_redirect_uri: str = Field(default="", alias="FYERS_REDIRECT_URI")
    fyers_static_ip: str = Field(default="", alias="FYERS_STATIC_IP")
    fyers_access_token: str = Field(default="", alias="FYERS_ACCESS_TOKEN")

    # --- Capital & risk (spec sections 2, 4, 5, 22, 23) ---
    initial_capital_inr: float = Field(default=5000.0, alias="INITIAL_CAPITAL_INR")
    protected_capital_inr: float = Field(default=5000.0, alias="PROTECTED_CAPITAL_INR")
    max_risk_per_trade_pct: float = Field(default=1.0, alias="MAX_RISK_PER_TRADE_PCT")
    max_daily_loss_pct: float = Field(default=2.0, alias="MAX_DAILY_LOSS_PCT")
    consecutive_loss_soft_limit: int = Field(default=3, alias="CONSECUTIVE_LOSS_SOFT_LIMIT")
    consecutive_loss_hard_limit: int = Field(default=5, alias="CONSECUTIVE_LOSS_HARD_LIMIT")

    # --- Database ---
    database_url: str = Field(default="", alias="DATABASE_URL")
    redis_url: str = Field(default="", alias="REDIS_URL")

    # --- Notifications ---
    owner_email: str = Field(default="", alias="OWNER_EMAIL")
    owner_mobile: str = Field(default="", alias="OWNER_MOBILE")

    # --- LLM (advisory only, spec section 47: cannot override risk engine) ---
    anthropic_api_key: str = Field(default="", alias="ANTHROPIC_API_KEY")
    llm_model: str = Field(default="claude-sonnet-4-6", alias="LLM_MODEL")

    # --- Ops ---
    log_level: str = Field(default="INFO", alias="LOG_LEVEL")
    timezone: str = Field(default="Asia/Kolkata", alias="TIMEZONE")

    @field_validator("max_risk_per_trade_pct")
    @classmethod
    def _cap_risk_per_trade(cls, v: float) -> float:
        # Hard ceiling regardless of what's in .env -- spec section 4.
        # This is a safety backstop, not the primary control; the risk
        # engine re-checks this on every single trade at runtime too.
        if v > 1.0:
            raise ValueError(
                f"MAX_RISK_PER_TRADE_PCT={v} exceeds the 1% hard ceiling set "
                "by the owner's spec. Refusing to start."
            )
        return v

    @field_validator("max_daily_loss_pct")
    @classmethod
    def _cap_daily_loss(cls, v: float) -> float:
        if v > 2.0:
            raise ValueError(
                f"MAX_DAILY_LOSS_PCT={v} exceeds the 2% recommended ceiling. "
                "Refusing to start -- lower it in .env if this is intentional "
                "and you understand the increased risk."
            )
        return v

    @property
    def is_live(self) -> bool:
        return self.trading_mode == TradingMode.LIVE


settings = Settings()
