from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    can_interface: str = "virtual"
    can_channel: str = "bus0"
    dbc_path: str = "vehicle.dbc"
    mcp_port: int = 6278

    model_config = SettingsConfigDict(
        env_prefix="MCP_CAN_",
        env_file=".env",
        extra="ignore",
    )


def get_settings() -> Settings:
    return Settings()


