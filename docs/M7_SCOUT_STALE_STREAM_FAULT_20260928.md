# M7 Scout Stale ROS Camera-Stream Fault — 28 September 2026

## Method and evidence boundary

I evaluated whether the Scout verifier fails closed after a previously live
ROS camera stream stops. The Scout first received frames from the ModalAI
tracking camera through `voxl_mpa_to_ros2_node`. Three unique preflight alerts
then produced three normal camera-based model inferences and correlated model
verdicts. After this live-input condition was recorded, I stopped only the ROS
camera bridge, retained the Scout verification node, waited two seconds, and
injected five additional unique alerts from the Sentinel host.

The underlying `voxl-camera-server` remained active. Both aircraft were
stationary with propellers removed, the Sentinel Pixhawk was unpowered, and no
vehicle command was published. This is therefore a ROS stream-loss test after
proven live input, not a physical camera-sensor or cable failure.

## Preregistered acceptance rule and result

The final fault phase had to return exactly one correlated `ERROR` verdict with
reason `stale_frame` for each of five alerts and execute no verification
inference after the stream stopped. Event identifiers had to agree across the
Sentinel probe outputs and Scout event log.

Trial `scout-stale-frame-20260928-r6` passed. The preflight retained one
`first_camera_frame` record, three camera-based verification inferences, and
three normal model verdicts. The subsequent five fault alerts produced five
correlated `ERROR/stale_frame` verdicts and zero post-stop inferences. All eight
event identifiers agreed across the devices. The node's exit code 124 was the
planned 180-second bounded timeout, not a crash.

| Measure | Result |
|---|---:|
| Live preflight alerts/model verdicts | 3/3 |
| Live preflight verification inferences | 3 |
| Fault repetitions | 5 |
| Correlated `ERROR/stale_frame` verdicts | 5/5 |
| Verification inferences after bridge stop | 0 |
| Fault-response latency mean | 35.341 ms |
| Fault-response latency median | 35.502 ms |
| Fault-response latency minimum | 31.031 ms |
| Fault-response latency maximum | 39.369 ms |
| Fault-response latency p95 | 39.210 ms |
| Fault-response latency population standard deviation | 3.316 ms |

Latency begins at injected-alert publication on the Sentinel and ends at its
verdict callback. With only five fault repetitions, these statistics are
descriptive and do not establish a general recovery-time distribution.

## Retained protocol-development history

Attempts r1–r3 waited for the asynchronous event file to expose the first-frame
record before injecting the fault. They ended during setup because the deployed
logger flushes every ten records. Attempt r4 proved two normal live verdicts,
but two alerts did not reach that flush boundary. Attempt r5 generated five
normal preflight verdicts, but only the first three were visible at the first
ten-record flush, so its five-verdict readiness condition was not met. These
attempts were not treated as camera or model failures. They are retained with
their controller logs. The final r6 protocol deliberately used three live
alerts because one first-frame record plus three alert/inference/verdict
triplets equals the logger's ten-record flush boundary.

## Traceability

Evidence is stored under:

`D:\Drones\recovery_images\sentinel_sd_20260909\hardware_evidence_20260928\faults_20260928\scout_stale_frame`

The transfer archives have SHA-256 hashes:

- Scout run and protocol-history archive:
  `c11642b64a0c752fb2363e6e1a0317d6b7e198b38e88bf9438b0bf836068ad3a`;
- Sentinel probe archive:
  `83414cd158d9e25ddbb132116c3eddfb7f9708bea01d55d940a14a0bca62e794`.

The executed Scout protocol script archived with the device evidence has hash
`2b5c4153b6e8c37cfe9cf9d922b2827049b4f2437f3bb872a20f42f973a7977a`.
The final Scout event log hash is
`d5058e0642a08e0f552855a589a353bba18a017d4d0b39684c62f44f054d5736`.
The derived analysis hash is
`4738c7778734db5625de7c9725bf1ce590863b9cc86d02afe7bbd649ef56839c`,
and the terminal-style visual hash is
`9dd552d6eeea5163f86c00e9af8300e2d649b0b2e8017699b12ec6e1a7e6e550`.

This result supports only the claim that the implemented Scout node failed
closed for five injected alerts after its previously live ROS camera stream
was stopped. It does not establish physical camera-hardware reliability,
flight safety, end-to-end hazard-detection accuracy, or industrial-site
reliability.
