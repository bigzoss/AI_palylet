from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from pydantic import AliasChoices, Field, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parents[1]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(ROOT / ".env copy.example", ROOT / ".env", ROOT / ".env.local"),
        extra="ignore",
        populate_by_name=True,
    )
    data_dir: Path = ROOT / "data"
    database_url: str = Field(default="", repr=False)
    mysql_host: str = Field(default="", validation_alias=AliasChoices("MYSQL_HOST", "DB_HOST"))
    mysql_port: int = Field(
        default=3306, ge=1, le=65535, validation_alias=AliasChoices("MYSQL_PORT", "DB_PORT")
    )
    mysql_database: str = Field(
        default="framecraft", validation_alias=AliasChoices("MYSQL_DATABASE", "DB_NAME")
    )
    mysql_user: str = Field(default="framecraft", validation_alias=AliasChoices("MYSQL_USER", "DB_USER"))
    mysql_password: str = Field(
        default="", repr=False, validation_alias=AliasChoices("MYSQL_PASSWORD", "DB_PASSWORD")
    )
    database_pool_size: int = Field(default=5, ge=1, le=30)
    database_pool_recycle: int = Field(default=1800, ge=60)
    mysql_local_managed: bool = False
    auth_username: str = "admin"
    auth_password: str = Field(default="", repr=False)
    auth_cookie_secure: bool = False
    auth_session_hours: int = Field(default=12, ge=1, le=168)
    openai_api_key: str = Field(default="", repr=False)
    openai_base_url: str = Field(
        default="https://api.openai.com/v1",
        validation_alias=AliasChoices("OPENAI_BASE_URL", "OPENAI_API_BASE"),
    )
    openai_api_mode: Literal["auto", "responses", "chat_completions"] = "auto"
    teacher_model: str = ""
    openai_vision_model: str = ""
    openai_text_model: str = ""
    openai_transcribe_model: str = "whisper-1"
    openai_image_model: str = ""
    openai_image_size: str = "auto"
    openai_image_interval_seconds: float | None = Field(default=None, ge=0, le=60)
    openai_timeout_seconds: int = Field(default=180, ge=10, le=600)
    openai_max_output_tokens: int = Field(default=16000, ge=256, le=32768)
    openai_enable_thinking: bool | None = None
    max_upload_mb: int = 200
    max_duration_seconds: int = 180
    max_frames: int = 120
    ffmpeg_path: str = ""
    ffprobe_path: str = ""

    @field_validator("openai_base_url")
    @classmethod
    def valid_base_url(cls, value):
        value = value.strip().rstrip("/")
        parsed = urlsplit(value)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username
            or parsed.password
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("模型地址必须为不含凭据、查询参数和片段的 HTTP(S) 基础地址")
        return value

    @model_validator(mode="after")
    def provider_defaults(self):
        if not self.openai_text_model and self.teacher_model:
            self.openai_text_model = self.teacher_model
        if self.is_ustc:
            # Tested USTC profile; explicit per-role settings always take precedence.
            if "openai_vision_model" not in self.model_fields_set:
                self.openai_vision_model = self.openai_text_model
            if "openai_image_model" not in self.model_fields_set:
                self.openai_image_model = "qwen-image-2.1"
        if not self.is_official and "openai_transcribe_model" not in self.model_fields_set:
            self.openai_transcribe_model = ""
        return self

    @property
    def is_official(self):
        return urlsplit(self.openai_base_url).hostname == "api.openai.com"

    @property
    def is_ustc(self):
        return urlsplit(self.openai_base_url).hostname == "api.llm.ustc.edu.cn"

    @property
    def provider_name(self):
        return (
            "中科大大模型公共服务平台"
            if self.is_ustc
            else ("OpenAI" if self.is_official else "OpenAI 兼容服务")
        )

    @property
    def api_mode(self):
        return (
            ("responses" if self.is_official else "chat_completions")
            if self.openai_api_mode == "auto"
            else self.openai_api_mode
        )

    @property
    def image_size(self):
        return (
            ("1024x1024" if not self.is_official else "1536x1024")
            if self.openai_image_size == "auto"
            else self.openai_image_size
        )

    @property
    def storage(self) -> Path:
        return self.data_dir.resolve()


settings = Settings()


def safe_path(relative: str) -> Path:
    result = (settings.storage / relative).resolve()
    if not result.is_relative_to(settings.storage):
        raise ValueError("文件路径越界")
    return result
