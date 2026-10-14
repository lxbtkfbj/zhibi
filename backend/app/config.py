from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_prefix="ZHIBI_", env_file=(".env", "../.env"), extra="ignore")

    database_url: str = "postgresql+psycopg://zhibi:zhibi@127.0.0.1:5433/zhibi"
    redis_url: str = "redis://127.0.0.1:6380/0"
    milvus_uri: str = "http://127.0.0.1:19530"
    secret_key: str = ""
    # 首次启动时若没有任何模型配置，用这几项创建一个默认配置（可选）
    default_llm_base_url: str = ""
    default_llm_api_key: str = ""
    default_llm_model: str = ""

    @property
    def checkpoint_dsn(self) -> str:
        """LangGraph 检查点使用原生 psycopg 连接串。"""
        return self.database_url.replace("postgresql+psycopg://", "postgresql://", 1)


@lru_cache
def get_settings() -> Settings:
    return Settings()
