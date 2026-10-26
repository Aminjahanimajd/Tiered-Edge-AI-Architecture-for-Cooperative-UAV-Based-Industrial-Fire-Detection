# M2 non-YOLO deployment preparation — 13 August 2026

## Purpose and claim boundary

I prepared the two non-YOLO candidates for later exact-device screening using
the frozen checkpoints and the 64-image validation calibration set. This was a
`[NO LAB]` laptop activity. It does not show that either model runs on the
Jetson Nano or VOXL 2, and it provides no device latency, resource, thermal, or
concurrent-service result.

## SSD MobileNet V2 FPNLite export lineage

I restored the completed `ckpt-47` checkpoint with TensorFlow 2.15.1 and the
pinned TensorFlow Model Garden Object Detection API. The official TFLite
exporter completed, and a float32 graph allocated successfully with XNNPACK.
The first export used the exporter's default maximum of ten detections. A
second append-only export explicitly used 100 detections, matching the frozen
native evaluator. A third requested the official regular-NMS option. No prior
attempt was overwritten.

Raw-output inspection established the tensor roles rather than inferring them
from output order: boxes `337`, classes `338`, scores `339`, and count `340`.
The pinned SSD feature-extractor source states that inputs must be mapped from
pixel values to `[-1,1]`; therefore the final diagnostic path used
`(2/255) * pixel - 1`. It also used TensorFlow bilinear resizing to reduce a
known framework-preprocessing difference.

The strongest SSD TFLite result still failed the preregistered fidelity gate:

| Quantity | Result | Frozen criterion |
|---|---:|---:|
| Calibration images | 64 | 64 |
| Native detections | 6,400 | — |
| Converted detections | 6,400 | — |
| IoU-matched detections | 5,577 | — |
| Detection match rate | 0.8714 | at least 0.95 |
| Mean absolute confidence difference | 0.00391 | at most 0.02 |

The confidence criterion passed, but the detection-match criterion did not.
Accordingly, the SSD TFLite candidate is classified `FIDELITY_FAILED`. I did
not relax the threshold. The artifact may be retained for diagnosis, but it is
not eligible to replace the native model or enter device performance ranking
as a fidelity-valid conversion.

The initial zero-prediction run was a decoder configuration error caused by
swapped class and score tensor indices. It remains retained as a failed
pre-fix run and is not an SSD accuracy result. Later preprocessing variants
also remain retained so the improved match rate cannot be mistaken for a
fresh, selectively reported experiment.

## EfficientDet-Lite0 status

EfficientDet-Lite0 completed training after full-state checkpoint recovery and
was exported by its native TensorFlow Lite Model Maker workflow. Its retained
TFLite file has SHA-256
`948e71fa53fa9a740a2bca45f169280a9c6e6596a49bfcab65d0ad9cfda2f12c`,
is 4,443,288 bytes, allocates successfully, and already generated the
canonical native calibration predictions.

Because this exact TFLite artifact is the native evaluated artifact, a
cross-format conversion-fidelity comparison is not applicable. It is marked
`NATIVE_TFLITE_READY_FOR_DEVICE_ATTEMPT`, not `DEPLOYED`. Runtime support and
performance must still be measured independently on each physical edge
device.

## Engineering interpretation

The offline work produces one eligible native TFLite candidate
(EfficientDet-Lite0) and one rejected converted TFLite candidate (SSD). The SSD
failure is useful evidence: successful graph conversion and interpreter
allocation alone do not guarantee prediction equivalence. Exact-device
screening remains necessary, and no laptop timing in these runs will be mixed
with Jetson or VOXL measurements.

## Evidence index

The tracked index is
`manifests/non_yolo_deployment_preparation_20260813.json`. It records artifact,
interface, run-summary, fidelity, tool, and failed-attempt hashes. Large raw
artifacts remain under
`artifacts/experiments/deployment_candidates_non_yolo_v1/`.
