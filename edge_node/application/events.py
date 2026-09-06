import threading
import time
from collections import deque
from datetime import datetime


def _print_safely(line: str) -> None:
    """
    Không để encoding của stdout làm gián đoạn luồng nghiệp vụ.
    """

    try:
        print(line, flush=True)
    except UnicodeEncodeError:
        fallback_line = line.encode(
            "ascii",
            errors="backslashreplace"
        ).decode("ascii")

        try:
            print(fallback_line, flush=True)
        except UnicodeEncodeError:
            # Sự kiện đã được lưu; lỗi console không được phá luồng gọi.
            pass


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

        _print_safely(
            f"[{event['time']}] "
            f"[{self.node_id}] "
            f"[{kind}] "
            f"{message}"
        )

    def get_all(self) -> list[dict]:
        with self.lock:
            return list(self.items)
