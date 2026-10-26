# M7 Scout Verification-Process-Unavailable Fault — 28 September 2026

## Method and boundary

I verified on the Scout device that no `scout_enhanced` process existed and
that the ROS 2 domain-85 graph exposed no Scout verification node. I then ran
the exact deployed Sentinel ROS node and 640-pixel TensorRT engine on the
Jetson Nano. To obtain deterministic repetitions without using an open flame,
I cancelled the node's camera-inference timer and injected five synthetic fire
detections at its internal alert-dispatch boundary. The node published its
normal `HazardAlert` messages, retained its configured 10,000 ms Scout timeout,
and used its normal timeout timer and `HazardDecision` publisher.

Both aircraft were stationary with propellers removed. The Sentinel Pixhawk
was unpowered and the test published no flight command. Because the detections
were injected after vision, this test does not measure camera detection or the
temporal filter.

## Acceptance rule and result

Each unique Sentinel alert had to produce exactly one correlated `TIMEOUT`
decision with reason `Scout response timeout`. No Scout verdict could be
observed. Trial `scout-process-unavailable-20260928-r1` passed all five
repetitions.

| Measure | Result |
|---|---:|
| Sentinel alerts | 5 |
| Correlated `TIMEOUT` decisions | 5/5 |
| Scout verdicts observed | 0 |
| Configured Scout timeout | 10,000 ms |
| Alert-to-decision mean | 10,023.481 ms |
| Alert-to-decision median | 10,028.977 ms |
| Alert-to-decision minimum | 10,001.388 ms |
| Alert-to-decision maximum | 10,029.125 ms |
| Alert-to-decision p95 | 10,029.110 ms |
| Population standard deviation | 11.047 ms |

The result demonstrates deterministic fail-safe timeout finalization in the
deployed Sentinel node for the five tested events. It does not demonstrate
network-disconnection recovery, physical flight behavior, camera-level hazard
detection, or industrial reliability.

## Traceability

Evidence is stored under:

`D:\Drones\recovery_images\sentinel_sd_20260909\hardware_evidence_20260928\faults_20260928\scout_process_unavailable`

The transfer archives have SHA-256 hashes:

- Sentinel execution archive:
  `cb3c721344abf438a2afb97a9a98856cd35ff0865ec0ec0bf33b5efce99bebdc`;
- Scout process/ROS-graph snapshot archive:
  `da0d4bb116da122ca9685ac48a65093b07b99ca5370259b050271c5f562cf6f3`.

The Sentinel event log hash is
`b4ecbfc85fd078ec5c4e990885edad9456cc1e66ac90c742672f4f992ebc8353`.
The derived analysis hash is
`5502909aba512aaae59cc1a4d9cf0bdcd04e4cb3c971ea52efc758baa3157551`,
and the terminal-style visual hash is
`e4ee06939305ff04d137291bf2b5996cfd58e9b0e39c06e6161dd33e10180738`.
The executed injection harness hash is
`618f490d481fdc78f6ffae8c40f2d35fdc47aaaca0be642bf38374d9b2a303dd`.

This result belongs in the experimental-methodology and fault-handling results
sections. The dispatch-boundary injection and absence of physical flight belong
in the limitations section.
