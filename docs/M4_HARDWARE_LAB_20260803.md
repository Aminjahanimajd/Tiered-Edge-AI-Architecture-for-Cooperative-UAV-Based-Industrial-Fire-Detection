# M4 Hardware Laboratory Validation — 3 August 2026

## 1. Outcome and evidence boundary

I completed a stationary, propeller-free proof-of-function evaluation of the
hierarchical edge architecture using the exact deployed Sentinel and Scout
models. The accepted evidence demonstrates that the Sentinel can detect a
visible lighter flame, publish a correlated ROS 2 hazard alert, wait while the
Scout performs independent live-camera inference, receive the Scout verdict,
and produce a final confirmed or rejected decision. It also demonstrates that
the outcome is sensitive to flame size and stability: a strong visible-flame
trial produced 13 confirmations from 13 visible-interval requests, whereas an
independent trial with an approximately 2 cm maximum flame produced one
confirmation from 10 visible-interval requests.

These results are proof-of-function observations under the defined laboratory
conditions. They are not estimates of population recall, precision,
false-positive rate, false-negative rate, localization accuracy, flight
performance, smoke-detection performance, or industrial reliability.

## 2. Preconditions and safety state

The aircraft remained stationary on a laboratory table. I removed both sets of
propellers before starting any software or camera test. Flight commands were
disabled in every formal node manifest. I positioned both cameras in the same
general viewing direction. The D435i optical height was approximately 19 cm
above the table and the Scout camera height was approximately 9.5 cm. The final
accepted positive trials used a handheld lighter approximately 20–25 cm from
the cameras. Ignition and extinction were recorded with independent ground-
truth markers.

The lighter became hot during repeated use, so I stopped ignition work rather
than extending a trial for a predetermined duration. This was a safety-driven
termination and is retained as a test limitation. The Scout battery also
required recharging and rebooted more than once; volatile `/tmp` deployment
files therefore had to be reconstructed during the session. No arming, motor,
take-off, or flight command was issued.

The setup photograph is preserved as
`raw/setup_photos/stationary_setup_camera_heights.jpg` with SHA-256
`26baac41396cc167186230a4ee106621be3a21e499b1c08d34920be0317eed33`.
It documents the stationary arrangement and camera-height measurement; it does
not by itself document room lighting, camera exposure, or precise flame pose.

## 3. Exact evaluated configuration

### 3.1 Sentinel

- Hardware: Jetson Nano 4 GB with Intel RealSense D435i.
- Camera path: explicit D435i YUY2 capture through GStreamer and conversion to
  BGR.
- Runtime: TensorRT inside the deployed NVIDIA L4T ROS 2 container.
- Engine SHA-256:
  `16f9018ac299c6f525610a877d798392ec26d53fccb84b589ff6533d76589bf2`.
- Tensor shapes: input `[1,3,640,640]`, output `[1,6,8400]`.
- Temporal filter: three consecutive frames.
- Role: initial fire hazard detection and alert publication.

The engine above is the final 640-pixel deployment. I did not reuse latency
measurements from the distinct historical 416-pixel engine.

### 3.2 Scout

- Hardware: ModalAI VOXL 2 / QRB5165.
- Camera path: Modal Pipe Architecture camera stream, ROS 2 bridge output at
  1024 × 768 with `yuv422` metadata, explicit UYVY-to-BGR conversion, BGR-to-RGB
  conversion, float32 normalization, and TFLite inference.
- Model SHA-256:
  `d533e320081be17ac91fb77c20a9de09f4bffada0d7f88c88326d57cd893bc35`.
- Tensor shapes: input `[1,640,640,3]`, output `[1,7,8400]`.
- Output-coordinate interpretation: normalized model coordinates.
- Fixed operational confidence threshold after the diagnostic phase: 0.05.
- Role: independent secondary fire verification.

The Scout manifest records
`sentinel_coordinates_used_for_scout_inference=false`. Therefore, the accepted
experiment proves correlated target designation and full-frame secondary
verification, but it does not prove coordinate-guided cropping, physical target
localization, or navigation to a transferred position.

### 3.3 Communication

Both devices used ROS 2 Foxy, Cyclone DDS, ROS domain 85, and the SwarmNet
wireless network. Alerts and verdicts carried experiment, trial, and event
identifiers. The analysis verified equality of the event-ID sets across
Sentinel alert publication, Scout receipt, Scout inference, Scout verdict
publication, and Sentinel final decision for both accepted integrated positive
trials.

## 4. Diagnostic correction before accepted trials

The initial Scout pipeline produced repeated zero-confidence results despite a
visible flame. I inspected the ModalAI camera metadata and decoded frames rather
than treating these records as model failures. The live ROS bridge published a
UYVY-compatible `yuv422` image. Explicit UYVY decoding produced valid BGR
frames.

I then found that the TFLite model output encoded bounding-box coordinates in
normalized units, while the shared decoder interpreted them as model-pixel
units. I added an explicit `output_coordinate_space` parameter, retained
`model_pixels` as the general default, and configured the Scout as
`normalized`. The Sentinel configuration was unchanged. A paired diagnostic
comparison then detected fire in the illuminated frame and no fire in the
unlit frame.

The diagnostic phase also showed that a 0.10 Scout threshold rejected a clearly
visible small flame whose maximum raw fire score was approximately 0.0835. I
selected 0.05 for the remaining laboratory trials because the observed unlit
scores were below approximately 0.0026 while visible-flame examples extended
above 0.05. This threshold was selected after inspecting diagnostic data; it
was not preregistered and must be calibrated on a representative validation
dataset before any general accuracy claim.

The complete host regression suite passed after this correction: 92 tests in
0.098 s in the established WSL Python 3.9 research environment. The saved raw
test output has SHA-256
`2e59aa8faff6db86c89edd105f101c424c009e567d28aa28f83b8bbe5bee38d8`.
The Windows Python 3.14 environment lacked NumPy, Pillow, and pytest; those
dependency errors were invocation-environment failures rather than behavioral
test failures.

## 5. Trial chronology and disposition

| Trial group | Purpose and observation | Disposition |
|---|---|---|
| `full-negative-01` to `full-negative-05` | Node, camera, service-restoration, and bounded-run bring-up | Preserved as engineering evidence; not used for final model-accuracy claims |
| `full-positive-01` to `full-positive-03` | Initial lighter tests; Sentinel detected but the pre-correction Scout pipeline rejected | Excluded from final performance summary because the Scout decoder configuration was incorrect |
| `full-postfix-positive-04` | First run after coordinate correction; physical flame visibility remained inconsistent | Diagnostic only |
| `full-postfix-diagnostic-05` | Threshold 0.01 and event-synchronized frame capture; confirmed that unobstructed visible flame produced Scout confirmations | Diagnostic only; threshold intentionally too permissive for deployment |
| `full-postfix-positive-06` | Threshold 0.10; visible small flame remained below the threshold | Diagnostic threshold-selection evidence |
| `full-postfix-positive-07` | Threshold 0.05, but the lighter was depleted and the flame was too small | Invalid positive condition; excluded |
| `full-postfix-positive-08` | Recharged, larger unobstructed flame at 20–25 cm, threshold 0.05 | Accepted strong positive proof-of-function |
| `full-postfix-negative-injected-09` | One injected correlated alert in an unlit scene | Accepted forced negative verification |
| `full-postfix-positive-10` | Target near the Sentinel image edge, followed by Scout battery depletion | Invalid replication; excluded |
| `full-postfix-positive-11` | Scout reboot cleared volatile deployment; Scout launch exited before a valid run | Invalid infrastructure run; excluded |
| `full-postfix-positive-12` | Both nodes became ready, but the Sentinel produced no candidate during the small acquisition sweep | Valid engineering observation but not an integrated positive trial |
| `full-postfix-positive-13` | Independent replication with approximately 2 cm maximum flame | Accepted limited positive replication |
| `full-postfix-negative-injected-14` | Five sequential correlated alerts in an unchanged unlit scene | Accepted forced negative replication |

Every failed or invalid trial remains in the raw evidence tree. I did not delete
or relabel unsuccessful trials as successful trials.

## 6. Accepted integrated results

### 6.1 Strong visible-flame trial: `full-postfix-positive-08`

The independently marked visible interval was 28.740 s, from
11:59:30.488 UTC to 11:59:59.228 UTC. One request occurred before the marked
visible interval and was rejected. All 13 requests whose verdict timestamps
fell within the visible interval were confirmed, giving an observed
condition-specific confirmation fraction of 13/13. The Sentinel generated 13
corresponding confirmed final decisions and alarm outputs.

| Metric | n | Mean | Median | Minimum | Maximum |
|---|---:|---:|---:|---:|---:|
| Scout inference latency (ms) | 14 | 1256.648 | 1244.841 | 1214.606 | 1416.544 |
| Sentinel alert-to-final-decision latency (ms) | 14 | 1438.437 | 1416.765 | 1405.759 | 1591.737 |
| Scout source-frame age at verification start (ms) | 14 | 53.174 | 51.041 | 9.210 | 135.652 |

Across the full bounded Sentinel node run, 2,220 inference events had a mean
inference time of 60.606 ms, a median of 60.190 ms, and a maximum of
174.018 ms. The reciprocal of the mean inference time is 16.50 inference calls
per second. This is a node inference-duration statistic, not a camera-to-alarm
throughput measurement. Neither node logger reported a dropped record.

### 6.2 Small-flame replication: `full-postfix-positive-13`

The independently marked visible interval was 86.907 s. One rejected request
occurred before the marked interval. Within the visible interval, the Scout
confirmed one of 10 verification requests and rejected nine. The confirmed
Scout confidence was 0.08857, and the Sentinel produced one corresponding
alarm. The 1/10 observed confirmation fraction is not presented as recall; it
is a direct observation demonstrating sensitivity to the approximately 2 cm,
unstable flame condition.

| Metric | n | Mean | Median | Minimum | Maximum |
|---|---:|---:|---:|---:|---:|
| Scout raw maximum fire score | 11 | 0.023289 | 0.011172 | 0.000713 | 0.088566 |
| Scout inference latency (ms) | 11 | 1278.495 | 1282.279 | 1215.390 | 1339.705 |
| Sentinel alert-to-final-decision latency (ms) | 11 | 1463.527 | 1472.488 | 1407.467 | 1531.124 |

The Sentinel again recorded 2,220 inference events. Mean inference time was
60.537 ms, median was 60.461 ms, and maximum was 170.501 ms, corresponding to
16.52 inference calls per second from the reciprocal mean. Event-ID correlation
was complete and both loggers reported zero dropped records.

### 6.3 Forced unlit verification

Trial `full-postfix-negative-injected-09` forced one Scout verification using a
correlated synthetic Sentinel alert. The live unlit Scout frame produced a raw
fire maximum of 0.000334 and a rejected verdict.

Trial `full-postfix-negative-injected-14` repeated this method five times in an
unchanged unlit scene. All five publishers discovered one Scout subscriber; all
five live-frame verification requests produced correlated rejected verdicts;
none produced a confirmation.

| Metric | n | Mean | Median | Minimum | Maximum |
|---|---:|---:|---:|---:|---:|
| Scout raw maximum fire score | 5 | 0.000890 | 0.000656 | 0.000441 | 0.002052 |
| Scout inference latency (ms) | 5 | 1315.770 | 1303.415 | 1265.969 | 1400.460 |
| Source-frame age at verification start (ms) | 5 | 24.501 | 22.268 | 16.151 | 33.643 |

The five-event event log, session manifest, publisher records, verdicts, and all
five original frame hashes are local. The Scout disconnected during JPEG
transfer and then rebooted, clearing its volatile `/tmp` directory. Two JPEGs
were copied and hash-verified; three JPEG payloads were lost after their hashes
had been recorded. The structured measurements are complete, but this partial
image transfer is retained as a limitation. These six forced unlit rejections
do not estimate environmental specificity or false-positive rate.

## 7. Supporting hardware measurements

Separate camera-free 100-iteration backend benchmarks measured the exact
deployed configurations. The Sentinel TensorRT pipeline had a mean latency of
58.151 ms (approximately 17.20 FPS), while the Scout TFLite pipeline had a mean
latency of 999.431 ms (approximately 1.00 FPS). The devices, models, runtimes,
and output tensors differ, so this is a system-role comparison supporting the
hierarchical design rationale, not a controlled model-only superiority claim.

Three camera-free ROS 2 round-trip runs completed 300/300 correlated exchanges.
Combined round-trip latency had a mean of 6.046 ms, median of 5.257 ms, 95th
percentile of 9.457 ms, and maximum of 36.120 ms. These measurements exclude
camera capture and AI inference and therefore cannot be subtracted directly
from the integrated alert-to-decision values as a causal decomposition.

### 7.1 Post-recharge Scout health snapshot

After the Scout battery was recharged, I collected a final read-only health
snapshot. The reported uptime of approximately one minute confirmed that the
device had rebooted, explaining the loss of volatile `/tmp` staging files. The
persistent TFLite model remained present and its SHA-256 still matched the
accepted-trial model. The camera server, MAVLink server, Micro DDS agent, PX4,
QVIO, and vision-hub services were active. `voxl-time-sync` was reported
inactive; therefore, the earlier measured clock-offset evidence and the stated
wall-clock limitations remain necessary.

The bounded post-reboot battery inspection reported 40% charge at 6.83 V,
0.62–0.65 A, and 4.23–4.44 W. CPU temperatures were approximately 37–40 °C,
GPU temperature approximately 36–37 °C, and memory use approximately
2.45 GB of 7.67 GB. These values describe a short idle/background-service
snapshot after reboot. They are not AI-inference power, thermal-endurance, or
flight-energy measurements.

Before leaving the laboratory, I verified that the Sentinel
`camera-stream.service` was active, its root filesystem was 30% used, and its
uptime was approximately five days and six hours. This was the known leave
state for continued remote access.

## 8. Statistical method

For a sample `x_1, …, x_n`, I calculated the arithmetic mean as
`sum(x_i)/n`, the median from the ordered sample, and the population standard
deviation as `sqrt(sum((x_i - mean)^2)/n)`. Minimum and maximum are observed
extrema. The observed confirmation fraction is the number of confirmed verdicts
divided by the number of requests classified inside the independently marked
visible interval.

Node event wall times have whole-second resolution, whereas the independent
ground-truth recorder stores milliseconds. I manually reviewed boundary events;
the only pre-visible events in the accepted positive trials occurred several
seconds before the marker, so the classification was unambiguous. I did not
calculate confidence intervals or statistical significance because the trial
count, environment diversity, ignition variation, and independence assumptions
are insufficient for a defensible population inference.

## 9. Reproducibility and primary evidence

The recomputation command is implemented in
`tools/analyze_integrated_trial.py`. It reads raw JSONL evidence, verifies event
identity sets, recomputes descriptive statistics, hashes its inputs, and writes
new derived JSON without editing source records. Recomputed outputs are stored
under:

- `artifacts/experiments/hardware_lab_20260803/derived/integrated_trial_reanalysis_r1/`;
- `artifacts/experiments/hardware_lab_20260803/derived/postfix_integrated_validation_r1/`;
- `artifacts/experiments/hardware_lab_20260803/raw/full_nodes/`;
- `artifacts/experiments/hardware_lab_20260803/raw/repeated_negative/`.

The accepted Trial 13 source hashes are:

- ground truth:
  `344cb61d7ec496c799ee74d6c7dcf6eb90c4bf13139b4f8d9a8f4c5830f63ac8`;
- Scout events:
  `e2d081b514e1b0823004cee515d07e4dc3231f72a4e4f7a21fd109448477e13b`;
- Scout manifest:
  `7cd1323d01f576dc1355c56c513542f0e7e28c28659317095de35ec4722508e0`;
- Sentinel events:
  `0e24912356759126e98a4b4b7937231e4828f0fef54ed81b658424f6b523769a`;
- Sentinel manifest:
  `694e87c115093e581b618e9473a9f92d481e0f7e34864772ae06d3c64b56bf26`.

## 10. Thesis interpretation and remaining work

The session provides defensible evidence that the implemented hierarchical edge
architecture can complete the detection–verification–decision workflow on the
two heterogeneous devices. It also provides negative evidence against an
overstated reliability claim: the small-flame replication was substantially
less successful than the larger-flame trial.

The hardware proof-of-function stage is sufficient to begin writing the system
implementation, experimental methodology, hardware results, limitations, and
discussion chapters. The overall research project is not yet experimentally
complete. The remaining high-priority work is primarily offline:

1. finish and validate the six-model comparison on the frozen research split;
2. evaluate the selected models once on the untouched test set using precision,
   recall, F1, confusion matrices, and documented thresholds;
3. compare accuracy with runtime, memory, thermal, and deployment feasibility;
4. clearly separate the deployed finalist models from models evaluated only on
   the laptop;
5. document that smoke is outside the validated live-hazard scope;
6. retain coordinate-guided Scout inference, localization, trajectory planning,
   and flight validation as uncompleted implementation or future work.

Additional lighter trials are not required to establish proof of function. A
future campaign would be valuable only if it introduced a preregistered test
matrix with repeatable flame sizes, distances, positions, lighting conditions,
independent ignition markers, and sufficient repetitions—not if it merely
repeated the same setup until a successful outcome appeared.
