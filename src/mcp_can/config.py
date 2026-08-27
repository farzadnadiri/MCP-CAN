import logging
from typing import List, Literal, Optional

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    can_interface: str = "virtual"
    can_channel: str = "bus0"
    dbc_path: str = "vehicle.dbc"
    mcp_port: int = 6278
    mcp_transport: Literal["sse", "streamable-http", "stdio"] = "sse"
    max_duration_s: float = 30.0
    log_level: str = "INFO"
    # Run the SAE J1939 (heavy-duty, 29-bit extended ID) side of the
    # simulator alongside the light-vehicle 11-bit signals. On by default;
    # set MCP_CAN_J1939_ENABLED=false for an 11-bit-only bus.
    j1939_enabled: bool = True
    # Wildcard by default for the zero-friction demo experience (e.g. MCP
    # Inspector connecting from a browser); override before any real
    # deployment. Credentialed CORS is only enabled once this is narrowed to
    # specific origins -- allow_credentials=True with a wildcard origin is a
    # combination browsers reject outright, so it's never turned on for "*".
    cors_allow_origins: List[str] = ["*"]

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
