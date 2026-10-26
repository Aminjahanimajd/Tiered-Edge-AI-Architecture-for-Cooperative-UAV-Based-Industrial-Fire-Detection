# M2 Camera-Free Backend Benchmark Record

**Benchmark date:** 29 July 2026  
**Code revision:** `35db4a7`  
**Scope:** exact deployed models, stationary devices, fixed synthetic input  
**Status:** completed; descriptive system-runtime baseline

## Objective

I performed this benchmark to quantify the runtime behavior of the exact model
and backend combination deployed on each drone. I measured preprocessing,
backend inference, YOLOv8 decoding, and the complete sequential pipeline. I did
not open either camera, start ROS 2, publish swarm messages, enable flight
control, or introduce a lighter.

The benchmark addresses a system-level question: how quickly does each current
hardware/software/model combination process the same-shaped synthetic input?
It is not a controlled model-only comparison because the Sentinel and Scout use
different hardware, models, runtimes, and output channel counts.

## Safety, identity, and source control

The physical safety conditions confirmed for the immediately preceding live
validation remained in force: both drones were powered, both had their
propellers removed, and my laptop was connected to `SwarmNet`. I referenced the
existing operator-assertion record rather than generating a false second
confirmation timestamp.

I committed the benchmark implementation and host tests as revision `35db4a7`.
All 28 tests present at that revision passed before deployment. I generated a
Git source archive with SHA-256
`545022c4f36dfe691cd3641d820b0049924b87dfaa46fe1a87cc6bbbc87a23ff`.
The archive contained no `__pycache__` directory or `.pyc` file. Both devices
reproduced the archive digest and compiled the benchmark and runtime sources
under Python 3.6 before execution.

The source was extracted only into
`/tmp/drone_enhanced_validation_35db4a7`. Historical workspaces and deployed
model artifacts were not overwritten.

## Experimental protocol

I used the following fixed protocol on both devices:

- synthetic input: one 480 x 640 x 3 black BGR `uint8` frame;
- resize method: letterbox;
- model input type: normalized `float32` RGB;
- warm-up pipelines: 5, excluded from all reported statistics;
- measured pipelines: 50;
- confidence threshold: 0.15;
- NMS IoU threshold: 0.45;
- allowed live class: fire only; and
- execution: sequential preprocessing, inference, and decoding.

The Scout used four TFLite threads. The two benchmarks ran concurrently on
their respective devices. No ROS 2 traffic was generated, but the devices
remained connected through the Sentinel access point. Concurrent execution and
ordinary background operating-system work are possible sources of run-to-run
variation.

Every measured iteration retained the four component durations and decoded
detection count. Timing used each device's monotonic clock. UTC timestamps were
used for session identity, not duration calculation.

## Statistical definitions

For each duration series `x_1, ..., x_n`, with `n = 50`, I calculated:

- mean: `x_bar = (1/n) sum(x_i)`;
- median: middle ordered value, or the mean of the two middle values;
- range: `max(x_i) - min(x_i)`;
- population variance: `(1/n) sum((x_i - x_bar)^2)`;
- population standard deviation: square root of population variance; and
- percentiles: linear interpolation at index
  `(n - 1) * percentage / 100`.

All durations are milliseconds. The displayed pipeline rate is
`1000 / mean_pipeline_ms`. It is a synthetic sequential processing rate, not a
camera FPS measurement.

I did not calculate a confidence interval or perform a significance test. The
50 observations came from one serial run per device using one repeated
deterministic frame; statistical independence and between-run variability were
not established.

## Results

### Pipeline timing

| Device | Component | Mean (ms) | Median (ms) | Min (ms) | Max (ms) | SD (ms) | P95 (ms) |
|---|---|---:|---:|---:|---:|---:|---:|
| Sentinel | Preprocess | 10.257 | 10.192 | 10.000 | 10.936 | 0.190 | 10.630 |
| Sentinel | TensorRT inference | 45.146 | 45.045 | 44.798 | 46.381 | 0.350 | 45.968 |
| Sentinel | Decode and NMS | 148.920 | 148.955 | 147.494 | 151.001 | 0.759 | 150.102 |
| Sentinel | Complete pipeline | 204.324 | 204.403 | 202.756 | 207.279 | 0.927 | 205.848 |
| Scout | Preprocess | 4.993 | 4.951 | 4.286 | 7.222 | 0.510 | 5.905 |
| Scout | TFLite inference | 982.684 | 984.980 | 934.524 | 1045.530 | 30.212 | 1028.504 |
| Scout | Decode and NMS | 83.134 | 83.021 | 81.849 | 84.895 | 0.578 | 84.299 |
| Scout | Complete pipeline | 1070.811 | 1073.499 | 1023.189 | 1133.602 | 30.371 | 1117.251 |

The Sentinel's mean complete-pipeline rate was 4.894 synthetic pipelines/s.
The Scout's rate was 0.934 synthetic pipelines/s. The Scout-to-Sentinel mean
pipeline-latency ratio was 5.241. Expressed with the Scout as the descriptive
baseline, the Sentinel's mean pipeline latency was 80.919% lower.

This percentage describes the two complete deployed systems under this protocol.
It must not be relabeled as an accuracy improvement, model-only speedup, or
hardware-only speedup.

### Component contribution

The Sentinel mean pipeline consisted of 5.02% preprocessing, 22.10% TensorRT
inference, and 72.88% decoding/NMS time. The Scout mean pipeline consisted of
0.47% preprocessing, 91.77% TFLite inference, and 7.76% decoding/NMS time.

This decomposition reveals two different bottlenecks. The Sentinel's measured
TensorRT inference alone was approximately 45.1 ms, but the current
hardware-independent Python decoder increased the complete pipeline to
approximately 204.3 ms. The Scout was dominated by TFLite inference at
approximately 982.7 ms. These observations provide evidence-driven targets for
optimization: vectorized decoding on the Sentinel and evaluation of Scout model
or runtime alternatives.

### Synthetic detection result

All 50 measured black-frame iterations on each device produced zero decoded fire
detections. This establishes deterministic behavior for this single synthetic
input within the run. It does not establish specificity or a false-positive
rate because the repeated black frame is neither an independent sample nor a
representative environmental negative dataset.

### Point-in-time resources and temperatures

The Sentinel process maximum resident-set-size counter increased from 27,424 KiB
before backend loading to 1,018,784 KiB after engine loading and 1,096,940 KiB
after the benchmark. Because `ru_maxrss` is a cumulative process maximum, these
values are not simultaneous allocation measurements. Available system memory
was 2,892,956 KiB before loading, 2,002,056 KiB after loading, and 1,961,788 KiB
after the benchmark.

The Sentinel `CPU-therm` point readings were 42.5 degrees C before loading,
43.0 degrees C after loading, and 43.5 degrees C after the benchmark. The
corresponding `GPU-therm` readings were 44.5, 43.5, and 44.0 degrees C.

The Scout process maximum resident-set-size counter was 31,372 KiB before
loading, 37,932 KiB after loading, and 210,052 KiB after the benchmark. Available
system memory was 5,367,484 KiB, 5,367,736 KiB, and 5,223,188 KiB at the same
three observation points. The representative `cpu-0-0-usr` sensor increased
from 36.3 degrees C before loading to 48.2 degrees C after the benchmark; the
`gpuss-max-step` value increased from 35.8 to 47.5 degrees C.

These readings bracket the run but are not continuous thermal traces. They do
not establish peak temperature, energy use, electrical power, throttling, or a
causal temperature increase attributable only to inference.

## Engineering interpretation

The timing pattern is consistent with the intended hierarchical edge
architecture: the Sentinel combination can execute the initial screening
pipeline more frequently, while the slower Scout combination can be invoked
conditionally for secondary hazard verification. Conditional invocation avoids
requiring the measured Scout pipeline to run continuously for every Sentinel
frame.

This result supports the feasibility rationale for dividing responsibilities,
but it does not prove the central hypothesis by itself. The required next
evidence includes model accuracy on leakage-controlled data, an optimized
decoder comparison, ROS 2 message latency and reliability, synchronized
positive and negative trials, and end-to-end event outcomes.

## Deviations and limitations

One verify/extract command failed in the local shell because nested quoting split
the argument before SSH execution. It created no evidence record and did not
extract either transferred archive. I simplified the literal hash check and the
next command passed on both devices.

Additional limitations are:

- one benchmark run per device;
- one repeated synthetic frame;
- no camera acquisition;
- no ROS 2 or DDS communication;
- no continuous power or thermal sampling;
- no process isolation from normal background services;
- different models, runtimes, hardware, and output shapes; and
- pure-Python decoding whose overhead is part of this implemented baseline.

## Evidence and reproducibility

The evidence directory contains six hashed records; all six commands passed.
The evidence index SHA-256 is
`2851e6142aac4037ab35905e7784a642f96b4aa2a9d4abad72fddf616bd42aca`.

The Sentinel benchmark record SHA-256 is
`b6be5745afdfdaf4c3f86abf3d427830eb109563ea2579034f567f3b6000f65d`.
The Scout benchmark record SHA-256 is
`014cc6a14c90a09b00f97799015a16c152eae03adcd48e622fad801336331f6f`.

The processed sample CSV contains 100 measured rows and has SHA-256
`b3210223f7a39fbfd7399ebb6933375a0825a1c94a1ed20efab8f1776e4650e3`.
The processed analysis JSON has SHA-256
`08291f9a04a4eae29314e6797cdf7e4be4e7f876a79c8ca7508322fe73a80b8e`.

To reproduce the analysis, run
`tools/analyze_backend_benchmarks.py` on the raw benchmark evidence directory.
The program first verifies the embedded evidence-record hashes, then exports the
sample-level CSV and analysis JSON without modifying the raw records.

The evidence-driven decoder optimization and standardized before-and-after
comparison are documented separately in
`docs/M2_DECODER_OPTIMIZATION_20260729.md`. The measurements in this document
remain the preserved pre-optimization baseline.
