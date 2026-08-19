import logging
from typing import Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    can_interface: str = "virtual"
    can_channel: str = "bus0"
    dbc_path: str = "vehicle.dbc"
    mcp_port: int = 6278
    mcp_transport: Literal["sse", "streamable-http", "stdio"] = "sse"
    max_duration_s: float = 30.0
    log_level: str = "INFO"

    model_config = SettingsConfigDict(
        env_prefix="MCP_CAN_",
        env_file=".env",
        extra="ignore",
    )


def get_settings() -> Settings:
    return Settings()


_logging_configured = False


def configure_logging(settings: Optional[Settings] = None) -> None:
    """Configure root logging once, using rich's colorized handler if available.

    Safe to call multiple times (e.g. from both the CLI entrypoint and a
    server/simulator `main()` used standalone) — only the first call takes
    effect.
    """
    global _logging_configured
    if _logging_configured:
        return
    settings = settings or get_settings()
    level = getattr(logging, settings.log_level.upper(), logging.INFO)
    try:
        from rich.logging import RichHandler

        logging.basicConfig(
            level=level,
            format="%(message)s",
            datefmt="[%X]",
            handlers=[RichHandler(rich_tracebacks=True, show_path=False)],
        )
    except ImportError:
        logging.basicConfig(
            level=level,
            format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
            datefmt="%H:%M:%S",
        )
    _logging_configured = True
