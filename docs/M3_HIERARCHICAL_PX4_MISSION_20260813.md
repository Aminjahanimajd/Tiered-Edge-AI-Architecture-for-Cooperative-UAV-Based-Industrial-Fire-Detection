# M3 Hierarchical Dual-PX4 Development Missions — 13 August 2026

## Purpose and safety boundary

I connected the typed two-vehicle mission controller to two distinct PX4
v1.17.0 SITL instances through namespaced ROS 2 Jazzy topics. I executed one
pre-registered confirmed-hazard scenario and one rejected-confounder scenario.
Both used the provisional X500 V2 Sentinel and ModalAI Development Kit/Starling
Scout simulation proxies in the industrial inspection world.

These are development simulation results. No physical vehicle, flight
controller, camera, motor, propeller, network, or laboratory system was used.
Scenario target coordinates are simulator-local ENU ground truth; they are not
vision-derived or geographic localization. Two passing runs do not constitute
a reliability estimate or flight certification.

## Implemented sequence

The executable mission path now contains:

1. identity and topic preflight;
2. Sentinel takeoff;
3. deterministic lawnmower patrol;
4. scenario-defined hazard trigger;
5. Sentinel suspect hold;
6. Scout takeoff and dispatch;
7. Scout navigation to a target-relative safe standoff;
8. verification hold and correlated verdict;
9. confirmed hold or rejected-resume behavior;
10. return to home, landing, and disarming.

All command publication is protected by an exact SITL-only acknowledgement,
vehicle-system-ID verification, namespace-specific topic allowlisting,
geofence validation, obstacle-clearance checks, and bounded command retries.
The physical `HazardAlert`, Scout verdict, and final-decision schemas were not
changed. Simulation positions remain in the versioned scenario manifest.

## Reproducible commands

Confirmed scenario:

```bash
PYTHONPATH=src:tools python3 tools/run_hierarchical_px4_mission.py \
  --output artifacts/experiments/hierarchical_px4_mission_20260813_confirmed_v1 \
  --event-id scenario-fire-tank-a \
  --agent-ip 172.30.176.1 --timeout-s 420 --settle-s 18
```

Rejected scenario:

```bash
PYTHONPATH=src:tools python3 tools/run_hierarchical_px4_mission.py \
  --output artifacts/experiments/hierarchical_px4_mission_20260813_rejected_v1 \
  --event-id scenario-reflection-pipe-b \
  --agent-ip 172.30.176.1 --timeout-s 420 --settle-s 18
```

The Agent address is a local WSL/Docker bridge endpoint and is not a physical
SwarmNet latency or networking measurement.

## Development results

| Run | Branch | Sentinel terminal state | Scout terminal state | Result |
|---|---|---|---|---|
| Confirmed v1 | `CONFIRMED` | `LANDED` | `LANDED` | PASS |
| Rejected v1 | `REJECTED` | `LANDED` | `LANDED` | PASS |

The confirmed run completed Sentinel patrol and hold, Scout dispatch and
standoff verification, confirmed hold, dual RTL, and dual landing. Each
vehicle used one mode command, one arm command, and one land command.

The rejected run completed Sentinel patrol and hold, Scout dispatch and
verification, Sentinel movement to the next patrol waypoint, Scout return to
standby and landing, Sentinel RTL, and Sentinel landing. The Scout required six
mode/arm attempts. Its PX4 log retained an initial `ekf2 missing data` warning
and five temporary arming rejections before health checks allowed the sixth
attempt. No preflight safety check was bypassed. This variability must be
included in later formal timing and reliability analysis.

Both ROS graphs contained every preregistered Sentinel and Scout command and
telemetry topic. Both nodes verified system IDs 2 and 3 respectively. No
wrong-vehicle command or namespace cross-talk was observed within these two
runs.

## Evidence

- Tracked summary:
  `manifests/hierarchical_px4_mission_development_20260813.json`.
- Confirmed raw manifest SHA-256:
  `ea140061e52669ec7fd3527689b91409c60f3f62129a8f9baf3c39191badb6fc`.
- Confirmed event log SHA-256:
  `d20a579b0785a47c76088e06a83912698007a732dcee4d221fe62a57fc726c29`.
- Rejected raw manifest SHA-256:
  `73c94d9b5489e0738232ebb692dc70f08b16af8dd1abc53ad7ae7b250d6aa3c4`.
- Rejected event log SHA-256:
  `a3e7e045a51fba5004f0918285df412645b6bb5ac0b079eeee8e31080ad243ad`.

The raw bundles are intentionally outside Git because they contain generated
PX4/Gazebo logs. They remain under `artifacts/experiments/` and are linked by
the tracked hashes above.

## Interpretation and remaining work

These pilots establish that both nominal decision branches can execute through
real PX4/ROS 2 command paths on the provisional simulator proxies. They do not
yet establish probabilities of mission success, timing distributions, formal
fault recovery, real-airframe dynamics, camera behavior, or industrial hazard
accuracy.

Before M8 formal runs, the airframe measurements from 24 August must be applied,
the proxies regenerated, scenario and source hashes frozen, visual-evidence
capture validated, and all formal fault injectors tested. Failed formal or
pre-fix runs must remain retained under new run identifiers.
