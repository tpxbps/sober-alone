from pydantic_settings import BaseSettings
from typing import Optional


# LLM提供商对应的默认模型
DEFAULT_MODELS: dict[str, str] = {
    "zhipuai": "glm-4.7",
    "deepseek": "deepseek-reasoner",
    "stepfun": "step-3.5-flash",
    "alibaba": "qwen3.5-flash-2026-02-23",
    "bytedance": "doubao-seed-2-0-mini-260215",
}


class Settings(BaseSettings):
    """Application settings"""

    # API
    API_V1_PREFIX: str = "/api/v1"
    PROJECT_NAME: str = "Sober Alone"

    # Database
    DATABASE_URL: str = "sqlite+aiosqlite:///./data/game_data.db"
    DEBUG: bool = True

    # PostgreSQL for Agent Checkpointer (生产环境使用)
    POSTGRES_URI: Optional[str] = None

    # LLM API Keys (推荐通过环境变量或 .env 注入)
    DEEPSEEK_API_KEY: Optional[str] = None
    ZHIPUAI_API_KEY: Optional[str] = None
    STEPFUN_API_KEY: Optional[str] = None
    QWEN_API_KEY: Optional[str] = None
    DOUBAO_API_KEY: Optional[str] = None

    # TTS API Keys
    MIMO_API_KEY: Optional[str] = None
    # STEPFUN_API_KEY: Optional[str] = None

    # LLM API Base URLs
    DEEPSEEK_API_BASE_URL: Optional[str] = "https://api.deepseek.com"
    ZHIPUAI_API_BASE_URL: Optional[str] = "https://open.bigmodel.cn/api/paas/v4/"
    STEPFUN_API_BASE_URL: Optional[str] = "https://api.stepfun.com/v1"
    QWEN_API_BASE_URL: Optional[str] = (
        "https://dashscope.aliyuncs.com/compatible-mode/v1"
    )
    DOUBAO_API_BASE_URL: Optional[str] = "https://ark.cn-beijing.volces.com/api/v3"
    MIMO_API_BASE_URL: Optional[str] = "https://api.xiaomimimo.com/v1"

    # 默认LLM提供商
    DEFAULT_LLM_PROVIDER: str = "stepfun"
    DEFAULT_LLM_MODEL: Optional[str] = (
        "step-3.5-flash"  # 为None时使用DEFAULT_MODELS中的默认值
    )

    # Vector database
    CHROMA_PERSIST_DIR: str = "./data/chroma"

    class Config:
        env_file = ".env"
        case_sensitive = True

    def get_llm_model_name(self, provider: str | None = None) -> str:
        """获取LLM模型名称"""
        if self.DEFAULT_LLM_MODEL:
            return self.DEFAULT_LLM_MODEL
        provider = provider or self.DEFAULT_LLM_PROVIDER
        return DEFAULT_MODELS.get(provider, "step-3.5-flash")

    def get_api_key(self, provider: str) -> Optional[str]:
        """获取指定提供商的API Key"""
        key_mapping = {
            "zhipuai": self.ZHIPUAI_API_KEY,
            "deepseek": self.DEEPSEEK_API_KEY,
            "stepfun": self.STEPFUN_API_KEY,
            "alibaba": self.QWEN_API_KEY,
            "bytedance": self.DOUBAO_API_KEY,
            "mimo": self.MIMO_API_KEY,
        }
        return key_mapping.get(provider)

    def get_base_url(self, provider: str) -> Optional[str]:
        """获取指定提供商的API Base URL"""
        url_mapping = {
            "zhipuai": self.ZHIPUAI_API_BASE_URL,
            "deepseek": self.DEEPSEEK_API_BASE_URL,
            "stepfun": self.STEPFUN_API_BASE_URL,
            "alibaba": self.QWEN_API_BASE_URL,
            "bytedance": self.DOUBAO_API_BASE_URL,
            "mimo": self.MIMO_API_BASE_URL,
        }
        return url_mapping.get(provider)


settings = Settings()
