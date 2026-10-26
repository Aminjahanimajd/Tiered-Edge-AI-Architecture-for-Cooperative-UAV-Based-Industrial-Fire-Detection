# Dual-PX4/Gazebo mission simulation

This folder contains the original world, distinct visual proxy definitions and runtime locks. It does not vendor PX4, Gazebo or a ROS installation.

The accepted v17 mission ran on 30 September 2026 using two PX4 v1.17.0 SITL instances, Gazebo 8, Ubuntu 24.04 and ROS 2 Jazzy in the isolated Windows/WSL/Docker setup. See [the mission report](../docs/M8_DUAL_PX4_VISUAL_MISSION_20260930.md), the [recording](../media/gazebo_full_mission.mp4) and the bundled event log under `artifacts/experiments/hierarchical_px4_visual_confirmed_20260930_v17/`.

## What executes

The mission node sends actual namespaced offboard setpoints and vehicle commands to PX4 SITL and reads telemetry/acknowledgements. Sentinel patrol, target hold, Scout dispatch, standoff verification, final decision, return and landing follow the mission state logic.

The trigger, hazard target and Scout verdict come from the versioned scenario. YOLO does not infer these events from Gazebo camera frames. The simulation separately exercises orchestration; it does not establish integrated aerial computer-vision performance.

## Proxy and coordinate boundary

- Orange Sentinel and blue Scout use separate visual geometry and identities.
- **Both inherit upstream X500 dynamics.** They are provisional proxies, not dynamically calibrated copies of the physical X500 V2 and ModalAI vehicle.
- Hazard coordinates are local-ENU scenario truth. They are not vision-derived localization and are not added to the physical image-plane hazard protocol.
- The physical Foxy deployment and simulated Jazzy deployment are different environments.
- One accepted development mission is not the planned 310-run reliability campaign, physical-flight validation or industrial-site validation.

The final visual scenario is `config/simulation_scenarios_visual_v3.json`. Earlier versioned scenarios and readiness gates remain to document the implementation lineage. A required physical measurement still set to `null` must keep formal calibrated-model generation blocked.

## Reproduction prerequisites

1. Obtain the upstream PX4 revision in `runtime_lock.json` and a compatible Gazebo/ROS 2 environment. Recorded local paths are historical, not universal install locations.
2. Build matching PX4 ROS interfaces and an isolated XRCE/DDS bridge. Verify unique instances, namespaces and system IDs before issuing SITL commands.
3. Review `tools/prepare_dual_px4_sim.py` and `tools/run_hierarchical_px4_mission.py` for the original host orchestration. Adapt paths/containers explicitly; do not run against physical flight controllers.
4. Use a new output directory and preserve failed runs. The accepted v17 run explicitly set the landing timeout to 60 s; the generic runner's default is a different configuration.

See [REPRODUCIBILITY.md](../docs/REPRODUCIBILITY.md) for the host/software/evidence distinctions. No simulator or hardware execution was repeated during publication cleanup.
