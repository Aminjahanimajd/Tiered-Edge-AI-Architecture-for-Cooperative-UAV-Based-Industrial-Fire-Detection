# M7 Delayed and Duplicate Scout-Verdict Fault — 28 September 2026

## Method and boundary

I verified on the Scout device that the verification process was absent. I
then instantiated the exact deployed Sentinel ROS 2 node and its 640-pixel
TensorRT engine on the Jetson Nano. To make the fault repetitions
deterministic without an open flame, I cancelled the node's camera-inference
timer and injected five synthetic fire detections at its internal alert-
dispatch boundary. Each event first completed through the unchanged
10,000 ms Scout-timeout path. Only after that final `TIMEOUT` decision, I
injected two `CONFIRMED` verdict messages carrying the already-finalized event
identifier.

Both aircraft were stationary with propellers removed. The Sentinel Pixhawk
was unpowered, and the test issued no flight command. This is deterministic
post-timeout fault injection; it does not measure a natural network-delay
distribution, camera detection, physical flight, or industrial reliability.

## Acceptance rule and result

Each of the five events had to produce exactly one timeout decision. All ten
post-timeout verdicts then had to be rejected as duplicates of a finalized
event, with no additional final decision. Trial
`delayed-duplicate-verdict-20260928-r1` passed all criteria.

| Measure | Result |
|---|---:|
| Events finalized as `TIMEOUT` | 5/5 |
| Late/duplicate `CONFIRMED` verdicts injected | 10 |
| Verdicts rejected as `duplicate finalized verdict` | 10/10 |
| Additional final decisions | 0 |
| Configured Scout timeout | 10,000 ms |
| Rejection-callback mean | 2.631 ms |
| Rejection-callback median | 2.611 ms |
| Rejection-callback minimum | 2.324 ms |
| Rejection-callback maximum | 2.842 ms |
| Rejection-callback p95 | 2.840 ms |
| Population standard deviation | 0.184 ms |

The result demonstrates idempotent finalization for the tested late and
duplicate verdict pattern: a verdict received after timeout did not reverse
or duplicate the final decision. It does not establish end-to-end recovery
from an actual wireless interruption or characterize real network delays.

## Traceability

Evidence is stored under:

`D:\Drones\recovery_images\sentinel_sd_20260909\hardware_evidence_20260928\faults_20260928\delayed_duplicate_verdict`

The transfer archives have SHA-256 hashes:

- Sentinel execution archive:
  `0664f364b8a2260d25652b4ac92bc0d034807fbf428132a2ac8ac096eca45407`;
- Scout process snapshot archive:
  `10c7b469391b763c1d1dba3daeacd7434c959828b2a3d00f3cf40066a528f86b`.

The Sentinel event log hash is
`6094ddd677f28ea196fb22c70db5c78be3214da317dbeb84b602a1ca7c93b4cd`.
The derived analysis hash is
`4b582699403d66851c0b9f8b545da2d06bd1eab01a72ee746095cd653aaee0e8`,
and the terminal-style visual hash is
`1a1a1d5ad97cded08570ffd3b9fbede77787ec0c3caf381456ad5e3e9f01fd20`.
The executed injection harness hash is
`aa84fbf291a5d6962b933938620f326ee40182bce19bc7b9060d0ddf669ada3a`.

This result belongs in the fault-injection methodology and hierarchy-safety
results. The dispatch-boundary injection, deliberate absence of the Scout
process, and lack of physical flight belong in the limitations section.
