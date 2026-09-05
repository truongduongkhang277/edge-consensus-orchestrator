from __future__ import annotations

from .models import LogEntry


class ServiceStateMachine:
    """
    Quản lý desired state của các microservice sau khi log đã commit.

    services có cấu trúc:

    {
        "patient-api": {
            "edge-1": 1,
            "edge-2": 2
        }
    }

    Ngữ nghĩa thao tác:

    - DEPLOY: đặt số replica mong muốn tại target.
    - REPLICATE: tăng thêm replica tại target.
    - MIGRATE: chuyển một số replica từ source sang target.
    - REMOVE: giảm một số replica tại target.
    """

    VALID_OPERATIONS = {
        "DEPLOY",
        "REPLICATE",
        "MIGRATE",
        "REMOVE"
    }

    def __init__(self):
        self.services: dict[str, dict[str, int]] = {}

    def rebuild(self, log: list[LogEntry]):
        """Khôi phục desired state từ phần log đã commit."""

        self.services = {}

        for entry in log:
            if entry.committed:
                self.apply(entry.command)

    @staticmethod
    def _read_replicas(command: dict) -> int:
        value = command.get("replicas", 1)

        # bool là lớp con của int trong Python nên phải loại riêng.
        if isinstance(value, bool):
            raise ValueError(
                "replicas phải là số nguyên dương"
            )

        try:
            replicas = int(value)
        except (TypeError, ValueError) as error:
            raise ValueError(
                "replicas phải là số nguyên dương"
            ) from error

        if replicas < 1:
            raise ValueError(
                "replicas phải lớn hơn hoặc bằng 1"
            )

        return replicas

    @staticmethod
    def _read_name(
        command: dict,
        field: str
    ) -> str:
        value = command.get(field)

        if not isinstance(value, str) or not value.strip():
            raise ValueError(
                f"{field} không được để trống"
            )

        return value.strip()

    def validate(self, command: dict):
        """Kiểm tra chuyển trạng thái mà không thay đổi dữ liệu."""

        operation = self._read_name(
            command,
            "operation"
        ).upper()

        if operation not in self.VALID_OPERATIONS:
            raise ValueError("Lệnh không hợp lệ")

        service = self._read_name(
            command,
            "service"
        )
        target = self._read_name(
            command,
            "target"
        )
        replicas = self._read_replicas(command)

        # DEPLOY có thể tạo service mới hoặc đặt lại desired replicas.
        if operation == "DEPLOY":
            return

        locations = self.services.get(service)

        if not locations:
            raise ValueError(
                f"Service {service} chưa được triển khai"
            )

        if operation == "REPLICATE":
            return

        if operation == "MIGRATE":
            source = self._read_name(
                command,
                "source"
            )

            if source == target:
                raise ValueError(
                    "Node nguồn và node đích phải khác nhau"
                )

            source_replicas = int(
                locations.get(source, 0)
            )

            if source_replicas < replicas:
                raise ValueError(
                    f"{service} tại {source} chỉ có "
                    f"{source_replicas} replica"
                )

            return

        target_replicas = int(
            locations.get(target, 0)
        )

        if target_replicas < replicas:
            raise ValueError(
                f"{service} tại {target} chỉ có "
                f"{target_replicas} replica"
            )

    def apply(self, command: dict):
        """Áp dụng một lệnh đã được consensus commit."""

        self.validate(command)

        operation = str(
            command["operation"]
        ).strip().upper()
        service = str(command["service"]).strip()
        target = str(command["target"]).strip()
        replicas = self._read_replicas(command)

        if operation == "DEPLOY":
            self._deploy(
                service=service,
                target=target,
                replicas=replicas
            )

        elif operation == "REPLICATE":
            self._replicate(
                service=service,
                target=target,
                replicas=replicas
            )

        elif operation == "MIGRATE":
            self._migrate(
                service=service,
                source=str(command["source"]).strip(),
                target=target,
                replicas=replicas
            )

        elif operation == "REMOVE":
            self._remove(
                service=service,
                target=target,
                replicas=replicas
            )

    def _deploy(
        self,
        service: str,
        target: str,
        replicas: int
    ):
        locations = self.services.setdefault(
            service,
            {}
        )
        locations[target] = replicas

    def _replicate(
        self,
        service: str,
        target: str,
        replicas: int
    ):
        locations = self.services[service]
        locations[target] = (
            int(locations.get(target, 0))
            + replicas
        )

    def _migrate(
        self,
        service: str,
        source: str,
        target: str,
        replicas: int
    ):
        locations = self.services[service]
        remaining = int(locations[source]) - replicas

        if remaining == 0:
            locations.pop(source)
        else:
            locations[source] = remaining

        locations[target] = (
            int(locations.get(target, 0))
            + replicas
        )

    def _remove(
        self,
        service: str,
        target: str,
        replicas: int
    ):
        locations = self.services[service]
        remaining = int(locations[target]) - replicas

        if remaining == 0:
            locations.pop(target)
        else:
            locations[target] = remaining

        if not locations:
            self.services.pop(service)