import logging
import unittest
from unittest.mock import MagicMock, patch

from edge_node.bootstrap import create_container_reconciler
from edge_node.logging_utils import get_logger


class LoggingTests(unittest.TestCase):
    def test_shared_logger_does_not_duplicate_handlers(self):
        logger = get_logger("edge_node.synthetic")
        before = len(logger.handlers)

        get_logger("edge_node.synthetic")

        self.assertEqual(len(logger.handlers), before)
        self.assertEqual(logger.level, logging.INFO)
        self.assertFalse(logger.propagate)

    def test_runtime_messages_use_levels_without_payload(self):
        with patch("edge_node.bootstrap.logger") as logger:
            with patch.dict(
                "os.environ",
                {"EDGE_ENABLE_CONTAINER_RUNTIME": "false"},
                clear=False,
            ):
                create_container_reconciler("synthetic-node")

        logger.info.assert_called_once_with(
            "container runtime disabled; using simulation mode"
        )
        logger.warning.assert_not_called()
        logger.error.assert_not_called()

    def test_runtime_warning_and_error_levels_are_safe(self):
        engine = MagicMock()
        engine.ping.return_value = False
        with patch.dict("os.environ", {"EDGE_ENABLE_CONTAINER_RUNTIME": "true"}):
            with patch("edge_node.bootstrap.logger") as logger:
                create_container_reconciler(
                    "synthetic-node",
                    docker_engine_factory=lambda: engine,
                    reconciler_factory=MagicMock(),
                )
        logger.warning.assert_called_once_with(
            "Docker Engine unavailable; continuing consensus only"
        )
        logger.error.assert_not_called()

        with patch.dict("os.environ", {"EDGE_ENABLE_CONTAINER_RUNTIME": "true"}):
            with patch("edge_node.bootstrap.logger") as logger:
                create_container_reconciler(
                    "synthetic-node",
                    docker_engine_factory=lambda: (_ for _ in ()).throw(
                        RuntimeError("synthetic failure")
                    ),
                    reconciler_factory=MagicMock(),
                )
        logger.error.assert_called_once_with(
            "Docker runtime initialization failed"
        )
