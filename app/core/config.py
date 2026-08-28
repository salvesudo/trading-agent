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
from pydantic import Field, field_validator, model_validator


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

    # --- Compliance (Phase 3: spec section 3) ---
    # Whether the FYERS app/account has been confirmed (by the owner, with
    # FYERS/exchange directly) to have whatever SEBI algo-trading
    # registration or permission current rules require. This is not
    # something code can verify -- FYERS' own requirements and SEBI's algo
    # framework change over time (see README's disclaimer). It exists so
    # that gap is an explicit, deliberate acknowledgment rather than a
    # silent assumption.
    owner_confirmed_algo_permissions: bool = Field(
        default=False, alias="OWNER_CONFIRMED_ALGO_PERMISSIONS"
    )

    # --- Capital & risk (spec sections 2, 4, 5, 22, 23) ---
    initial_capital_inr: float = Field(default=5000.0, alias="INITIAL_CAPITAL_INR")
    protected_capital_inr: float = Field(default=5000.0, alias="PROTECTED_CAPITAL_INR")
    max_risk_per_trade_pct: float = Field(default=1.0, alias="MAX_RISK_PER_TRADE_PCT")
    max_daily_loss_pct: float = Field(default=2.0, alias="MAX_DAILY_LOSS_PCT")
    consecutive_loss_soft_limit: int = Field(default=3, alias="CONSECUTIVE_LOSS_SOFT_LIMIT")
    consecutive_loss_hard_limit: int = Field(default=5, alias="CONSECUTIVE_LOSS_HARD_LIMIT")

    # Owner-directed profit-reserve policy (added after Phase 9): after
    # every trade that closes in profit, this percentage of that profit
    # is swept into an untouchable reserve (app/risk/capital_ledger.py)
    # that is never risked again. Losses are unaffected -- the reserve
    # protects gains, it doesn't subsidize losses.
    profit_reserve_pct: float = Field(default=20.0, alias="PROFIT_RESERVE_PCT")

    # --- Paper trading engine (Phase 11) ---
    # Portfolio-level exposure cap: the Risk Engine only ever evaluates
    # one candidate at a time and has no notion of "how many other
    # positions are already open" -- this is that missing portfolio-level
    # control, enforced by app/paper/engine.py, not the Risk Engine
    # itself. A defensible starting number, not calibrated (see
    # docs/PRINCIPLES.md on unvalidated thresholds).
    max_concurrent_positions: int = Field(default=3, alias="MAX_CONCURRENT_POSITIONS")
    # Intraday positions are force-closed at this time of day (IST,
    # "HH:MM", 24-hour) regardless of stop/target -- this system holds
    # nothing overnight (see docs/PRINCIPLES.md section 20.5: long-term
    # holds are explicitly deferred). Defaults to 15 minutes before NSE's
    # 15:30 IST close, a common practical buffer against last-minute
    # liquidity/volatility, not a number FYERS or NSE requires.
    intraday_square_off_time: str = Field(default="15:15", alias="INTRADAY_SQUARE_OFF_TIME")
    # Added 2026-08-28 after the first real-data backtests: a RELIANCE
    # trend-following trade entered at 14:20 IST, 55 minutes before
    # square-off, and got flattened at a loss with no realistic chance
    # of reaching its target in that window. This blocks *new* entries
    # too close to the forced-flat time -- existing open positions are
    # unaffected, this only stops opening fresh ones with too little
    # runway left. See docs/PRINCIPLES.md section 24.
    min_minutes_before_square_off_for_entry: int = Field(
        default=30, alias="MIN_MINUTES_BEFORE_SQUARE_OFF_FOR_ENTRY"
    )
    # Added the same day: a RELIANCE SELL got stopped out, and the very
    # next signal immediately flipped to a BUY at the same price/moment
    # -- which also lost. Blocks re-entering the *same symbol* for this
    # long after it stops a position out, to avoid chasing a reversal
    # right after getting proven wrong on it.
    post_stop_loss_cooldown_minutes: int = Field(
        default=30, alias="POST_STOP_LOSS_COOLDOWN_MINUTES"
    )

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

    @field_validator("profit_reserve_pct")
    @classmethod
    def _validate_profit_reserve_pct(cls, v: float) -> float:
        if not (0.0 <= v <= 100.0):
            raise ValueError(
                f"PROFIT_RESERVE_PCT={v} must be between 0 and 100. Refusing to start."
            )
        return v

    @field_validator("max_concurrent_positions")
    @classmethod
    def _validate_max_concurrent_positions(cls, v: int) -> int:
        if v < 1:
            raise ValueError(
                f"MAX_CONCURRENT_POSITIONS={v} must be at least 1. Refusing to start."
            )
        return v

    @field_validator("intraday_square_off_time")
    @classmethod
    def _validate_intraday_square_off_time(cls, v: str) -> str:
        import datetime as _dt

        try:
            _dt.datetime.strptime(v, "%H:%M")
        except ValueError:
            raise ValueError(
                f"INTRADAY_SQUARE_OFF_TIME={v!r} must be 24-hour 'HH:MM' (e.g. '15:15'). "
                "Refusing to start."
            ) from None
        return v

    @field_validator("min_minutes_before_square_off_for_entry", "post_stop_loss_cooldown_minutes")
    @classmethod
    def _validate_non_negative_minutes(cls, v: int) -> int:
        if v < 0:
            raise ValueError(f"{v} must be >= 0 minutes. Refusing to start.")
        return v

    @model_validator(mode="after")
    def _reject_unstripped_inline_comments(self) -> "Settings":
        # pydantic-settings' .env parser only strips a trailing "# comment"
        # when a real value already precedes it on that line; on a *blank*
        # value it reads the whole comment as the literal value instead
        # (bit us once already with FYERS_STATIC_IP -- see git history).
        # No legitimate value in this config should ever contain "#", so
        # catch the whole bug class here rather than relying on every .env
        # line being hand-formatted correctly forever.
        for name in self.__class__.model_fields:
            value = getattr(self, name)
            if isinstance(value, str) and "#" in value:
                raise ValueError(
                    f"{name} contains '#' ({value!r}) -- this usually means "
                    "an inline comment in .env got read as part of the value "
                    "because the value before it was blank. Put the comment "
                    "on its own line above the KEY=value line instead, and "
                    "leave the value line completely clean."
                )
        return self

    @property
    def is_live(self) -> bool:
        return self.trading_mode == TradingMode.LIVE


settings = Settings()
