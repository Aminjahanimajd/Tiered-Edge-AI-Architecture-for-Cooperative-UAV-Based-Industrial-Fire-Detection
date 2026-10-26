# M2 YOLO ONNX Export and Fidelity — 13 August 2026

## Objective and boundary

I exported the four frozen YOLO checkpoints into isolated ONNX candidates for
later Jetson and VOXL runtime attempts. This work establishes only graph
preparation and laptop conversion fidelity. It does not establish deployment,
latency, resource use, or accuracy on either edge computer.

## Export protocol

Each source checkpoint hash was verified against the deployment registry and
copied into a versioned, ignored output directory. Ultralytics 8.4.45 exported
fixed batch-1, fixed-input, FP32 ONNX graphs at opset 12 without simplification.
The ONNX 1.22 checker accepted all four graphs.

| Candidate | Input | ONNX bytes | ONNX SHA-256 |
|---|---:|---:|---|
| YOLOv8n-416 | 416 | 12,141,401 | `aefbc333350898a1be0e7c7e1fe1038722fbecb00ddc5b25f5d5f599ff473a80` |
| YOLOv8n-640 | 640 | 12,238,425 | `ebbc2c06ed3d98a8fd1c34dc8529138c812bce56da84862b528ec48c8a3f9dfe` |
| YOLOv8s-416 | 416 | 44,622,009 | `ef2fbce918f2109caa072f6aac30a49334ba68529ddec7cca21d2379f4e3e207` |
| YOLOv8s-640 | 640 | 44,719,033 | `8cbcdc54de3f1013ed8f9f4daa8c6cc571c15326acd888280f1e5901a8bd7a3f` |

## Fidelity protocol

I ran each ONNX model through ONNX Runtime 1.28.0 on the same 64 frozen
calibration images. Preprocessing and decoding used the Ultralytics letterbox,
detection head, and non-maximum suppression path at the native validation
floor (`confidence=0.001`, `NMS IoU=0.7`). Converted detections were greedily
matched to the retained native-framework detections within each image and
class at box IoU at least 0.50.

The preregistered pass rule required both:

- detection match rate at least 0.95, using the larger detection count as the
  denominator; and
- mean absolute matched-confidence difference no greater than 0.02.

| Candidate | Native detections | ONNX detections | Matched | Match rate | Confidence MAE | Result |
|---|---:|---:|---:|---:|---:|---|
| YOLOv8n-416 | 857 | 824 | 823 | 0.9603 | 0.000056 | PASS |
| YOLOv8n-640 | 1,032 | 985 | 980 | 0.9496 | 0.000255 | `FIDELITY_FAILED` |
| YOLOv8s-416 | 1,892 | 1,833 | 1,816 | 0.9598 | 0.000223 | PASS |
| YOLOv8s-640 | 2,503 | 2,307 | 2,295 | 0.9169 | 0.000212 | `FIDELITY_FAILED` |

I did not round the YOLOv8n-640 match rate upward or relax the gate after
observing it. Its result remains a failure under the frozen rule even though it
missed by only 0.0004. The very small confidence errors show that matched boxes
had similar scores, but they do not override unmatched detection counts.

## Failure lineage

The first fidelity invocation attempted to pass the 64 file paths through one
fixed-shape ONNX call and failed with an expected-batch-1 versus observed-batch-
64 runtime error. Its v1 output directory is retained. In v2, I invoked one
image at a time, which matches the deployment batch contract. This was an
evaluator correction, not a model or threshold change.

## Traceability and next action

- Export manifest SHA-256:
  `e596e209e3a13fde71adae26d9e6649504b3b80fd1ad07d650400f6c11ff5cbe`.
- Fidelity manifest SHA-256:
  `4f67ce2404e009318e068b9a414ac87874dee3d43f9ad3f0d25739c728ce0612`.
- Native calibration manifest SHA-256:
  `1d4ed49048f77e57bcc73ef27eea7dfc901d07ad834a4fc5c05b04e3346ffdb3`.

Only the two fidelity-valid 416-pixel ONNX candidates proceed as accepted ONNX
conversion artifacts under this rule. The historical 640-pixel TensorRT and
TFLite deployments remain separate evidence and are not invalidated by this
new post-hoc ONNX conversion screen. SSD and EfficientDet conversion/fidelity,
and all exact-device runtime outcomes, remain pending.
