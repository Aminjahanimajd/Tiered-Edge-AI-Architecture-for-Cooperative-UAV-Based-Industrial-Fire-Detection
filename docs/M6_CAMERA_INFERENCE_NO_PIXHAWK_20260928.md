# M6 Stationary Camera and Inference Baseline — 28 September 2026

## Scope

I evaluated whether the current Sentinel and Scout camera/inference paths
could coexist with ROS 2 transport, asynchronous logging, and resource
sampling on their exact edge computers. The aircraft were stationary with
their propellers removed. The Sentinel Pixhawk and flight battery remained
unpowered, and both ROS nodes used `enable_flight_commands=false`. This test
does not measure physical flight, navigation, power consumption, detector
accuracy, ignition-to-detection latency, or industrial reliability.

## Configuration and acceptance rules

The formal trial identifier was `camera10m-threads1-20260928-r1`. The Sentinel
used its deployed TensorRT engine with a live Intel RealSense D435i input. The
Scout used `/home/root/colcon_ws/best.tflite`, the live ModalAI `/tracking`
camera path, and one TFLite interpreter thread. A synthetic correlated hazard
alert was published every five seconds for 540 seconds. Each alert had a
three-second verdict timeout. Host-wide resources were sampled at approximately
1 Hz for the surrounding ten-minute node lifetime.

The preregistered checks relevant to this partial-stack run were:

- every injected alert receives one correctly correlated verdict;
- every Scout verdict uses a fresh camera frame;
- neither node crashes or stops silently;
- Sentinel `MemAvailable` remains at least 512 MiB;
- Scout p95 alert-to-verdict latency is at most 2 s.

## Preserved development evidence

I retained every pre-formal attempt. In the first attempt, the probe and Scout
used different trial identifiers; the Scout correctly rejected the cross-trial
messages. In the second attempt, a stopped ModalAI camera stream caused stale-
frame verdicts; restarting `voxl-camera-server` restored a sequential 1280 x
800 RAW8 stream at approximately 30 frames/s. In the third attempt, the default
four-thread TFLite interpreter completed one inference and then starved the
camera bridge. A two-thread diagnostic reproduced this behavior. A one-thread
90-second diagnostic instead returned 12/12 fresh verdicts, but its 2.667 s p95
latency exceeded the 2 s target. I therefore froze one interpreter thread for
the formal run and preserved the target unchanged.

## Results

| Measure | Sentinel | Scout / hierarchy |
|---|---:|---:|
| Node lifetime represented by resource samples | 609.6 s | 612.9 s |
| Resource samples | 488 | 581 |
| Inference frames / verification inferences | 9,411 | 108 |
| Inference latency, mean | 60.233 ms | 2,437.849 ms |
| Inference latency, p95 | 61.239 ms | 2,504.387 ms |
| Host CPU, mean | 28.76% | 47.63% |
| Minimum `MemAvailable` | 1,581.8 MiB | 4,879.5 MiB |
| Swap growth, first to last sample | 0 MiB | 0 MiB |
| Maximum retained thermal-zone value | 50.0 degrees C | 47.5 degrees C |
| Logged camera or stale-frame errors | 0 | 0 |
| Logger dropped-record maximum | 0 | 0 |
| Node exit code | 0 | 0 |

The probe received 108/108 verdicts. Missing, mismatched, duplicate, and
unexpected counts were all zero. Alert-to-verdict latency was 2,529.161 ms
mean, 2,515.474 ms median, 2,483.855 ms minimum, 2,794.235 ms maximum, and
2,616.852 ms p95 (population standard deviation 54.295 ms, n=108).

## Acceptance and interpretation

The run passed the fresh-frame, clean-exit, correlation, completeness, memory,
and no-swap-growth checks. It failed the preregistered Scout p95 latency limit:
2,616.852 ms was 616.852 ms above the 2 s target. This is a measured resource-
constrained coexistence limit of the stable one-thread Scout configuration,
not a reason to discard the run or revise the acceptance threshold.

The result supports the narrower claim that the two stationary edge pipelines
can sustain live-camera inference and correlated ROS 2 decisions for the
observed interval without message loss, stale frames, memory exhaustion, swap
growth, or process failure. It does not support complete-stack sustainability
because Sentinel flight-controller services were absent.

## Traceability

Raw evidence is retained outside the repository at:

`D:\Drones\recovery_images\sentinel_sd_20260909\hardware_evidence_20260928\camera_inference_no_pixhawk_20260928`

The transferred archives have SHA-256 hashes:

- Sentinel archive: `40f104157995d9cfcb8808791c3da3f3a3f46b3c8aa131c8cf55477ea54d18f4`
- Scout archive: `b16c0bf74c70e24236067998db8314422028635701d5bc99f4a64234bbfbe069`

The derived analysis is in
`derived_analysis/camera10m-threads1-20260928-r1/analysis.json`. Its visual
manifest binds the rendered terminal panel and time-series figure to the raw
input hashes. The main event hashes are:

- probe events: `0cb717e01aff4426f0b7a503a245586ab9d3d5f02896a04c6333f67a10f6693b`;
- Sentinel events: `77204dd9a21d0a0e59a2f51e7057e3ade165f8cdc2df70ab1a886e3b50e7163c`;
- Scout events: `5db80fedd009f3ce589413eab49f61fc0a18b3e7763763f525f8a28a2b1923cc`.

The terminal-style panel is suitable as appendix evidence. The time-series
figure is suitable for the Results chapter if its caption retains the no-
Pixhawk scope and the failed 2 s latency criterion.
