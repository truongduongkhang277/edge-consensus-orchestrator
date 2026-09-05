from __future__ import annotations

import re

import docker
from docker.errors import DockerException, ImageNotFound, NotFound

from .container_engine import ContainerEngine


class DockerEngine(ContainerEngine):
    MANAGED_LABEL = "edge.orchestrator.managed"
    NODE_LABEL = "edge.orchestrator.node"
    SERVICE_LABEL = "edge.orchestrator.service"
    REPLICA_LABEL = "edge.orchestrator.replica"

    def __init__(self):
        self.client = docker.from_env()

    def ping(self) -> bool:
        try:
            return bool(self.client.ping())
        except DockerException:
            return False

    @staticmethod
    def _safe_name(value: str) -> str:
        value = value.strip().lower()

        return re.sub(
            r"[^a-z0-9_.-]+",
            "-",
            value
        ).strip("-.")

    def _container_name(
        self,
        node_id: str,
        service: str,
        replica_number: int
    ) -> str:
        safe_node = self._safe_name(node_id)
        safe_service = self._safe_name(service)

        return (
            f"eco-{safe_node}-"
            f"{safe_service}-"
            f"{replica_number}"
        )

    def _labels(
        self,
        node_id: str,
        service: str,
        replica_number: int
    ) -> dict[str, str]:
        return {
            self.MANAGED_LABEL: "true",
            self.NODE_LABEL: node_id,
            self.SERVICE_LABEL: service,
            self.REPLICA_LABEL: str(replica_number)
        }

    @staticmethod
    def _serialize(container) -> dict:
        container.reload()

        attributes = container.attrs
        network_settings = attributes.get(
            "NetworkSettings",
            {}
        )

        raw_ports = (
            network_settings.get("Ports")
            or {}
        )

        published_ports = {}

        for container_port, bindings in (
            raw_ports.items()
        ):
            published_ports[container_port] = sorted({
                binding.get("HostPort")
                for binding in (bindings or [])
                if binding.get("HostPort")
            })

        labels = (
            attributes
            .get("Config", {})
            .get("Labels", {})
            or {}
        )

        return {
            "id": container.short_id,
            "name": container.name,
            "status": container.status,
            "image": (
                attributes
                .get("Config", {})
                .get("Image")
            ),
            "node_id": labels.get(
                DockerEngine.NODE_LABEL
            ),
            "service": labels.get(
                DockerEngine.SERVICE_LABEL
            ),
            "replica": labels.get(
                DockerEngine.REPLICA_LABEL
            ),
            "ports": published_ports
        }

    def list_containers(
        self,
        *,
        node_id: str | None = None
    ) -> list[dict]:
        labels = [
            f"{self.MANAGED_LABEL}=true"
        ]

        if node_id:
            labels.append(
                f"{self.NODE_LABEL}={node_id}"
            )

        containers = self.client.containers.list(
            all=True,
            filters={
                "label": labels
            }
        )

        return [
            self._serialize(container)
            for container in containers
        ]

    def ensure_replicas(
        self,
        *,
        node_id: str,
        service: str,
        image: str,
        replicas: int,
        container_port: int | None = None,
        environment: dict | None = None
    ) -> list[dict]:
        replicas = max(0, int(replicas))

        try:
            self.client.images.get(image)
        except ImageNotFound:
            self.client.images.pull(image)

        desired_names = {
            self._container_name(
                node_id,
                service,
                replica_number
            )
            for replica_number in range(
                1,
                replicas + 1
            )
        }

        # Tạo hoặc khởi động các replica còn thiếu.
        for replica_number in range(
            1,
            replicas + 1
        ):
            container_name = self._container_name(
                node_id,
                service,
                replica_number
            )

            try:
                container = (
                    self.client.containers.get(
                        container_name
                    )
                )

                labels = container.labels or {}

                belongs_to_orchestrator = (
                    labels.get(
                        self.MANAGED_LABEL
                    ) == "true"
                    and labels.get(
                        self.NODE_LABEL
                    ) == node_id
                    and labels.get(
                        self.SERVICE_LABEL
                    ) == service
                )

                if not belongs_to_orchestrator:
                    raise RuntimeError(
                        "Tên container đã được sử dụng: "
                        f"{container_name}"
                    )

                container.reload()

                if container.status != "running":
                    container.start()

            except NotFound:
                port_mapping = None

                if container_port:
                    # Docker tự chọn host port còn trống.
                    port_mapping = {
                        f"{container_port}/tcp": None
                    }

                self.client.containers.run(
                    image=image,
                    name=container_name,
                    detach=True,
                    environment=environment or {},
                    ports=port_mapping,
                    labels=self._labels(
                        node_id,
                        service,
                        replica_number
                    ),
                    restart_policy={
                        "Name": "unless-stopped"
                    }
                )

        # Xóa replica thừa khi scale down.
        existing_containers = (
            self.client.containers.list(
                all=True,
                filters={
                    "label": [
                        (
                            f"{self.MANAGED_LABEL}"
                            "=true"
                        ),
                        (
                            f"{self.NODE_LABEL}"
                            f"={node_id}"
                        ),
                        (
                            f"{self.SERVICE_LABEL}"
                            f"={service}"
                        )
                    ]
                }
            )
        )

        for container in existing_containers:
            if container.name not in desired_names:
                container.remove(force=True)

        return [
            container
            for container in self.list_containers(
                node_id=node_id
            )
            if container["service"] == service
        ]

    def remove_service(
        self,
        *,
        node_id: str,
        service: str
    ) -> list[str]:
        removed_names = []

        containers = self.client.containers.list(
            all=True,
            filters={
                "label": [
                    f"{self.MANAGED_LABEL}=true",
                    f"{self.NODE_LABEL}={node_id}",
                    f"{self.SERVICE_LABEL}={service}"
                ]
            }
        )

        for container in containers:
            removed_names.append(
                container.name
            )

            container.remove(force=True)

        return removed_names