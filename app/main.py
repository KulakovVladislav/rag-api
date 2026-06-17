from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.api.documents import router as document_router
from app.api.search import router as search_router
from app.config import settings
from app.core.context import request_id_ctx
from app.core.logging import setup_logging
from app.core.middleware import register_middlewares, logger

setup_logging()
app = FastAPI(title=settings.app_title)

app.include_router(document_router, prefix="/api/documents", tags=["Documents"])
app.include_router(search_router, prefix="/api/search", tags=["Search"])

register_middlewares(app)


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception) -> JSONResponse:
    req_id = request_id_ctx.get("unknown")

    logger.error(
        f"Unhandled exception occurred during request {req_id}: {str(exc)}",
        exc_info=True
    )

    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal Server Error",
            "request_id": req_id
        }
    )