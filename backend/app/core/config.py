from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_ROOT = Path(__file__).resolve().parents[2]
LOCAL_DATA_DIR = BACKEND_ROOT / ".local-data"


def _sqlite_url(path: Path) -> str:
    return f"sqlite+aiosqlite:///{path.resolve().as_posix()}"


# LLM提供商对应的默认模型
DEFAULT_MODELS: dict[str, str] = {
    "deepseek": "deepseek-v4-flash",
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
    DATABASE_URL: str = _sqlite_url(LOCAL_DATA_DIR / "game_data.db")
    DEBUG: bool = False

    # PostgreSQL for Agent Checkpointer (生产环境使用)
    POSTGRES_URI: str | None = None

    # LLM API Keys (推荐通过环境变量或 .env 注入)
    DEEPSEEK_API_KEY: str | None = None
    ZHIPUAI_API_KEY: str | None = None
    STEPFUN_API_KEY: str | None = None
    QWEN_API_KEY: str | None = None
    DOUBAO_API_KEY: str | None = None

    # TTS API Keys
    MIMO_API_KEY: str | None = None
    # STEPFUN_API_KEY: Optional[str] = None

    # LLM API Base URLs
    DEEPSEEK_API_BASE_URL: str | None = "https://api.deepseek.com"
    ZHIPUAI_API_BASE_URL: str | None = "https://open.bigmodel.cn/api/paas/v4/"
    STEPFUN_API_BASE_URL: str | None = "https://api.stepfun.com/v1"
    QWEN_API_BASE_URL: str | None = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    DOUBAO_API_BASE_URL: str | None = "https://ark.cn-beijing.volces.com/api/v3"
    MIMO_API_BASE_URL: str | None = "https://api.xiaomimimo.com/v1"

    # 默认LLM提供商
    DEFAULT_LLM_PROVIDER: str = "deepseek"
    DEFAULT_LLM_MODEL: str | None = "deepseek-v4-flash"  # 为None时使用DEFAULT_MODELS中的默认值
    SCRIPT_EDITOR_MODEL: str | None = "deepseek-v4-flash"

    # Vector database
    CHROMA_PERSIST_DIR: str = str(LOCAL_DATA_DIR / "chroma")

    model_config = SettingsConfigDict(
        env_file=BACKEND_ROOT / ".env",
        case_sensitive=True,
        extra="ignore",
    )

    @property
    def local_data_dir(self) -> Path:
        return LOCAL_DATA_DIR

    @property
    def audio_dir(self) -> Path:
        return LOCAL_DATA_DIR / "audio"

    @property
    def image_dir(self) -> Path:
        return LOCAL_DATA_DIR / "images"

    def get_llm_model_name(self, provider: str | None = None) -> str:
        """获取LLM模型名称"""
        provider = provider or self.DEFAULT_LLM_PROVIDER
        if provider == self.DEFAULT_LLM_PROVIDER and self.DEFAULT_LLM_MODEL:
            return self.DEFAULT_LLM_MODEL
        return DEFAULT_MODELS.get(provider, "deepseek-v4-flash")

    def get_api_key(self, provider: str) -> str | None:
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

    def get_base_url(self, provider: str) -> str | None:
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
