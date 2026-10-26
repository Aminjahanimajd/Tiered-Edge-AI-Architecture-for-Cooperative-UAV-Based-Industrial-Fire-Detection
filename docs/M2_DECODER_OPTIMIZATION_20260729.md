# M2 NumPy Decoder Optimization: Before-and-After Record

**Optimization date:** 29 July 2026  
**Baseline revision:** `35db4a7`  
**Optimized revision:** `8b634cd`  
**Status:** implemented, host-equivalence tested, and benchmarked on both devices

## Objective

The first camera-free benchmark showed that the portable YOLOv8 decoder consumed
72.88% of the Sentinel's mean pipeline time. I therefore optimized candidate
filtering and coordinate conversion for real NumPy arrays while retaining the
portable sequence-based implementation as a fallback. My objective was to reduce
software overhead without changing the deployed model, thresholds, input,
backend inference call, or fire-only decision policy.

## Implementation

The baseline decoder inspected 8,400 anchors through nested Python indexing.
The optimized path uses NumPy operations to perform class selection, confidence
and finiteness filtering, allowed-class filtering, coordinate transformation,
and geometric validity filtering across all anchors. It converts only surviving
candidates to `Detection` objects before applying the existing class-aware NMS.

The public decoding function selects this path only for a real NumPy array. The
portable implementation remains available for list inputs and environments
without NumPy. This preserves the hardware-independent core behavior while
using the array library already installed on both target devices.

I added a host test that sends the same representative channel-first output to
the portable list path and NumPy path. It checks class identity, confidence,
restored coordinates, and NMS outcome. All 31 tests then passed in a NumPy-enabled
host runtime. A NumPy-free host runtime passed the remaining 30 tests and marked
the NumPy-specific equivalence test as skipped rather than falsely passing it.

This host test establishes representative numerical equivalence. It does not
replace the still-required comparison against frozen positive and negative
Ultralytics reference outputs.

## Deployment identity and isolation

I committed the optimized implementation as revision `8b634cd` and generated a
source archive with SHA-256
`c5bf3df14d4e5de92a1fbc514943c73e31a8b439754ec6d36818c1d728e59676`.
Both devices reproduced this digest and compiled the Python sources under their
native Python 3.6 runtimes. I extracted the revision only under
`/tmp/drone_enhanced_validation_8b634cd`; I did not overwrite historical source,
ROS workspaces, or deployed models.

The deployed model hashes remained identical to the baseline:

- Sentinel TensorRT engine:
  `16f9018ac299c6f525610a877d798392ec26d53fccb84b589ff6533d76589bf2`;
- Scout TFLite model:
  `d533e320081be17ac91fb77c20a9de09f4bffada0d7f88c88326d57cd893bc35`.

## Comparison design

I repeated the baseline protocol without changing its declared parameters:

- fixed 480 x 640 x 3 black BGR `uint8` frame;
- letterbox and normalized `float32` RGB preprocessing;
- 5 warm-up pipelines excluded from statistics;
- 50 measured pipelines per device;
- fire-only confidence threshold 0.15;
- NMS IoU threshold 0.45; and
- four TFLite threads on the Scout.

The before and after measurements are separate serial runs, not paired samples.
The controlled fields were device, model hash, input, preprocessing, warm-up
count, measurement count, thresholds, and backend configuration. The intended
changed field was decoder implementation. Background load, starting temperature,
and ordinary run-to-run variation were not controlled completely. I therefore
report descriptive effects and no confidence interval, hypothesis test, or
statistical-significance claim.

## Results

| Device | Metric | Baseline mean (ms) | Optimized mean (ms) | Absolute change (ms) | Relative reduction |
|---|---|---:|---:|---:|---:|
| Sentinel | Decode and NMS | 148.920 | 1.290 | -147.630 | 99.134% |
| Sentinel | Complete pipeline | 204.324 | 57.049 | -147.274 | 72.079% |
| Scout | Decode and NMS | 83.134 | 0.992 | -82.142 | 98.806% |
| Scout | Complete pipeline | 1070.811 | 979.667 | -91.144 | 8.512% |

The Sentinel's calculated mean synthetic pipeline rate increased from 4.894 to
17.529 pipelines/s, a ratio of 3.582 and a relative increase of 258.152%. The
Scout's calculated mean rate increased from 0.934 to 1.021 pipelines/s, a ratio
of 1.093 and a relative increase of 9.304%.

The optimized Sentinel inference mean was 44.974 ms, compared with 45.146 ms in
the baseline. The optimized Scout inference mean was 974.293 ms, compared with
982.684 ms. These small inference differences were 0.382% and 0.854%,
respectively, and are compatible with ordinary run-to-run variation; the
optimization did not modify backend inference.

All 50 optimized black-frame iterations on both devices again produced zero
decoded fire detections. This is a fixed-input consistency observation, not a
specificity measurement.

## Engineering interpretation

The before-and-after result shows that an ostensibly minor implementation detail
can dominate an edge-AI pipeline. TensorRT acceleration alone did not determine
the Sentinel's original end-to-end rate: Python anchor iteration obscured most of
the available inference performance. Vectorizing the decoder reduced that
bottleneck by 99.13% and made inference the largest remaining Sentinel component.

The same decoder change had a smaller complete-pipeline effect on the Scout
because TFLite inference already dominated its baseline. This contrast is useful
for the thesis: resource-aware optimization must target the measured bottleneck
of each heterogeneous node rather than apply one optimization strategy uniformly.

The optimized timing is a strong engineering result, but it does not establish
accuracy preservation on the deployed models' full output distribution. Before
formal trials, I must compare both paths against recorded frames containing
positive, negative, overlapping, and low-confidence candidates and an
Ultralytics reference.

## Evidence and reproducibility

The optimized evidence directory contains six hashed command records and all six
passed. Its evidence-index SHA-256 is
`08c33b2fd6d74d4d39681fbc2c78b72deda06217e5e26f6198e89a19ca0af117`.

The optimized Sentinel benchmark record SHA-256 is
`ad35b0aa9bc476338b529ab5d11b4b98a039da633b94eaff91fbc2f39b87fdf3`.
The optimized Scout benchmark record SHA-256 is
`cd77c395e9d3abb80ad23f822812858d14fc9bf3e534a4fc3411e305af9e3a64`.

The optimized 100-row sample CSV has SHA-256
`86c71e103b55d90e7bbddf1f93945f4347ef5982374261a776e303f93d5cbce8`.
The optimized analysis JSON has SHA-256
`250b853e7886fd6bafa1860bb76c5a9840a5a9a6d69c30fcbff87ba52e9c7072`.
The explicit before-and-after comparison JSON has SHA-256
`cbc3598c1b2d2932b5f44b8ecae4162487017670bce7eedbb35a45049cefbba5`.

I generated the optimized sample analysis with
`tools/analyze_backend_benchmarks.py`, selecting the optimized evidence label.
I generated the controlled comparison with
`tools/compare_decoder_optimization.py`. Both tools preserve their source-file
hashes and claim boundaries in the processed output.

## Thesis placement

- **Methodology:** fixed benchmark protocol, formulas, controlled fields, and
  separate-run design.
- **Results:** raw timing summaries and before-and-after reductions.
- **Discussion:** decoder bottleneck, heterogeneous optimization targets, and
  conditional Scout role.
- **Limitations:** one run per revision, synthetic input, no camera/ROS/power
  measurement, and incomplete positive-output equivalence evidence.
- **Appendix:** source revision, commands, record hashes, sample CSV, and analysis
  JSON schemas.
