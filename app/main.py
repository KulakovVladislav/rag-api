from fastapi import FastAPI

from app.api.documents import router as document_router
from app.api.search import router as search_router
from app.config import settings

app = FastAPI(title=settings.app_title)

app.include_router(document_router, prefix="/api/documents", tags=["Documents"])
app.include_router(search_router, prefix="/api/search", tags=["Search"])
