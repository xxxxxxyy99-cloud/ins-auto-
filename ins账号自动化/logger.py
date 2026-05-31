"""Structured logging — writes to both DB (activity_log) and console."""

import sys
import os
from datetime import datetime

class ActivityLogger:
    LEVELS = {"debug": 0, "info": 1, "warn": 2, "error": 3}

    def __init__(self, source: str = "system"):
        self._source = source

    def _log(self, severity: str, event: str, product: str | None = None,
             message: str | None = None, metadata: dict | None = None):
        ts = datetime.now().strftime("%H:%M:%S")
        prefix = f"[{ts}] [{severity.upper()}] [{self._source}]"
        msg = f" {message}" if message else ""
        product_str = f" ({product})" if product else ""
        try:
            print(f"{prefix}{product_str}{msg}", file=sys.stderr)
        except OSError:
            pass

        try:
            from .db import log_event
            log_event(event, product, message, metadata, severity)
        except Exception:
            pass

    def info(self, event: str, product: str | None = None, message: str | None = None, metadata: dict | None = None):
        self._log("info", event, product, message, metadata)

    def warn(self, event: str, product: str | None = None, message: str | None = None, metadata: dict | None = None):
        self._log("warn", event, product, message, metadata)

    def error(self, event: str, product: str | None = None, message: str | None = None, metadata: dict | None = None):
        self._log("error", event, product, message, metadata)

    def debug(self, event: str, product: str | None = None, message: str | None = None, metadata: dict | None = None):
        self._log("debug", event, product, message, metadata)


_LOG = ActivityLogger("system")


def get_logger(source: str = "automation") -> ActivityLogger:
    return ActivityLogger(source)