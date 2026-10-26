import importlib.util
import unittest
from unittest import mock
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "run_dual_px4_spawn_probe", ROOT / "tools" / "run_dual_px4_spawn_probe.py"
)
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class DualPx4SpawnProbeTests(unittest.TestCase):
    def test_expected_identities_are_unique_and_consistent(self):
        sentinel = MODULE.EXPECTED["sentinel"]
        scout = MODULE.EXPECTED["scout"]
        self.assertNotEqual(sentinel["instance"], scout["instance"])
        self.assertNotEqual(sentinel["model"], scout["model"])
        self.assertNotEqual(sentinel["namespace"], scout["namespace"])
        for row in (sentinel, scout):
            self.assertEqual(row["mavlink_system_id"], row["instance"] + 1)
            self.assertEqual(row["dds_key"], row["instance"] + 1)

    def test_log_analysis_requires_every_marker(self):
        valid = "\n".join([
            "INFO [px4] instance: 1",
            "INFO [gz_bridge] world: industrial_inspection_proxy_v1, model: x500_v2_sentinel_proxy_1",
            "INFO [uxrce_dds_client] init UDP agent IP:127.0.0.1, port:8888",
            "INFO [px4] Startup script returned successfully",
        ])
        self.assertTrue(MODULE.analyze_log("sentinel", valid)["passed"])
        self.assertFalse(MODULE.analyze_log("sentinel", valid.replace("port:8888", "port:9999"))["passed"])

    def test_environment_has_safety_and_namespace_controls(self):
        sentinel = MODULE.launch_environment("sentinel")
        scout = MODULE.launch_environment("scout")
        self.assertEqual(sentinel["HEADLESS"], "1")
        self.assertEqual(sentinel["PX4_UXRCE_DDS_NS"], "sentinel")
        self.assertEqual(scout["PX4_UXRCE_DDS_NS"], "scout")
        self.assertNotIn("PX4_GZ_STANDALONE", sentinel)
        self.assertEqual(scout["PX4_GZ_STANDALONE"], "1")

    def test_gui_environment_is_explicit_and_not_default(self):
        self.assertEqual(MODULE.launch_environment("sentinel")["HEADLESS"], "1")
        self.assertNotIn(
            "HEADLESS", MODULE.launch_environment("sentinel", headless=False)
        )

    def test_launch_command_uses_explicit_instance_working_directory(self):
        runtime = Path("/sim/PX4")
        expected = runtime / "build" / "px4_sitl_default" / "rootfs" / "1"
        with mock.patch.object(Path, "is_dir", return_value=True):
            command = MODULE.launch_command(runtime, "sentinel")
        self.assertEqual(command[-2:], ["-w", str(expected)])
        self.assertEqual(command[:4], [
            str(runtime / "build" / "px4_sitl_default" / "bin" / "px4"),
            "-d", "-i", "1",
        ])

    def test_wait_for_marker_detects_flushed_startup_log(self):
        process = mock.Mock()
        process.poll.return_value = None
        with mock.patch.object(Path, "is_file", return_value=True), mock.patch.object(
            Path, "read_text", return_value="Startup script returned successfully"
        ):
            self.assertTrue(MODULE.wait_for_marker(
                process, Path("probe.log"), "Startup script returned successfully", 0.1
            ))

    def test_duration_waits_when_no_cancel_event_exists(self):
        with mock.patch.object(MODULE.time, "sleep") as sleep:
            self.assertEqual(MODULE.wait_for_duration(12.0), "duration_elapsed")
        sleep.assert_called_once_with(12.0)

    def test_duration_reports_cancellation(self):
        event = mock.Mock()
        event.wait.return_value = True
        self.assertEqual(MODULE.wait_for_duration(12.0, event), "cancelled")
        event.wait.assert_called_once_with(12.0)

    def test_duration_guard(self):
        with self.assertRaisesRegex(ValueError, "at least 5"):
            MODULE.run(ROOT, Path("/missing"), Path("/tmp/unused_dual_px4_probe"), 1.0)

    def test_stop_group_uses_sigint_then_wait(self):
        process = mock.Mock()
        process.poll.return_value = None
        process.pid = 123
        process.returncode = 0
        with mock.patch.object(MODULE.os, "killpg", create=True) as killpg:
            self.assertEqual(MODULE.stop_group(process), 0)
        killpg.assert_called_once_with(123, MODULE.signal.SIGINT)
        process.wait.assert_called_once_with(timeout=8.0)

    def test_stop_group_escalates_to_sigterm_after_timeout(self):
        process = mock.Mock()
        process.poll.return_value = None
        process.pid = 123
        process.returncode = -15
        process.wait.side_effect = [MODULE.subprocess.TimeoutExpired("px4", 8), None]
        with mock.patch.object(MODULE.os, "killpg", create=True) as killpg:
            self.assertEqual(MODULE.stop_group(process), -15)
        self.assertEqual(killpg.call_args_list, [
            mock.call(123, MODULE.signal.SIGINT),
            mock.call(123, MODULE.signal.SIGTERM),
        ])

    def test_route_commands_preserve_vehicle_identity(self):
        completed = mock.Mock(
            returncode=0, stdout="NAV_DLL_ACT: 0 COM_RCL_EXCEPT: 4", stderr=""
        )
        with mock.patch.object(
            MODULE.subprocess, "run", return_value=completed
        ) as run:
            records = MODULE.route_xrce_clients(ROOT, "172.30.176.1")
        self.assertTrue(records["sentinel"]["passed"])
        self.assertTrue(records["scout"]["passed"])
        commands = [call.args[0] for call in run.call_args_list]
        self.assertIn("sentinel", commands[1])
        self.assertIn("scout", commands[7])
        self.assertIn("172.30.176.1", commands[1])
        self.assertEqual(commands[2][-3:], ["set", "NAV_DLL_ACT", "0"])
        self.assertEqual(commands[3][-3:], ["set", "COM_RCL_EXCEPT", "4"])

    def test_route_rejects_non_ip_agent_target(self):
        with self.assertRaises(ValueError):
            MODULE.route_xrce_clients(ROOT, "host.example")

    def test_forced_old_client_stop_is_accepted_only_if_restart_passes(self):
        forced = mock.Mock(
            returncode=255, stdout="timeout, forcing stop", stderr=""
        )
        started = mock.Mock(returncode=0, stdout="", stderr="")
        configured = mock.Mock(returncode=0, stdout="parameter set", stderr="")
        nav_readback = mock.Mock(
            returncode=0, stdout="NAV_DLL_ACT: 0", stderr=""
        )
        rc_readback = mock.Mock(
            returncode=0, stdout="COM_RCL_EXCEPT: 4", stderr=""
        )
        per_vehicle = [
            forced, started, configured, configured, nav_readback, rc_readback
        ]
        with mock.patch.object(
            MODULE.subprocess, "run", side_effect=per_vehicle * 2
        ):
            records = MODULE.route_xrce_clients(ROOT, "172.30.176.1")
        self.assertTrue(all(row["passed"] for row in records.values()))
        self.assertTrue(all(
            row["stop_disposition"] == "FORCED_STOP_AFTER_TIMEOUT"
            for row in records.values()
        ))

if __name__ == "__main__":
    unittest.main()
