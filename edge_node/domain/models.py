from dataclasses import dataclass
from typing import Any


@dataclass
class LogEntry:
    """
    Một bản ghi trong Distributed Log.
    """

    index: int
    term: int
    command: dict[str, Any]
    committed: bool = False