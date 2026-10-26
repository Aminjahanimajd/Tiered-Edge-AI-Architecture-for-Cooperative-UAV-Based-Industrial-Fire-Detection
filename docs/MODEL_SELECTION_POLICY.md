# Frozen Model-Selection and Test-Opening Policy

**Policy version:** 1.0

**Frozen:** 4 August 2026, before common validation and before the untouched test split

**Access:** `[NO LAB]`

## Experimental boundary

The six candidates are compared on the same source-grouped, fire-only dataset
using seed 20260729. This is a controlled single-seed screening experiment, not
a claim that the globally best detector family has been identified.

Laptop predictive and runtime screening is separate from deployment evidence.
Only a model/backend combination that has been executed on a named device with
an exact artifact hash may be described as hardware-validated.

## Validation rules

1. Each producer emits COCO-format predictions down to confidence 0.001.
2. The common evaluator uses COCO IoU thresholds 0.50:0.05:0.95.
3. A reporting confidence threshold is selected on validation data by maximum
   object-level F1 at IoU 0.50 over thresholds 0.01 through 0.99.
4. If several thresholds have the same F1 within numerical precision, the
   threshold with higher recall is selected; an exact remaining tie uses the
   lower threshold.
5. Background false-positive image rate is reported instead of a conventional
   object-detection true-negative rate, because object detection has no unique
   count of true-negative boxes.
6. COCO AP for small, medium, and large ground-truth objects is reported where
   each stratum contains observations.
7. Framework-specific preprocessing and decoding are recorded, but ground
   truth, category mapping, metric code, and split are common.

The validation audit found no COCO-small objects: all 392 retained validation
boxes exceed the standard \(32^2\)-pixel boundary. AP-small will therefore be
reported as unavailable, not interpreted as zero. I predeclare an additional
descriptive recall analysis using bounding-box area as a fraction of image area:
below 1%, 1--5%, 5--20%, and at least 20%. These dataset-relative strata do not
establish performance on the materially smaller live lighter flame.

## Pareto comparison

No post-hoc weighted score will be used. A candidate is Pareto-efficient when
no other candidate is at least as good on every reported axis and strictly
better on at least one axis.

The primary axes are:

- AP50--95 and validation-selected F1: higher is better;
- fire recall: higher is better for Sentinel suitability;
- fire precision and background rejection: higher is better for Scout suitability;
- median and 95th-percentile host inference latency: lower is better;
- artifact size and peak measured memory: lower is better;
- demonstrated device deployability: reported as a separate evidence flag.

The deployed YOLO models remain the experimentally demonstrated two-device
system unless another candidate receives exact-backend hardware evidence.

## Untouched test opening gate

The 733-image test split may be opened only after all items below are recorded:

- validation predictions and metrics for every valid candidate;
- chosen validation threshold for every candidate;
- candidate checkpoint and configuration hashes;
- common evaluator hash;
- dataset/test annotation hash;
- Pareto table and deployment-evidence flags;
- a signed/dated test-opening record.

Test results must not change model weights, confidence thresholds, preprocessing,
or candidate selection. A demonstrable evaluator defect may be corrected only
by preserving the first output and recording the code defect, correction, and
new hash.

## EfficientDet fallback

If the full-state recovery does not finish by 10 August, the best valid
epoch-aligned checkpoint is evaluated and labelled `truncated`. It may appear
in the six-candidate table but cannot be described as a completed 100-epoch
run.
