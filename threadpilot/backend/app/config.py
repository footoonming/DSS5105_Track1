"""场景 1.1–3.3：统一环境配置。"""
from pathlib import Path
from typing import Literal
from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[2]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=ROOT / 'backend/.env', extra='ignore')
    database_url: SecretStr = SecretStr('mysql+pymysql://threadpilot@127.0.0.1:3306/threadpilot')
    ai_database_url: SecretStr = SecretStr('')
    openai_api_key: SecretStr = SecretStr('')
    openai_base_url: str | None = None
    openai_model: str = 'gpt-4.1'
    intent_api_style: Literal['responses', 'chat_completions'] = 'responses'
    openai_timeout_seconds: float = 60
    data_api_token: SecretStr = SecretStr('')
    sync_enabled: bool = False
    sync_interval_minutes: int = Field(default=5, ge=1)
    sync_files: list[str] = []
    raw_data_dir: Path = ROOT / 'data/raw'
    max_upload_bytes: int = Field(default=10_485_760, ge=1024)
    sql_max_rows: int = Field(default=100, ge=1, le=1000)
    sql_timeout_ms: int = Field(default=5000, ge=100, le=60000)
    sql_agent_steps: int = Field(default=16, ge=4, le=50)
    workflow_db: Path = ROOT / 'backend/runtime/workflow.sqlite3'
    business_now: str = 'live'

