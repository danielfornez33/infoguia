from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    database_url: str = "postgresql://infoguia:infoguia@127.0.0.1:5434/infoguia"
    redis_url: str = "redis://127.0.0.1:6380/0"

    panel_user: str = "admin"
    panel_password: str = "change-me"

    crawl_user_agent: str = "InfoGuiaBot/1.0 (+tu-correo@dominio.com)"
    crawl_rps: float = 0.3
    crawl_burst: int = 1
    daily_cap: int = 8000
    off_peak_only: bool = False
    off_peak_start: int = 0
    off_peak_end: int = 7

    raw_dir: str = "/data/raw"
    seed_urls: str = "https://infoguia.com/ct.asp?key=repuestos-caracas&cat=738&ciud=41"
    discovery_enabled: bool = False
    products_enabled: bool = True
    max_pages_per_listing: int = 30

    http_timeout: float = 30.0
    max_retries: int = 3
    robots_ttl: int = 86400

    proxy_urls: str = ""
    rotate_user_agents: bool = False
    proxy_rotation_enabled: bool = False
    conditional_requests: bool = True

    @property
    def seeds(self) -> list[str]:
        return [item.strip() for item in self.seed_urls.split(",") if item.strip()]

    @property
    def proxies(self) -> list[str]:
        return [item.strip() for item in self.proxy_urls.split(",") if item.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
