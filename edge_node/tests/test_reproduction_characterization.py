import tempfile
import unittest
from unittest.mock import patch

from edge_node.application.consensus import RaftNode
from edge_node.domain.scheduler import ResourceScheduler
from edge_node.scripts.run_experiments import (
    build_aggregate_rows,
    confidence_interval_95,
)


def configured_peers(count: int) -> dict[str, str]:
    return {
        f"peer-{index}": f"http://127.0.0.1:{5000 + index}"
        for index in range(1, count)
    }


def deploy_command(target: str = "edge-1") -> dict:
    return {
        "operation": "DEPLOY",
        "service": "patient-api",
        "target": target,
        "replicas": 1,
    }


class ReproductionCharacterizationTests(unittest.TestCase):
    def make_node(self, data_dir: str, count: int = 1) -> RaftNode:
        node = RaftNode(
            node_id="edge-1",
            peers=configured_peers(count),
            data_dir=data_dir,
        )
        node.role = "leader"
        node.leader_id = node.id
        node.term = 1
        node.voted_for = node.id
        node.send_heartbeats = lambda: None
        return node

    def test_six_logical_nodes_are_reflected_in_status_and_quorum(self):
        with tempfile.TemporaryDirectory() as data_dir:
            node = self.make_node(data_dir, count=6)
            try:
                status = node.status()
                self.assertEqual(status["configured_nodes"], 6)
                self.assertEqual(status["majority"], 4)
                self.assertEqual(node.majority, 4)
            finally:
                node.stop()

    @unittest.expectedFailure
    def test_leader_is_temporary_per_request(self):
        """Paper behavior: completed requests must release the temporary leader."""
        with tempfile.TemporaryDirectory() as data_dir:
            node = self.make_node(data_dir)
            try:
                status, _ = node.orchestrate(deploy_command())
                self.assertEqual(status, 201)
                self.assertNotEqual(node.role, "leader")
            finally:
                node.stop()

    @unittest.skip(
        "MISSING: request_queue/request_service/request model do not implement "
        "priority, aging, or timestamp ordering."
    )
    def test_priority_aging_and_timestamp_for_multiple_candidates(self):
        self.fail("No paper-compatible candidate queue exists to characterize.")

    def test_loss_of_quorum_does_not_commit_or_deploy(self):
        reconciled = []
        with tempfile.TemporaryDirectory() as data_dir:
            node = self.make_node(data_dir, count=3)
            try:
                node._request_reconcile = lambda: reconciled.append(True)
                node._replicate_proposal = lambda entry, payload: 1

                status, result = node.orchestrate(deploy_command())

                self.assertEqual(status, 503)
                self.assertEqual(result["acks"], 1)
                self.assertEqual(result["required"], 2)
                self.assertEqual(node.commit_index, 0)
                self.assertEqual(node.last_applied, 0)
                self.assertEqual(node.log, [])
                self.assertEqual(node.services, {})
                self.assertEqual(reconciled, [])
            finally:
                node.stop()

    def test_scheduler_ranks_multiple_candidates_by_current_weighted_score(self):
        candidates = ResourceScheduler.rank([
            {
                "node_id": "busy",
                "resources": {"cpu_percent": 70, "memory_percent": 60},
                "service_replicas": 0,
            },
            {
                "node_id": "cool",
                "resources": {"cpu_percent": 20, "memory_percent": 30},
                "service_replicas": 0,
            },
            {
                "node_id": "replica-heavy",
                "resources": {"cpu_percent": 20, "memory_percent": 30},
                "service_replicas": 2,
            },
        ])

        self.assertEqual([item["node_id"] for item in candidates], [
            "cool", "replica-heavy", "busy"
        ])
        self.assertEqual(candidates[0]["score"], 19.0)

    def test_commit_state_precedes_reconcile_request(self):
        observations = []
        with tempfile.TemporaryDirectory() as data_dir:
            node = self.make_node(data_dir)
            try:
                def observe_commit():
                    observations.append((node.commit_index, node.last_applied))

                node._request_reconcile = observe_commit
                status, _ = node.orchestrate(deploy_command())

                self.assertEqual(status, 201)
                self.assertEqual(observations, [(1, 1)])
            finally:
                node.stop()

    def test_successful_orchestration_exposes_eight_section8_metrics(self):
        with tempfile.TemporaryDirectory() as data_dir:
            node = self.make_node(data_dir)
            try:
                status, result = node.orchestrate(deploy_command())
                self.assertEqual(status, 201)
                self.assertEqual(set(result["leader_metrics"]), {
                    "schedule_ms",
                    "proposal_persist_ms",
                    "replication_ms",
                    "commit_persist_ms",
                    "heartbeat_ms",
                    "full_sync_fallbacks",
                })
                self.assertEqual(set(result["gateway_metrics"]), {
                    "queue_wait_ms",
                    "total_ms",
                })
                self.assertEqual(
                    set(node.status()["last_orchestration_metrics"]),
                    {"queue_wait_ms", "total_ms", "status_code"},
                )
            finally:
                node.stop()

    def test_load_experiment_defaults_cover_requested_rates_and_ci95_is_computable(self):
        with patch("sys.argv", ["run_experiments"]):
            from edge_node.scripts.run_experiments import build_parser

            rates = build_parser().parse_args([]).rates

        self.assertEqual(rates, [0.5, 1, 1.5, 2, 2.5, 3])
        self.assertEqual(confidence_interval_95([10.0]), (10.0, 10.0, 10.0))
        aggregate = build_aggregate_rows([
            {
                "rate_rps": 0.5,
                "gateway_count": 1,
                "completed": True,
                "mean_latency_ms": 10,
                "p95_latency_ms": 15,
                "success_rate_percent": 100,
            },
            {
                "rate_rps": 0.5,
                "gateway_count": 1,
                "completed": True,
                "mean_latency_ms": 14,
                "p95_latency_ms": 20,
                "success_rate_percent": 90,
            },
        ])
        self.assertEqual(aggregate[0]["rate_rps"], 0.5)
        self.assertLess(aggregate[0]["ci95_low_ms"], aggregate[0]["ci95_high_ms"])

    @unittest.skip(
        "Requires live gateways and a real six-node load run; network is "
        "intentionally not used by local characterization tests."
    )
    def test_live_load_05_to_3_rps_and_ci95(self):
        self.fail("Run edge_node/scripts/run_experiments.py with live gateways.")


if __name__ == "__main__":
    unittest.main()
