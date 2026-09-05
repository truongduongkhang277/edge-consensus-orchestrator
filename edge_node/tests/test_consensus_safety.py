import tempfile
import unittest

from edge_node.application.consensus import RaftNode


class ConsensusSafetyTests(unittest.TestCase):
    def _leader(self, data_dir: str, peers=None):
        node = RaftNode(
            node_id="n1",
            peers=peers or {},
            data_dir=data_dir
        )
        node.role = "leader"
        node.leader_id = "n1"
        node.term = 1
        node.send_heartbeats = lambda: None
        return node

    def test_single_node_commit_updates_last_applied(self):
        with tempfile.TemporaryDirectory() as data_dir:
            node = self._leader(data_dir)

            status, _ = node.orchestrate({
                "operation": "DEPLOY",
                "service": "patient-api",
                "target": "n1",
                "replicas": 1
            })

            self.assertEqual(status, 201)
            self.assertEqual(node.commit_index, 1)
            self.assertEqual(node.last_applied, 1)
            self.assertTrue(node.log[0].committed)

    def test_rejected_proposal_is_removed(self):
        with tempfile.TemporaryDirectory() as data_dir:
            node = self._leader(
                data_dir,
                peers={"n2": "http://127.0.0.1:9999"}
            )
            node._replicate_proposal = (
                lambda entry, payload: 1
            )

            status, result = node.orchestrate({
                "operation": "DEPLOY",
                "service": "patient-api",
                "target": "n1",
                "replicas": 1
            })

            self.assertEqual(status, 503)
            self.assertEqual(result["error"], "Không đạt đa số")
            self.assertEqual(node.commit_index, 0)
            self.assertEqual(node.last_applied, 0)
            self.assertEqual(node.log, [])
            self.assertEqual(node.services, {})

    def test_committed_prefix_cannot_be_overwritten(self):
        with tempfile.TemporaryDirectory() as data_dir:
            node = self._leader(data_dir)
            status, _ = node.orchestrate({
                "operation": "DEPLOY",
                "service": "patient-api",
                "target": "n1",
                "replicas": 1
            })
            self.assertEqual(status, 201)

            result = node.append_entries({
                "term": 1,
                "leader_id": "n2",
                "leader_commit": 1,
                "entries": [{
                    "index": 1,
                    "term": 1,
                    "command": {
                        "operation": "DEPLOY",
                        "service": "different-api",
                        "target": "n2",
                        "replicas": 1
                    },
                    "committed": True
                }]
            })

            self.assertFalse(result["success"])
            self.assertIn("patient-api", node.services)
            self.assertNotIn("different-api", node.services)


if __name__ == "__main__":
    unittest.main()
