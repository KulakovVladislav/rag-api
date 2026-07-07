import logging
from contextlib import closing

from fastapi import APIRouter, Response
from sqlalchemy import text
from starlette import status

from app.core.redis import get_redis_client
from app.database.db import get_db
from app.schemas import ReadinessResponse
from app.services.embedding_service import get_embedding

logger = logging.getLogger(__name__)
router = APIRouter()


def check_database() -> str:
    try:
        with closing(next(get_db())) as db:
            db.execute(text("SELECT 1"))
        return "ok"
    except Exception as e:
        logger.error(f"Failed to connect with database: {e}")
        return "unreachable"


def check_redis() -> str:
    try:
        get_redis_client().ping()
        return "ok"
    except Exception as e:
        logger.error(f"Failed to connect with Redis: {e}")
        return "unreachable"


async def check_embedding_model() -> str:
    try:
        await get_embedding("healthcheck")
        return "ok"
    except Exception as e:
        logger.error(f"Failed to connect with embedding model: {e}")
        return "unreachable"


@router.get("/live")
def system_alive():
    return {"status": "alive"}


@router.get("/ready", response_model=ReadinessResponse)
async def system_ready(response: Response):
    checks = {
        "database": check_database(),
        "redis": check_redis(),
        "embedding_model": await check_embedding_model()
    }

    if all(status_value == "ok" for status_value in checks.values()):
        return {
            "status": "ready",
            "checks": checks
        }

    response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return {
        "status": "unavailable",
        "checks": checks
    }
