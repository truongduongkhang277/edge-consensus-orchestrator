import json
import os
import threading
import time
from dataclasses import asdict
from pathlib import Path

from ..domain.models import LogEntry


class JsonStateRepository:
    """
    Lưu trạng thái Raft và Distributed Log xuống file JSON.
    """

    def __init__(
        self,
        data_dir: str,
        node_id: str
    ):
        self.path = (
            Path(data_dir)
            / f"{node_id}.json"
        )

        self.path.parent.mkdir(
            parents=True,
            exist_ok=True
        )

    def load(self) -> dict:
        """
        Đọc trạng thái đã lưu khi Edge Node khởi động.
        """

        if not self.path.exists():
            return {}

        try:
            content = self.path.read_text(
                encoding="utf-8"
            )

            return json.loads(content)

        except (
            ValueError,
            OSError,
            TypeError
        ):
            return {}

    def save(
        self,
        term: int,
        voted_for: str | None,
        commit_index: int,
        log: list[LogEntry]
    ):
        """
        Ghi trạng thái an toàn trên Windows.
        """

        state = {
            "term": term,
            "voted_for": voted_for,
            "commit_index": commit_index,
            "log": [
                asdict(entry)
                for entry in log
            ]
        }

        temporary_file = self.path.with_name(
            f"{self.path.stem}-"
            f"{os.getpid()}-"
            f"{threading.get_ident()}-"
            f"{time.time_ns()}.tmp"
        )

        temporary_file.write_text(
            json.dumps(
                state,
                ensure_ascii=False,
                indent=2
            ),
            encoding="utf-8"
        )

        for attempt in range(10):
            try:
                os.replace(
                    temporary_file,
                    self.path
                )
                return

            except PermissionError:
                if attempt == 9:
                    raise

                time.sleep(0.05)