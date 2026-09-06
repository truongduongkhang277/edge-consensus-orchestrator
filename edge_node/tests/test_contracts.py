"""
Characterization tests — Commit 2 (REFACTOR_PLAN.md).

Đóng băng *hợp đồng công khai* hiện tại của RaftNode qua API công khai:

- RaftNode.majority / RaftNode.status() cho cụm cấu hình 1, 3, 5, 10, 12 node
  (majority tính theo số node *cấu hình*, không theo node online; không khởi
  tiến trình nào — chỉ dựng đối tượng RaftNode với peers giả).
- RaftNode.status() — các trường mà HTTP /status dựa vào.
- RaftNode.vote() — hợp đồng vote_granted theo term/log.
- RaftNode.append_entries() — nhân bản log + áp dụng commit.
- RaftNode.orchestrate() — các "HTTP status" mà http_server gửi thẳng
  (201/400/503) thông qua tuple (status_code, result).

Quy ước: không kiểm tra method private; không đóng băng nguyên văn thông báo
lỗi (chỉ kiểm tra mã lỗi + sự hiện diện khóa "error"); không đòi Docker; dùng
TemporaryDirectory cho dữ liệu node.
"""

import tempfile
import unittest

from edge_node.application.consensus import RaftNode

# majority theo số node cấu hình N = len(peers) + 1, quy tắc floor(N/2)+1.
# N=1->1, 3->2, 5->3, 10->6, 12->7.
MAJORITY_BY_CONFIGURED_NODES = {
    1: 1,
    3: 2,
    5: 3,
    10: 6,
    12: 7,
}

STATUS_CONTRACT_KEYS = {
    "node_id",
    "role",
    "term",
    "leader_id",
    "commit_index",
    "last_applied",
    "log_length",
    "configured_nodes",
    "majority",
    "service_replicas",
    "replication",
    "last_orchestration_metrics",
    "resources",
}

STATUS_RESOURCE_KEYS = {
    "cpu_percent",
    "memory_percent",
}


def build_peers(configured_nodes: int, base_port: int = 5000) -> dict[str, str]:
    """Peers giả cho configured_nodes-1 node đồng hành (không khởi tiến trình)."""
    peers: dict[str, str] = {}

    for offset in range(configured_nodes - 1):
        peers[f"peer-{offset + 1}"] = (
            f"http://127.0.0.1:{base_port + offset}"
        )

    return peers


def build_node(
    node_id: str,
    configured_nodes: int,
    data_dir: str,
) -> RaftNode:
    """Dựng RaftNode trong một cụm cấu hình configured_nodes (peers giả)."""
    peers = build_peers(configured_nodes)

    return RaftNode(
        node_id=node_id,
        peers=peers,
        data_dir=data_dir,
    )


def deploy_command(
    service: str = "patient-api",
    target: str = "n1",
    replicas: int = 1,
) -> dict:
    """Lệnh DEPLOY hợp lệ dùng chung cho các kịch bản commit."""
    return {
        "operation": "DEPLOY",
        "service": service,
        "target": target,
        "replicas": replicas,
    }


class MajorityContractTests(unittest.TestCase):
    """majority & configured_nodes cho 1, 3, 5, 10, 12 node cấu hình."""

    def test_majority_and_configured_nodes(self):
        for configured, expected in MAJORITY_BY_CONFIGURED_NODES.items():
            with self.subTest(configured_nodes=configured):
                with tempfile.TemporaryDirectory() as data_dir:
                    node = build_node("n1", configured, data_dir)

                    # majority là property công khai.
                    self.assertEqual(node.majority, expected)

                    # status() phản ánh cùng con số mà HTTP /status hiển thị.
                    status = node.status()
                    self.assertEqual(
                        status["configured_nodes"],
                        configured,
                    )
                    self.assertEqual(status["majority"], expected)

                    node.stop()


class StatusContractTests(unittest.TestCase):
    """status() — public contract dùng cho HTTP /status."""

    def test_status_initial_single_node_shape(self):
        with tempfile.TemporaryDirectory() as data_dir:
            node = build_node("n1", 1, data_dir)

            status = node.status()

            # Không yêu cầu chính xác mọi field, chỉ đóng băng hợp đồng hiện có.
            self.assertTrue(
                STATUS_CONTRACT_KEYS.issubset(status.keys()),
                f"thiếu key so với hợp đồng: "
                f"{STATUS_CONTRACT_KEYS - status.keys()}",
            )

            self.assertEqual(status["node_id"], "n1")
            self.assertEqual(status["role"], "follower")
            self.assertEqual(status["term"], 0)
            self.assertIsNone(status["leader_id"])
            self.assertEqual(status["commit_index"], 0)
            self.assertEqual(status["last_applied"], 0)
            self.assertEqual(status["log_length"], 0)
            self.assertEqual(status["configured_nodes"], 1)
            self.assertEqual(status["majority"], 1)

            # resources hiện diện và đủ field cốt lõi.
            resources = status["resources"]
            self.assertTrue(
                STATUS_RESOURCE_KEYS.issubset(resources.keys())
            )

            node.stop()

    def test_status_role_reflects_term_change_after_vote(self):
        with tempfile.TemporaryDirectory() as data_dir:
            node = build_node("n1", 1, data_dir)

            # Người ứng viên cùng tiến trình log, term cao hơn.
            node.vote({
                "term": 3,
                "candidate_id": "a",
                "last_log_index": 0,
                "last_log_term": 0,
            })

            status = node.status()
            self.assertEqual(status["term"], 3)
            # Chưa bầu xong nên vẫn là follower; majority không đổi.
            self.assertEqual(status["role"], "follower")
            self.assertEqual(status["majority"], 1)

            node.stop()


class VoteContractTests(unittest.TestCase):
    """vote() — hợp đồng vote_granted qua public API."""

    def test_vote_granted_then_same_term_denied_then_stale_term_denied(self):
        with tempfile.TemporaryDirectory() as data_dir:
            node = build_node("n1", 1, data_dir)

            # 1) Người đầu tiên, term cao hơn, log ngang bằng -> được chấp thuận.
            first = node.vote({
                "term": 1,
                "candidate_id": "candidate-a",
                "last_log_index": 0,
                "last_log_term": 0,
            })
            self.assertTrue(first["vote_granted"])
            self.assertEqual(first["term"], 1)

            # 2) Ứng viên khác, cùng term 1 -> từ chối (đã bỏ phiếu).
            second = node.vote({
                "term": 1,
                "candidate_id": "candidate-b",
                "last_log_index": 0,
                "last_log_term": 0,
            })
            self.assertFalse(second["vote_granted"])

            # 3) Ứng viên có term thấp hơn node hiện tại -> từ chối.
            stale = node.vote({
                "term": 0,
                "candidate_id": "candidate-c",
                "last_log_index": 0,
                "last_log_term": 0,
            })
            self.assertFalse(stale["vote_granted"])

            # Mỗi phản hồi luôn trả "term" hiện tại của node.
            self.assertEqual(stale["term"], 1)

            node.stop()


class AppendEntriesContractTests(unittest.TestCase):
    """append_entries() — nhân bản log + áp dụng commit qua public API."""

    def test_follower_applies_committed_entry(self):
        with tempfile.TemporaryDirectory() as data_dir:
            node = build_node("n1", 1, data_dir)

            result = node.append_entries({
                "term": 2,
                "leader_id": "leader-1",
                "prev_log_index": 0,
                "prev_log_term": 0,
                "entries": [{
                    "index": 1,
                    "term": 2,
                    "command": deploy_command(
                        service="patient-api",
                        target="n1",
                        replicas=1,
                    ),
                    "committed": True,
                }],
                "leader_commit": 1,
            })

            self.assertTrue(result["success"])
            self.assertEqual(result["match_index"], 1)

            # Node trở thành follower theo leader, term tăng.
            self.assertEqual(node.role, "follower")
            self.assertEqual(node.leader_id, "leader-1")
            self.assertEqual(node.term, 2)

            # Commit được áp dụng: log, commit_index, services.
            self.assertEqual(node.commit_index, 1)
            self.assertEqual(node.last_applied, 1)
            self.assertEqual(node.services, {"patient-api": {"n1": 1}})
            self.assertEqual(node.status()["log_length"], 1)

            node.stop()

    def test_stale_term_rejected(self):
        with tempfile.TemporaryDirectory() as data_dir:
            node = build_node("n1", 1, data_dir)

            # Đưa node lên term 2.
            node.append_entries({
                "term": 2,
                "leader_id": "leader-1",
                "prev_log_index": 0,
                "prev_log_term": 0,
                "entries": [],
                "leader_commit": 0,
            })

            # AppendEntries term thấp hơn -> từ chối, không hỏng trạng thái.
            stale = node.append_entries({
                "term": 1,
                "leader_id": "leader-0",
                "entries": [],
                "leader_commit": 0,
            })
            self.assertFalse(stale["success"])
            self.assertEqual(node.term, 2)

            node.stop()


class OrchestrateContractTests(unittest.TestCase):
    """orchestrate() — các HTTP status (201/400/503) do http_server gửi thẳng."""

    def _make_leader(self, node: RaftNode):
        node.role = "leader"
        node.leader_id = node.id
        node.term = 1
        node.voted_for = node.id

    def test_single_node_leader_commits_with_201(self):
        with tempfile.TemporaryDirectory() as data_dir:
            node = build_node("n1", 1, data_dir)
            self._make_leader(node)

            code, result = node.orchestrate(deploy_command())

            # orchestrate luôn trả tuple (status_code, payload).
            self.assertIsInstance(code, int)
            self.assertIsInstance(result, dict)
            self.assertEqual(code, 201)
            self.assertEqual(result["status"], "committed")
            self.assertEqual(node.commit_index, 1)
            self.assertEqual(node.last_applied, 1)
            self.assertEqual(node.services, {"patient-api": {"n1": 1}})

            node.stop()

    def test_follower_without_leader_returns_503(self):
        with tempfile.TemporaryDirectory() as data_dir:
            # Node mới: follower, chưa biết leader -> không forward được.
            node = build_node("n1", 3, data_dir)

            code, result = node.orchestrate(deploy_command())

            self.assertEqual(code, 503)
            self.assertIn("error", result)

            node.stop()

    def test_invalid_command_returns_400(self):
        with tempfile.TemporaryDirectory() as data_dir:
            node = build_node("n1", 1, data_dir)

            # Thiếu "service" và "target" -> 400 (validate xảy ra trước vai trò).
            code, result = node.orchestrate({
                "operation": "DEPLOY",
            })

            self.assertEqual(code, 400)
            self.assertIn("error", result)
            # Không commit gì.
            self.assertEqual(node.commit_index, 0)

            node.stop()


if __name__ == "__main__":
    unittest.main()
