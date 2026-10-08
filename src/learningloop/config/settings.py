from __future__ import annotations

from functools import lru_cache
from pathlib import Path

from pydantic import BaseModel, SecretStr, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class ProviderSettings(BaseModel):
    alias: str
    base_url: str
    flash_key: SecretStr | None = None
    pro_key: SecretStr | None = None
    flash_model: str = "deepseek-v4-flash"
    pro_model: str = "deepseek-v4-pro"

    @field_validator("base_url")
    @classmethod
    def normalize_base_url(cls, value: str) -> str:
        return value.rstrip("/")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_prefix="LEARNINGLOOP_",
        extra="ignore",
    )

    vibe_base_url: str = "https://www.vibeapi.cn/v1"
    vibe_flash_key: SecretStr | None = None
    vibe_pro_key: SecretStr | None = None
    vibe_flash_model: str = "deepseek-v4-flash"
    vibe_pro_model: str = "deepseek-v4-pro"
    # 官方 DeepSeek 是生产主路由；中转站仅作为显式开启的开发备用。
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_api_key: SecretStr | None = None
    deepseek_flash_model: str = "deepseek-v4-flash"
    deepseek_pro_model: str = "deepseek-v4-pro"
    enable_relay_fallback: bool = False
    kcne_base_url: str = "https://api.kcne.top/v1"
    kcne_flash_key: SecretStr | None = None
    kcne_pro_key: SecretStr | None = None
    kcne_flash_model: str = "deepseek-v4-flash"
    kcne_pro_model: str = "deepseek-v4-pro"

    data_dir: Path = Path("data")
    skills_dir: Path = Path("skills")
    host: str = "127.0.0.1"
    port: int = 8765
    enable_real_models: bool = True
    request_timeout_seconds: float = 60.0
    turn_input_limit: int = 120_000
    turn_output_limit: int = 16_000
    turn_call_limit: int = 4
    session_input_warning: int = 500_000
    session_output_warning: int = 80_000
    session_call_warning: int = 30
    daily_input_limit: int = 2_000_000
    daily_output_limit: int = 300_000
    daily_call_limit: int = 150
    development_cost_limit_usd: float = 5.0
    raw_message_retention_days: int = 90
    max_recent_messages: int = 8
    working_memory_tokens: int = 32_000
    summary_max_tokens: int = 1_500
    context_concept_limit: int = 40
    context_summary_char_limit: int = 6_000
    global_concurrency: int = 3
    auth_enabled: bool = False
    auth_cookie_name: str = "learningloop_session"
    auth_session_hours: int = 168
    auth_cookie_secure: bool = True
    otel_enabled: bool = False
    otel_service_name: str = "learningloop"
    otel_exporter_endpoint: str = ""
    smtp_host: str = ""
    smtp_port: int = 465
    smtp_username: str = ""
    smtp_password: SecretStr | None = None
    smtp_use_tls: bool = False
    smtp_use_ssl: bool = True
    smtp_sender: str = ""
    notification_timezone: str = "Asia/Shanghai"
    notification_morning_time: str = "08:30"
    notification_evening_time: str = "20:30"
    notification_scheduler_enabled: bool = True
    notification_poll_seconds: int = 30
    notification_retry_limit: int = 3
    notification_catchup_hours: int = 6

    @property
    def database_path(self) -> Path:
        return self.data_dir / "learningloop.db"

    @property
    def workspace_dir(self) -> Path:
        return self.data_dir / "workspaces"

    @property
    def trace_dir(self) -> Path:
        return self.data_dir / "traces"

    @property
    def notification_outbox_dir(self) -> Path:
        return self.data_dir / "notifications" / "outbox"

    @property
    def providers(self) -> dict[str, ProviderSettings]:
        return {
            "official": ProviderSettings(
                alias="official",
                base_url=self.deepseek_base_url,
                flash_key=self.deepseek_api_key,
                pro_key=self.deepseek_api_key,
                flash_model=self.deepseek_flash_model,
                pro_model=self.deepseek_pro_model,
            ),
            "vibe": ProviderSettings(
                alias="vibe",
                base_url=self.vibe_base_url,
                flash_key=self.vibe_flash_key,
                pro_key=self.vibe_pro_key,
                flash_model=self.vibe_flash_model,
                pro_model=self.vibe_pro_model,
            ),
            "kcne": ProviderSettings(
                alias="kcne",
                base_url=self.kcne_base_url,
                flash_key=self.kcne_flash_key,
                pro_key=self.kcne_pro_key,
                flash_model=self.kcne_flash_model,
                pro_model=self.kcne_pro_model,
            ),
        }

    def prepare_directories(self) -> None:
        for path in (self.data_dir, self.workspace_dir, self.trace_dir, self.notification_outbox_dir):
            path.mkdir(parents=True, exist_ok=True)


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    settings = Settings()
    settings.prepare_directories()
    return settings
