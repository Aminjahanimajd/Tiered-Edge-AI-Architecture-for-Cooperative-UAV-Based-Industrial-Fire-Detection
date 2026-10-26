# M3 Cross-Split Perceptual Refinement and Visual Audit

**Audit date:** 29 July 2026  
**Status:** all dHash candidates refined; provisional split rejected pending
regrouping

**Subsequent work:** iterative regrouping and repeated audits are documented in
`docs/M3_SOURCE_FAMILY_REGROUPING_20260729.md`. No later version is yet approved
for training.

## Objective and decision boundary

I performed this audit to determine whether the 1,701 cross-split pairs found
by the first-pass difference-hash screen were only low-texture collisions or
evidence of related scenes crossing the provisional train, validation, and test
boundaries. I did not modify any source image, source label, or provisional
manifest record. I also did not use the resulting similarity score as an
automatic duplicate label.

The input manifest contains 23,220 fire-only records. Its SHA-256 is
`cc1cc0d9be3798f0333fd1b785095d9077b65e2ae878401890ac82bd345f9bf2`.

## Complete candidate reconstruction

The first audit stored only the first 5,000 of 5,649 cross-group examples and
therefore contained only 1,193 of the 1,701 cross-split examples. I regenerated
the same mirror-invariant, 64-bit difference-hash screen with an example limit
of 10,000. The complete report has SHA-256
`0652497a7f3aac67f25ef202993bd5c3eafcc56c4e097bde1d4b2a8d39c46f43`.

The repeated scan decoded all 23,220 images and reproduced the original
counts: 250 exact duplicate sets, zero exact cross-split sets, 5,649
cross-group dHash candidates, and 1,701 cross-split candidates. Thus, the first
report's aggregate counts were sound, but its stored examples were incomplete.

## Stronger comparison method

For each of the 1,701 cross-split candidates, I decoded both images, applied
EXIF orientation, converted them to RGB, and resized them to 128 x 128 pixels
with Lanczos interpolation. Pixel values were normalized to [0, 1]. I retained
the original width and height because square stretching can conceal or
exaggerate geometric differences.

I evaluated the second image both directly and horizontally mirrored. This was
necessary because the first-pass dHash was mirror-invariant. The orientation
with the larger review-priority score was retained. The following dimensionless
descriptors were calculated:

- RGB mean absolute error (MAE): the mean absolute difference across all RGB
  pixels and channels;
- grayscale root mean squared error (RMSE), using
  `Y = 0.299R + 0.587G + 0.114B`;
- gradient MAE: the mean absolute difference between horizontal and vertical
  grayscale first differences;
- color-histogram distance: one minus the mean 32-bin intersection across RGB
  channels; and
- zero-mean normalized grayscale cross-correlation (NCC).

For deterministic review ordering only, I calculated:

`score = 1 - (0.40 RGB_MAE + 0.25 gray_RMSE + 0.20 gradient_MAE + 0.15 histogram_distance)`.

The weights were not trained or statistically calibrated. The score is not a
probability and is not used as a thesis accuracy metric.

## Computed results

All 1,701 cross-split pairs completed the stronger comparison. No pair became
pixel-identical after 128 x 128 normalization. A mirrored orientation was
selected for 691 pairs.

| Metric | Minimum | Median | Mean | Population SD | Maximum |
|---|---:|---:|---:|---:|---:|
| RGB MAE | 0.0003 | 0.1284 | 0.1834 | 0.1601 | 0.7124 |
| Grayscale RMSE | 0.0008 | 0.1470 | 0.2021 | 0.1614 | 0.7427 |
| Gradient MAE | 0.0002 | 0.0188 | 0.0212 | 0.0133 | 0.0668 |
| Histogram distance | 0.0020 | 0.3801 | 0.4147 | 0.3021 | 1.0000 |
| Grayscale NCC | -0.3600 | 0.8751 | 0.7266 | 0.3030 | 1.0000 |
| Review-priority score | 0.3854 | 0.8481 | 0.8097 | 0.1465 | 0.9993 |

The candidate composition was:

| Dimension | Group | Pairs |
|---|---|---:|
| Category | background--background | 382 |
| Category | background--fire-positive | 362 |
| Category | fire-positive--fire-positive | 957 |
| Split route | test--train | 654 |
| Split route | test--validation | 434 |
| Split route | train--validation | 613 |
| dHash distance | 0 | 252 |
| dHash distance | 1 | 529 |
| dHash distance | 2 | 920 |

The detailed metric report SHA-256 is
`01d0270201f64b85e1d98097a3e4f557edaf1e33287f6d06a2e0649b74f91b3f`.

## Stratified visual review

I generated a deterministic 98-pair review queue consisting of the 60 highest
scores plus the 0th, 25th, 50th, 75th, and 100th score percentiles within each
observed dHash-distance/category-pair stratum. Duplicate selections were
removed. Nine contact sheets showed each pair side by side, applying the chosen
mirror orientation only for viewing.

I reviewed all 98 pairs and recorded one of three labels:

| Visual label | Reviewed pairs |
|---|---:|
| Visually the same scene | 69 |
| Not visibly the same scene at contact-sheet resolution | 28 |
| Uncertain related sequence | 1 |
| **Total** | **98** |

All of the 60 highest-scoring pairs were visibly the same underlying scene or
an extremely close derivative. The examples included weather negatives,
repeated fire photographs, adjacent-looking video frames, and closely related
indoor lighter images. The lower-score strata also contained expected false
matches, including fog, sunrise, and dark flame images that shared coarse color
or structure but not the same visible scene.

This is a deliberately enriched and stratified review queue, not a random
sample. Therefore 69/98 must not be reported as the estimated prevalence of
leakage among all 1,701 candidates. It is sufficient, however, to reject the
current split because confirmed same-scene pairs cross its boundaries.

The source-controlled decision manifest has SHA-256
`93d2feed4234b5c8c4b2a79bf1163f5f26cdb07ef438928c589cd7357a74bd8a`.
The joined decision CSV has SHA-256
`9128857455f314d89e6cb549003c49f54c87dd5e2ac37856a0a0bc962ffeb7ba`.

## Reproduction commands

From the enhanced repository root, with the bundled analysis Python available
as `<python>`, I used:

```powershell
<python> tools/audit_manifest_duplicates.py artifacts/processed/fire_only_grouped_manifest_v1/records.jsonl --output artifacts/processed/fire_only_grouped_manifest_v1/duplicate_audit_all_pairs.json --maximum-dhash-distance 2 --maximum-examples 10000
<python> tools/refine_perceptual_duplicates.py artifacts/processed/fire_only_grouped_manifest_v1/records.jsonl artifacts/processed/fire_only_grouped_manifest_v1/duplicate_audit_all_pairs.json --output artifacts/processed/fire_only_grouped_manifest_v1/perceptual_refinement.json --review-csv artifacts/processed/fire_only_grouped_manifest_v1/manual_review_queue.csv --contact-sheet-directory artifacts/processed/fire_only_grouped_manifest_v1/manual_review_contact_sheets --standardized-size 128 --top-review-count 60
<python> tools/apply_manual_duplicate_review.py artifacts/processed/fire_only_grouped_manifest_v1/manual_review_queue.csv config/manual_duplicate_review_20260729.json --output-csv artifacts/processed/fire_only_grouped_manifest_v1/manual_review_decisions.csv --output-summary artifacts/processed/fire_only_grouped_manifest_v1/manual_review_summary.json
```

All output paths use exclusive creation. Reproduction therefore requires a new
versioned output directory or removal of disposable regenerated outputs after
their hashes have been checked; it never requires changing raw data.

## Dataset decision and corrective action

I reject `fire_only_grouped_manifest_v1` for final training or model comparison.
It remains a preserved provisional artifact and must not be described as a
leakage-free split.

The next dataset revision must:

1. merge group IDs connected by the 69 visually confirmed same-scene edges;
2. strengthen filename/source rules for repeated weather images, named fire
   collections, and numbered frame families visible in the review;
3. conservatively group the uncertain pair until provenance proves
   independence;
4. reassign complete groups, never individual images, to train, validation,
   and test;
5. rerun exact hashing, the complete dHash screen, stronger comparison, and a
   new visual audit; and
6. freeze the test split only after no reviewed same-scene edge crosses a split.

## Claim boundary and thesis placement

- **Dataset preparation/methodology:** provenance-aware grouping, exact hash,
  dHash candidate generation, continuous refinement metrics, and deterministic
  visual sampling.
- **Results:** only the counts and descriptive values reported above.
- **Discussion:** the first-pass filename grouping was insufficient and could
  inflate apparent generalization if used for model comparison.
- **Limitations:** resized-pixel metrics are not semantic embeddings; visual
  decisions cover 98 prioritized pairs rather than all candidates; contact-
  sheet review may miss subtle source relationships; no inter-rater agreement
  was measured.
- **Appendix:** the complete candidate report, metric report, review queue,
  contact sheets, decision manifest, joined decisions, commands, and hashes.
