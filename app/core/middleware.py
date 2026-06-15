import logging
import time
import traceback
import uuid

from fastapi import FastAPI, Request, Response
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from app.core.context import request_id_ctx

logger = logging.getLogger("profiler")


class ProfilerAndExceptionMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("x-request-id") or str(uuid.uuid4())

        start_time = time.perf_counter()
        token = request_id_ctx.set(request_id)
        try:
            response: Response = await call_next(request)

        except Exception as exc:
            stack_trace = traceback.format_exc()
            logger.error(f"[UNEXPECTED ERROR] {exc}\n{stack_trace}")

            response = JSONResponse(
                status_code=500,
                content={"detail": "Internal Server Error"}
            )

        finally:
            try:
                request_id_ctx.reset(token)
            except Exception:
                pass

        process_time = (time.perf_counter() - start_time) * 1000
        latency_str = f"{process_time:.2f}ms"

        response.headers["X-Response-Time"] = latency_str
        response.headers["X-Request-ID"] = request_id

        logger.info(
            f"[PROFILER] Method: {request.method} | "
            f"Path: {request.url.path} | "
            f"Status: {response.status_code} | "
            f"Latency: {latency_str}"
        )

        return response


def register_middlewares(app: FastAPI) -> None:
    app.add_middleware(ProfilerAndExceptionMiddleware)
