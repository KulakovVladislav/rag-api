from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_title: str
    database_url: str
    test_database_url: str
    redis_url: str = "redis://redis:6379/0"
    search_cache_ttl: int = 60

    db_host: str = Field(validation_alias="POSTGRES_HOST")
    db_port: int = Field(validation_alias="POSTGRES_PORT")

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False
    )


settings = Settings()
