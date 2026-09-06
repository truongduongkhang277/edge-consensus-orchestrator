import io
import sys
import threading
import unittest
from unittest.mock import patch

from edge_node.application.events import EventRecorder


class EventRecorderTests(unittest.TestCase):
    def test_record_preserves_event_when_stdout_cannot_encode_message(self):
        output_buffer = io.BytesIO()
        ascii_stdout = io.TextIOWrapper(
            output_buffer,
            encoding="ascii",
        )
        recorder = EventRecorder(
            node_id="edge-1",
            lock=threading.RLock(),
        )
        message = "Khởi động nút edge-1; đang chạy"

        with patch.object(sys, "stdout", ascii_stdout):
            recorder.record("NODE_START", message)
            ascii_stdout.flush()

        events = recorder.get_all()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["message"], message)
        self.assertIn(
            b"Kh\\u1edfi \\u0111\\u1ed9ng n\\xfat edge-1",
            output_buffer.getvalue(),
        )


if __name__ == "__main__":
    unittest.main()
