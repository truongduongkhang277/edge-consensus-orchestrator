from __future__ import annotations

from abc import ABC, abstractmethod


class ContainerEngine(ABC):
    """
    Giao diện chung cho tầng quản lý container.

    Application chỉ phụ thuộc vào interface này,
    không phụ thuộc trực tiếp Docker SDK.
    """

    @abstractmethod
    def ping(self) -> bool:
        """Kiểm tra Container Engine có hoạt động."""

    @abstractmethod
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
        """
        Bảo đảm service có đúng số replica yêu cầu.
        """

    @abstractmethod
    def remove_service(
        self,
        *,
        node_id: str,
        service: str
    ) -> list[str]:
        """Xóa toàn bộ container của service trên node."""

    @abstractmethod
    def list_containers(
        self,
        *,
        node_id: str | None = None
    ) -> list[dict]:
        """Danh sách container do orchestrator quản lý."""