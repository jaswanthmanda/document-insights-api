from typing import Literal

from pydantic import BaseModel, Field, ConfigDict


class DocumentCreate(BaseModel):
    user_id: str = Field(min_length=1, max_length=100)
    title: str = Field(min_length=1, max_length=200)
    content: str = Field(min_length=1, max_length=100_000)

    model_config = ConfigDict(str_strip_whitespace=True)


class DocumentAccepted(BaseModel):
    document_id: str
    status: Literal["queued", "completed"]


class DocumentResponse(BaseModel):
    document_id: str
    user_id: str
    title: str
    status: str
    summary: dict | None = None
    error: str | None = None


class DocumentListResponse(BaseModel):
    items: list[DocumentResponse]
    page: int
    page_size: int
    total: int