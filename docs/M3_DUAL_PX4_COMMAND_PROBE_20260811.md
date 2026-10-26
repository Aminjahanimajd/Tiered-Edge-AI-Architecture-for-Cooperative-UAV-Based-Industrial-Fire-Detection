# M3 Dual-PX4 ROS 2 Command-Path Probe  11 August 2026

## Purpose and scope

I executed a bounded development probe to verify that two distinct PX4 v1.17.0
SITL instances could receive namespaced ROS 2 commands, move their respective
Gazebo proxy airframes, and reach a safe terminal state. This was a
simulation-only engineering test. No physical interface, flight controller,
motor, propeller, or vehicle was connected.

The run is not a hierarchical hazard mission, formal reliability campaign,
physical flight result, airframe calibration, or certification result. The
proxy dynamics remain provisional until physical measurements are recorded in
the laboratory.

## Preconditions and safety state

- PX4 source/tag: v1.17.0 at commit
  `d6f12ad1c4f70ad3230afd7d86e971421e02fef4`.
- PX4 binary SHA-256:
  `a04edce74bd8472df0c021f18ceb1c3b46d8c78bde1b08ef3d5eb2b60755daa6`.
- Gazebo Sim: 8.11.0.
- ROS 2 Jazzy and the pinned `px4_msgs` build ran inside the isolated
  `drone-xrce-ros-probe` container.
- Sentinel identity: instance 1, system ID 2, namespace `/sentinel`.
- Scout identity: instance 2, system ID 3, namespace `/scout`.
- The command node required the exact
  `DRONE_ENHANCED_SIMULATION_ONLY=I_ACKNOWLEDGE_PX4_SITL_ONLY` token.
- Published PX4 input topics were restricted by an allowlist and checked
  against the expected vehicle namespace.
- Target coordinates were validated against the scenario bounds before
  publication.

PX4 initially rejected arming in retained v3 evidence because no simulated GCS
was attached. For v4 I changed only two parameters in each isolated SITL
instance: `NAV_DLL_ACT=0` disabled the GCS-loss action and
`COM_RCL_EXCEPT=4` exempted Offboard mode from manual-control-loss handling.
The runner recorded the previous values, set commands, return codes, and
readbacks. These simulator-only values must never be copied to a physical
vehicle configuration without a separate safety review.

## Reproducible command

```bash
cd /mnt/d/Drones/Drone_Enhanced
PYTHONPATH=src:tools python3 tools/run_dual_px4_command_probe.py \
  --output artifacts/experiments/dual_px4_command_probe_20260811_v4 \
  --agent-ip 172.30.176.1 \
  --duration-s 240 \
  --settle-s 18
```

The Agent address is a local WSL/Docker bridge endpoint, not a drone-network
measurement and not a portable deployment setting.

## Acceptance criterion

Both distinct PX4 SITL vehicles had to verify their configured system identity,
expose the required namespaced ROS 2 topics, arm in Offboard mode, reach a
three-metre takeoff setpoint, translate to their own bounded target, hold,
land, and disarm. Any wrong identity, missing topic, command failure, timeout,
or unsafe terminal state caused failure.

## Results

The v4 bundle passed.

| Item | Sentinel | Scout |
|---|---:|---:|
| Verified PX4 system ID | 2 | 3 |
| Local NED target (m) | (3, 3, -3) | (3, 4, -3) |
| Final NED position (m) | (2.941, 2.939, 0.014) | (2.947, 3.912, 0.003) |
| Mode command attempts | 1 | 1 |
| Arm command attempts | 1 | 1 |
| Land command attempts | 1 | 1 |
| Final state | landed and disarmed | landed and disarmed |
| Probe status | PASS | PASS |

Both required `vehicle_command` and `vehicle_status_v1` topics were present
under both namespaces. PX4 returned accepted acknowledgements for both arm
commands and both land commands; the Sentinel mode acknowledgement was not
observed by the transient subscriber, but the accepted arm, position response,
and completed Offboard trajectory demonstrate that the mode path executed.
This single missing observed acknowledgement is a logging limitation, not a
network-loss estimate.

The Scout XRCE client stop command returned code 255 after its old client timed
out and forced shutdown. The subsequent restart returned code 0, the expected
Scout namespace and identity were observed, all route parameter readbacks
passed, and the complete Scout motion probe passed. The forced-stop record is
therefore preserved as a recovery observation rather than silently removed.

## Evidence and hashes

- Raw bundle:
  `artifacts/experiments/dual_px4_command_probe_20260811_v4`.
- Command manifest SHA-256:
  `4f8c7cea2b98eac971f634393d254e0a43dc586a566364ff114f528a0a6dcd87`.
- Spawn manifest SHA-256:
  `7106aea572ed7b2dbe22e44deeaaf608273b9debb2b48623096a444bd715b33e`.
- Sentinel event log SHA-256:
  `8162adb5b237a0325d6b2b14ba878afd478714173837b11037748a8ca8e1d752`.
- Scout event log SHA-256:
  `5c06897bc0de5692879d5440e878197119be3d3a23a3ef9ec3f67817104e61df`.
- Source hashes are frozen in
  `manifests/dual_px4_command_probe_20260811_v4.json`.

Failed attempts v1 through v3 remain in their versioned artifact directories.
They record, respectively, an output-path defect, a container Python-path
defect, and PX4 preflight rejection caused by simulated GCS-loss policy.

## Engineering interpretation and limits

This probe establishes that the dual-instance ROS 2/PX4 command path can
control the two distinct provisional simulator proxies without namespace or
system-ID cross-talk in one bounded run. It does not estimate mission success
probability, network reliability, detector behavior, hazard localization,
industrial performance, or physical flight safety. M3 remains in progress:
patrol, correlated hazard dispatch, verification decisions, rejection memory,
fault handling, RTL, and the preregistered repeated-run campaign are still
required.
