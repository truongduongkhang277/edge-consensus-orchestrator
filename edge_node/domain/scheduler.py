from __future__ import annotations


class ResourceScheduler:
    """
    Xếp hạng Edge Node theo tài nguyên.

    Score càng thấp thì node càng phù hợp.
    """

    CPU_WEIGHT = 0.5
    MEMORY_WEIGHT = 0.3
    REPLICA_WEIGHT = 0.2

    @staticmethod
    def _clamp(
        value: float,
        minimum: float = 0.0,
        maximum: float = 100.0
    ) -> float:
        return max(
            minimum,
            min(value, maximum)
        )

    @classmethod
    def evaluate(
        cls,
        node_status: dict
    ) -> dict:
        resources = node_status.get(
            "resources",
            {}
        )

        cpu_percent = cls._clamp(
            float(
                resources.get(
                    "cpu_percent",
                    100
                )
            )
        )

        memory_percent = cls._clamp(
            float(
                resources.get(
                    "memory_percent",
                    100
                )
            )
        )

        service_replicas = max(
            0,
            int(
                node_status.get(
                    "service_replicas",
                    0
                )
            )
        )

        # Mỗi replica được quy đổi thành 25% tải logic.
        replica_load = cls._clamp(
            service_replicas * 25
        )

        score = (
            cls.CPU_WEIGHT
            * cpu_percent
            + cls.MEMORY_WEIGHT
            * memory_percent
            + cls.REPLICA_WEIGHT
            * replica_load
        )

        return {
            "node_id": node_status["node_id"],
            "score": round(score, 2),
            "cpu_percent": cpu_percent,
            "memory_percent": memory_percent,
            "service_replicas": service_replicas,
            "replica_load": replica_load
        }

    @classmethod
    def rank(
        cls,
        node_statuses: list[dict],
        excluded_nodes: set[str] | None = None
    ) -> list[dict]:
        excluded_nodes = (
            excluded_nodes or set()
        )

        candidates = [
            cls.evaluate(status)
            for status in node_statuses
            if status.get("node_id")
            not in excluded_nodes
        ]

        return sorted(
            candidates,
            key=lambda candidate: (
                candidate["score"],
                candidate["node_id"]
            )
        )