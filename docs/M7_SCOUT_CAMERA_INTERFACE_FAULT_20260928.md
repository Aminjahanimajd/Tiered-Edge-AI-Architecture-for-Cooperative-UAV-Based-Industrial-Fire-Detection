# M7 Scout ROS Camera-Interface-Unavailable Fault — 28 September 2026

## Method and boundary

I tested the Scout verifier's fail-closed behavior when no ROS camera frames
were available. The ModalAI camera service remained running, but I deliberately
did not start `voxl_mpa_to_ros2_node`. The Scout verification node remained
online on ROS domain 85 with its deployed TFLite model and one interpreter
thread. From the Sentinel host, I injected five unique, correlated hazard
alerts. Both aircraft were stationary with propellers removed, the Sentinel
Pixhawk was unpowered, and no vehicle command was published.

This is a ROS camera-interface-unavailable test. It is not evidence of a
physical camera sensor or cable failure.

## Acceptance rule and result

For each repetition, the Scout had to:

1. receive the correctly correlated alert;
2. avoid running inference without a current frame;
3. publish exactly one correlated `ERROR` verdict with reason `no_frame`.

All five repetitions satisfied the rule. Five distinct event identifiers were
present in the Sentinel probe records, Scout alert records, and Scout verdict
records. The Scout executed zero verification inferences. The bounded node
ended with timeout status 124, which was the planned 75-second stop condition,
not a crash.

| Measure | Result |
|---|---:|
| Repetitions | 5 |
| Correlated `ERROR/no_frame` verdicts | 5 |
| Verification inferences | 0 |
| Latency mean | 47.389 ms |
| Latency median | 33.586 ms |
| Latency minimum | 30.023 ms |
| Latency maximum | 107.106 ms |
| Latency p95 | 92.565 ms |
| Latency population standard deviation | 29.896 ms |

The latency begins at injected-alert publication on the Sentinel host and ends
at its verdict callback. With only five repetitions, the distribution is
descriptive and is not a general recovery-time estimate.

## Traceability

Evidence is stored under:

`D:\Drones\recovery_images\sentinel_sd_20260909\hardware_evidence_20260928\faults_20260928\scout_camera_ros_unavailable`

The transfer archives have SHA-256 hashes:

- Sentinel probe archive:
  `509f9673a11c4808f4626268428c322acf5bd6bb59c9de786617bb27e7c1fadb`;
- Scout node archive:
  `2a3bb892a476d1994e74bfe6d5e8650a11f0e6f8fd748403eae3e2c26b727926`.

The Scout event log SHA-256 is
`286d5e593faf9d9d975d209cd59db99a2d6174f268f80c3fa3e2203569b9b02f`.
The derived analysis and visual manifest bind the remaining probe records and
terminal-style evidence image to their raw hashes.

The result supports only the claim that the implemented Scout node failed
closed for five injected alerts when its ROS camera interface supplied no
frame. It does not establish physical camera reliability, end-to-end hazard
detection performance, flight safety, or industrial-site reliability.
