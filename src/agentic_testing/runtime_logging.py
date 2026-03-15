"""
Shared runtime logging helpers for structured diagnostics.
"""
from __future__ import annotations

import datetime as _dt
import json
import logging
import os
import traceback
from pathlib import Path
from typing import Any, Dict, Optional


_SENSITIVE_FRAGMENTS = (
    "token",
    "api_key",
    "apikey",
    "secret",
    "password",
    "authorization",
    "bearer",
)


def _log_level() -> int:
    level_name = (os.getenv("AGENTIC_LOG_LEVEL") or os.getenv("LOG_LEVEL") or "INFO").upper()
    return getattr(logging, level_name, logging.INFO)


def _safe_json_dumps(value: Any) -> str:
    try:
        return json.dumps(value, default=str, ensure_ascii=True)
    except Exception:
        return json.dumps(str(value), ensure_ascii=True)


def _truncate_text(text: str, max_chars: int) -> str:
    if len(text) <= max_chars:
        return text
    return text[: max_chars - 3] + "..."


def _sanitize(value: Any, max_chars: int = 6000) -> Any:
    if isinstance(value, dict):
        out: Dict[str, Any] = {}
        for k, v in value.items():
            key = str(k)
            if any(fragment in key.lower() for fragment in _SENSITIVE_FRAGMENTS):
                out[key] = "***REDACTED***"
            else:
                out[key] = _sanitize(v, max_chars=max_chars)
        return out
    if isinstance(value, list):
        return [_sanitize(v, max_chars=max_chars) for v in value[:200]]
    if isinstance(value, tuple):
        return [_sanitize(v, max_chars=max_chars) for v in value[:200]]
    if isinstance(value, str):
        return _truncate_text(value, max_chars=max_chars)
    return value


def get_runtime_logger(name: str) -> logging.Logger:
    logger = logging.getLogger(f"agentic_testing.{name}")
    logger.setLevel(_log_level())
    logger.propagate = False
    if not logger.handlers:
        handler = logging.StreamHandler()
        handler.setFormatter(
            logging.Formatter(
                fmt="%(asctime)s %(levelname)s %(name)s %(message)s",
                datefmt="%Y-%m-%dT%H:%M:%S",
            )
        )
        logger.addHandler(handler)
    return logger


def _write_jsonl(workspace_path: Optional[str], payload: Dict[str, Any]) -> None:
    if not workspace_path:
        return
    try:
        path = Path(workspace_path) / "logs" / "runtime_debug.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "a", encoding="utf-8") as f:
            f.write(_safe_json_dumps(payload) + "\n")
    except Exception:
        # Logging should never break runtime flow.
        return


def log_event(
    logger: logging.Logger,
    *,
    event: str,
    level: str = "INFO",
    run_id: Optional[str] = None,
    stage: Optional[str] = None,
    workspace_path: Optional[str] = None,
    context: Optional[Dict[str, Any]] = None,
    exc: Optional[BaseException] = None,
) -> Dict[str, Any]:
    record: Dict[str, Any] = {
        "ts_utc": _dt.datetime.utcnow().isoformat() + "Z",
        "event": event,
        "run_id": run_id or "unknown_run",
        "stage": stage or "",
        "context": _sanitize(context or {}),
    }
    if exc is not None:
        record["exception"] = {
            "type": exc.__class__.__name__,
            "message": str(exc),
            "traceback": _truncate_text(traceback.format_exc(), max_chars=12000),
        }

    level_upper = (level or "INFO").upper()
    line = _safe_json_dumps(record)
    if level_upper == "DEBUG":
        logger.debug(line)
    elif level_upper == "WARNING":
        logger.warning(line)
    elif level_upper == "ERROR":
        logger.error(line)
    else:
        logger.info(line)

    _write_jsonl(workspace_path, record)
    return record

