# M3 Fire-Only Annotation Integrity Audit

**Audit date:** 29 July 2026  
**Input:** provisional source-family manifest version 9  
**Status:** automated format/geometry checks passed; ten flagged samples were
adjudicated into immutable derived version 10; expanded tiny-box review remains
open before final training

## Objective and evidence policy

I audited the derived one-class fire annotations before freezing a dataset or
running a controlled YOLOv8n/YOLOv8s comparison. I read every manifest record
and source image without changing any image, original label, derived label, or
split assignment. All generated reports, queues, decisions, and contact sheets
are separate derived artifacts.

The input contains 23,220 images: 20,584 fire-positive and 2,636 background.
It contains 29,111 retained class-0 bounding boxes. The version-9 record-
manifest SHA-256 is
`62de12ee1cecf0f2477651c0bb43259485b64e8c137a42c9d605e8bd52291e86`.

## Automated validation method

For every record, I checked:

1. JSONL readability and record category;
2. source-image and original-label existence;
3. image readability and positive dimensions;
4. consistency between `fire_positive`/`background` and retained box count;
5. duplicate derived rows inside one image;
6. exactly five numeric YOLO fields per row;
7. finite, integer class identifier equal to zero;
8. normalized center coordinates in [0, 1];
9. normalized width and height in (0, 1]; and
10. all four box edges remaining inside the image within a numerical tolerance
    of `1e-9`.

The tool also calculated box count, normalized area, source-pixel width,
source-pixel height, and source-pixel area distributions. Linear interpolation
was used for reported percentiles. Pixel dimensions refer to each original
source image, not the later network input size.

## Automated results

No structural or geometric issue was found in the defined checks: zero missing
or unreadable images, zero missing referenced original labels, zero malformed
rows, zero unexpected classes, zero invalid or non-finite coordinates, zero
out-of-image boxes, zero duplicate rows, zero positive records without a box,
and zero background records with a box.

| Metric | Count / value |
|---|---:|
| Images | 23,220 |
| Fire-positive images | 20,584 |
| Background images | 2,636 |
| Fire boxes | 29,111 |
| Mean boxes per image | 1.254 |
| Median boxes per image | 1 |
| Maximum boxes in one image | 14 |
| Median normalized box area | 0.03975 |
| 1st percentile normalized area | 0.0009375 |
| 99th percentile normalized area | 0.63695 |
| Median source-pixel box area | 16,280 px² |
| Minimum source-pixel box area | 36 px² |
| Boxes below 64 px² | 18 |
| Boxes below 256 px² | 163 |
| Boxes below 1,024 px² | 1,218 |

The small-object tail is directly relevant to the lighter observations and the
resource-constrained detector comparison. These source-pixel areas must not be
substituted for the post-resize areas seen by 416- or 640-pixel model inputs.

The complete automated report SHA-256 is
`9e9b13d5d22c708a75463bb1aced25a6fbb86bf39a01e1cdf31418f675f52a8c`.

## Deterministic visual review

I created five strata from each record's smallest normalized box area:
background, less than 0.001, 0.001 to less than 0.01, 0.01 to less than 0.10,
and at least 0.10. I selected three deterministic records from every available
split-by-size stratum using seed `20260729`, yielding 45 images across train,
validation, and test. Red boxes were rendered only on derived contact sheets.

I classified each sample as:

- `acceptable`: visible fire was plausibly covered, or a background correctly
  had no localized fire target;
- `questionable`: smoke/non-fire content, fragmented boxes, or insufficient
  review resolution made the label uncertain; or
- `incorrect`: the rendered box did not cover visible fire at the review
  resolution.

The results were 35 acceptable, 4 questionable, and 6 incorrect. The raw sample
proportions are therefore 77.8%, 8.9%, and 13.3%, respectively. I do **not**
interpret these percentages as whole-dataset error rates because the queue is
size-stratified and deterministic rather than a simple random sample, and the
review used one reviewer and contact-sheet resolution.

The six apparently incorrect cases were concentrated in the tiny/small strata
and showed boxes on clothing, image borders, or other regions without visible
fire. The four questionable cases contained smoke-heavy or unusually
fragmented annotations. I preserved all ten version-9 records unchanged for
full-resolution adjudication.

The review-queue SHA-256 is
`983c7c06e4546e7d0999fa36c28fbbe09fb65fee5bea558592a71621774f6703`.
The joined decision CSV SHA-256 is
`7eab2f8c1bb08e3ad3356b6a5e178998785d6a11de27125efbe643d482bc6795`.
The source-controlled decision manifest SHA-256 is
`9345ed439a7ebfd99af58a659cb1a6c6e6b4a1f249502dedc32045ba721bfef0`.

## Full-resolution adjudication and version 10

I generated ten full-source-resolution renders with each retained box indexed.
The derived-render manifest SHA-256 is
`9869fb9ef3066d07c7bd59c1c09d5bf08ce210ba6216c8ea58fd1a4dce9d8932`.
The higher-resolution review confirmed that six images had no visible fire in
their only retained edge/non-fire box. I excluded those six records rather than
converting them to background. For the four images containing clear fire, I
retained the clear fire boxes and removed smoke-only or fragmented extra boxes.

These actions created `fire_only_source_family_manifest_v10`; they did not
overwrite an original image, label, or version-9 record. The action affected:

- 6 of 23,220 records by exclusion (0.026%);
- 10 of 23,220 records by exclusion or box filtering (0.043%); and
- 16 of 29,111 boxes by removal (0.055%).

Version 10 contains 23,214 records, 29,095 boxes, and the same 2,631 group IDs
that remain after empty-group removal. Its split totals are 16,147 train, 3,537
validation, and 3,530 test records. Its record-manifest SHA-256 is
`fd14d2b42d82181ba8d093e26e8df7b51e52a92a4366349cc3b6950691d06292`.

I repeated both complete automated audits. The annotation scan again reported
zero defined format, pairing, readability, class, or geometry issues. Its
SHA-256 is
`38eb650b6a09f0f3276c877efdf4bed7fbcafc021c4a7c19ff0b7f65b5693f5a`.
The duplicate scan decoded all 23,214 images, found zero corrupt images and zero
exact cross-split duplicate sets, and retained the version-9 screening counts
of 1,214 cross-group and 704 cross-split dHash candidates. Its SHA-256 is
`a76363fbf2c2496317e5433b447e49273d497784c7bfc6db4902c0fd82c8cbd2`.

## Acceptance decision and required next work

The annotation format and coordinate geometry pass the defined automated gate.
The ten known semantic defects have been conservatively resolved in derived
version 10. This adjudication is single-reviewer and is not evidence that every
remaining label is semantically correct.

Before final training, I should expand review of the tiny-box tail because the
version-9 audit contained 163 boxes below 256 source pixels² and this tail is
central to the observed difficulty detecting a lighter flame. The independent
split also remains provisional pending completion of the refreshed duplicate
queue documented in the source-family report.

## Claim boundary and thesis placement

- **Methodology:** automated validation rules, area formulas, deterministic
  sampling, strata, classifications, and immutable evidence policy.
- **Results:** record/box totals, zero structural issues, size distributions,
  35/4/6 sample decisions, ten adjudication actions, and version-10 re-audits.
- **Discussion:** valid YOLO geometry does not imply semantic correctness; tiny
  annotations are a material risk for small-flame performance.
- **Limitations:** single reviewer, enriched rather than probabilistic sample,
  contact-sheet first pass, unknown original annotation procedure, and limited
  review coverage of the tiny-box tail.
- **Appendix:** complete JSON audit, review CSV, contact sheets, decision
  manifest, joined decisions, tool command, and hashes.

## Superseding curated-dataset annotation result

I addressed the open tiny-box and semantic-review gate through the curated
dataset lineage rather than expanding the 23,214-record source manifest. In the
5,185-record curated candidate, I reviewed a new split- and size-stratified
queue, rendered 18 ambiguous cases at full resolution, excluded six ambiguous
positive records, and removed 28 non-fire or redundant boxes from nine records.

A subsequent resample exposed systematic sibling errors. I therefore
quarantined five noisy source families as complete units, removing 188 further
records. Final curated version 7 contains 4,991 records and 3,400 boxes, passes
the defined automated structural checks, and all 50 records in its final
stratified semantic queue were accepted. These are enriched single-reviewer
checks, not a whole-dataset label-error estimate.

The authoritative current dataset decision and reproducibility hashes are in
`docs/M3_CURATED_RESEARCH_DATASET_20260729.md`. The version-10 results above
remain valid historical inputs to that derivation.
