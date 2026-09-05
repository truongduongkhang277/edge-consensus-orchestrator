import unittest

from edge_node.domain.models import LogEntry
from edge_node.domain.orchestration import ServiceStateMachine


class ServiceStateMachineTests(unittest.TestCase):
    def setUp(self):
        self.machine = ServiceStateMachine()

    def test_deploy_sets_desired_replicas(self):
        self.machine.apply({
            "operation": "DEPLOY",
            "service": "patient-api",
            "target": "edge-1",
            "replicas": 2
        })

        self.assertEqual(
            self.machine.services,
            {"patient-api": {"edge-1": 2}}
        )

    def test_replicate_adds_replicas(self):
        self.machine.apply({
            "operation": "DEPLOY",
            "service": "patient-api",
            "target": "edge-1",
            "replicas": 1
        })
        self.machine.apply({
            "operation": "REPLICATE",
            "service": "patient-api",
            "target": "edge-2",
            "replicas": 2
        })

        self.assertEqual(
            self.machine.services["patient-api"],
            {"edge-1": 1, "edge-2": 2}
        )

    def test_migrate_moves_only_requested_replicas(self):
        self.machine.apply({
            "operation": "DEPLOY",
            "service": "patient-api",
            "target": "edge-1",
            "replicas": 3
        })
        self.machine.apply({
            "operation": "MIGRATE",
            "service": "patient-api",
            "source": "edge-1",
            "target": "edge-2",
            "replicas": 2
        })

        self.assertEqual(
            self.machine.services["patient-api"],
            {"edge-1": 1, "edge-2": 2}
        )

    def test_remove_decreases_replicas(self):
        self.machine.apply({
            "operation": "DEPLOY",
            "service": "patient-api",
            "target": "edge-1",
            "replicas": 3
        })
        self.machine.apply({
            "operation": "REMOVE",
            "service": "patient-api",
            "target": "edge-1",
            "replicas": 1
        })

        self.assertEqual(
            self.machine.services["patient-api"]["edge-1"],
            2
        )

    def test_migrate_rejects_missing_source(self):
        self.machine.apply({
            "operation": "DEPLOY",
            "service": "patient-api",
            "target": "edge-1",
            "replicas": 1
        })

        with self.assertRaises(ValueError):
            self.machine.apply({
                "operation": "MIGRATE",
                "service": "patient-api",
                "source": "edge-3",
                "target": "edge-2",
                "replicas": 1
            })

    def test_remove_last_replica_removes_service(self):
        self.machine.apply({
            "operation": "DEPLOY",
            "service": "patient-api",
            "target": "edge-1",
            "replicas": 1
        })
        self.machine.apply({
            "operation": "REMOVE",
            "service": "patient-api",
            "target": "edge-1",
            "replicas": 1
        })

        self.assertNotIn("patient-api", self.machine.services)

    def test_rebuild_uses_only_committed_entries(self):
        log = [
            LogEntry(
                index=1,
                term=1,
                command={
                    "operation": "DEPLOY",
                    "service": "patient-api",
                    "target": "edge-1",
                    "replicas": 1
                },
                committed=True
            ),
            LogEntry(
                index=2,
                term=1,
                command={
                    "operation": "DEPLOY",
                    "service": "lab-api",
                    "target": "edge-2",
                    "replicas": 1
                },
                committed=False
            )
        ]

        self.machine.rebuild(log)

        self.assertIn("patient-api", self.machine.services)
        self.assertNotIn("lab-api", self.machine.services)


if __name__ == "__main__":
    unittest.main()
