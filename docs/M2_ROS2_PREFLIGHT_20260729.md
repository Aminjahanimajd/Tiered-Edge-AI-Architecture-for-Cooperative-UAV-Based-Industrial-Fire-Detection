# M2 ROS 2 Build and Bidirectional Transport Preflight

**Validation date:** 29 July 2026  
**Enhanced runtime revision:** `8b634cd`  
**Validation utilities:** revisions `8c8e3cc` and `307d8be`  
**DDS configuration revision:** `ba62ce5`  
**Status:** isolated builds and bidirectional injected transport passed

## Objective and safety boundary

I performed this stage to verify that the enhanced message packages and node
modules build on both target ROS 2 Foxy environments and that correlated
messages can cross `SwarmNet` in both directions. I kept the drones stationary
with their propellers removed. I did not open a camera, run either full detection
node, load a flight-control interface, or introduce a lighter.

The passed result is a ROS 2 build and transport proof. It is not an end-to-end
hazard-detection, verification, final-alarm, latency, or reliability experiment.

## Runtime inventory

### Sentinel

The Sentinel host did not expose ROS 2 or colcon directly. It provided Docker
20.10.21 and the historical image
`dustynv/ros:foxy-ros-base-l4t-r32.7.1`. The stopped historical
`sentinel_node` container used host networking, the NVIDIA runtime, and a
read-write bind from `/home/unime-nano/ros2_ws` to `/workspace/ros2_ws`.

I did not start or reuse that container because doing so would expose the frozen
historical workspace to changes. Instead, I used newly named disposable
containers with `--rm` and mounted only the isolated enhanced tree under `/tmp`.

### Scout

The Scout provided native ROS 2 Foxy at `/opt/ros/foxy`, colcon at
`/usr/local/bin/colcon`, and 189 discoverable ROS packages. The first inventory
attempt used `set -u`; the Foxy setup script referenced unset
`COLCON_CURRENT_PREFIX` and exited. I retained that failed record and repeated
the inventory without nounset. The corrected inventory passed.

One still earlier preflight command failed in the local Windows argument parser
because nested quoting split the intended remote command. It created no SSH
action and no evidence record.

## Isolated build method and result

I built revision `8b634cd`, whose source archive had SHA-256
`c5bf3df14d4e5de92a1fbc514943c73e31a8b439754ec6d36818c1d728e59676`.
The archive and source had already passed Python 3.6 compilation on both devices.

On the Scout, I sourced native Foxy and built into these isolated paths:

- `ros2_ws/build_scout`;
- `ros2_ws/install_scout`; and
- `ros2_ws/log_scout`.

Both packages completed in 29.0 s. The build produced no standard-error output.
The evidence-record SHA-256 is
`e55011f62ed4a10084b0271cf4a4a203d060e0c9157cdf9cf24037da63a702b0`.

On the Sentinel, I used a disposable Foxy container and built into
`build_sentinel`, `install_sentinel`, and `log_sentinel` within the isolated
mounted tree. Both packages completed in 55.8 s. The build emitted CMake policy
`CMP0148` development warnings from the Foxy/CMake Python discovery stack and a
`setup.py install` deprecation warning. It nevertheless completed both packages
with exit code zero. I classify it as **passed with warnings**, not as a clean
pass. The evidence-record SHA-256 is
`9f75b55fccd82f0acb80806be0568e1834a5fc889c350444930b1cfbccc1f87b`.

These durations include package generation and build work and are not runtime
performance measurements.

## Interface and import verification

I used version-controlled utilities rather than an inline Python expression.
Their file hashes were verified after transfer:

- `check_ros_imports.py`:
  `1311a0bd48877b3c95e6013c4d907ca82d2d5a08fbefa1aa8463ba9b4468331c`;
- `check_ros_install.sh`:
  `82e0520f628d5bff46fe4f2accc5b86c3f5002780a49cb7e2a151373aa27b6f3`.

Both isolated installations exposed `HazardAlert`, `HazardVerdict`, and
`HazardDecision` with the expected experiment, trial, event, source, hazard,
confidence, monotonic-time, model-hash, normalized-target, verdict, and terminal
decision fields. The Sentinel imported `drone_enhanced_nodes.sentinel_node`; the
Scout imported `drone_enhanced_nodes.scout_node`. Neither node class was
instantiated, so no camera or model was opened during this check.

The Sentinel import-check record SHA-256 is
`e22c3547be9f7acd61e30e3fe0f5dcf2ca1165980ede9e00a2864298a99767df`.
The Scout record SHA-256 is
`6a1dc748b89ec996f40f9ced18fbfd627025f589f921bababc9212af02567457`.

An earlier inline import invocation failed in the local argument parser before
SSH execution. It performed no remote action. I replaced it with the hashed
utility rather than weakening command traceability.

## DDS middleware selection and first transport failure

The Sentinel image declared `rmw_cyclonedds_cpp`. The Scout provided
`rmw_cyclonedds_cpp`, Fast DDS, and Connext-related RMW packages. I selected
Cyclone DDS explicitly on both devices and used isolated `ROS_DOMAIN_ID=42`.

The first injected `HazardAlert` test failed. Cyclone DDS selected
`eth0 (172.17.6.35)` on the multi-interface Sentinel but
`wlan0 (10.42.0.125)` on the Scout. The Sentinel discovered no subscriber, and
the Scout received no expected event before timeout. These are network-interface
selection failures, not message-schema or correlation failures.

The failed Sentinel record SHA-256 is
`684c896e4aa83174999a7c2338f8fec416d05a13cf5d195ca8fc3b8c2cf5fcb5`.
The failed Scout record SHA-256 is
`f231db4e0bb156ff4450148deaf5f63b1d11e6425204dff0ef33ccd7a2918c27`.

## SwarmNet DDS correction

I added `config/cyclonedds_swarmnet.xml`, which explicitly selects `wlan0`,
allows multicast, and uses automatic participant indexing. The configuration
file SHA-256 is
`ef67394695080ab6450fc6998396d59f1a287b7e86d3e590989a68e04bea329f`.
I transferred and verified the same file on both isolated trees and set
`CYCLONEDDS_URI` to its device-local file URI.

This setting is now a required session parameter. A formal SwarmNet test must
stop if either participant reports a different network interface.

## Corrected bidirectional transport results

### Sentinel to Scout: `HazardAlert`

For trial `alert-transport-002`, the Sentinel publisher discovered one
subscriber and published event `event-alert-002`. The Scout received that exact
event with:

- experiment `m2-injected-20260729`;
- trial `alert-transport-002`;
- source `sentinel`;
- hazard type `fire`;
- confidence 0.75;
- temporal count 3;
- normalized target `(0.5, 0.5)`; and
- no unexpected event ID.

The Scout explicitly reported that all correlation fields matched. The Sentinel
publisher record SHA-256 is
`aac94f8f35b8fb40052499ec8ffb5155b4a64aa3e4bfc4130e3c9884fa05be6f`.
The Scout subscriber record SHA-256 is
`5a03dca6f298d44c4b7b65a53246cb4faf11a3386518aa88163acfb6365bff03`.

### Scout to Sentinel: `HazardVerdict`

For trial `verdict-transport-001`, the Scout publisher discovered one subscriber
and published event `event-verdict-001`. The Sentinel received the same
experiment, trial, event, source `scout`, hazard type `fire`, confidence 0.75,
verdict `CONFIRMED`, and the injected-test reason. It reported matching
correlation fields and no unexpected event ID.

The Scout publisher record SHA-256 is
`f0244b92bc0806c824820743ddaf6aac615ca5dd3ed97e6cad52e94688a5bd6f`.
The Sentinel subscriber record SHA-256 is
`1023e904611b2bd9982ea84fedcb395c09fc08ce00418a1cee33d1689019b8f2`.

## Timing boundary

The transport utility preserved publisher and subscriber monotonic timestamps
but deliberately set `latency_claim_permitted` to false. Monotonic clocks have
independent host-specific epochs; subtracting the Sentinel value from the Scout
value would not produce network latency. UTC offset and uncertainty also have
not yet been estimated with a controlled clock probe. Therefore, this stage
reports successful delivery and field integrity only.

## Acceptance decision

I classify the following as passed:

- interface and node packages build on both target Foxy environments;
- generated messages expose the intended fields on both devices;
- both installed node modules import under Python 3.6;
- both devices share an explicitly selected Cyclone DDS implementation;
- `wlan0` binding corrects multi-interface discovery on SwarmNet;
- a correlated alert travels from Sentinel to Scout; and
- a correlated verdict travels from Scout to Sentinel.

I do not yet classify the enhanced integrated runtime as complete. The full
nodes have not exchanged an event while processing camera frames, the Sentinel
has not emitted a final `HazardDecision` from a matched live verdict, message
loss/latency has not been measured, and no synchronized positive or negative
pilot has run.

## Evidence index

This stage contains 18 records: 14 `PASS`, one `PASS_WITH_STDERR`, and three
`FAIL`. The failed records are intentionally retained because they establish the
setup-script and network-interface corrections. All embedded record hashes
verify. The evidence-index SHA-256 is
`75e6a948d34406b3f23f467ab35bb9e4d53305bb1884e108ac2e2162fc831ff8`.

## Thesis placement

- **Architecture and implementation:** explicit message schemas and shared RMW.
- **Experimental methodology:** isolated domain, injected events, exact
  correlation checks, and failure-preserving evidence.
- **Results:** build outcomes and bidirectional delivery.
- **Discussion:** multi-interface DDS failure and deterministic `wlan0` binding.
- **Limitations:** no cameras, full nodes, clock-corrected latency, repeated
  transport, packet-loss estimate, or flight.
- **Appendix:** raw commands, build warnings, utility hashes, DDS profile, and
  evidence index.
