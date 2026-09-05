from __future__ import annotations

import json
import threading
from pathlib import Path

from ..infrastructure.container_engine import (
    ContainerEngine
)


class ContainerReconciler:
    """
    Đồng bộ desired state trong distributed log
    với actual state của Container Engine.
    """

    def __init__(
        self,
        node_id: str,
        container_engine: ContainerEngine,
        deployment_file: str | None = None
    ):
        self.node_id = node_id
        self.container_engine = container_engine
        self.lock = threading.Lock()

        if deployment_file:
            self.deployment_file = Path(
                deployment_file
            )
        else:
            self.deployment_file = (
                Path(__file__)
                .resolve()
                .parents[1]
                / "config"
                / "deployments.json"
            )

        self.deployments = (
            self._load_deployments()
        )

    def _load_deployments(self) -> dict:
        if not self.deployment_file.exists():
            raise FileNotFoundError(
                "Không tìm thấy cấu hình deployment: "
                f"{self.deployment_file}"
            )

        with self.deployment_file.open(
            "r",
            encoding="utf-8"
        ) as file:
            data = json.load(file)

        if not isinstance(data, dict):
            raise ValueError(
                "deployments.json phải là object JSON"
            )

        return data

    def reload_deployments(self):
        """
        Nạp lại cấu hình mà không cần khởi động lại.
        """

        with self.lock:
            self.deployments = (
                self._load_deployments()
            )

    def reconcile(
        self,
        desired_services: dict
    ) -> dict:
        """
        desired_services có dạng:

        {
            "patient-api": {
                "edge-1": 1,
                "edge-2": 2
            }
        }
        """

        with self.lock:
            actual_containers = (
                self.container_engine
                .list_containers(
                    node_id=self.node_id
                )
            )

            actual_service_names = {
                container["service"]
                for container in actual_containers
                if container.get("service")
            }

            desired_replicas = {}

            for service, nodes in (
                desired_services.items()
            ):
                if not isinstance(nodes, dict):
                    continue

                desired_replicas[service] = max(
                    0,
                    int(
                        nodes.get(
                            self.node_id,
                            0
                        )
                    )
                )

            all_services = (
                set(desired_replicas)
                | actual_service_names
            )

            results = []

            for service in sorted(
                all_services
            ):
                replicas = desired_replicas.get(
                    service,
                    0
                )

                # Service không còn trong desired state.
                if replicas <= 0:
                    removed = (
                        self.container_engine
                        .remove_service(
                            node_id=self.node_id,
                            service=service
                        )
                    )

                    results.append({
                        "service": service,
                        "desired_replicas": 0,
                        "running_replicas": 0,
                        "status": "removed",
                        "removed": removed
                    })

                    continue

                deployment = (
                    self.deployments.get(
                        service
                    )
                )

                if not deployment:
                    results.append({
                        "service": service,
                        "desired_replicas": replicas,
                        "running_replicas": 0,
                        "status": "failed",
                        "error": (
                            "Không có cấu hình deployment "
                            f"cho {service}"
                        )
                    })

                    continue

                try:
                    containers = (
                        self.container_engine
                        .ensure_replicas(
                            node_id=self.node_id,
                            service=service,
                            image=deployment["image"],
                            replicas=replicas,
                            container_port=(
                                deployment.get(
                                    "container_port"
                                )
                            ),
                            environment=(
                                deployment.get(
                                    "environment",
                                    {}
                                )
                            )
                        )
                    )

                    running_replicas = sum(
                        1
                        for container in containers
                        if (
                            container.get("status")
                            == "running"
                        )
                    )

                    status = (
                        "running"
                        if running_replicas == replicas
                        else "degraded"
                    )

                    results.append({
                        "service": service,
                        "desired_replicas": replicas,
                        "running_replicas": (
                            running_replicas
                        ),
                        "status": status,
                        "containers": containers
                    })

                except Exception as error:
                    results.append({
                        "service": service,
                        "desired_replicas": replicas,
                        "running_replicas": 0,
                        "status": "failed",
                        "error": str(error)
                    })

            return {
                "node_id": self.node_id,
                "services": results,
                "containers": (
                    self.container_engine
                    .list_containers(
                        node_id=self.node_id
                    )
                )
            }