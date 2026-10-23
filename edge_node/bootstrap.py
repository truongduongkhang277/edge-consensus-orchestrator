from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import TYPE_CHECKING

from .application.consensus import RaftNode
from .presentation.http_server import (
    create_http_server
)
from .logging_utils import get_logger

if TYPE_CHECKING:
    from .application.container_reconciler import (
        ContainerReconciler
    )


CONTAINER_RUNTIME_ENV = (
    "EDGE_ENABLE_CONTAINER_RUNTIME"
)
ENABLED_ENV_VALUES = {
    "1",
    "true",
    "yes",
    "on"
}

logger = get_logger(__name__)


def parse_peers(
    raw_peers: str
) -> dict[str, str]:
    """
    Chuyển chuỗi:

    edge-2=http://127.0.0.1:8002,
    edge-3=http://127.0.0.1:8003

    thành dictionary.
    """

    peers = {}

    if not raw_peers:
        return peers

    for item in raw_peers.split(","):
        item = item.strip()

        if not item:
            continue

        if "=" not in item:
            raise ValueError(
                f"Peer không hợp lệ: {item}"
            )

        node_id, node_url = item.split(
            "=",
            1
        )

        peers[node_id.strip()] = (
            node_url.strip()
        )

    return peers


def create_argument_parser():
    parser = argparse.ArgumentParser(
        description=(
            "Edge Consensus Orchestrator"
        )
    )

    parser.add_argument(
        "--id",
        required=True,
        help="Mã Edge Node"
    )

    parser.add_argument(
        "--port",
        required=True,
        type=int,
        help="Cổng HTTP"
    )

    parser.add_argument(
        "--host",
        default="0.0.0.0",
        help="Địa chỉ lắng nghe"
    )

    parser.add_argument(
        "--peers",
        default="",
        help="Danh sách các Edge Node khác"
    )

    default_data_dir = os.getenv(
        "DATA_DIR",
        (
            "/data"
            if Path("/data").exists()
            else "data"
        )
    )

    parser.add_argument(
        "--data-dir",
        default=default_data_dir,
        help="Thư mục lưu Distributed Log"
    )

    return parser


def is_container_runtime_enabled() -> bool:
    """
    Docker runtime chỉ được bật bằng cấu hình chủ động.
    """

    configured_value = os.getenv(
        CONTAINER_RUNTIME_ENV,
        "false"
    )

    return (
        configured_value.strip().lower()
        in ENABLED_ENV_VALUES
    )

def create_container_reconciler(
    node_id: str,
    *,
    docker_engine_factory=None,
    reconciler_factory=None,
) -> ContainerReconciler | None:
    """
    Khởi tạo Docker integration khi được bật rõ ràng.

    Chế độ mặc định không import adapter Docker, không tạo
    Docker client và không ping daemon. Raft cùng state machine
    mô phỏng vẫn hoạt động bình thường.
    """

    if not is_container_runtime_enabled():
        logger.info("container runtime disabled; using simulation mode")

        return None

    try:
        if docker_engine_factory is None:
            from .infrastructure.docker_engine import DockerEngine
            docker_engine_factory = DockerEngine

        if reconciler_factory is None:
            from .application.container_reconciler import ContainerReconciler
            reconciler_factory = ContainerReconciler

        docker_engine = docker_engine_factory()

        if not docker_engine.ping():
            logger.warning("Docker Engine unavailable; continuing consensus only")

            return None

        logger.info("Docker Engine connected")

        return reconciler_factory(
            node_id=node_id,
            container_engine=docker_engine
        )

    except Exception:
        logger.error("Docker runtime initialization failed")

        return None

def main():
    parser = create_argument_parser()
    arguments = parser.parse_args()

    peers = parse_peers(
        arguments.peers
    )

    container_reconciler = (
        create_container_reconciler(
            arguments.id
        )
    )

    node = RaftNode(
        node_id=arguments.id,
        peers=peers,
        data_dir=arguments.data_dir,
        container_reconciler=(
            container_reconciler
        )
    )

    node.start()

    server = create_http_server(
        node=node,
        host=arguments.host,
        port=arguments.port
    )

    logger.info("node started on configured host and port")

    logger.info("peer configuration loaded")

    try:
        server.serve_forever()

    except KeyboardInterrupt:
        logger.info("node shutdown requested")

    finally:
        node.stop()
        server.server_close()

        logger.info("node stopped")


if __name__ == "__main__":
    main()
