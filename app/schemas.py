from typing import Optional

from pydantic import BaseModel, field_validator, Field, ConfigDict


class DocumentCreate(BaseModel):
    title: str
    content: str
    doc_metadata: Optional[dict] = Field(default=None, alias="metadata")
    model_config = ConfigDict(populate_by_name=True)

    @field_validator("content")
    @classmethod
    def validate_content_not_empty(cls, v: str) -> str:
        if not v or not v.strip():
            raise ValueError("Content cannot be empty or contain only whitespaces")
        return v


class DocumentResponse(BaseModel):
    id: int
    title: str
    status: str
    chunk_count: int


class SearchResult(BaseModel):
    chunk_id: int
    document_title: str
    content: str
    score: float
    doc_metadata: Optional[dict] = Field(default=None, alias="metadata")
    model_config = ConfigDict(populate_by_name=True)


class DocumentDetail(DocumentResponse):
    content: str
    chunking_time_ms: Optional[float] = None
    embedding_time_ms: Optional[float] = None
    total_processing_time_ms: Optional[float] = None
    doc_metadata: Optional[dict] = Field(default=None, alias="metadata")
    model_config = ConfigDict(populate_by_name=True)


class ReadinessResponse(BaseModel):
    status: str
    checks: dict[str, str]
