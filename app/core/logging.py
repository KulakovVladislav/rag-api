import logging
import sys

from app.core.context import request_id_ctx


class RequestFilter(logging.Filter):
    def filter(self, record):
        try:
            request_id = request_id_ctx.get()
        except LookupError:
            request_id = None
        record.request_id = request_id or ""
        return True


def setup_logging():
    logger = logging.getLogger("profiler")
    if not logger.handlers:
        stdout_handler = logging.StreamHandler(sys.stdout)
        formatter = logging.Formatter('%(levelname)s:     %(message)s:     %(request_id)s')
        stdout_handler.setFormatter(formatter)
        stdout_handler.addFilter(RequestFilter())
        logger.addHandler(stdout_handler)
    logger.setLevel(logging.INFO)
    logger.propagate = False
