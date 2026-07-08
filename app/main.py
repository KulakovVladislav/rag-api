from fastapi import FastAPI

from app.api.documents import router as document_router
from app.api.search import router as search_router
from app.api.system import router as system_router
from app.config import settings
from app.core.logging import setup_logging
from app.core.middleware import register_middlewares

setup_logging()
app = FastAPI(title=settings.app_title)
app.include_router(system_router, prefix="/system", tags=["System"])
app.include_router(document_router, prefix="/api/documents", tags=["Documents"])
app.include_router(search_router, prefix="/api/search", tags=["Search"])

register_middlewares(app)
