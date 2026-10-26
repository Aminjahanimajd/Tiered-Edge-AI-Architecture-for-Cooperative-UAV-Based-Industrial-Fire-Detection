import unittest

from drone_enhanced_core.px4_sim_adapter import (
    SIMULATION_ACKNOWLEDGEMENT,
    EnuPosition,
    NedPosition,
    SimulationCommandGuard,
    absolute_enu_to_local_ned,
    landing_position_valid,
    setpoint_reached,
)


class Px4SimulationAdapterTests(unittest.TestCase):
    def test_scout_absolute_enu_target_becomes_home_relative_ned(self):
        target = EnuPosition(9.0, 5.0, 4.0)
        scout_home = EnuPosition(-4.0, 0.0, 0.0)
        self.assertEqual(
            absolute_enu_to_local_ned(target, scout_home),
            NedPosition(5.0, 13.0, -4.0),
        )

    def test_guard_fails_without_exact_sitl_acknowledgement(self):
        with self.assertRaises(PermissionError):
            SimulationCommandGuard("yes", "sentinel")

    def test_guard_uses_distinct_namespaces_and_system_ids(self):
        sentinel = SimulationCommandGuard(SIMULATION_ACKNOWLEDGEMENT, "sentinel")
        scout = SimulationCommandGuard(SIMULATION_ACKNOWLEDGEMENT, "scout")
        self.assertEqual(
            sentinel.topic("/fmu/in/vehicle_command"),
            "/sentinel/fmu/in/vehicle_command",
        )
        self.assertEqual(
            scout.topic("/fmu/in/vehicle_command"),
            "/scout/fmu/in/vehicle_command",
        )
        sentinel.validate_status_identity(2)
        scout.validate_status_identity(3)
        with self.assertRaises(PermissionError):
            sentinel.validate_status_identity(3)

    def test_non_allowlisted_topic_is_rejected(self):
        guard = SimulationCommandGuard(SIMULATION_ACKNOWLEDGEMENT, "sentinel")
        with self.assertRaises(PermissionError):
            guard.topic("/fmu/in/actuator_motors")

    def test_out_of_geofence_target_is_rejected(self):
        guard = SimulationCommandGuard(SIMULATION_ACKNOWLEDGEMENT, "scout")
        with self.assertRaisesRegex(ValueError, "outside"):
            guard.validate_target(EnuPosition(21.0, 5.0, 4.0), 20, 30, 8)

    def test_shifted_geofence_includes_scout_home(self):
        guard = SimulationCommandGuard(SIMULATION_ACKNOWLEDGEMENT, "scout")
        self.assertEqual(
            guard.validate_target(
                EnuPosition(-4.0, 0.0, 0.0),
                width_m=25.0,
                length_m=30.0,
                maximum_altitude_m=8.0,
                minimum_east_m=-5.0,
            ),
            EnuPosition(-4.0, 0.0, 0.0),
        )

    def test_setpoint_reached_uses_separate_horizontal_and_vertical_limits(self):
        target = NedPosition(5.0, 13.0, -4.0)
        self.assertTrue(setpoint_reached(NedPosition(5.3, 12.7, -3.8), target))
        self.assertFalse(setpoint_reached(NedPosition(5.8, 13.0, -4.0), target))
        self.assertFalse(setpoint_reached(NedPosition(5.0, 13.0, -3.5), target))

    def test_landing_position_gate_rejects_large_home_error(self):
        self.assertTrue(landing_position_valid(NedPosition(0.2, -0.3, 0.1)))
        self.assertFalse(landing_position_valid(NedPosition(-4.3, -0.3, 0.05)))
