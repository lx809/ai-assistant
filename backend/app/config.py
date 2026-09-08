from functools import lru_cache
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
PROJECT_DIR = BACKEND_DIR.parent


class Settings(BaseSettings):
    deepseek_api_key: str = ""
    deepseek_base_url: str = "https://api.deepseek.com"
    deepseek_model: str = "deepseek-chat"
    embedding_model: Path = BACKEND_DIR / "models" / "bge-large-zh-v1.5"
    knowledge_dir: Path = PROJECT_DIR / "knowledge"
    data_dir: Path = PROJECT_DIR / "data"
    db_path: Path = PROJECT_DIR / "data" / "assistant.db"
    mcp_config_path: Path = PROJECT_DIR / "mcp_config.json"
    host: str = "127.0.0.1"
    port: int = 8000
    log_level: str = "INFO"
    log_dir: Path = PROJECT_DIR / "data" / "logs"

    model_config = SettingsConfigDict(
        env_file=BACKEND_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache  # 缓存配置，避免重复加载
def get_settings() -> Settings:
    return Settings()


