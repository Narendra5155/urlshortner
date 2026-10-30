from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, HttpUrl, computed_field

from app.config import get_settings


class LinkCreate(BaseModel):
    url: HttpUrl
    custom_alias: str | None = Field(
        default=None, min_length=3, max_length=32, pattern=r"^[A-Za-z0-9_-]+$"
    )
    expires_in_days: int | None = Field(default=None, ge=1, le=365)


class LinkOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    code: str
    target_url: str
    created_at: datetime
    expires_at: datetime | None
    clicks: int
    last_clicked_at: datetime | None

    @computed_field
    @property
    def short_url(self) -> str:
        return f"{get_settings().base_url.rstrip('/')}/{self.code}"


class LinkList(BaseModel):
    items: list[LinkOut]
    total: int
