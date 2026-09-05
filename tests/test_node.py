import tempfile
import unittest
from edge_node.app import RaftNode


class NodeTests(unittest.TestCase):
    def test_majority(self):
        with tempfile.TemporaryDirectory() as d:
            node = RaftNode("n1", {"n2": "x", "n3": "y"}, d)
            self.assertEqual(node.majority, 2)

    def test_apply_operations(self):
        with tempfile.TemporaryDirectory() as d:
            node = RaftNode("n1", {}, d)
            node._apply({"operation": "DEPLOY", "service": "api", "target": "n1", "replicas": 1})
            node._apply({"operation": "REPLICATE", "service": "api", "target": "n2", "replicas": 2})
            node._apply({"operation": "MIGRATE", "service": "api", "source": "n1", "target": "n3"})
            self.assertEqual(node.services["api"], {"n2": 2, "n3": 1})

    def test_single_node_commit(self):
        with tempfile.TemporaryDirectory() as d:
            node = RaftNode("n1", {}, d)
            node.role, node.term, node.leader_id = "leader", 1, "n1"
            status, result = node.orchestrate({"operation": "DEPLOY", "service": "api", "target": "n1"})
            self.assertEqual(status, 201)
            self.assertEqual(result["status"], "committed")
            self.assertEqual(node.commit_index, 1)


if __name__ == "__main__":
    unittest.main()

