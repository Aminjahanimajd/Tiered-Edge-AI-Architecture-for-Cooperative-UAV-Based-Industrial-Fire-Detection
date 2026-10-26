# M3 Low-Battery Fault Pilot — 13 August 2026

## Purpose and evidence boundary

I tested whether an injected low-battery condition before Scout dispatch caused
the hierarchical controller to enter a typed degraded state and terminate
safely through the real ROS 2/PX4 SITL command path. This was a development
pilot on provisional Gazebo airframe proxies. It is not physical-flight,
industrial-deployment, or formal reliability evidence.

The safety state was PX4/Gazebo SITL only. The simulator-only acknowledgement
token was mandatory, and no physical transport, actuator, or vehicle was used.
The Scout was deliberately kept on the ground and never received arm or flight
commands after the fault was injected.

## Acceptance rule

The pilot passed only if:

1. the injected fault was recorded;
2. both vehicles entered the specified typed safe-state sequence;
3. the active Sentinel returned, landed, and disarmed;
4. the inactive Scout remained unarmed and was finalized as landed;
5. both PX4 identities and ROS namespaces remained isolated; and
6. final horizontal touchdown error was no greater than 2.0 m and vertical
   error was no greater than 0.5 m from the configured home position.

The terminal-position rule was added after v1 exposed a weakness in the
original acceptance checker. The original v1 manifest is preserved unchanged.

## Development lineage

| Run | Raw runner result | Evidence-based classification | Sentinel horizontal error | Interpretation |
|---|---|---|---:|---|
| v1 | PASS | FAIL | 4.35 m | The original checker verified landing and disarm but did not gate touchdown position. The raw PASS is therefore a pre-gate false pass. |
| v2 | FAIL | FAIL | 3.39 m | The new terminal-position gate correctly rejected residual drift after immediate landing at the RTL tolerance boundary. |
| v3 | PASS | PASS | 0.076 m | A bounded 3 s home-position hold before landing removed the observed residual drift while retaining the original 2.0 m tolerance. |

In v3, the Sentinel ended at local NED
`[-0.0532, -0.0536, -0.0100]` m. The Scout ended at
`[-0.0539, -0.0273, -0.0113]` m and had no mode, arm, or land command attempts.
The Sentinel required five mode and five arm attempts before PX4 health checks
allowed flight; these retries are retained as observed simulator behavior and
were not bypassed.

## Reproducible recovery command

```bash
PYTHONPATH=src:tools python3 tools/run_hierarchical_px4_mission.py \
  --output artifacts/experiments/hierarchical_px4_fault_20260813_low_battery_v3 \
  --event-id scenario-fire-tank-a \
  --agent-ip 172.30.176.1 --timeout-s 300 --settle-s 18 \
  --fault low_battery
```

The Agent address is the local WSL/Docker bridge endpoint. It is not a
measurement of the physical SwarmNet connection.

## Traceability

| Run | Manifest SHA-256 | Event-log SHA-256 |
|---|---|---|
| v1 | `0ec52a486860c67289ca74278dd8ad3e5b34255a871e41805fb1fe0ef4e0189f` | `1f7629d63ea3b02cce700a5f7ea2963783f2f923d1006f6376200a6f3db95215` |
| v2 | `393d61743aae458f97a415245c6d6d1b318c511a61afdf63726e3b7e9d243bbb` | `252b5b01c328084daa1e14aaccbe232cb2559260bd760a84f53d636bfacfb589` |
| v3 | `4e5bc46b0c8268f19609ae5e04529af90af9987667d89949d0d9ebdc7abf91dc` | `49cf0defd6645ee93b55f93d9b646b7955a63df28c421e7411b46b861e3482eb` |

Raw bundles remain unchanged under `artifacts/experiments/`. The tracked
machine-readable summary is
`manifests/hierarchical_px4_low_battery_pilot_20260813.json`.

## Interpretation and limitation

The pilot demonstrates the intended low-battery safe path once under the
current provisional simulator configuration. The failed predecessors show that
checking only landed/disarmed state was insufficient: a terminal spatial gate
was also required. The result does not estimate a success probability. Formal
M8 evidence still requires the frozen, calibrated simulator and 20 independent
runs for this fault, with failures retained and Wilson intervals calculated at
the run level.
