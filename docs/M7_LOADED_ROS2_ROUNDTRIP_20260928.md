# M7 ROS 2 Round Trip Under Live Inference Load — 28 September 2026

## Purpose and safety state

I measured the Sentinel–Scout ROS 2/DDS round-trip distribution while both
edge computers were concurrently operating their live camera and inference
paths. Both aircraft were stationary with propellers removed. The Sentinel
Pixhawk remained unpowered, and no vehicle-command publisher was used. The
test therefore evaluates loaded edge-compute communication, not physical
flight or the complete flight-controller service stack.

## Concurrent load and timing proof

The loaded camera/inference trial was `loaded-rtt1000-20260928-r2`. It ran the
Sentinel D435i and TensorRT detector, the Scout `/tracking` camera bridge and
one-thread TFLite verifier, asynchronous node logs, and approximately 1 Hz
host-resource collectors. On ROS domain 85, an independent probe injected a
correlated alert every five seconds from 12:02:14 to 12:05:14 UTC. It received
36/36 fresh Scout verdicts with no missing, mismatched, duplicate, stale-frame,
or error verdict.

The 1,000-event RTT trial `ros2-loaded-1000-20260928-r2` used isolated ROS
domain 86 from 12:03:36 to 12:03:51 UTC. Thus, its full measurement interval
was contained within the independently observed live-verification interval.
Process snapshots on both devices additionally record the active camera and
inference nodes. The identical `roundtrip_loaded_v1` bundles on both devices
contained the probe, runner, and Cyclone DDS configuration with these hashes:

- `ros_roundtrip_probe.py`:
  `b2a01b232c4439f5f5c6f9d38024a661d210eb3ce181f40b6bcfc0d98829fa91`;
- `run_current_ros_roundtrip_device.sh`:
  `b831796859cbbc70c2db74bc797c0938c9ef0311dace280454d17f5c886e5027`;
- `cyclonedds_swarmnet.xml`:
  `ef67394695080ab6450fc6998396d59f1a287b7e86d3e590989a68e04bea329f`.

## Results

| Measure | Result |
|---|---:|
| Requested round trips | 1,000 |
| Received round trips | 1,000 |
| Delivery fraction | 1.000 |
| Wilson 95% interval for delivery fraction | 0.99617–1.00000 |
| Missing events | 0 |
| Correlation mismatches | 0 |
| Responder duplicates | 0 |
| Unexpected events | 0 |
| RTT mean | 4.897 ms |
| RTT median | 4.393 ms |
| RTT minimum | 2.671 ms |
| RTT maximum | 44.011 ms |
| RTT p95 | 7.984 ms |
| RTT population standard deviation | 2.167 ms |

The sample unit is one correlated `HazardAlert` publication followed by its
matching `HazardVerdict` callback. The clocks were used only for round trips on
the Sentinel process; I did not infer one-way latency.

For context, the earlier idle-network result had a 4.665 ms mean and 8.270 ms
p95 RTT for 1,000/1,000 delivered events. The two observed distributions are
descriptively similar, but this comparison does not establish equivalence or
causality because it comprises one run per condition and uncontrolled shared-
laboratory network traffic may differ between runs.

## Preserved setup failure

The first responder attempt, `ros2-loaded-1000-20260928-r1`, failed before
receiving any event because its launcher was pointed at a directory that did
not contain both the probe script and DDS configuration. I retained its console
record. I then assembled identical versioned bundles, verified their hashes,
and used the new `r2` trial ID. No failed result was overwritten or included in
the successful sample.

## Evidence and claim boundary

The raw Sentinel initiator SHA-256 is
`b0b66ea9bc31ff83ee9da944e14512cd70b059a0ae4767475236cb9a68680316`.
The raw Scout responder SHA-256 is
`3ee08c4f6d420504684611be80da4bb71e7c94de3d50f7d5524d03bcb7f637ce`.
The local transfer-archive hashes are:

- Sentinel: `b90323154f91aca129b9b98607f8638b5179676edbad5c7beb832fd619a45bd6`;
- Scout: `44d7d533a0980d2b153b16cee04684f73b55f36d0f93fa4cda4a8087af7b2509`.

Raw and derived evidence is stored under:

`D:\Drones\recovery_images\sentinel_sd_20260909\hardware_evidence_20260928\ros2_loaded_20260928`

The result supports reliable correlated message exchange only for the observed
stationary SwarmNet condition under the recorded concurrent load. It does not
support claims of one-way latency, physical flight, a powered Sentinel flight
controller, general network reliability, or industrial-site operation.
