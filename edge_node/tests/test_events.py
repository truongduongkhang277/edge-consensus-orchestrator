import threading
import unittest
from unittest.mock import patch

from edge_node.application.events import EventRecorder


class EventRecorderTests(unittest.TestCase):
    def test_record_preserves_event_and_emits_log_message(self):
        recorder = EventRecorder(
            node_id="edge-1",
            lock=threading.RLock(),
        )
        message = "synthetic startup message"

        with patch("edge_node.application.events.logger") as logger:
            recorder.record("NODE_START", message)

        events = recorder.get_all()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["message"], message)
        logger.log.assert_called_once_with(
            20,
            "[%s] [%s] %s",
            "edge-1",
            "NODE_START",
            message,
            extra={"event_kind": "NODE_START", "node_id": "edge-1"},
        )


if __name__ == "__main__":
    unittest.main()
