import importlib.util
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))
SPEC = importlib.util.spec_from_file_location(
    "run_hierarchical_px4_mission",
    ROOT / "tools/run_hierarchical_px4_mission.py",
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class HierarchicalPx4MissionRunnerTests(unittest.TestCase):
    def test_parser_finds_result_after_ros_logging(self):
        value = MODULE.parse_result(
            'ros noise\n{"status":"PASS","event_id":"event-a"}\n'
        )
        self.assertEqual(value["event_id"], "event-a")

    def test_parser_rejects_missing_result(self):
        with self.assertRaisesRegex(ValueError, "no status"):
            MODULE.parse_result("logging without a final result")

    def test_parser_accepts_restart_handoff_result(self):
        value = MODULE.parse_result(
            'ros noise\n{"status":"RESTART_REQUIRED","fault_triggered":true}\n'
        )
        self.assertEqual(value["status"], "RESTART_REQUIRED")

    def test_container_command_preserves_scenario_event_and_safety_token(self):
        scenario = ROOT / "config/simulation_scenarios_v2.json"
        event_log = ROOT / "artifacts/experiments/test/mission_events.jsonl"
        command = MODULE.container_mission_command(
            "container", ROOT, scenario, "scenario-fire-tank-a", event_log, 420
        )
        shell = command[-1]
        self.assertIn("I_ACKNOWLEDGE_PX4_SITL_ONLY", shell)
        self.assertIn("simulation_scenarios_v2.json", shell)
        self.assertIn("scenario-fire-tank-a", shell)
        self.assertIn("mission_events.jsonl", shell)
        self.assertIn("--fault none", shell)
        self.assertIn("--runner-mode single_event", shell)

    def test_container_command_preserves_repeated_confounder_mode(self):
        command = MODULE.container_mission_command(
            "container",
            ROOT,
            ROOT / "config/simulation_scenarios_v2.json",
            "scenario-reflection-pipe-b",
            ROOT / "artifacts/experiments/test/mission_events.jsonl",
            420,
            "none",
            "repeated_confounder",
        )
        self.assertIn("--runner-mode repeated_confounder", command[-1])

    def test_recovery_command_is_explicit_and_cannot_inject_a_fault(self):
        command = MODULE.container_mission_command(
            "container",
            ROOT,
            ROOT / "config/simulation_scenarios_v2.json",
            "scenario-fire-tank-a",
            ROOT / "artifacts/experiments/test/recovery.jsonl",
            420,
            "none",
            "single_event",
            recovery_only=True,
        )
        self.assertIn("--fault none", command[-1])
        self.assertIn("--runner-mode single_event", command[-1])
        self.assertIn("--recovery-only", command[-1])

    def test_container_command_preserves_fault_injection(self):
        command = MODULE.container_mission_command(
            "container",
            ROOT,
            ROOT / "config/simulation_scenarios_v2.json",
            "scenario-fire-tank-a",
            ROOT / "artifacts/experiments/test/mission_events.jsonl",
            420,
            "low_battery",
        )
        self.assertIn("--fault low_battery", command[-1])

    def test_container_command_preserves_duplicate_stale_fault_injection(self):
        command = MODULE.container_mission_command(
            "container",
            ROOT,
            ROOT / "config/simulation_scenarios_v2.json",
            "scenario-fire-tank-a",
            ROOT / "artifacts/experiments/test/mission_events.jsonl",
            420,
            "duplicate_or_stale_verdict",
        )
        self.assertIn("--fault duplicate_or_stale_verdict", command[-1])

    def test_container_command_preserves_invalid_geofence_fault_injection(self):
        command = MODULE.container_mission_command(
            "container",
            ROOT,
            ROOT / "config/simulation_scenarios_v2.json",
            "scenario-fire-tank-a",
            ROOT / "artifacts/experiments/test/mission_events.jsonl",
            420,
            "invalid_or_out_of_geofence_target",
        )
        self.assertIn("--fault invalid_or_out_of_geofence_target", command[-1])

    def test_required_topics_cover_both_vehicle_command_paths(self):
        for vehicle_id in ("sentinel", "scout"):
            self.assertIn(
                f"/{vehicle_id}/fmu/in/vehicle_command",
                MODULE.REQUIRED_TOPICS,
            )
            self.assertIn(
                f"/{vehicle_id}/fmu/out/vehicle_status_v1",
                MODULE.REQUIRED_TOPICS,
            )

    def test_topic_readiness_poll_preserves_failed_attempt_then_passes(self):
        missing = mock.Mock(returncode=0, stdout="/rosout\n", stderr="")
        ready = mock.Mock(
            returncode=0,
            stdout="\n".join(MODULE.REQUIRED_TOPICS) + "\n",
            stderr="",
        )
        with mock.patch.object(
            MODULE.subprocess, "run", side_effect=[missing, ready]
        ), mock.patch.object(MODULE.time, "sleep"):
            completed, checks, attempts = MODULE.wait_for_required_topics(
                ["topic-list"], MODULE.REQUIRED_TOPICS, timeout_s=10.0,
                interval_s=0.1,
            )
        self.assertIs(completed, ready)
        self.assertTrue(all(checks.values()))
        self.assertEqual(len(attempts), 2)
        self.assertFalse(all(attempts[0]["checks"].values()))

    def test_restart_fault_requires_two_real_process_results(self):
        initial_process = mock.Mock(returncode=75)
        recovery_process = mock.Mock(returncode=0)
        initial_result = {
            "status": "RESTART_REQUIRED",
            "injected_fault": "mission_node_restart",
            "fault_triggered": True,
        }
        recovery_result = {
            "status": "PASS",
            "recovery_only": True,
            "mission_states": {"sentinel": "LANDED", "scout": "LANDED"},
        }
        topics = mock.Mock(returncode=0, stdout="ready", stderr="")
        checks = {topic: True for topic in MODULE.REQUIRED_TOPICS}
        with tempfile.TemporaryDirectory(dir=ROOT / "tmp") as directory:
            output = Path(directory) / "restart-run"

            def fake_execute(command, stdout_path, stderr_path, timeout_s):
                recovery = "--recovery-only" in command[-1]
                stdout_path.write_text("result", encoding="utf-8")
                stderr_path.write_text("", encoding="utf-8")
                log_name = (
                    "mission_events_after_restart.jsonl"
                    if recovery else "mission_events_before_restart.jsonl"
                )
                (output / log_name).write_text("{}\n", encoding="utf-8")
                return (
                    (recovery_process, recovery_result)
                    if recovery else (initial_process, initial_result)
                )

            with mock.patch.object(
                MODULE.spawn_probe, "run", return_value={"status": "PASS"}
            ), mock.patch.object(MODULE.time, "sleep"), mock.patch.object(
                MODULE,
                "wait_for_required_topics",
                return_value=(topics, checks, [{"checks": checks}]),
            ), mock.patch.object(
                MODULE,
                "execute_mission",
                side_effect=fake_execute,
            ):
                manifest = MODULE.run(
                    ROOT,
                    ROOT,
                    output,
                    ROOT / "config/simulation_scenarios_v2.json",
                    "scenario-fire-tank-a",
                    "container",
                    "127.0.0.1",
                    fault="mission_node_restart",
                )
        self.assertEqual(manifest["status"], "PASS")
        self.assertEqual(manifest["mission_returncode"], 75)
        self.assertEqual(manifest["recovery_returncode"], 0)
        self.assertIn("--recovery-only", manifest["recovery_command"][-1])


if __name__ == "__main__":
    unittest.main()
