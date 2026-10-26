# M3 Fault and Visual-Evidence Checkpoint — 13 August 2026

## Purpose and boundary

I exercised four additional hierarchical failure paths through the real ROS 2
and PX4 SITL command interfaces: lost alert, Scout unavailable, delayed Scout
verdict, and sensor/inference error. All runs used provisional Gazebo proxies
and scenario-defined local coordinates. They are development evidence only,
not physical-flight or formal reliability results.

## Results

| Fault | Retained run | Outcome | Scout actuation | Safe-state evidence |
|---|---|---|---|---|
| Lost alert | v2 | PASS | No command attempts | Sentinel and grounded Scout entered `DEGRADED`, then `RTL`, then `LANDED`; an unverified-hazard record was retained. |
| Scout unavailable | v2 | PASS | No command attempts | Sentinel and grounded Scout reached the same typed safe sequence; the failure reason remained distinct. |
| Delayed verdict | v1 | PASS | Both vehicles had flown | Timeout moved both vehicles from active verification states through `DEGRADED`, `RTL`, and `LANDED`. |
| Sensor/inference error | v1 | PASS | Both vehicles had flown | Error moved both vehicles through the same safe path and retained an unverified-hazard record. |

The first lost-alert and Scout-unavailable pilots are preserved as pre-fix
runs. Both correctly avoided Scout flight commands, but `report_suspect` had
already assigned the typed Scout state `TAKEOFF` before the simulated message
loss/unavailability was evaluated. I separated Sentinel suspect acceptance from
Scout dispatch-state assignment and reran both as v2. The corrected logs show
the Scout moving from `PREFLIGHT` to `DEGRADED` without a false takeoff state.

No wrong-system command or namespace cross-talk was observed in these runs.
That statement applies only to these individual pilots and is not a probability
estimate.

## Raw evidence hashes

| Run | Manifest SHA-256 | Event-log SHA-256 |
|---|---|---|
| Scout unavailable v1 (pre-fix) | `5636f53257fd0453d95306c91caf8abc853fbfed795220b7d98b8469aeed7233` | `a76d9d7ea6e3bc8d0381e8e367328be496f2f0edf471c241c3dc1b0f0e4d8049` |
| Scout unavailable v2 | `c3b6018d88ffa4d894d5b8e98237bbc0f5199d722696e7c44ea4615fe7ca16a1` | `08e029573d3bd09f5380127e0d2133ea3eae4a9925dc7e078a3ce9bef99d5b17` |
| Lost alert v1 (pre-fix) | `2a64341d15d38d7111355feeaf75767b156d35724d6081f4d04c777c91730777` | `97048bc7b664ab6bbde52163b3a869c981c5adbd980603cba5522a209debdf65` |
| Lost alert v2 | `e63730032ca14cb54d87c18960bbd81602aa52bddd144e8527486e2b59d07a91` | `48fb6db2d0f2ef7882be210342c1e9c114aa74ba311a5bf1e65cdefd77df1a3b` |
| Delayed verdict v1 | `ba231f2a74a4235ecb13c388a1be25c7a9d1286e6c6747e2a54fb60de6449b03` | `6e0a0a85d18761f83b3768fd3b5196e3435a8e7e0a850a4ff52c7625526ad184` |
| Sensor/inference error v1 | `1f8952ac5a50741b73f6d7e4ae21af3a1f768d13f1d823a8c1307cf98580e6c4` | `52254d117987675dba8e19a35b97bc3033bbe37579a9fbf8c640a2439c7aa27c` |

## Visual evidence

I added `tools/render_simulation_evidence.py` to create two traceable visual
artifacts for a run:

- a two-vehicle typed-state timeline; and
- a rendered image of the retained UTF-8 terminal transcript.

Each image is derived from a hashed run manifest and event log. The image
itself states that it is not a Gazebo screenshot or physical-flight image. A
per-run visual manifest stores the generator hash, command, source hashes, and
output hashes. The authoritative evidence remains the raw log, not the image.

Derived visuals were generated for low-battery v3, Scout-unavailable v2,
lost-alert v2, delayed-verdict v1, and sensor-error v1. Their tracked hash
index is `manifests/simulation_visual_evidence_20260813.json`.

Actual Gazebo GUI screenshots and screen recordings are still required for the
frozen formal M8 campaign. Those source captures will show the distinct
airframe proxies and industrial world, and will be retained unedited alongside
annotated thesis derivatives. No headless development image will be
misrepresented as a GUI capture.

## Remaining M8 work

These pilots do not satisfy the preregistered 20-run fault counts. Duplicate or
stale verdict, mission-node restart, and invalid/geofenced target injectors are
also not yet implemented in the real dual-PX4 runner. Formal execution remains
blocked on the 24 August physical airframe measurements and subsequent
simulator-parameter freeze.
