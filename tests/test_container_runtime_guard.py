import os
import unittest
from unittest.mock import patch

from edge_node.bootstrap import (
    CONTAINER_RUNTIME_ENV,
    create_container_reconciler,
)


class ContainerRuntimeGuardTests(unittest.TestCase):
    def test_default_mode_never_calls_docker_or_creates_reconciler(self):
        environment = {
            key: value
            for key, value in os.environ.items()
            if key != CONTAINER_RUNTIME_ENV
        }

        with patch.dict(os.environ, environment, clear=True):
            with patch(
                "edge_node.infrastructure.docker_engine.docker.from_env"
            ) as docker_from_env:
                with patch(
                    "edge_node.application.container_reconciler."
                    "ContainerReconciler"
                ) as reconciler_class:
                    reconciler = create_container_reconciler("edge-1")

        self.assertIsNone(reconciler)
        docker_from_env.assert_not_called()
        reconciler_class.assert_not_called()

    def test_false_value_never_calls_docker(self):
        with patch.dict(
            os.environ,
            {CONTAINER_RUNTIME_ENV: "false"},
            clear=False,
        ):
            with patch(
                "edge_node.infrastructure.docker_engine.docker.from_env"
            ) as docker_from_env:
                reconciler = create_container_reconciler("edge-1")

        self.assertIsNone(reconciler)
        docker_from_env.assert_not_called()

    def test_enabled_mode_keeps_existing_docker_flow(self):
        with patch.dict(
            os.environ,
            {CONTAINER_RUNTIME_ENV: "true"},
            clear=False,
        ):
            with patch(
                "edge_node.infrastructure.docker_engine.DockerEngine"
            ) as docker_engine_class:
                with patch(
                    "edge_node.application.container_reconciler."
                    "ContainerReconciler"
                ) as reconciler_class:
                    with patch("builtins.print"):
                        docker_engine = docker_engine_class.return_value
                        docker_engine.ping.return_value = True

                        reconciler = create_container_reconciler("edge-1")

        docker_engine_class.assert_called_once_with()
        docker_engine.ping.assert_called_once_with()
        reconciler_class.assert_called_once_with(
            node_id="edge-1",
            container_engine=docker_engine,
        )
        self.assertIs(reconciler, reconciler_class.return_value)


if __name__ == "__main__":
    unittest.main()
