from pydantic import BaseModel


class DocumentCreate(BaseModel):
    title: str
    content: str


class DocumentResponse(BaseModel):
    id: int
    title: str
    chunk_count: int


class SearchResult(BaseModel):
    chunk_id: int
    document_title: str
    content: str
    score: float



class DocumentDetail(DocumentResponse):
    content: str