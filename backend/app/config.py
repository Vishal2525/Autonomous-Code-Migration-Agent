"""Application settings loaded from environment / backend/.env."""
from pathlib import Path

from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parents[1]  # backend/


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=BASE_DIR / ".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # server
    host: str = "127.0.0.1"
    port: int = 8000
    cors_origins: str = "http://localhost:5173,http://127.0.0.1:5173"
    log_json: bool = False

    # database
    mongodb_uri: str = "mongodb://localhost:27017"
    mongodb_db: str = "code_migration_agent"

    # llm
    llm_provider: str = "groq"  # "gemini" | "groq"
    gemini_api_key: str = ""
    groq_api_key: str = ""
    gemini_model: str = "gemini-2.0-flash"
    groq_model: str = "llama-3.3-70b-versatile"
    llm_temperature: float = 0.2
    llm_max_output_tokens: int = 4096
    llm_max_retries: int = 5

    # agent behaviour
    default_mode: str = "AUTO"  # AUTO | HITL
    max_repair_attempts: int = 5
    max_agent_iterations: int = 30
    crash_after_task: str = ""  # simulate a crash after this task checkpoints

    # workspace + timeouts (seconds)
    workspace_root: Path = BASE_DIR / "workspace"
    clone_timeout: int = 300
    tool_timeout: int = 60
    test_timeout: int = 600
    pip_timeout: int = 900

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


settings = Settings()
