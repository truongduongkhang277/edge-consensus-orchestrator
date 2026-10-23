"""Shared, safe logging configuration for the edge node application."""

from __future__ import annotations

import logging
import sys


LOGGER_NAME = "edge_node"
_HANDLER_MARKER = "_edge_node_shared_handler"


def get_logger(name: str | None = None) -> logging.Logger:
    """Return an application logger with idempotent stream configuration."""

    logger = logging.getLogger(LOGGER_NAME)
    logger.setLevel(logging.INFO)
    logger.propagate = False

    if not any(
        getattr(handler, _HANDLER_MARKER, False)
        for handler in logger.handlers
    ):
        handler = logging.StreamHandler(sys.stdout)
        setattr(handler, _HANDLER_MARKER, True)
        handler.setFormatter(
            logging.Formatter("%(levelname)s %(name)s: %(message)s")
        )
        logger.addHandler(handler)

    return logger
