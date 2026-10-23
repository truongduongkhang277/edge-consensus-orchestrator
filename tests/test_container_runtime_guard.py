import os
import unittest
from unittest.mock import MagicMock, patch

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
            docker_factory = MagicMock()
            reconciler_factory = MagicMock()
            reconciler = create_container_reconciler(
                "edge-1",
                docker_engine_factory=docker_factory,
                reconciler_factory=reconciler_factory,
            )

        self.assertIsNone(reconciler)
        self.assertFalse(docker_factory.called)
        self.assertFalse(reconciler_factory.called)

    def test_false_value_never_calls_docker(self):
        with patch.dict(
            os.environ,
            {CONTAINER_RUNTIME_ENV: "false"},
            clear=False,
        ):
            docker_factory = MagicMock()
            reconciler_factory = MagicMock()
            reconciler = create_container_reconciler(
                "edge-1",
                docker_engine_factory=docker_factory,
                reconciler_factory=reconciler_factory,
            )

        self.assertIsNone(reconciler)
        self.assertFalse(docker_factory.called)
        self.assertFalse(reconciler_factory.called)

    def test_enabled_mode_keeps_existing_docker_flow(self):
        with patch.dict(
            os.environ,
            {CONTAINER_RUNTIME_ENV: "true"},
            clear=False,
        ):
            docker_engine_class = MagicMock()
            reconciler_class = MagicMock()
            docker_engine = docker_engine_class.return_value
            docker_engine.ping.return_value = True
            reconciler = create_container_reconciler(
                "edge-1",
                docker_engine_factory=docker_engine_class,
                reconciler_factory=reconciler_class,
            )

        docker_engine_class.assert_called_once_with()
        docker_engine.ping.assert_called_once_with()
        reconciler_class.assert_called_once_with(
            node_id="edge-1",
            container_engine=docker_engine,
        )
        self.assertIs(reconciler, reconciler_class.return_value)

    def test_enabled_mode_accepts_injected_factories(self):
        class FakeEngine:
            def ping(self):
                return True

        engine = FakeEngine()
        reconciler = object()

        with patch.dict(
            os.environ,
            {CONTAINER_RUNTIME_ENV: "true"},
            clear=False,
        ):
            result = create_container_reconciler(
                "edge-1",
                docker_engine_factory=lambda: engine,
                reconciler_factory=lambda **kwargs: reconciler,
            )

        self.assertIs(result, reconciler)


if __name__ == "__main__":
    unittest.main()
