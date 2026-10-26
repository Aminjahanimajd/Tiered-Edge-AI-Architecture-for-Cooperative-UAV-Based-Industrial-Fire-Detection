# M3 Curated Fire-Only Research Dataset

**Date:** 29 July 2026  
**Freeze candidate:** `fire_only_curated_manifest_v7`  
**Scope:** controlled fire detection; smoke is not a live target class

## Decision

I will not use the nominal 23,214-record cleaned source manifest directly for
the controlled model comparison. Its size overstates its evidential value:
three inferred mega-groups contain 16,364 records (70.5%) and dominate separate
splits, creating a strong source/domain confound. The images were obtained from
third-party datasets, not collected by me, and original capture-session IDs are
not available.

I created a smaller, deterministic, provenance-aware freeze candidate. It
contains 4,991 records: 2,404 positive fire images and 2,587 legitimate
fire-free hard negatives. Intentional negative examples are not erroneous data;
they are retained because they measure false-alert behavior for smoke, fog,
cloud, glare, sun, and visually confusing environments. Mislabeled,
smoke-only, ambiguous, corrupted-boundary, broadcast-overlay, or systematically
unreliable positive annotations were excluded or quarantined.

## Dataset lineage

1. I started from immutable source-family manifest version 10: 23,214 records,
   29,095 boxes, and no detected structural annotation errors.
2. I excluded three over-broad mega-groups and retained 6,850 records spanning
   2,628 inferred groups.
3. I deterministically capped each retained group at 50 records with seed
   `20260729`, producing 5,185 records with nearly equal positive/background
   support.
4. I assigned whole groups to train, validation, and test using a deterministic
   70/15/15 target. Confirmed duplicate components were subsequently routed
   together while unaffected groups retained their split.
5. I adjudicated a split- and box-size-stratified annotation sample at full
   resolution. Six ambiguous positive records were excluded and 28 boxes were
   removed from nine records.
6. When the resample exposed sibling variants with the same systematic defects,
   I quarantined five complete source families. This removed 188 additional
   records rather than allowing augmented siblings to survive record-level
   cleaning.
7. I repeated structural, corruption, exact-duplicate, perceptual-candidate,
   group-overlap, and stratified semantic checks on version 7.

All transformations created new manifests. No original image, label, or prior
manifest was overwritten.

## Frozen-candidate composition

| Split | Positive | Background | Total |
|---|---:|---:|---:|
| Train | 1,731 | 1,827 | 3,558 |
| Validation | 319 | 381 | 700 |
| Test | 354 | 379 | 733 |
| **Total** | **2,404** | **2,587** | **4,991** |

The manifest contains 3,400 retained fire boxes and 2,615 inferred groups. The
class balance is 48.2% positive and 51.8% background. Relative to source-family
manifest version 10, the record count is reduced by 78.5%. This reduction is a
quality and independence control, not evidence that 78.5% of the source data
was intrinsically false.

## Provenance and licensing

The freeze candidate is a curated third-party dataset. I did not collect these
images. The manifest retains per-record provenance:

| Recorded source | Records | Recorded license |
|---|---:|---|
| Drone-Fire-Smoke v1 | 2,461 | CC BY 4.0 |
| Weather Image Recognition / WEAPD derivative | 1,366 | CC0, as recorded on the Kaggle dataset page |
| Weather Classification | 1,164 | CC0, as recorded on the Kaggle dataset page |

The source URLs are retained inside every record's `provenance` object. License
statements must still be cited from the original dataset pages in the thesis,
and dataset creators must receive attribution where required.

## Quality controls and acceptance evidence

- Readability: 4,991/4,991 records readable; zero corrupt or unreadable files.
- Annotation structure: zero detected format, range, dimension, class, or
  geometry issues; 3,400 retained boxes.
- Group integrity: zero inferred group IDs span multiple splits.
- Exact duplicates: 17 exact-duplicate sets remain within a single split; zero
  exact-duplicate sets cross splits.
- Perceptual screening: 456 cross-split dHash candidates remain because dHash is
  intentionally sensitive to low-detail fog, glare, and flame imagery.
- Manual duplicate adjudication: the stabilized 108-pair enriched high-risk
  queue contained no remaining visually same-scene pair. The queue includes
  hard background/background and background/fire candidates and is not a
  prevalence sample.
- Final semantic adjudication: all 50 records in the final deterministic
  split- and box-size-stratified review queue were acceptable after record,
  box, and source-family corrections.

## Reproducibility anchors

| Artifact | SHA-256 |
|---|---|
| Version-7 records JSONL | `478803efb7f8f4f6c3fe74d58658958bccfa2d0f58ec50a1a5c16535e393a7dd` |
| Annotation audit JSON | `7edabc62a98a012a16c5fa382f80e55a2d76a574f45d90575387d776b44def51` |
| Duplicate audit JSON | `a680fa8bfdb8213647f7208eff32de8036ab3e78603aa47dd22c87ff724bf6dc` |
| Perceptual refinement JSON | `ec5736d0ab7ae06954f56febd495ec66fdd66702e8c8a464b8a6bc3f1aa12dd8` |
| Final annotation decisions CSV | `a669cd4cfb0a5964779c598c0f907c622a0ad7e46acbd87384b294bbf5cfbf79` |
| Final duplicate decisions CSV | `9f127c6fe906e7f6076fe229bc738971df3b19d1d6e2a28ccf7afbb922d25d79` |

The source-controlled policy and decision files are under `config/`; generated
records, audit reports, review queues, decisions, and contact sheets are under
`artifacts/processed/fire_only_curated_manifest_v7/`.

## Claim boundary and limitations

This freeze candidate supports a controlled within-project comparison of model
capacity and constrained deployment. It does not prove industrial-site
generalization, capture-session independence, or exhaustive label correctness.
The following limitations must be explicit in the thesis:

- original video/scene/session identifiers could only be inferred from names,
  hashes, and visual review;
- source-family parsing can be over-broad or under-broad;
- manual decisions were made by one reviewer;
- enriched review queues cannot estimate population label-error or duplicate
  prevalence;
- the fire positives and weather negatives originate from different source
  collections, so source-domain cues may remain;
- the untouched test split must not be inspected for model selection after
  training begins.

Subject to preserving the version-7 hash and test-set boundary, this manifest is
accepted as the dataset for the controlled YOLOv8n/YOLOv8s comparison. Any later
change requires a new version, renewed audits, and a documented reason.
