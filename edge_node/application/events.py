import logging
import threading
import time
from collections import deque
from datetime import datetime
from ..logging_utils import get_logger


logger = get_logger(__name__)


def _log_level(kind: str) -> int:
    if kind.endswith(("_ERROR", "_FAILED")):
        return logging.ERROR
    if kind.endswith("_WARNING") or kind.endswith("_TIMEOUT"):
        return logging.WARNING
    return logging.INFO


class EventRecorder:
    """
    Ghi lại sự kiện nghiệp vụ để hiển thị trên web và CMD.
    """

    def __init__(
        self,
        node_id: str,
        lock: threading.RLock,
        max_events: int = 200
    ):
        self.node_id = node_id
        self.lock = lock

        self.items = deque(
            maxlen=max_events
        )

    def record(
        self,
        kind: str,
        message: str,
        **details
    ):
        event = {
            "timestamp": time.time(),

            "time": datetime.now().strftime(
                "%H:%M:%S.%f"
            )[:-3],

            "node": self.node_id,
            "kind": kind,
            "message": message,
            "details": details
        }

        with self.lock:
            self.items.appendleft(event)

        logger.log(
            _log_level(kind),
            "[%s] [%s] %s",
            self.node_id,
            kind,
            message,
            extra={"event_kind": kind, "node_id": self.node_id},
        )

    def get_all(self) -> list[dict]:
        with self.lock:
            return list(self.items)
