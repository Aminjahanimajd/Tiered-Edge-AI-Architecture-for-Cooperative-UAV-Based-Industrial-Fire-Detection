# M3 dual-PX4 spawn regression and recovery — 13 August 2026

## Purpose and safety state

I revalidated concurrent startup of the two distinct PX4/Gazebo development
proxies after later mission and visual-evidence work exposed intermittent
startup failures. Every run was software-in-the-loop only. No physical device,
arming command, actuator, takeoff, detector, or mission command was involved.

## Preserved diagnostic lineage

I retained every versioned raw run under
`artifacts/experiments/dual_px4_spawn_probe_20260813_v4` through `v11`.
The early probes failed during Gazebo startup. A direct bounded Gazebo server
test and a direct Sentinel PX4 invocation then established that the world,
Sentinel model, bridge, and pinned PX4 binary could initialize successfully.

Run v8 proved full Sentinel startup but did not produce a usable Scout console
log before the bound expired. It also exposed a cleanup defect: signalling only
the PX4 parent left the exact Gazebo server process alive. I stopped that exact
PID, verified that no PX4 process remained, and did not discard the failed
bundle. Run v9 tested line-buffering and a different process-group strategy;
it failed during Sentinel Gazebo startup and was also preserved.

The reproducible cause was launch sequencing. A fixed four-second delay could
start Scout before the Sentinel-owned world had completed initialization. I
changed the runner to:

1. start Sentinel in PX4 daemon mode in an isolated process group;
2. wait up to 30 seconds for the successful startup marker;
3. only then start Scout in standalone-attachment mode;
4. wait for the same marker from Scout;
5. run for the bounded observation interval; and
6. stop both isolated process groups with `SIGINT`, escalating to `SIGTERM`
   only after a timeout.

The runner refuses to overwrite an existing evidence directory. Unit tests
cover the explicit per-instance working directories, readiness marker, vehicle
identities, namespaces, and shutdown escalation.

## Passing result

Runs v10 and v11 both passed the startup checks. A later visual-capture pilot
exposed that the runner recorded the requested post-start duration but returned
immediately when no cancellation event was supplied. This timing defect does
not remove the already-written startup markers, model identities, or clean
return codes, but v10/v11 cannot support a 12-second post-start dwell claim.
The raw manifests remain unchanged. The tracked v11 summary marks its duration
field as superseded pending a corrected run.

V11 therefore supports only this startup checkpoint:

| Vehicle | Instance | Namespace | Gazebo model | Startup checks | Return code |
|---|---:|---|---|---|---:|
| Sentinel | 1 | `/sentinel` | `x500_v2_sentinel_proxy_1` | 5/5 | 0 |
| Scout | 2 | `/scout` | `modalai_devkit_scout_proxy_2` | 5/5 | 0 |

For each vehicle, the five checks were the expected PX4 instance, world,
model, DDS endpoint on UDP 8888, and successful startup marker. The raw v11
manifest SHA-256 is
`19cce6188d1b423fc9ea889f3eaae4dfc606c0ee4746eb6dca98f46a74df4d19`.
The Sentinel and Scout log hashes are recorded in
`manifests/dual_px4_spawn_probe_20260813_v11.json`. A post-run process check
found no PX4 or Gazebo process.

I corrected the timer and added regression tests covering elapsed and
cancelled waits. Run v12 then repeated all ten startup checks, observed the
requested 12-second post-start dwell, stopped cleanly, and left no PX4 or
Gazebo process. Its raw manifest SHA-256 is
`451dd567001bfa993e60d2038d1cc6d691bbdef4ce172d5e3561c16a8bbf57a7`;
the tracked summary is `manifests/dual_px4_spawn_probe_20260813_v12.json`.

An accidental repository-level `test_data` link created during the direct PX4
diagnostic was inspected before removal. It pointed exactly to the pinned
PX4 v1.17.0 runtime's `test_data` directory; I removed only the link, not its
target.

## Interpretation and limits

This repeated startup pass supports compatibility of the pinned runtime, industrial
proxy world, distinct model identities, instance separation, namespace launch
configuration, and bounded cleanup. It does not establish mission correctness,
ROS 2 message delivery, detector performance, physical flight, simulator
fidelity, or operational industrial reliability. Those claims require their
separate evidence bundles and formal campaigns. The WSL duplicate
`user.default` configuration warning remained visible but did not prevent the
passing runs; it is an environment-maintenance issue rather than experimental
evidence.
