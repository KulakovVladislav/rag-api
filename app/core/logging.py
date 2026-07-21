import json
import logging
import sys
from datetime import datetime, timezone

from app.core.context import request_id_ctx


class RequestFilter(logging.Filter):
    def filter(self, record):
        # Don't clobber a request_id passed explicitly via extra={} (e.g.
        # process_document_background, which runs after the middleware's
        # ContextVar token has already been reset — request_id_ctx.get()
        # would raise LookupError there).
        if "request_id" not in record.__dict__:
            try:
                record.request_id = request_id_ctx.get()
            except LookupError:
                record.request_id = ""
        return True


# Standard LogRecord attributes — anything else on the record was passed
# via extra={} and should be folded into the JSON output.
_RESERVED_RECORD_ATTRS = {
    "name", "msg", "args", "levelname", "levelno", "pathname", "filename",
    "module", "exc_info", "exc_text", "stack_info", "lineno", "funcName",
    "created", "msecs", "relativeCreated", "thread", "threadName",
    "processName", "process", "message", "asctime", "taskName",
}


class JsonProfileFormatter(logging.Formatter):
    def format(self, record):
        log_record = {
            "timestamp": datetime.fromtimestamp(record.created, tz=timezone.utc).isoformat(),
            "level": record.levelname,
            "logger_name": record.name,
            "message": record.getMessage(),
            "request_id": getattr(record, "request_id", ""),
        }

        for key, value in record.__dict__.items():
            if key in _RESERVED_RECORD_ATTRS or key == "request_id":
                continue
            log_record[key] = value

        if record.exc_info:
            log_record["exc_info"] = self.formatException(record.exc_info)

        return json.dumps(log_record, ensure_ascii=False, default=str)


def setup_logging():
    stdout_handler = logging.StreamHandler(sys.stdout)
    stdout_handler.setFormatter(JsonProfileFormatter())
    stdout_handler.addFilter(RequestFilter())
    logging.basicConfig(
        level=logging.INFO,
        handlers=[stdout_handler],
        force=True
    )
