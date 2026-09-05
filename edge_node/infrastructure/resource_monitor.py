from __future__ import annotations

import os

import psutil


class ResourceMonitor:
    """
    Thu thập tài nguyên thật của Edge Node.
    """

    @staticmethod
    def snapshot() -> dict:
        cpu_percent = psutil.cpu_percent(
            interval=0.05
        )

        memory = psutil.virtual_memory()

        disk_path = os.getcwd()
        disk = psutil.disk_usage(
            disk_path
        )

        try:
            load_1m = round(
                psutil.getloadavg()[0],
                2
            )

        except (
            AttributeError,
            OSError
        ):
            # Một số phiên bản Windows không hỗ trợ loadavg.
            load_1m = round(
                cpu_percent / 100,
                2
            )

        return {
            "cpu_percent": round(
                cpu_percent,
                2
            ),
            "memory_percent": round(
                memory.percent,
                2
            ),
            "memory_available_mb": round(
                memory.available
                / 1024
                / 1024,
                2
            ),
            "disk_free_mb": round(
                disk.free
                / 1024
                / 1024,
                2
            ),
            # Giữ trường cũ để dashboard vẫn tương thích.
            "load_1m": load_1m
        }